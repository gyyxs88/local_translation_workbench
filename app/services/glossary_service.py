from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, replace
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
from .glossary_types import (
    GlossaryExtraction,
    GlossaryExtractionEnvelope,
    GlossaryLlmQualityReview,
    MatchedExistingGlossaryTerm,
)
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
        route_preset_key: str | None = None,
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
            pipeline=GlossaryPipelineService(
                self.session,
                provider=self.provider,
                parallel_session_factory=workflow_runtime.log_session_factory,
            ),
            stage_run_id=stage_run_id,
            route_preset_key=route_preset_key,
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
        status_rows = self.glossary.list_chapter_statuses(project_id)
        chapter_map = self._load_chapter_map(chapter_ids=[int(status.chapter_id) for status in status_rows])
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
            "chapter_statuses": [
                self._build_chapter_status_payload(status=status, chapter=chapter_map.get(int(status.chapter_id)))
                for status in status_rows
            ],
            "relation_groups": self.relation_groups.build_relation_groups(
                items=entry_rows,
                member_id_field="entry_id",
            ),
        }

    def _load_chapter_map(self, *, chapter_ids: list[int]) -> dict[int, Chapter]:
        if not chapter_ids:
            return {}
        rows = self.session.execute(
            select(Chapter).where(Chapter.id.in_(sorted(set(chapter_ids))))
        ).scalars().all()
        return {int(chapter.id): chapter for chapter in rows}

    def _build_chapter_status_payload(self, *, status, chapter: Chapter | None) -> dict[str, object]:
        current_source_hash = None if chapter is None else self._read_current_chapter_hash(chapter)
        return {
            "id": int(status.id),
            "project_id": int(status.project_id),
            "chapter_id": int(status.chapter_id),
            "chapter_index": None if chapter is None else int(chapter.chapter_index),
            "chapter_title": None if chapter is None else str(chapter.chapter_title),
            "workflow_run_id": None if status.workflow_run_id is None else int(status.workflow_run_id),
            "workflow_step_run_id": (
                None if status.workflow_step_run_id is None else int(status.workflow_step_run_id)
            ),
            "source_hash": str(status.source_hash),
            "current_source_hash": current_source_hash,
            "is_stale": current_source_hash is None or current_source_hash != str(status.source_hash),
            "extraction_status": str(status.extraction_status),
            "candidate_count": int(status.candidate_count),
            "finalized_count": int(status.finalized_count),
            "quality_issue_count": int(status.quality_issue_count),
            "model_profile_id": status.model_profile_id,
            "model_name": status.model_name,
            "reason": status.reason,
        }

    def _read_current_chapter_hash(self, chapter: Chapter) -> str | None:
        try:
            text = Path(chapter.normalized_path).read_text(encoding="utf-8")
        except OSError:
            return None
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

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
        matched_existing_terms: list[MatchedExistingGlossaryTerm],
        risk_signals: list[str],
        previous_extraction: dict[str, object] | None = None,
    ) -> GlossaryExtractionEnvelope:
        if self.provider is None:
            raise ToolError(code="invalid_arguments", message="缺少术语提取 provider。", status=400)
        prompt = self.prompts.build_extraction_prompt(
            chapter_text=chapter_text,
            chapter_index=chapter_index,
            chapter_title=chapter_title,
            source_language=source_language,
            target_language=target_language,
            matched_existing_terms=matched_existing_terms,
            risk_signals=risk_signals,
            previous_extraction=previous_extraction,
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
                return replace(self.prompts.parse_extraction_response(repair_response.content), repaired=True)
            except ToolError as repair_error:
                repair_error.details = {
                    "first_error": first_error.message,
                    "repair_error": repair_error.message,
                }
                self._attach_generation_metadata_to_exception(repair_error)
                raise

    def _review_extraction_quality(
        self,
        *,
        chapter_text: str,
        chapter_index: int,
        chapter_title: str,
        extraction_payload: dict[str, object],
        quality_issues: list[dict[str, object]],
        model_name: str,
    ) -> GlossaryLlmQualityReview:
        if self.provider is None:
            raise ToolError(code="invalid_arguments", message="缺少术语质检 provider。", status=400)
        prompt = self.prompts.build_extraction_quality_review_prompt(
            chapter_text=chapter_text,
            chapter_index=chapter_index,
            chapter_title=chapter_title,
            extraction_payload=extraction_payload,
            quality_issues=quality_issues,
        )
        response = self.provider.generate_text(
            prompt=prompt,
            model_name=model_name,
            timeout_seconds=60,
        )
        self._generation_results.append(response)
        return self.prompts.parse_extraction_quality_review_response(response.content)

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

    def _review_consistency(
        self,
        *,
        project_id: int,
        draft_items: list[GlossaryDraftCandidate],
        model_name: str,
    ) -> list[dict[str, object]]:
        if not draft_items:
            return []
        active_entries = [
            item
            for item in self.glossary.list_entries(project_id)
            if str(item.status) == "active"
        ]
        default_items = self._build_default_consistency_reviews(
            draft_items=draft_items,
            active_entries=active_entries,
        )
        if self.provider is None:
            return default_items
        prompt = self.prompts.build_consistency_review_prompt(
            draft_items=draft_items,
            active_entries=active_entries,
            deterministic_reviews=default_items,
        )
        try:
            response = self.provider.generate_text(prompt=prompt, model_name=model_name, timeout_seconds=120)
        except ToolError:
            return default_items
        self._generation_results.append(response)
        parsed_items = self.prompts.parse_review_items(response.content, "items")
        return self._merge_consistency_reviews(
            draft_items=draft_items,
            parsed_items=parsed_items,
            default_items=default_items,
        )

    def _build_default_consistency_reviews(
        self,
        *,
        draft_items: list[GlossaryDraftCandidate],
        active_entries: list[GlossaryEntry],
    ) -> list[dict[str, object]]:
        issues_by_draft_id: dict[int, list[dict[str, object]]] = {
            int(item.id): [] for item in draft_items
        }
        self._add_same_source_translation_conflicts(
            draft_items=draft_items,
            issues_by_draft_id=issues_by_draft_id,
        )
        self._add_active_glossary_conflicts(
            draft_items=draft_items,
            active_entries=active_entries,
            issues_by_draft_id=issues_by_draft_id,
        )
        self._add_relation_group_conflicts(
            draft_items=draft_items,
            issues_by_draft_id=issues_by_draft_id,
        )

        return [
            self._build_consistency_review_payload(
                draft_item=item,
                issues=issues_by_draft_id[int(item.id)],
                style_baseline=self._build_style_baseline(
                    category=item.category,
                    active_entries=active_entries,
                ),
            )
            for item in draft_items
        ]

    def _add_same_source_translation_conflicts(
        self,
        *,
        draft_items: list[GlossaryDraftCandidate],
        issues_by_draft_id: dict[int, list[dict[str, object]]],
    ) -> None:
        grouped: dict[str, list[GlossaryDraftCandidate]] = defaultdict(list)
        for item in draft_items:
            grouped[item.source_term].append(item)
        for source_term, members in grouped.items():
            target_terms = sorted({item.suggested_term for item in members if item.suggested_term.strip()})
            if len(target_terms) <= 1:
                continue
            draft_candidate_ids = [int(item.id) for item in members]
            for item in members:
                issues_by_draft_id[int(item.id)].append(
                    {
                        "code": "source_translation_conflict",
                        "severity": "warning",
                        "source_term": source_term,
                        "target_terms": target_terms,
                        "draft_candidate_ids": draft_candidate_ids,
                    }
                )

    def _add_active_glossary_conflicts(
        self,
        *,
        draft_items: list[GlossaryDraftCandidate],
        active_entries: list[GlossaryEntry],
        issues_by_draft_id: dict[int, list[dict[str, object]]],
    ) -> None:
        active_by_source: dict[str, list[GlossaryEntry]] = defaultdict(list)
        for entry in active_entries:
            active_by_source[entry.source_term].append(entry)
        for item in draft_items:
            matching_entries = active_by_source.get(item.source_term, [])
            if not matching_entries:
                continue
            preferred = sorted(matching_entries, key=lambda entry: (0 if int(entry.locked or 0) else 1, entry.id))[0]
            if preferred.target_term == item.suggested_term:
                continue
            issues_by_draft_id[int(item.id)].append(
                {
                    "code": "active_glossary_target_conflict",
                    "severity": "error" if int(preferred.locked or 0) else "warning",
                    "source_term": item.source_term,
                    "draft_target_term": item.suggested_term,
                    "preferred_target_term": preferred.target_term,
                    "active_entry_id": int(preferred.id),
                    "locked": bool(preferred.locked),
                }
            )

    def _add_relation_group_conflicts(
        self,
        *,
        draft_items: list[GlossaryDraftCandidate],
        issues_by_draft_id: dict[int, list[dict[str, object]]],
    ) -> None:
        grouped: dict[str, list[GlossaryDraftCandidate]] = defaultdict(list)
        for item in draft_items:
            grouped[item.term_group_key].append(item)
        for term_group_key, members in grouped.items():
            if len(members) <= 1:
                continue
            canonical_count = sum(1 for item in members if item.relation_role == "canonical")
            category_values = {item.category for item in members if item.category}
            gender_values = {item.gender for item in members if item.category == "character" and item.gender}
            age_values = {item.age_group for item in members if item.category == "character" and item.age_group}
            group_issues: list[dict[str, object]] = []
            if canonical_count == 0:
                group_issues.append({"code": "missing_canonical", "severity": "warning"})
            elif canonical_count > 1:
                group_issues.append({"code": "multiple_canonical", "severity": "warning"})
            if len(category_values) > 1:
                group_issues.append({"code": "mixed_category", "severity": "warning"})
            if len(gender_values) > 1:
                group_issues.append({"code": "gender_conflict", "severity": "warning"})
            if len(age_values) > 1:
                group_issues.append({"code": "age_group_conflict", "severity": "warning"})
            if not group_issues:
                continue
            member_ids = [int(item.id) for item in members]
            for item in members:
                for issue in group_issues:
                    issues_by_draft_id[int(item.id)].append(
                        {
                            **issue,
                            "term_group_key": term_group_key,
                            "draft_candidate_ids": member_ids,
                        }
                    )

    def _build_style_baseline(
        self,
        *,
        category: str,
        active_entries: list[GlossaryEntry],
    ) -> dict[str, object]:
        examples = [
            {
                "entry_id": int(entry.id),
                "source_term": entry.source_term,
                "target_term": entry.target_term,
                "term_group_key": entry.term_group_key,
                "relation_role": entry.relation_role,
                "locked": bool(entry.locked),
            }
            for entry in active_entries
            if entry.category == category
        ][:12]
        return {
            "source": "active_glossary",
            "category": category,
            "entry_count": len(examples),
            "examples": examples,
            "status": "available" if examples else "missing",
        }

    def _build_consistency_review_payload(
        self,
        *,
        draft_item: GlossaryDraftCandidate,
        issues: list[dict[str, object]],
        style_baseline: dict[str, object],
    ) -> dict[str, object]:
        severities = {str(issue.get("severity") or "warning") for issue in issues}
        suggested_term = self._preferred_target_term_from_issues(issues)
        if "error" in severities:
            decision = "conflict"
            score = 0.0
        elif issues:
            decision = "warning"
            score = 0.5
        else:
            decision = "pass"
            score = 1.0
        payload: dict[str, object] = {
            "draft_candidate_id": int(draft_item.id),
            "decision": decision,
            "score": score,
            "reason_codes": self._collect_issue_codes(issues),
            "issues": issues,
            "style_baseline": style_baseline,
        }
        if suggested_term is not None:
            payload["suggested_term"] = suggested_term
        return payload

    def _preferred_target_term_from_issues(self, issues: list[dict[str, object]]) -> str | None:
        for issue in issues:
            preferred_target_term = self.prompts.normalize_text(issue.get("preferred_target_term"))
            if preferred_target_term:
                return preferred_target_term
        return None

    def _collect_issue_codes(self, issues: list[dict[str, object]]) -> list[str]:
        codes: list[str] = []
        for issue in issues:
            code = self.prompts.normalize_text(issue.get("code"))
            if code and code not in codes:
                codes.append(code)
        return codes

    def _merge_consistency_reviews(
        self,
        *,
        draft_items: list[GlossaryDraftCandidate],
        parsed_items: list[dict[str, object]],
        default_items: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        draft_ids = {int(item.id) for item in draft_items}
        parsed_by_id: dict[int, dict[str, object]] = {}
        for item in parsed_items:
            draft_candidate_id = item.get("draft_candidate_id")
            if isinstance(draft_candidate_id, int) and draft_candidate_id in draft_ids:
                parsed_by_id[draft_candidate_id] = item

        merged_items: list[dict[str, object]] = []
        for default_item in default_items:
            draft_candidate_id = int(default_item["draft_candidate_id"])
            parsed_item = parsed_by_id.get(draft_candidate_id)
            if parsed_item is None:
                merged_items.append(default_item)
                continue
            default_issues = [
                dict(issue) for issue in default_item.get("issues", []) if isinstance(issue, dict)
            ]
            parsed_issues = [
                dict(issue) for issue in parsed_item.get("issues", []) if isinstance(issue, dict)
            ]
            reason_codes = self._merge_reason_codes(
                default_item.get("reason_codes"),
                parsed_item.get("reason_codes"),
                parsed_issues,
            )
            decision = self.prompts.normalize_text(parsed_item.get("decision")) or str(default_item["decision"])
            if any(str(issue.get("severity")) == "error" for issue in default_issues):
                decision = "conflict"
            merged: dict[str, object] = {
                **default_item,
                **parsed_item,
                "draft_candidate_id": draft_candidate_id,
                "decision": decision,
                "reason_codes": reason_codes,
                "issues": default_issues + parsed_issues,
                "style_baseline": default_item["style_baseline"],
            }
            if "score" not in parsed_item:
                merged["score"] = default_item["score"]
            merged_items.append(merged)
        return merged_items

    def _merge_reason_codes(
        self,
        default_codes: object,
        parsed_codes: object,
        parsed_issues: list[dict[str, object]],
    ) -> list[str]:
        merged: list[str] = []
        for raw_codes in (default_codes, parsed_codes):
            if not isinstance(raw_codes, list):
                continue
            for code in raw_codes:
                normalized_code = self.prompts.normalize_text(code)
                if normalized_code and normalized_code not in merged:
                    merged.append(normalized_code)
        if not (isinstance(parsed_codes, list) and parsed_codes):
            for issue in parsed_issues:
                normalized_code = self.prompts.normalize_text(issue.get("code"))
                if normalized_code and normalized_code not in merged:
                    merged.append(normalized_code)
        return merged

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
        project_scope_terms, chapter_scope_terms = self._build_retained_existing_terms_from_extract_payload(
            workflow_run_id=workflow_run_id,
        )
        for item in finalized_terms:
            source_chapter_id = int(item["chapter_id"])
            scope_level = str(item["scope_level"])
            scope_chapter_id = item.get("scope_chapter_id")
            if scope_level == "project_term":
                scope_chapter_id = None
                project_scope_terms.add(str(item["source_term"]))
            else:
                if scope_chapter_id is None:
                    scope_chapter_id = int(item["chapter_id"])
                chapter_scope_terms.setdefault(int(scope_chapter_id), set()).add(str(item["source_term"]))
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
                chapter_id=source_chapter_id,
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

        finalized_counts_by_chapter: dict[int, int] = {}
        for item in finalized_terms:
            source_chapter_id = int(item["chapter_id"])
            finalized_counts_by_chapter[source_chapter_id] = finalized_counts_by_chapter.get(source_chapter_id, 0) + 1
        for chapter_id in chapter_ids:
            self.glossary.update_chapter_status_finalized_count(
                project_id=project_id,
                chapter_id=chapter_id,
                finalized_count=finalized_counts_by_chapter.get(chapter_id, 0),
            )

        self.glossary.delete_unlocked_entries_not_in_terms(
            project_id,
            sorted(project_scope_terms),
            scope_level="project_term",
        )
        for chapter_id in chapter_ids:
            self.glossary.delete_unlocked_entries_not_in_terms(
                project_id,
                sorted(chapter_scope_terms.get(chapter_id, set())),
                scope_level="chapter_term",
                scope_chapter_id=chapter_id,
            )
        self.project_staleness.mark_glossary_downstream_stale(project_id=project_id, chapters=chapters)
        return GlossaryResult(candidate_count=candidate_count)

    def _build_retained_existing_terms_from_extract_payload(
        self,
        *,
        workflow_run_id: int,
    ) -> tuple[set[str], dict[int, set[str]]]:
        project_scope_terms: set[str] = set()
        chapter_scope_terms: dict[int, set[str]] = {}
        statement = (
            select(WorkflowStepRun)
            .where(
                WorkflowStepRun.workflow_run_id == workflow_run_id,
                WorkflowStepRun.action == "glossary.extract",
            )
            .order_by(WorkflowStepRun.id.asc())
        )
        for step_run in self.session.execute(statement).scalars().all():
            if not isinstance(step_run.output_payload, dict):
                continue
            chapter_results = step_run.output_payload.get("chapter_results")
            if not isinstance(chapter_results, list):
                continue
            for chapter_result in chapter_results:
                if not isinstance(chapter_result, dict):
                    continue
                matched_terms = chapter_result.get("matched_existing_terms")
                if not isinstance(matched_terms, list):
                    continue
                for term in matched_terms:
                    if not isinstance(term, dict):
                        continue
                    source_term = str(term.get("source_term") or "").strip()
                    if source_term == "":
                        continue
                    scope_level = str(term.get("scope_level") or "project_term")
                    if scope_level == "project_term":
                        project_scope_terms.add(source_term)
                        continue
                    if scope_level != "chapter_term":
                        continue
                    raw_scope_chapter_id = term.get("scope_chapter_id") or chapter_result.get("chapter_id")
                    if raw_scope_chapter_id is None:
                        continue
                    chapter_scope_terms.setdefault(int(raw_scope_chapter_id), set()).add(source_term)
        return project_scope_terms, chapter_scope_terms

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
