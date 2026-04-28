from __future__ import annotations

import hashlib
from pathlib import Path

from ..db.models import TranslationProject
from ..errors import ToolError
from ..repositories.glossary import GlossaryRepository
from .glossary_existing_term_context_service import GlossaryExistingTermContextService
from .glossary_extraction_quality_service import GlossaryExtractionQualityService
from .glossary_service import GlossaryService
from .glossary_types import GlossaryChapterExtractionResult, GlossaryExtraction, MatchedExistingGlossaryTerm


class GlossaryWorkflowDomainService:
    def __init__(self, session, *, provider=None) -> None:
        self.session = session
        self.provider = provider
        self.glossary = GlossaryRepository(session)
        self.glossary_service = GlossaryService(session, provider=provider)
        self.existing_term_context = GlossaryExistingTermContextService(self.glossary)
        self.extraction_quality = GlossaryExtractionQualityService()

    def extract_draft_candidates(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        scope: dict[str, object],
        model_profile_id: str,
        provider_model_name: str | None,
    ) -> dict[str, object]:
        project = self.session.get(TranslationProject, project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        chapters = self.glossary_service._resolve_chapters(project_id=project_id, scope=scope)
        if not chapters:
            raise ToolError(code="invalid_arguments", message="scope 范围内没有可处理的章节。", status=400)

        created = 0
        skipped_chapters: list[dict[str, object]] = []
        chapter_results: list[GlossaryChapterExtractionResult] = []
        quality_issues: list[dict[str, object]] = []
        batch_context_terms: list[MatchedExistingGlossaryTerm] = []
        actual_model_name = provider_model_name or model_profile_id
        self.glossary_service.reset_generation_tracking()
        for chapter in chapters:
            chapter_text = Path(chapter.normalized_path).read_text(encoding="utf-8")
            source_hash = hashlib.sha256(chapter_text.encode("utf-8")).hexdigest()
            persisted_matched_terms = self.existing_term_context.list_matched_terms_for_chapter(
                project_id=project_id,
                chapter_id=chapter.id,
                chapter_title=chapter.chapter_title,
                chapter_text=chapter_text,
            )
            batch_matched_terms = self._list_matched_batch_terms_for_chapter(
                batch_context_terms=batch_context_terms,
                chapter_title=chapter.chapter_title,
                chapter_text=chapter_text,
            )
            matched_existing_terms = self._merge_matched_terms(
                persisted_matched_terms,
                batch_matched_terms,
            )
            try:
                extraction = self.glossary_service._extract_terms(
                    chapter_text=chapter_text,
                    chapter_index=chapter.chapter_index,
                    chapter_title=chapter.chapter_title,
                    source_language=project.source_language,
                    target_language=project.target_language,
                    model_name=actual_model_name,
                    matched_existing_terms=matched_existing_terms,
                    risk_signals=[],
                )
            except ToolError as exc:
                skipped_chapters.append(
                    {
                        "chapter_id": chapter.id,
                        "chapter_index": chapter.chapter_index,
                        "chapter_title": chapter.chapter_title,
                        "code": exc.code,
                        "message": exc.message,
                    }
                )
                self.glossary.upsert_chapter_status(
                    project_id=project_id,
                    chapter_id=chapter.id,
                    source_hash=source_hash,
                    extraction_status="skipped",
                    candidate_count=0,
                    finalized_count=0,
                    quality_issue_count=1,
                    workflow_run_id=workflow_run_id,
                    workflow_step_run_id=workflow_step_run_id,
                    model_profile_id=model_profile_id,
                    model_name=actual_model_name,
                    reason=exc.message,
                )
                continue
            quality_result = self.extraction_quality.evaluate(
                chapter_id=chapter.id,
                chapter_index=chapter.chapter_index,
                chapter_title=chapter.chapter_title,
                chapter_text=chapter_text,
                envelope=extraction,
                matched_existing_terms=matched_existing_terms,
            )
            if self.extraction_quality.should_run_llm_quality_review(quality_result):
                llm_review = self.glossary_service._review_extraction_quality(
                    chapter_text=chapter_text,
                    chapter_index=chapter.chapter_index,
                    chapter_title=chapter.chapter_title,
                    extraction_payload=quality_result.as_payload(),
                    quality_issues=[issue.as_payload() for issue in quality_result.quality_issues],
                    model_name=actual_model_name,
                )
                if any(issue.suggested_action == "targeted_reextract" for issue in llm_review.issues):
                    risk_signals = [
                        issue.issue_type
                        for issue in quality_result.quality_issues + llm_review.issues
                    ]
                    retry_extraction = self.glossary_service._extract_terms(
                        chapter_text=chapter_text,
                        chapter_index=chapter.chapter_index,
                        chapter_title=chapter.chapter_title,
                        source_language=project.source_language,
                        target_language=project.target_language,
                        model_name=actual_model_name,
                        matched_existing_terms=matched_existing_terms,
                        risk_signals=risk_signals,
                        previous_extraction=quality_result.as_payload(),
                    )
                    quality_result = self.extraction_quality.evaluate(
                        chapter_id=chapter.id,
                        chapter_index=chapter.chapter_index,
                        chapter_title=chapter.chapter_title,
                        chapter_text=chapter_text,
                        envelope=retry_extraction,
                        matched_existing_terms=matched_existing_terms,
                    )
                quality_result = GlossaryChapterExtractionResult(
                    chapter_id=quality_result.chapter_id,
                    chapter_index=quality_result.chapter_index,
                    chapter_title=quality_result.chapter_title,
                    status=quality_result.status,
                    terms=quality_result.terms,
                    matched_existing_terms=quality_result.matched_existing_terms,
                    reason=quality_result.reason,
                    quality_issues=quality_result.quality_issues,
                    llm_quality_review=llm_review.as_payload(),
                )
            chapter_results.append(quality_result)
            quality_issues.extend(
                issue.as_payload()
                | {
                    "chapter_id": chapter.id,
                    "chapter_index": chapter.chapter_index,
                }
                for issue in quality_result.quality_issues
            )
            decided_terms = self.glossary_service._decide_terms(
                project=project,
                chapter=chapter,
                extracted_terms=quality_result.terms,
                model_name=actual_model_name,
            )
            chapter_candidate_count = 0
            for item in decided_terms:
                self.glossary.create_draft_candidate(
                    workflow_run_id=workflow_run_id,
                    project_id=project_id,
                    chapter_id=chapter.id,
                    source_term=item.source_term,
                    suggested_term=item.suggested_term,
                    category=item.category,
                    gender=item.gender,
                    age_group=item.age_group,
                    term_group_key=item.term_group_key,
                    relation_role=item.relation_role,
                    scope_level="project_term",
                    scope_chapter_id=None,
                    evidence_payload={
                        "workflow_step_run_id": workflow_step_run_id,
                        "chapter_id": chapter.id,
                        "chapter_index": chapter.chapter_index,
                        "chapter_title": chapter.chapter_title,
                        "note": item.note,
                        "gender": item.gender,
                        "age_group": item.age_group,
                    },
                    status="pending",
                )
                created += 1
                chapter_candidate_count += 1
                batch_context_terms.append(
                    self._build_batch_context_term(item)
                )
            self.glossary.upsert_chapter_status(
                project_id=project_id,
                chapter_id=chapter.id,
                source_hash=source_hash,
                extraction_status=quality_result.status,
                candidate_count=chapter_candidate_count,
                finalized_count=0,
                quality_issue_count=len(quality_result.quality_issues),
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=workflow_step_run_id,
                model_profile_id=model_profile_id,
                model_name=actual_model_name,
                reason=quality_result.reason,
            )
        status_counts: dict[str, int] = {
            "terms_found": 0,
            "no_new_terms": 0,
            "suspicious_empty": 0,
            "skipped": len(skipped_chapters),
        }
        for result in chapter_results:
            status_counts[result.status] = status_counts.get(result.status, 0) + 1
        payload: dict[str, object] = {
            "draft_candidate_count": created,
            "chapter_results": [result.as_payload() for result in chapter_results],
            "terms_found_count": status_counts.get("terms_found", 0),
            "no_new_terms_count": status_counts.get("no_new_terms", 0),
            "suspicious_empty_count": status_counts.get("suspicious_empty", 0),
            "skipped_chapter_count": status_counts.get("skipped", 0),
            "quality_issues": quality_issues,
        }
        if skipped_chapters:
            payload["skipped_chapters"] = skipped_chapters
        return payload | self.glossary_service.build_generation_metadata()

    def _list_matched_batch_terms_for_chapter(
        self,
        *,
        batch_context_terms: list[MatchedExistingGlossaryTerm],
        chapter_title: str,
        chapter_text: str,
    ) -> list[MatchedExistingGlossaryTerm]:
        if not batch_context_terms:
            return []
        matched_terms = self.existing_term_context.translation_assets.build_prompt_glossary_entries(
            glossary_entries=batch_context_terms,
            source_text=f"{chapter_title}\n{chapter_text}",
        )
        return sorted(
            matched_terms,
            key=lambda item: (
                str(item.scope_level),
                int(item.scope_chapter_id or 0),
                str(item.term_group_key),
                str(item.relation_role),
                str(item.source_term),
            ),
        )

    def _merge_matched_terms(
        self,
        *term_groups: list[MatchedExistingGlossaryTerm],
    ) -> list[MatchedExistingGlossaryTerm]:
        merged: list[MatchedExistingGlossaryTerm] = []
        seen: set[tuple[str, int | None, str]] = set()
        for terms in term_groups:
            for term in terms:
                key = (term.scope_level, term.scope_chapter_id, term.source_term)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(term)
        return merged

    def _build_batch_context_term(self, item: GlossaryExtraction) -> MatchedExistingGlossaryTerm:
        return MatchedExistingGlossaryTerm(
            source_term=item.source_term,
            target_term=item.suggested_term,
            category=item.category,
            note=item.note,
            gender=item.gender,
            age_group=item.age_group,
            term_group_key=item.term_group_key,
            relation_role=item.relation_role,
            scope_level="project_term",
            scope_chapter_id=None,
        )

    def normalize_candidates(self, *, workflow_run_id: int, workflow_step_run_id: int) -> dict[str, object]:
        draft_items = self.glossary.list_draft_candidates(workflow_run_id=workflow_run_id)
        unique_terms = {
            (
                item.chapter_id,
                item.source_term,
                item.suggested_term,
                item.category,
                item.gender,
                item.age_group,
                item.term_group_key,
                item.relation_role,
            )
            for item in draft_items
        }
        return {
            "draft_candidate_count": len(draft_items),
            "normalized_candidate_count": len(unique_terms),
            "workflow_step_run_id": workflow_step_run_id,
        }

    def review_relation_candidates(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
    ) -> dict[str, object]:
        draft_items = self.glossary.list_draft_candidates(workflow_run_id=workflow_run_id)
        self.glossary_service.reset_generation_tracking()
        decisions = self.glossary_service._review_relationships(
            draft_items=draft_items,
            model_name=provider_model_name or model_profile_id,
        )
        for item in decisions:
            self.glossary.create_candidate_review(
                draft_candidate_id=int(item["draft_candidate_id"]),
                step_run_id=workflow_step_run_id,
                review_type="relation",
                decision=str(item["relation_role"]),
                score=float(item["score"]) if item.get("score") is not None else None,
                reason_codes=[str(code) for code in item.get("reason_codes", [])],
                structured_payload=dict(item),
            )
        return {
            "draft_candidate_count": len(draft_items),
            "reviewed_count": len(decisions),
        } | self.glossary_service.build_generation_metadata()

    def review_scope_candidates(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
    ) -> dict[str, object]:
        draft_items = self.glossary.list_draft_candidates(workflow_run_id=workflow_run_id)
        self.glossary_service.reset_generation_tracking()
        decisions = self.glossary_service._review_scope_levels(
            draft_items=draft_items,
            model_name=provider_model_name or model_profile_id,
        )
        for item in decisions:
            self.glossary.create_candidate_review(
                draft_candidate_id=int(item["draft_candidate_id"]),
                step_run_id=workflow_step_run_id,
                review_type="scope",
                decision=str(item["scope_level"]),
                score=float(item["score"]) if item.get("score") is not None else None,
                reason_codes=[str(code) for code in item.get("reason_codes", [])],
                structured_payload=dict(item),
            )
        return {
            "draft_candidate_count": len(draft_items),
            "reviewed_count": len(decisions),
        } | self.glossary_service.build_generation_metadata()

    def finalize_candidates(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
    ) -> dict[str, object]:
        result = self.glossary_service.finalize_from_workflow(
            workflow_run_id=workflow_run_id,
            workflow_step_run_id=workflow_step_run_id,
            project_id=project_id,
            model_name=provider_model_name or model_profile_id,
        )
        return {
            "candidate_count": result.candidate_count,
            "workflow_step_run_id": workflow_step_run_id,
            "finalized_terms": self.glossary_service.build_finalized_terms_preview(
                workflow_run_id=workflow_run_id
            ),
        }
