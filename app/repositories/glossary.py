from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db.models import (
    Chapter,
    GlossaryCandidate,
    GlossaryCandidateReview,
    GlossaryDraftCandidate,
    GlossaryEntry,
    WorkflowStepRun,
)


class GlossaryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_entry(
        self,
        project_id: int,
        source_term: str,
        *,
        scope_level: str = "project_term",
        scope_chapter_id: int | None = None,
    ) -> GlossaryEntry | None:
        normalized_scope_level, normalized_scope_chapter_id = self._normalize_entry_scope(
            scope_level=scope_level,
            scope_chapter_id=scope_chapter_id,
        )
        scope_anchor = self._build_entry_scope_anchor(
            scope_level=normalized_scope_level,
            scope_chapter_id=normalized_scope_chapter_id,
        )
        statement = select(GlossaryEntry).where(
            GlossaryEntry.project_id == project_id,
            GlossaryEntry.source_term == source_term,
            GlossaryEntry.scope_anchor == scope_anchor,
        )
        return self.session.execute(statement).scalar_one_or_none()

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
        locked: int = 0,
        term_group_key: str | None = None,
        relation_role: str = "independent",
        scope_level: str = "project_term",
        scope_chapter_id: int | None = None,
    ) -> GlossaryEntry:
        normalized_scope_level, normalized_scope_chapter_id = self._normalize_entry_scope(
            scope_level=scope_level,
            scope_chapter_id=scope_chapter_id,
        )
        scope_anchor = self._build_entry_scope_anchor(
            scope_level=normalized_scope_level,
            scope_chapter_id=normalized_scope_chapter_id,
        )
        if normalized_scope_chapter_id is not None:
            self._ensure_chapter_belongs_to_project(project_id=project_id, chapter_id=normalized_scope_chapter_id)
        existing = self.get_entry(
            project_id,
            source_term,
            scope_level=normalized_scope_level,
            scope_chapter_id=normalized_scope_chapter_id,
        )
        if existing is not None:
            raise ValueError(
                f"project_id={project_id} 下已存在 source_term={source_term} 的 {normalized_scope_level} 术语。"
            )
        entry = GlossaryEntry(
            project_id=project_id,
            source_term=source_term,
            target_term=target_term,
            category=category,
            note=note,
            gender=gender,
            age_group=age_group,
            status=status,
            locked=locked,
            term_group_key=term_group_key or source_term,
            relation_role=relation_role,
            scope_level=normalized_scope_level,
            scope_chapter_id=normalized_scope_chapter_id,
            scope_anchor=scope_anchor,
        )
        self.session.add(entry)
        self.session.flush()
        return entry

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
        workflow_run_id: int | None = None,
    ) -> GlossaryCandidate:
        self._ensure_chapter_belongs_to_project(project_id=project_id, chapter_id=chapter_id)
        normalized_scope_level, normalized_scope_chapter_id = self._normalize_candidate_scope(
            chapter_id=chapter_id,
            scope_level=scope_level,
            scope_chapter_id=scope_chapter_id,
        )
        if normalized_scope_chapter_id is not None:
            self._ensure_chapter_belongs_to_project(project_id=project_id, chapter_id=normalized_scope_chapter_id)
        candidate = GlossaryCandidate(
            project_id=project_id,
            chapter_id=chapter_id,
            source_term=source_term,
            suggested_term=suggested_term,
            category=category,
            note=note,
            gender=gender,
            age_group=age_group,
            status=status,
            term_group_key=term_group_key or source_term,
            relation_role=relation_role,
            scope_level=normalized_scope_level,
            scope_chapter_id=normalized_scope_chapter_id,
            workflow_run_id=workflow_run_id,
        )
        self.session.add(candidate)
        self.session.flush()
        return candidate

    def create_draft_candidate(
        self,
        *,
        workflow_run_id: int,
        project_id: int,
        chapter_id: int,
        source_term: str,
        suggested_term: str,
        category: str,
        gender: str | None = None,
        age_group: str | None = None,
        status: str = "pending",
        term_group_key: str | None = None,
        relation_role: str = "independent",
        scope_level: str | None = None,
        scope_chapter_id: int | None = None,
        evidence_payload: dict[str, object] | list[object] | None = None,
    ) -> GlossaryDraftCandidate:
        self._ensure_chapter_belongs_to_project(project_id=project_id, chapter_id=chapter_id)
        normalized_scope_level, normalized_scope_chapter_id = self._normalize_candidate_scope(
            chapter_id=chapter_id,
            scope_level=scope_level,
            scope_chapter_id=scope_chapter_id,
        )
        if normalized_scope_chapter_id is not None:
            self._ensure_chapter_belongs_to_project(project_id=project_id, chapter_id=normalized_scope_chapter_id)
        draft_candidate = GlossaryDraftCandidate(
            workflow_run_id=workflow_run_id,
            project_id=project_id,
            chapter_id=chapter_id,
            source_term=source_term,
            suggested_term=suggested_term,
            category=category,
            gender=gender,
            age_group=age_group,
            status=status,
            term_group_key=term_group_key or source_term,
            relation_role=relation_role,
            scope_level=normalized_scope_level,
            scope_chapter_id=normalized_scope_chapter_id,
            evidence_payload=evidence_payload,
        )
        self.session.add(draft_candidate)
        self.session.flush()
        return draft_candidate

    def create_candidate_review(
        self,
        *,
        draft_candidate_id: int,
        step_run_id: int,
        review_type: str,
        decision: str,
        score: float | None = None,
        reason_codes: list[str] | None = None,
        structured_payload: dict[str, object] | None = None,
    ) -> GlossaryCandidateReview:
        draft_candidate = self.session.get(GlossaryDraftCandidate, draft_candidate_id)
        if draft_candidate is None:
            raise ValueError(f"找不到 draft_candidate_id={draft_candidate_id}。")
        step_run = self.session.get(WorkflowStepRun, step_run_id)
        if step_run is None:
            raise ValueError(f"找不到 step_run_id={step_run_id}。")
        if draft_candidate.workflow_run_id != step_run.workflow_run_id:
            raise ValueError(
                f"step_run_id={step_run_id} 的 workflow_run_id={step_run.workflow_run_id} 与 "
                f"draft_candidate_id={draft_candidate_id} 的 workflow_run_id={draft_candidate.workflow_run_id} 不一致。"
            )
        review = GlossaryCandidateReview(
            draft_candidate_id=draft_candidate_id,
            step_run_id=step_run_id,
            review_type=review_type,
            decision=decision,
            score=score,
            reason_codes=reason_codes,
            structured_payload=structured_payload,
        )
        self.session.add(review)
        self.session.flush()
        return review

    def list_entries(self, project_id: int) -> list[GlossaryEntry]:
        statement = (
            select(GlossaryEntry)
            .where(GlossaryEntry.project_id == project_id)
            .order_by(GlossaryEntry.source_term.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def list_active_entries(
        self,
        project_id: int,
        *,
        scope_level: str = "project_term",
        scope_chapter_id: int | None = None,
        include_project_scope: bool = False,
    ) -> list[GlossaryEntry]:
        normalized_scope_level, normalized_scope_chapter_id = self._normalize_entry_scope(
            scope_level=scope_level,
            scope_chapter_id=scope_chapter_id,
        )
        statement = (
            select(GlossaryEntry)
            .where(
                GlossaryEntry.project_id == project_id,
                GlossaryEntry.status == "active",
                self._build_entry_scope_condition(
                    scope_level=normalized_scope_level,
                    scope_chapter_id=normalized_scope_chapter_id,
                    include_project_scope=include_project_scope,
                ),
            )
            .order_by(GlossaryEntry.source_term.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def list_active_entries_for_matching(
        self,
        project_id: int,
        *,
        scope_level: str = "project_term",
        scope_chapter_id: int | None = None,
        include_project_scope: bool = False,
    ) -> list[GlossaryEntry]:
        normalized_scope_level, normalized_scope_chapter_id = self._normalize_entry_scope(
            scope_level=scope_level,
            scope_chapter_id=scope_chapter_id,
        )
        statement = (
            select(GlossaryEntry)
            .where(
                GlossaryEntry.project_id == project_id,
                GlossaryEntry.status == "active",
                self._build_entry_scope_condition(
                    scope_level=normalized_scope_level,
                    scope_chapter_id=normalized_scope_chapter_id,
                    include_project_scope=include_project_scope,
                ),
            )
            .order_by(
                GlossaryEntry.scope_level.asc(),
                GlossaryEntry.scope_chapter_id.asc(),
                GlossaryEntry.term_group_key.asc(),
                GlossaryEntry.relation_role.asc(),
                GlossaryEntry.source_term.asc(),
            )
        )
        return list(self.session.execute(statement).scalars().all())

    def list_candidates(self, project_id: int) -> list[GlossaryCandidate]:
        statement = (
            select(GlossaryCandidate)
            .where(GlossaryCandidate.project_id == project_id)
            .order_by(GlossaryCandidate.chapter_id.asc(), GlossaryCandidate.source_term.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def list_draft_candidates(self, workflow_run_id: int) -> list[GlossaryDraftCandidate]:
        statement = (
            select(GlossaryDraftCandidate)
            .where(GlossaryDraftCandidate.workflow_run_id == workflow_run_id)
            .order_by(GlossaryDraftCandidate.chapter_id.asc(), GlossaryDraftCandidate.source_term.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def delete_candidates_for_chapters(self, project_id: int, chapter_ids: list[int]) -> None:
        if not chapter_ids:
            return
        self.session.execute(
            delete(GlossaryCandidate).where(
                GlossaryCandidate.project_id == project_id,
                GlossaryCandidate.chapter_id.in_(chapter_ids),
            )
        )

    def list_project_candidate_terms(self, project_id: int) -> list[str]:
        statement = (
            select(GlossaryCandidate.source_term)
            .where(GlossaryCandidate.project_id == project_id)
            .distinct()
            .order_by(GlossaryCandidate.source_term.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def delete_unlocked_entries_not_in_terms(
        self,
        project_id: int,
        source_terms: list[str],
        *,
        scope_level: str = "project_term",
        scope_chapter_id: int | None = None,
    ) -> None:
        normalized_scope_level, normalized_scope_chapter_id = self._normalize_entry_scope(
            scope_level=scope_level,
            scope_chapter_id=scope_chapter_id,
        )
        statement = delete(GlossaryEntry).where(
            GlossaryEntry.project_id == project_id,
            GlossaryEntry.locked == 0,
            self._build_entry_scope_condition(
                scope_level=normalized_scope_level,
                scope_chapter_id=normalized_scope_chapter_id,
            ),
        )
        if source_terms:
            statement = statement.where(GlossaryEntry.source_term.not_in(source_terms))
        self.session.execute(statement)

    def inspect_draft_candidates(self, workflow_run_id: int) -> list[dict[str, object]]:
        statement = (
            select(GlossaryDraftCandidate)
            .where(GlossaryDraftCandidate.workflow_run_id == workflow_run_id)
            .order_by(GlossaryDraftCandidate.chapter_id.asc(), GlossaryDraftCandidate.source_term.asc())
        )
        return [
            {
                "id": candidate.id,
                "workflow_run_id": candidate.workflow_run_id,
                "project_id": candidate.project_id,
                "chapter_id": candidate.chapter_id,
                "source_term": candidate.source_term,
                "suggested_term": candidate.suggested_term,
                "category": candidate.category,
                "gender": candidate.gender,
                "age_group": candidate.age_group,
                "scope_level": candidate.scope_level,
                "scope_chapter_id": candidate.scope_chapter_id,
                "evidence_payload": candidate.evidence_payload,
                "status": candidate.status,
                "term_group_key": candidate.term_group_key,
                "relation_role": candidate.relation_role,
            }
            for candidate in self.session.execute(statement).scalars().all()
        ]

    def inspect_candidate_reviews(self, workflow_run_id: int) -> list[dict[str, object]]:
        statement = (
            select(GlossaryCandidateReview, GlossaryDraftCandidate, WorkflowStepRun)
            .join(
                GlossaryDraftCandidate,
                GlossaryDraftCandidate.id == GlossaryCandidateReview.draft_candidate_id,
            )
            .join(
                WorkflowStepRun,
                WorkflowStepRun.id == GlossaryCandidateReview.step_run_id,
            )
            .where(GlossaryDraftCandidate.workflow_run_id == workflow_run_id)
            .order_by(GlossaryCandidateReview.id.asc())
        )
        return [
            {
                "id": review.id,
                "draft_candidate_id": review.draft_candidate_id,
                "step_run_id": review.step_run_id,
                "workflow_run_id": step_run.workflow_run_id,
                "step_key": step_run.step_key,
                "action": step_run.action,
                "llm_role": step_run.llm_role,
                "review_type": review.review_type,
                "decision": review.decision,
                "score": review.score,
                "reason_codes": review.reason_codes,
                "structured_payload": review.structured_payload,
                "project_id": draft_candidate.project_id,
                "chapter_id": draft_candidate.chapter_id,
                "source_term": draft_candidate.source_term,
                "suggested_term": draft_candidate.suggested_term,
                "category": draft_candidate.category,
                "gender": draft_candidate.gender,
                "age_group": draft_candidate.age_group,
                "scope_level": draft_candidate.scope_level,
                "scope_chapter_id": draft_candidate.scope_chapter_id,
                "evidence_payload": draft_candidate.evidence_payload,
                "status": draft_candidate.status,
                "term_group_key": draft_candidate.term_group_key,
                "relation_role": draft_candidate.relation_role,
            }
            for review, draft_candidate, step_run in self.session.execute(statement).all()
        ]

    def _ensure_chapter_belongs_to_project(self, *, project_id: int, chapter_id: int) -> Chapter:
        chapter = self.session.get(Chapter, chapter_id)
        if chapter is None:
            raise ValueError(f"找不到 chapter_id={chapter_id}。")
        if chapter.project_id != project_id:
            raise ValueError(f"chapter_id={chapter_id} 不属于 project_id={project_id}。")
        return chapter

    def _normalize_entry_scope(
        self,
        *,
        scope_level: str,
        scope_chapter_id: int | None,
    ) -> tuple[str, int | None]:
        normalized_scope_level = scope_level.strip()
        if normalized_scope_level == "project_term":
            if scope_chapter_id is not None:
                raise ValueError("scope_level=project_term 时不能提供 scope_chapter_id。")
            return normalized_scope_level, None
        if normalized_scope_level == "chapter_term":
            if scope_chapter_id is None:
                raise ValueError("scope_level=chapter_term 时必须提供 scope_chapter_id。")
            return normalized_scope_level, scope_chapter_id
        raise ValueError(f"不支持的 scope_level={normalized_scope_level}。")

    def _build_entry_scope_anchor(
        self,
        *,
        scope_level: str,
        scope_chapter_id: int | None,
    ) -> str:
        if scope_level == "project_term":
            return "project"
        return f"chapter:{scope_chapter_id}"

    def _normalize_candidate_scope(
        self,
        *,
        chapter_id: int,
        scope_level: str | None,
        scope_chapter_id: int | None,
    ) -> tuple[str, int | None]:
        normalized_scope_level = (scope_level or "chapter_term").strip()
        if normalized_scope_level == "project_term":
            if scope_chapter_id is not None:
                raise ValueError("scope_level=project_term 时不能提供 scope_chapter_id。")
            return normalized_scope_level, None
        if normalized_scope_level == "chapter_term":
            return normalized_scope_level, scope_chapter_id or chapter_id
        raise ValueError(f"不支持的 scope_level={normalized_scope_level}。")

    def _build_entry_scope_condition(
        self,
        *,
        scope_level: str,
        scope_chapter_id: int | None,
        include_project_scope: bool = False,
    ):
        scope_anchors = [
            self._build_entry_scope_anchor(
                scope_level=scope_level,
                scope_chapter_id=scope_chapter_id,
            )
        ]
        if include_project_scope and scope_level == "chapter_term":
            scope_anchors.append("project")
        if len(scope_anchors) == 1:
            return GlossaryEntry.scope_anchor == scope_anchors[0]
        return GlossaryEntry.scope_anchor.in_(scope_anchors)
