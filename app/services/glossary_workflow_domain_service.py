from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from ..db.models import Chapter, TranslationProject
from ..errors import ToolError
from ..repositories.glossary import GlossaryRepository
from ..token_usage import merge_token_usage_payloads
from .glossary_extraction_progress_service import GlossaryExtractionProgressTracker
from .glossary_existing_term_context_service import GlossaryExistingTermContextService
from .glossary_extraction_quality_service import GlossaryExtractionQualityService
from .glossary_service import GlossaryService
from .glossary_types import GlossaryChapterExtractionResult, GlossaryExtraction, MatchedExistingGlossaryTerm


class GlossaryWorkflowDomainService:
    def __init__(
        self,
        session,
        *,
        provider=None,
        parallel_session_factory=None,
        max_parallel_workers: int = 3,
    ) -> None:
        self.session = session
        self.provider = provider
        self.parallel_session_factory = parallel_session_factory
        self.max_parallel_workers = max(1, int(max_parallel_workers))
        self.glossary = GlossaryRepository(session)
        self.glossary_service = GlossaryService(session, provider=provider)
        self.existing_term_context = GlossaryExistingTermContextService(self.glossary)
        self.extraction_quality = GlossaryExtractionQualityService()

    def fork_for_session(self, session) -> "GlossaryWorkflowDomainService":
        return GlossaryWorkflowDomainService(
            session,
            provider=self.provider,
            parallel_session_factory=self.parallel_session_factory,
            max_parallel_workers=self.max_parallel_workers,
        )

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

        actual_model_name = provider_model_name or model_profile_id
        session_factory = self._parallel_session_factory()
        max_workers = self._chapter_worker_count(chapter_count=len(chapters))
        self.session.commit()
        progress_tracker = GlossaryExtractionProgressTracker(
            session_factory=session_factory,
            workflow_step_run_id=workflow_step_run_id,
            chapters=chapters,
            max_parallel_workers=max_workers,
        )
        progress_tracker.initialize()

        try:
            if self._should_run_chapters_parallel(chapter_count=len(chapters)):
                chapter_outputs = self._extract_chapters_parallel(
                    chapters=chapters,
                    progress_tracker=progress_tracker,
                    workflow_run_id=workflow_run_id,
                    workflow_step_run_id=workflow_step_run_id,
                    project_id=project_id,
                    model_profile_id=model_profile_id,
                    actual_model_name=actual_model_name,
                )
            else:
                chapter_outputs = []
                for chapter in chapters:
                    try:
                        output = self._extract_chapter_in_session(
                            progress_tracker=progress_tracker,
                            workflow_run_id=workflow_run_id,
                            workflow_step_run_id=workflow_step_run_id,
                            project_id=project_id,
                            chapter_id=int(chapter.id),
                            model_profile_id=model_profile_id,
                            actual_model_name=actual_model_name,
                        )
                        self.session.commit()
                        self._mark_chapter_finished_from_output(
                            progress_tracker=progress_tracker,
                            output=output,
                        )
                        chapter_outputs.append(output)
                    except Exception as exc:
                        self.session.rollback()
                        progress_tracker.mark_failed(chapter_id=int(chapter.id), error=str(exc))
                        raise
        except Exception as exc:
            self._attach_progress_to_exception(exc, progress_tracker=progress_tracker)
            raise

        return self._build_extract_payload(
            chapter_outputs=chapter_outputs,
            progress=progress_tracker.snapshot(),
        )

    def _extract_chapters_parallel(
        self,
        *,
        chapters: list[Chapter],
        progress_tracker: GlossaryExtractionProgressTracker,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        model_profile_id: str,
        actual_model_name: str,
    ) -> list[dict[str, object]]:
        with ThreadPoolExecutor(max_workers=self._chapter_worker_count(chapter_count=len(chapters))) as executor:
            futures = [
                executor.submit(
                    self._extract_chapter_in_parallel_session,
                    progress_tracker=progress_tracker,
                    workflow_run_id=workflow_run_id,
                    workflow_step_run_id=workflow_step_run_id,
                    project_id=project_id,
                    chapter_id=int(chapter.id),
                    model_profile_id=model_profile_id,
                    actual_model_name=actual_model_name,
                )
                for chapter in chapters
            ]
            return [future.result() for future in futures]

    def _extract_chapter_in_parallel_session(
        self,
        *,
        progress_tracker: GlossaryExtractionProgressTracker,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        chapter_id: int,
        model_profile_id: str,
        actual_model_name: str,
    ) -> dict[str, object]:
        worker_session = self._parallel_session_factory()()
        try:
            worker = self.fork_for_session(worker_session)
            result = worker._extract_chapter_in_session(
                progress_tracker=progress_tracker,
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=workflow_step_run_id,
                project_id=project_id,
                chapter_id=chapter_id,
                model_profile_id=model_profile_id,
                actual_model_name=actual_model_name,
            )
            worker_session.commit()
            self._mark_chapter_finished_from_output(
                progress_tracker=progress_tracker,
                output=result,
            )
            return result
        except Exception as exc:
            worker_session.rollback()
            progress_tracker.mark_failed(chapter_id=chapter_id, error=str(exc))
            raise
        finally:
            worker_session.close()

    def _extract_chapter_in_session(
        self,
        *,
        progress_tracker: GlossaryExtractionProgressTracker,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        chapter_id: int,
        model_profile_id: str,
        actual_model_name: str,
    ) -> dict[str, object]:
        project = self.session.get(TranslationProject, project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)
        chapter = self.session.get(Chapter, chapter_id)
        if chapter is None:
            raise ToolError(code="not_found", message=f"找不到章节 {chapter_id}。", status=404)

        self.glossary_service.reset_generation_tracking()
        progress_tracker.mark_running(chapter_id=chapter_id)
        return self._extract_chapter_core(
            workflow_run_id=workflow_run_id,
            workflow_step_run_id=workflow_step_run_id,
            project=project,
            chapter=chapter,
            model_profile_id=model_profile_id,
            actual_model_name=actual_model_name,
        )

    def _extract_chapter_core(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project: TranslationProject,
        chapter: Chapter,
        model_profile_id: str,
        actual_model_name: str,
    ) -> dict[str, object]:
        chapter_text = Path(chapter.normalized_path).read_text(encoding="utf-8")
        source_hash = hashlib.sha256(chapter_text.encode("utf-8")).hexdigest()
        persisted_matched_terms = self.existing_term_context.list_matched_terms_for_chapter(
            project_id=project.id,
            chapter_id=chapter.id,
            chapter_title=chapter.chapter_title,
            chapter_text=chapter_text,
        )
        matched_existing_terms = self._merge_matched_terms(persisted_matched_terms)
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
            skipped_chapter = {
                "chapter_id": chapter.id,
                "chapter_index": chapter.chapter_index,
                "chapter_title": chapter.chapter_title,
                "code": exc.code,
                "message": exc.message,
            }
            self.glossary.upsert_chapter_status(
                project_id=project.id,
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
            return {
                "chapter_id": int(chapter.id),
                "chapter_index": int(chapter.chapter_index),
                "created": 0,
                "chapter_result": None,
                "quality_issues": [],
                "skipped_chapter": skipped_chapter,
                "generation_metadata": self.glossary_service.build_generation_metadata(),
                "progress_status": "skipped",
                "progress_error": exc.message,
            }

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
                project_id=project.id,
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
            chapter_candidate_count += 1
        self.glossary.upsert_chapter_status(
            project_id=project.id,
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
        return {
            "chapter_id": int(chapter.id),
            "chapter_index": int(chapter.chapter_index),
            "created": chapter_candidate_count,
            "chapter_result": quality_result.as_payload(),
            "quality_issues": [
                issue.as_payload()
                | {
                    "chapter_id": chapter.id,
                    "chapter_index": chapter.chapter_index,
                }
                for issue in quality_result.quality_issues
            ],
            "skipped_chapter": None,
            "generation_metadata": self.glossary_service.build_generation_metadata(),
            "progress_status": "completed",
            "progress_extraction_status": quality_result.status,
            "progress_candidate_count": chapter_candidate_count,
            "progress_quality_issue_count": len(quality_result.quality_issues),
        }

    def _mark_chapter_finished_from_output(
        self,
        *,
        progress_tracker: GlossaryExtractionProgressTracker,
        output: dict[str, object],
    ) -> None:
        chapter_id = int(output["chapter_id"])
        progress_status = str(output.get("progress_status") or "completed")
        if progress_status == "skipped":
            progress_tracker.mark_skipped(
                chapter_id=chapter_id,
                error=str(output.get("progress_error") or "章节被跳过。"),
            )
            return
        progress_tracker.mark_completed(
            chapter_id=chapter_id,
            extraction_status=str(output.get("progress_extraction_status") or "completed"),
            candidate_count=int(output.get("progress_candidate_count") or 0),
            quality_issue_count=int(output.get("progress_quality_issue_count") or 0),
        )

    def _build_extract_payload(
        self,
        *,
        chapter_outputs: list[dict[str, object]],
        progress: dict[str, object],
    ) -> dict[str, object]:
        sorted_outputs = sorted(chapter_outputs, key=lambda item: int(item.get("chapter_index") or 0))
        skipped_chapters = [
            dict(item["skipped_chapter"])
            for item in sorted_outputs
            if isinstance(item.get("skipped_chapter"), dict)
        ]
        chapter_results = [
            dict(item["chapter_result"])
            for item in sorted_outputs
            if isinstance(item.get("chapter_result"), dict)
        ]
        quality_issues: list[dict[str, object]] = []
        for item in sorted_outputs:
            raw_issues = item.get("quality_issues")
            if isinstance(raw_issues, list):
                quality_issues.extend(dict(issue) for issue in raw_issues if isinstance(issue, dict))

        status_counts: dict[str, int] = {
            "terms_found": 0,
            "no_new_terms": 0,
            "suspicious_empty": 0,
            "skipped": len(skipped_chapters),
        }
        for result in chapter_results:
            status = str(result.get("status") or "")
            status_counts[status] = status_counts.get(status, 0) + 1

        payload: dict[str, object] = {
            "draft_candidate_count": sum(int(item.get("created") or 0) for item in sorted_outputs),
            "chapter_results": chapter_results,
            "terms_found_count": status_counts.get("terms_found", 0),
            "no_new_terms_count": status_counts.get("no_new_terms", 0),
            "suspicious_empty_count": status_counts.get("suspicious_empty", 0),
            "skipped_chapter_count": status_counts.get("skipped", 0),
            "quality_issues": quality_issues,
            "progress": progress,
        }
        if skipped_chapters:
            payload["skipped_chapters"] = skipped_chapters
        return payload | self._merge_generation_metadata(
            [
                dict(item["generation_metadata"])
                for item in sorted_outputs
                if isinstance(item.get("generation_metadata"), dict)
            ]
        )

    def _merge_generation_metadata(self, metadata_items: list[dict[str, object]]) -> dict[str, object]:
        if not metadata_items:
            return {}
        payload: dict[str, object] = {}
        for key in ("model_name", "provider_name", "model_profile_id"):
            for item in reversed(metadata_items):
                if item.get(key) not in {None, ""}:
                    payload[key] = item[key]
                    break
        fallback_depths = []
        for item in metadata_items:
            try:
                fallback_depths.append(int(item.get("fallback_depth") or 0))
            except (TypeError, ValueError):
                continue
        if fallback_depths:
            payload["fallback_depth"] = max(fallback_depths)
        token_usage = merge_token_usage_payloads(item.get("token_usage") for item in metadata_items)
        if token_usage is not None:
            payload["token_usage"] = token_usage
        return payload

    def _attach_progress_to_exception(
        self,
        error: Exception,
        *,
        progress_tracker: GlossaryExtractionProgressTracker,
    ) -> None:
        payload = {"progress": progress_tracker.snapshot()}
        existing_payload = getattr(error, "_step_output_payload", None)
        if isinstance(existing_payload, dict):
            payload = dict(existing_payload) | payload
        setattr(error, "_step_output_payload", payload)

    def _should_run_chapters_parallel(self, *, chapter_count: int) -> bool:
        return chapter_count > 1 and self._chapter_worker_count(chapter_count=chapter_count) > 1

    def _chapter_worker_count(self, *, chapter_count: int) -> int:
        return max(1, min(int(chapter_count), self.max_parallel_workers))

    def _parallel_session_factory(self):
        if self.parallel_session_factory is not None:
            return self.parallel_session_factory
        return sessionmaker(
            bind=self.session.get_bind(),
            autoflush=False,
            expire_on_commit=False,
            future=True,
        )

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

    def review_consistency_candidates(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
    ) -> dict[str, object]:
        draft_items = self.glossary.list_draft_candidates(workflow_run_id=workflow_run_id)
        self.glossary_service.reset_generation_tracking()
        decisions = self.glossary_service._review_consistency(
            project_id=project_id,
            draft_items=draft_items,
            model_name=provider_model_name or model_profile_id,
        )
        issue_counts: dict[str, int] = {}
        active_baseline_count = 0
        for item in decisions:
            structured_payload = dict(item)
            style_baseline = structured_payload.get("style_baseline")
            if isinstance(style_baseline, dict):
                active_baseline_count += int(style_baseline.get("entry_count") or 0)
            issues = structured_payload.get("issues")
            if isinstance(issues, list):
                for issue in issues:
                    if not isinstance(issue, dict):
                        continue
                    code = str(issue.get("code") or "").strip()
                    if not code:
                        continue
                    issue_counts[code] = issue_counts.get(code, 0) + 1
            self.glossary.create_candidate_review(
                draft_candidate_id=int(item["draft_candidate_id"]),
                step_run_id=workflow_step_run_id,
                review_type="consistency",
                decision=str(item["decision"]),
                score=float(item["score"]) if item.get("score") is not None else None,
                reason_codes=[str(code) for code in item.get("reason_codes", [])],
                structured_payload=structured_payload,
            )
        return {
            "draft_candidate_count": len(draft_items),
            "reviewed_count": len(decisions),
            "active_baseline_count": active_baseline_count,
            "issue_counts": issue_counts,
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
