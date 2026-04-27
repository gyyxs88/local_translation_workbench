from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import (
    Chapter,
    ChapterSegment,
    ExportRun,
    GlossaryCandidate,
    GlossaryDraftCandidate,
    GlossaryEntry,
    ReviewRun,
    SegmentTranslation,
    SegmentTranslationVersion,
    StageRun,
    TranslationProject,
    WorkflowRun,
    WorkflowStepRun,
)
from ..errors import ToolError
from ..providers.base import Provider, TextGenerationResult
from ..repositories.glossary import GlossaryRepository
from ..token_usage import summarize_generation_results
from .glossary_finalize_service import GlossaryFinalizeService
from .glossary_prompt_service import GlossaryPromptService
from .glossary_relation_group_service import GlossaryRelationGroupService
from .glossary_types import GlossaryExtraction
from .project_staleness_service import ProjectStalenessService
from .scope_service import ensure_scope_supported, get_stage_scope_types
from .workflow_profile_service import WorkflowProfileService
from .workflow_runtime_service import WorkflowRuntimeService


@dataclass(frozen=True)
class GlossaryResult:
    candidate_count: int
    token_usage: dict[str, int] | None = None


class GlossaryService:
    def __init__(self, session: Session, *, provider: Provider | None = None) -> None:
        self.session = session
        self.provider = provider
        self.glossary = GlossaryRepository(session)
        self._generation_results: list[TextGenerationResult] = []
        self.project_staleness = ProjectStalenessService(session)
        self.relation_groups = GlossaryRelationGroupService()
        self.prompts = GlossaryPromptService()
        self.finalizer = GlossaryFinalizeService(
            glossary=self.glossary,
            provider=self.provider,
            prompts=self.prompts,
        )

    def seed_locked_entry(self, *, project_id: int, source_term: str, target_term: str) -> GlossaryEntry:
        existing = self.glossary.get_entry(project_id, source_term)
        if existing is None:
            entry = self.glossary.create_entry(
                project_id=project_id,
                source_term=source_term,
                target_term=target_term,
                locked=1,
                term_group_key=source_term,
                relation_role="independent",
            )
        else:
            existing.target_term = target_term
            existing.locked = 1
            entry = existing
        self.session.commit()
        return entry

    def get_entry(self, *, project_id: int, source_term: str) -> GlossaryEntry:
        entry = self.glossary.get_entry(project_id, source_term)
        if entry is None:
            raise ToolError(code="not_found", message=f"找不到术语 {source_term}。", status=404)
        return entry

    def run(
        self,
        *,
        request_id: str,
        project_id: int,
        scope: dict[str, object],
        model_profile_id: str = "default",
        provider_model_name: str | None = None,
        workflow_key: str | None = None,
        stage_run_id: int | None = None,
        heartbeat: Callable[[], None] | None = None,
    ) -> GlossaryResult:
        project = self.session.get(TranslationProject, project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)
        ensure_scope_supported(scope, stage="glossary", allowed_types=get_stage_scope_types("glossary"))
        if self.provider is None:
            raise ToolError(code="invalid_arguments", message="缺少术语提取 provider。", status=400)
        profile_service = WorkflowProfileService(self.session)
        if profile_service.ensure_builtin_profiles():
            if stage_run_id is None:
                self.session.commit()
            else:
                self.session.flush()

        workflow_runtime = WorkflowRuntimeService(self.session)
        workflow_definition = workflow_runtime.resolve_workflow_definition(stage="glossary", workflow_key=workflow_key)

        from .glossary_pipeline_service import GlossaryPipelineService

        result = workflow_runtime.run_glossary_workflow(
            workflow_definition=workflow_definition,
            workflow_key=str(workflow_definition["workflow_key"]),
            request_id=request_id,
            project_id=project_id,
            scope=scope,
            request_model_profile_id=model_profile_id,
            provider_model_name=provider_model_name,
            pipeline=GlossaryPipelineService(self.session, provider=self.provider),
            stage_run_id=stage_run_id,
            heartbeat=heartbeat,
        )

        summary = json.dumps(
            {
                "request_id": request_id,
                "candidate_count": result.candidate_count,
                **({"token_usage": result.token_usage} if result.token_usage is not None else {}),
            },
            ensure_ascii=False,
        )
        if stage_run_id is None:
            self.session.add(
                StageRun(
                    project_id=project_id,
                    stage="glossary",
                    scope_type=str(scope["type"]),
                    scope_value=json.dumps(scope, ensure_ascii=False),
                    status="completed",
                    summary=summary,
                )
            )
            self.session.commit()
        else:
            stage_run = self.session.get(StageRun, stage_run_id)
            if stage_run is None:
                raise ToolError(code="not_found", message=f"找不到 stage_run {stage_run_id}。", status=404)
            self.session.flush()
        return result

    def inspect(self, *, project_id: int) -> dict[str, list[dict[str, object]]]:
        entry_rows = self.glossary.list_entries(project_id)
        candidate_rows = self.glossary.list_candidates(project_id)
        entries = [
            {
                "id": entry.id,
                "project_id": entry.project_id,
                "source_term": entry.source_term,
                "target_term": entry.target_term,
                "category": entry.category,
                "gender": entry.gender,
                "age_group": entry.age_group,
                "status": entry.status,
                "locked": entry.locked,
                "term_group_key": entry.term_group_key,
                "relation_role": entry.relation_role,
            }
            for entry in entry_rows
        ]
        candidates = [
            {
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
            }
            for candidate in candidate_rows
        ]
        return {
            "entries": entries,
            "candidates": candidates,
            "relation_groups": self.relation_groups.build_relation_groups(
                items=entry_rows,
                member_id_field="entry_id",
            ),
        }

    def build_finalized_terms_preview(self, *, workflow_run_id: int) -> list[dict[str, object]]:
        finalize_step = self.session.execute(
            select(WorkflowStepRun)
            .where(
                WorkflowStepRun.workflow_run_id == workflow_run_id,
                WorkflowStepRun.action == "glossary.finalize",
            )
            .order_by(WorkflowStepRun.id.desc())
        ).scalars().first()
        if finalize_step is not None and isinstance(finalize_step.output_payload, dict):
            finalized_terms = finalize_step.output_payload.get("finalized_terms")
            if isinstance(finalized_terms, list):
                return [item for item in finalized_terms if isinstance(item, dict)]

        workflow_run = self.session.get(WorkflowRun, workflow_run_id)
        if workflow_run is None:
            return []
        return [
            {
                "draft_candidate_id": None,
                "chapter_id": candidate.chapter_id,
                "source_term": candidate.source_term,
                "target_term": candidate.suggested_term,
                "category": candidate.category,
                "note": candidate.note,
                "gender": candidate.gender,
                "age_group": candidate.age_group,
                "term_group_key": candidate.term_group_key,
                "relation_role": candidate.relation_role,
                "scope_level": candidate.scope_level,
                "scope_chapter_id": candidate.scope_chapter_id,
            }
            for candidate in self.glossary.list_candidates(workflow_run.project_id)
            if candidate.workflow_run_id == workflow_run_id
        ]

    def reset_generation_tracking(self) -> None:
        self._generation_results = []

    def build_generation_metadata(self) -> dict[str, object]:
        if not self._generation_results:
            return {}
        last_result = self._generation_results[-1]
        payload: dict[str, object] = {
            "model_name": last_result.model_name,
            "provider_name": last_result.provider_name,
            "fallback_depth": max(int(item.fallback_depth or 0) for item in self._generation_results),
        }
        if last_result.model_profile_id:
            payload["model_profile_id"] = last_result.model_profile_id
        token_usage = summarize_generation_results(self._generation_results)
        if token_usage is not None:
            payload["token_usage"] = token_usage
        return payload

    def _attach_generation_metadata_to_exception(self, error: Exception) -> None:
        payload = self.build_generation_metadata()
        if not payload:
            return
        existing_payload = getattr(error, "_step_output_payload", None)
        if isinstance(existing_payload, dict):
            payload = dict(existing_payload) | payload
        setattr(error, "_step_output_payload", payload)

    def _resolve_chapters(self, *, project_id: int, scope: dict[str, object]) -> list[Chapter]:
        ensure_scope_supported(scope, stage="glossary", allowed_types=get_stage_scope_types("glossary"))
        statement = select(Chapter).where(Chapter.project_id == project_id)
        scope_type = str(scope["type"])
        if scope_type == "chapter_range":
            statement = statement.where(
                Chapter.chapter_index >= int(scope["start"]),
                Chapter.chapter_index <= int(scope["end"]),
            )
        if scope_type == "chapter_list":
            statement = statement.where(Chapter.chapter_index.in_(list(scope["chapters"])))
        statement = statement.order_by(Chapter.chapter_index.asc())
        return list(self.session.execute(statement).scalars().all())

    def _extract_terms(
        self,
        *,
        chapter_text: str,
        chapter_index: int,
        chapter_title: str,
        source_language: str,
        target_language: str,
        model_name: str,
    ) -> list[GlossaryExtraction]:
        if self.provider is None:
            raise ToolError(code="invalid_arguments", message="缺少术语提取 provider。", status=400)
        prompt = self.prompts.build_extraction_prompt(
            chapter_text=chapter_text,
            chapter_index=chapter_index,
            chapter_title=chapter_title,
            source_language=source_language,
            target_language=target_language,
        )
        response = self.provider.generate_text(
            prompt=prompt,
            model_name=model_name,
            timeout_seconds=60,
        )
        self._generation_results.append(response)
        try:
            return self.prompts.parse_extraction_response(response.content)
        except ToolError as first_error:
            repair_prompt = self.prompts.build_extraction_json_repair_prompt(
                broken_content=response.content,
            )
            repair_response = self.provider.generate_text(
                prompt=repair_prompt,
                model_name=model_name,
                timeout_seconds=60,
            )
            self._generation_results.append(repair_response)
            try:
                return self.prompts.parse_extraction_response(repair_response.content)
            except ToolError as repair_error:
                repair_error.details = {
                    "first_error": first_error.message,
                    "repair_error": repair_error.message,
                }
                self._attach_generation_metadata_to_exception(repair_error)
                raise

    def _decide_terms(
        self,
        *,
        project: TranslationProject,
        chapter: Chapter,
        extracted_terms: list[GlossaryExtraction],
        model_name: str,
    ) -> list[GlossaryExtraction]:
        if not extracted_terms:
            return []
        return self.prompts.filter_extracted_terms(extracted_terms)

    def _review_relationships(
        self,
        *,
        draft_items: list[GlossaryDraftCandidate],
        model_name: str,
    ) -> list[dict[str, object]]:
        if not draft_items:
            return []
        default_items = [
            {
                "draft_candidate_id": item.id,
                "term_group_key": item.term_group_key,
                "relation_role": item.relation_role,
                "score": 1.0,
                "reason_codes": ["carry_forward"],
            }
            for item in draft_items
        ]
        if self.provider is None:
            return default_items
        prompt = self.prompts.build_relationship_review_prompt(draft_items)
        try:
            response = self.provider.generate_text(prompt=prompt, model_name=model_name, timeout_seconds=120)
        except ToolError:
            return default_items
        self._generation_results.append(response)
        parsed_items = self.prompts.parse_review_items(response.content, "items")
        return self.prompts.merge_review_items_with_defaults(
            draft_items=draft_items,
            parsed_items=parsed_items,
            default_items=default_items,
        )

    def _review_scope_levels(
        self,
        *,
        draft_items: list[GlossaryDraftCandidate],
        model_name: str,
    ) -> list[dict[str, object]]:
        if not draft_items:
            return []
        default_items = [
            {
                "draft_candidate_id": item.id,
                "scope_level": item.scope_level,
                "scope_chapter_id": item.scope_chapter_id,
                "score": 1.0,
                "reason_codes": ["carry_forward"],
            }
            for item in draft_items
        ]
        if self.provider is None:
            return default_items
        prompt = self.prompts.build_scope_review_prompt(draft_items)
        try:
            response = self.provider.generate_text(prompt=prompt, model_name=model_name, timeout_seconds=120)
        except ToolError:
            return default_items
        self._generation_results.append(response)
        parsed_items = self.prompts.parse_review_items(response.content, "items")
        return self.prompts.merge_review_items_with_defaults(
            draft_items=draft_items,
            parsed_items=parsed_items,
            default_items=default_items,
        )

    def finalize_from_workflow(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        model_name: str,
    ) -> GlossaryResult:
        project = self.session.get(TranslationProject, project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)
        workflow_run = self.session.get(WorkflowRun, workflow_run_id)
        if workflow_run is None:
            raise ToolError(code="not_found", message=f"找不到 workflow_run {workflow_run_id}。", status=404)

        draft_items = self.glossary.list_draft_candidates(workflow_run_id=workflow_run_id)
        chapters = self._resolve_workflow_chapters(
            project_id=project_id,
            workflow_run=workflow_run,
            draft_items=draft_items,
        )
        chapter_ids = [chapter.id for chapter in chapters]
        if chapter_ids:
            self.glossary.delete_candidates_for_chapters(project_id, chapter_ids)

        finalized_terms = self.finalizer.build_finalized_terms(
            workflow_run_id=workflow_run_id,
            draft_items=draft_items,
            model_name=model_name,
        )
        candidate_count = 0
        project_scope_terms: list[str] = []
        chapter_scope_terms: dict[int, list[str]] = {}
        for item in finalized_terms:
            scope_level = str(item["scope_level"])
            scope_chapter_id = item.get("scope_chapter_id")
            if scope_level == "project_term":
                scope_chapter_id = None
                project_scope_terms.append(str(item["source_term"]))
            else:
                if scope_chapter_id is None:
                    scope_chapter_id = int(item["chapter_id"])
                chapter_scope_terms.setdefault(int(scope_chapter_id), []).append(str(item["source_term"]))
            entry = self.glossary.get_entry(
                project_id,
                str(item["source_term"]),
                scope_level=scope_level,
                scope_chapter_id=int(scope_chapter_id) if scope_chapter_id is not None else None,
            )
            if entry is None:
                self.glossary.create_entry(
                    project_id=project_id,
                    source_term=str(item["source_term"]),
                    target_term=str(item["target_term"]),
                    category=str(item["category"]),
                    note=self.prompts.normalize_optional_text(item.get("note")),
                    gender=self.prompts.normalize_gender(
                        category=str(item["category"]),
                        gender=item.get("gender"),
                    ),
                    age_group=self.prompts.normalize_age_group(
                        category=str(item["category"]),
                        age_group=item.get("age_group"),
                    ),
                    locked=0,
                    term_group_key=str(item["term_group_key"]),
                    relation_role=str(item["relation_role"]),
                    scope_level=scope_level,
                    scope_chapter_id=int(scope_chapter_id) if scope_chapter_id is not None else None,
                )
            elif entry.locked == 0:
                entry.target_term = str(item["target_term"])
                entry.category = str(item["category"])
                entry.note = self.prompts.normalize_optional_text(item.get("note"))
                entry.gender = self.prompts.normalize_gender(category=entry.category, gender=item.get("gender"))
                entry.age_group = self.prompts.normalize_age_group(
                    category=entry.category,
                    age_group=item.get("age_group"),
                )
                entry.status = "active"
                entry.term_group_key = str(item["term_group_key"])
                entry.relation_role = str(item["relation_role"])
                entry.scope_level = scope_level
                entry.scope_chapter_id = int(scope_chapter_id) if scope_chapter_id is not None else None
                entry.scope_anchor = "project" if scope_level == "project_term" else f"chapter:{scope_chapter_id}"

            self.glossary.create_candidate(
                project_id=project_id,
                chapter_id=int(item["chapter_id"]),
                source_term=str(item["source_term"]),
                suggested_term=str(item["target_term"]),
                category=str(item["category"]),
                note=self.prompts.normalize_optional_text(item.get("note")),
                gender=self.prompts.normalize_gender(
                    category=str(item["category"]),
                    gender=item.get("gender"),
                ),
                age_group=self.prompts.normalize_age_group(
                    category=str(item["category"]),
                    age_group=item.get("age_group"),
                ),
                status="pending",
                term_group_key=str(item["term_group_key"]),
                relation_role=str(item["relation_role"]),
                scope_level=scope_level,
                scope_chapter_id=int(scope_chapter_id) if scope_chapter_id is not None else None,
                workflow_run_id=workflow_run_id,
            )
            candidate_count += 1

        self.glossary.delete_unlocked_entries_not_in_terms(
            project_id,
            project_scope_terms,
            scope_level="project_term",
        )
        for chapter_id in chapter_ids:
            self.glossary.delete_unlocked_entries_not_in_terms(
                project_id,
                chapter_scope_terms.get(chapter_id, []),
                scope_level="chapter_term",
                scope_chapter_id=chapter_id,
            )
        self.project_staleness.mark_glossary_downstream_stale(project_id=project_id, chapters=chapters)
        return GlossaryResult(candidate_count=candidate_count)

    def inspect_result(self, *, project_id: int, workflow_run_id: int) -> GlossaryResult:
        candidates = [
            candidate
            for candidate in self.glossary.list_candidates(project_id)
            if candidate.workflow_run_id == workflow_run_id
        ]
        return GlossaryResult(candidate_count=len(candidates))

    def _resolve_draft_chapters(self, draft_items: list[GlossaryDraftCandidate]) -> list[Chapter]:
        chapter_ids = sorted({item.chapter_id for item in draft_items})
        if not chapter_ids:
            return []
        statement = select(Chapter).where(Chapter.id.in_(chapter_ids)).order_by(Chapter.chapter_index.asc())
        return list(self.session.execute(statement).scalars().all())

    def _resolve_workflow_chapters(
        self,
        *,
        project_id: int,
        workflow_run: WorkflowRun,
        draft_items: list[GlossaryDraftCandidate],
    ) -> list[Chapter]:
        chapters = self._resolve_draft_chapters(draft_items)
        if chapters:
            return chapters
        scope_value = self._decode_summary(workflow_run.scope_value)
        if isinstance(scope_value, dict) and scope_value.get("type") is not None:
            return self._resolve_chapters(project_id=project_id, scope=scope_value)
        return []

    def _decode_summary(self, value: str | None) -> object:
        if value is None or value == "":
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
