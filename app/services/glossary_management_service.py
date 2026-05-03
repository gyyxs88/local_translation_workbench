from __future__ import annotations

from sqlalchemy import select

from ..db.models import Chapter, GlossaryCandidate, GlossaryEntry, TranslationProject
from ..errors import ToolError
from ..repositories.glossary import GlossaryRepository
from .glossary_prompt_service import GlossaryPromptService
from .project_staleness_service import ProjectStalenessService


class GlossaryManagementService:
    def __init__(self, session) -> None:
        self.session = session
        self.glossary = GlossaryRepository(session)
        self.prompts = GlossaryPromptService()
        self.staleness = ProjectStalenessService(session)

    def create_entry(
        self,
        *,
        project_id: int,
        source_term: str,
        target_term: str,
        category: str = "entity",
        note: str | None = None,
        gender: str | None = None,
        age_group: str | None = None,
        status: str = "active",
        locked: bool = False,
        term_group_key: str | None = None,
        relation_role: str = "independent",
        scope_level: str = "project_term",
        scope_chapter_id: int | None = None,
    ) -> dict[str, object]:
        self._ensure_project(project_id)
        try:
            entry = self.glossary.create_entry(
                project_id=project_id,
                source_term=self._require_text(source_term, "source_term"),
                target_term=self._require_text(target_term, "target_term"),
                category=self._normalize_text(category) or "entity",
                note=self._normalize_optional_text(note),
                gender=self._normalize_gender(category=category, gender=gender),
                age_group=self._normalize_age_group(category=category, age_group=age_group),
                status=self._normalize_text(status) or "active",
                locked=1 if locked else 0,
                term_group_key=self._normalize_text(term_group_key) or self._require_text(source_term, "source_term"),
                relation_role=self._normalize_text(relation_role) or "independent",
                scope_level=scope_level,
                scope_chapter_id=scope_chapter_id,
            )
        except ValueError as exc:
            raise self._entry_create_error(exc) from exc
        self._mark_entry_scope_stale(entry)
        return self._entry_payload(entry)

    def update_entry(
        self,
        *,
        entry_id: int | None = None,
        project_id: int | None = None,
        source_term: str | None = None,
        scope_level: str = "project_term",
        scope_chapter_id: int | None = None,
        target_term: str | None = None,
        category: str | None = None,
        note: str | None = None,
        gender: str | None = None,
        age_group: str | None = None,
        status: str | None = None,
        locked: bool | None = None,
        term_group_key: str | None = None,
        relation_role: str | None = None,
    ) -> dict[str, object]:
        entry = self._resolve_entry(
            entry_id=entry_id,
            project_id=project_id,
            source_term=source_term,
            scope_level=scope_level,
            scope_chapter_id=scope_chapter_id,
        )
        if source_term is not None and entry_id is not None:
            new_source_term = self._require_text(source_term, "source_term")
            existing = self.glossary.get_entry(
                int(entry.project_id),
                new_source_term,
                scope_level=str(entry.scope_level),
                scope_chapter_id=entry.scope_chapter_id,
            )
            if existing is not None and existing.id != entry.id:
                raise ToolError(
                    code="conflict_error",
                    message=f"project_id={entry.project_id} 下已存在 source_term={new_source_term} 的术语。",
                    status=409,
                    details={"entry_id": existing.id},
                )
            if entry.term_group_key == entry.source_term:
                entry.term_group_key = new_source_term
            entry.source_term = new_source_term
        if target_term is not None:
            entry.target_term = self._require_text(target_term, "target_term")
        if category is not None:
            entry.category = self._normalize_text(category) or "entity"
        if note is not None:
            entry.note = self._normalize_optional_text(note)
        if gender is not None:
            entry.gender = self._normalize_gender(category=entry.category, gender=gender)
        if age_group is not None:
            entry.age_group = self._normalize_age_group(category=entry.category, age_group=age_group)
        if status is not None:
            entry.status = self._normalize_text(status) or "active"
        if locked is not None:
            entry.locked = 1 if locked else 0
        if term_group_key is not None:
            entry.term_group_key = self._normalize_text(term_group_key) or entry.source_term
        if relation_role is not None:
            entry.relation_role = self._normalize_text(relation_role) or "independent"
        self.session.flush()
        self._mark_entry_scope_stale(entry)
        return self._entry_payload(entry)

    def delete_entry(
        self,
        *,
        entry_id: int | None = None,
        project_id: int | None = None,
        source_term: str | None = None,
        scope_level: str = "project_term",
        scope_chapter_id: int | None = None,
        force: bool = False,
    ) -> dict[str, object]:
        entry = self._resolve_entry(
            entry_id=entry_id,
            project_id=project_id,
            source_term=source_term,
            scope_level=scope_level,
            scope_chapter_id=scope_chapter_id,
        )
        if entry.locked and not force:
            raise ToolError(
                code="conflict_error",
                message="术语已锁定，删除时必须显式传 force=true。",
                status=409,
                details={"entry_id": entry.id},
            )
        payload = {"id": entry.id, "project_id": entry.project_id, "deleted": True}
        stale_chapters = self._chapters_for_entry_scope(entry)
        self.glossary.delete_entry(entry)
        self._mark_chapters_stale(project_id=int(payload["project_id"]), chapters=stale_chapters)
        return payload

    def set_entry_lock(
        self,
        *,
        locked: bool,
        entry_id: int | None = None,
        project_id: int | None = None,
        source_term: str | None = None,
        scope_level: str = "project_term",
        scope_chapter_id: int | None = None,
    ) -> dict[str, object]:
        entry = self._resolve_entry(
            entry_id=entry_id,
            project_id=project_id,
            source_term=source_term,
            scope_level=scope_level,
            scope_chapter_id=scope_chapter_id,
        )
        entry.locked = 1 if locked else 0
        self.session.flush()
        self._mark_entry_scope_stale(entry)
        return self._entry_payload(entry)

    def create_candidate(
        self,
        *,
        project_id: int,
        chapter_id: int,
        source_term: str,
        suggested_term: str,
        category: str = "entity",
        note: str | None = None,
        gender: str | None = None,
        age_group: str | None = None,
        status: str = "pending",
        term_group_key: str | None = None,
        relation_role: str = "independent",
        scope_level: str | None = None,
        scope_chapter_id: int | None = None,
    ) -> dict[str, object]:
        self._ensure_project(project_id)
        try:
            candidate = self.glossary.create_candidate(
                project_id=project_id,
                chapter_id=chapter_id,
                source_term=self._require_text(source_term, "source_term"),
                suggested_term=self._require_text(suggested_term, "suggested_term"),
                category=self._normalize_text(category) or "entity",
                note=self._normalize_optional_text(note),
                gender=self._normalize_gender(category=category, gender=gender),
                age_group=self._normalize_age_group(category=category, age_group=age_group),
                status=self._normalize_text(status) or "pending",
                term_group_key=self._normalize_text(term_group_key) or self._require_text(source_term, "source_term"),
                relation_role=self._normalize_text(relation_role) or "independent",
                scope_level=scope_level,
                scope_chapter_id=scope_chapter_id,
            )
        except ValueError as exc:
            raise ToolError(code="invalid_arguments", message=str(exc), status=400) from exc
        return self._candidate_payload(candidate)

    def update_candidate(
        self,
        *,
        candidate_id: int,
        source_term: str | None = None,
        suggested_term: str | None = None,
        category: str | None = None,
        note: str | None = None,
        gender: str | None = None,
        age_group: str | None = None,
        status: str | None = None,
        term_group_key: str | None = None,
        relation_role: str | None = None,
    ) -> dict[str, object]:
        candidate = self._resolve_candidate(candidate_id)
        if source_term is not None:
            candidate.source_term = self._require_text(source_term, "source_term")
        if suggested_term is not None:
            candidate.suggested_term = self._require_text(suggested_term, "suggested_term")
        if category is not None:
            candidate.category = self._normalize_text(category) or "entity"
        if note is not None:
            candidate.note = self._normalize_optional_text(note)
        if gender is not None:
            candidate.gender = self._normalize_gender(category=candidate.category, gender=gender)
        if age_group is not None:
            candidate.age_group = self._normalize_age_group(category=candidate.category, age_group=age_group)
        if status is not None:
            candidate.status = self._normalize_text(status) or "pending"
        if term_group_key is not None:
            candidate.term_group_key = self._normalize_text(term_group_key) or candidate.source_term
        if relation_role is not None:
            candidate.relation_role = self._normalize_text(relation_role) or "independent"
        self.session.flush()
        return self._candidate_payload(candidate)

    def approve_candidate(self, *, candidate_id: int) -> dict[str, object]:
        return self.update_candidate(candidate_id=candidate_id, status="approved")

    def reject_candidate(self, *, candidate_id: int) -> dict[str, object]:
        return self.update_candidate(candidate_id=candidate_id, status="rejected")

    def delete_candidate(self, *, candidate_id: int) -> dict[str, object]:
        candidate = self._resolve_candidate(candidate_id)
        payload = {"id": candidate.id, "project_id": candidate.project_id, "deleted": True}
        self.glossary.delete_candidate(candidate)
        return payload

    def promote_candidate(self, *, candidate_id: int, locked: bool = False, force: bool = False) -> dict[str, object]:
        candidate = self._resolve_candidate(candidate_id)
        scope_chapter_id = candidate.scope_chapter_id if candidate.scope_level == "chapter_term" else None
        entry = self.glossary.get_entry(
            int(candidate.project_id),
            str(candidate.source_term),
            scope_level=str(candidate.scope_level),
            scope_chapter_id=scope_chapter_id,
        )
        if entry is None:
            entry = self.glossary.create_entry(
                project_id=int(candidate.project_id),
                source_term=str(candidate.source_term),
                target_term=str(candidate.suggested_term),
                category=str(candidate.category),
                note=candidate.note,
                gender=candidate.gender,
                age_group=candidate.age_group,
                locked=1 if locked else 0,
                term_group_key=str(candidate.term_group_key),
                relation_role=str(candidate.relation_role),
                scope_level=str(candidate.scope_level),
                scope_chapter_id=scope_chapter_id,
            )
        else:
            if entry.locked and not force:
                raise ToolError(
                    code="conflict_error",
                    message="目标正式术语已锁定，提升候选时必须显式传 force=true。",
                    status=409,
                    details={"entry_id": entry.id, "candidate_id": candidate.id},
                )
            entry.target_term = str(candidate.suggested_term)
            entry.category = str(candidate.category)
            entry.note = candidate.note
            entry.gender = candidate.gender
            entry.age_group = candidate.age_group
            entry.status = "active"
            entry.locked = 1 if locked else entry.locked
            entry.term_group_key = str(candidate.term_group_key)
            entry.relation_role = str(candidate.relation_role)
        candidate.status = "promoted"
        self.session.flush()
        self._mark_entry_scope_stale(entry)
        return {
            "candidate": self._candidate_payload(candidate),
            "entry": self._entry_payload(entry),
        }

    def _resolve_entry(
        self,
        *,
        entry_id: int | None,
        project_id: int | None,
        source_term: str | None,
        scope_level: str,
        scope_chapter_id: int | None,
    ) -> GlossaryEntry:
        if entry_id is not None:
            entry = self.glossary.get_entry_by_id(entry_id)
        else:
            if project_id is None or source_term is None:
                raise ToolError(
                    code="invalid_arguments",
                    message="定位正式术语必须提供 entry_id，或同时提供 project_id 与 source_term。",
                    status=400,
                )
            entry = self.glossary.get_entry(
                project_id,
                source_term,
                scope_level=scope_level,
                scope_chapter_id=scope_chapter_id,
            )
        if entry is None:
            raise ToolError(code="not_found", message="找不到正式术语。", status=404)
        return entry

    def _resolve_candidate(self, candidate_id: int) -> GlossaryCandidate:
        candidate = self.glossary.get_candidate_by_id(candidate_id)
        if candidate is None:
            raise ToolError(code="not_found", message=f"找不到候选术语 candidate_id={candidate_id}。", status=404)
        return candidate

    def _ensure_project(self, project_id: int) -> TranslationProject:
        project = self.session.get(TranslationProject, project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)
        return project

    def _chapters_for_entry_scope(self, entry: GlossaryEntry) -> list[Chapter]:
        if entry.scope_level == "chapter_term":
            if entry.scope_chapter_id is None:
                return []
            chapter = self.session.get(Chapter, int(entry.scope_chapter_id))
            return [chapter] if chapter is not None else []
        return list(
            self.session.execute(
                select(Chapter)
                .where(Chapter.project_id == entry.project_id)
                .order_by(Chapter.chapter_index.asc())
            ).scalars().all()
        )

    def _mark_entry_scope_stale(self, entry: GlossaryEntry) -> None:
        self._mark_chapters_stale(project_id=int(entry.project_id), chapters=self._chapters_for_entry_scope(entry))

    def _mark_chapters_stale(self, *, project_id: int, chapters: list[Chapter]) -> None:
        if chapters:
            self.staleness.mark_glossary_downstream_stale(project_id=project_id, chapters=chapters)

    def _entry_payload(self, entry: GlossaryEntry) -> dict[str, object]:
        return {
            "id": entry.id,
            "project_id": entry.project_id,
            "source_term": entry.source_term,
            "target_term": entry.target_term,
            "category": entry.category,
            "note": entry.note,
            "gender": entry.gender,
            "age_group": entry.age_group,
            "status": entry.status,
            "locked": entry.locked,
            "term_group_key": entry.term_group_key,
            "relation_role": entry.relation_role,
            "scope_level": entry.scope_level,
            "scope_chapter_id": entry.scope_chapter_id,
        }

    def _candidate_payload(self, candidate: GlossaryCandidate) -> dict[str, object]:
        return {
            "id": candidate.id,
            "project_id": candidate.project_id,
            "chapter_id": candidate.chapter_id,
            "source_term": candidate.source_term,
            "suggested_term": candidate.suggested_term,
            "category": candidate.category,
            "note": candidate.note,
            "gender": candidate.gender,
            "age_group": candidate.age_group,
            "status": candidate.status,
            "term_group_key": candidate.term_group_key,
            "relation_role": candidate.relation_role,
            "scope_level": candidate.scope_level,
            "scope_chapter_id": candidate.scope_chapter_id,
            "workflow_run_id": candidate.workflow_run_id,
        }

    def _require_text(self, value: str | None, field_name: str) -> str:
        normalized = self._normalize_text(value)
        if not normalized:
            raise ToolError(code="invalid_arguments", message=f"{field_name} 不能为空。", status=400)
        return normalized

    def _normalize_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    def _normalize_optional_text(self, value: str | None) -> str | None:
        return self.prompts.normalize_optional_text(value)

    def _normalize_gender(self, *, category: str, gender: str | None) -> str | None:
        return self.prompts.normalize_gender(category=self._normalize_text(category) or "entity", gender=gender)

    def _normalize_age_group(self, *, category: str, age_group: str | None) -> str | None:
        return self.prompts.normalize_age_group(category=self._normalize_text(category) or "entity", age_group=age_group)

    def _entry_create_error(self, exc: ValueError) -> ToolError:
        message = str(exc)
        if "已存在" in message:
            return ToolError(code="conflict_error", message=message, status=409)
        return ToolError(code="invalid_arguments", message=message, status=400)
