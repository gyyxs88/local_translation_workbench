from __future__ import annotations

import hashlib
from pathlib import Path
from time import perf_counter
from typing import Callable

from sqlalchemy import and_, select

from ..db.models import Chapter, ChapterSegment, SegmentTranslation, SegmentTranslationVersion, TranslationProject
from ..errors import ToolError
from ..providers.base import Provider
from ..repositories.glossary import GlossaryRepository
from ..repositories.translations import TranslationRepository
from ..token_usage import merge_token_usage_payloads, summarize_generation_results
from ..utils import ensure_directory
from .review_prompt_service import ReviewPromptService
from .translation_assets_service import TranslationAssetsService

ReviewRow = tuple[Chapter, ChapterSegment, SegmentTranslation | None, SegmentTranslationVersion | None]


class ReviewQualityLoopService:
    def __init__(self, session, *, base_data_dir: Path, provider: Provider | None) -> None:
        self.session = session
        self.base_data_dir = Path(base_data_dir)
        self.provider = provider
        self.prompts = ReviewPromptService()
        self.glossary = GlossaryRepository(session)
        self.translations = TranslationRepository(session)
        self.translation_assets = TranslationAssetsService()

    def resolve_review_rows_for_tests(self, *, project_id: int) -> list[ReviewRow]:
        statement = (
            select(Chapter, ChapterSegment, SegmentTranslation, SegmentTranslationVersion)
            .join(ChapterSegment, ChapterSegment.chapter_id == Chapter.id)
            .outerjoin(
                SegmentTranslation,
                and_(SegmentTranslation.segment_id == ChapterSegment.id, SegmentTranslation.project_id == project_id),
            )
            .outerjoin(SegmentTranslationVersion, SegmentTranslationVersion.id == SegmentTranslation.active_version_id)
            .where(Chapter.project_id == project_id, ChapterSegment.project_id == project_id)
            .order_by(Chapter.chapter_index.asc(), ChapterSegment.segment_index.asc())
        )
        return list(self.session.execute(statement).all())

    def run(
        self,
        *,
        project_id: int,
        rows: list[ReviewRow],
        hard_issues_by_segment: dict[int, list[dict[str, object]]],
        model_profile_id: str,
        provider_model_name: str | None,
        max_rewrite_rounds: int,
        progress_callback: Callable[[dict[str, object]], None] | None = None,
        heartbeat: Callable[[], None] | None = None,
    ) -> dict[str, object]:
        if self.provider is None:
            raise ToolError(code="invalid_arguments", message="review_mode=hybrid 需要可用 provider。", status=400)
        project = self.session.get(TranslationProject, project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        all_issues: list[dict[str, object]] = []
        rewrite_version_ids: list[int] = []
        round_summaries: list[dict[str, object]] = []
        token_payloads: list[dict[str, int]] = []
        passed_count = 0
        needs_revision_count = 0

        for chapter, segment, translation, version in rows:
            completed_before_segment = passed_count + needs_revision_count
            self._emit_progress(
                progress_callback,
                {
                    "phase": "segment_started",
                    "segment_id": int(segment.id),
                    "chapter_index": int(chapter.chapter_index),
                    "segment_index": int(segment.segment_index),
                    "completed_segments": completed_before_segment,
                },
            )
            result = self._run_segment_loop(
                project=project,
                chapter=chapter,
                segment=segment,
                translation=translation,
                version=version,
                hard_issues=hard_issues_by_segment.get(int(segment.id), []),
                model_profile_id=model_profile_id,
                provider_model_name=provider_model_name or model_profile_id,
                max_rewrite_rounds=max_rewrite_rounds,
                progress_callback=progress_callback,
                heartbeat=heartbeat,
                completed_segments=completed_before_segment,
            )
            all_issues.extend(result["issues"])
            rewrite_version_ids.extend(int(item) for item in result["rewrite_version_ids"])
            round_summaries.extend(result["rounds"])
            if result["status"] == "reviewed":
                segment.review_status = "reviewed"
                passed_count += 1
            else:
                segment.review_status = "needs_revision"
                needs_revision_count += 1
            if result.get("token_usage") is not None:
                token_payloads.append(result["token_usage"])
            self._emit_progress(
                progress_callback,
                {
                    "phase": "segment_completed",
                    "segment_id": int(segment.id),
                    "chapter_index": int(chapter.chapter_index),
                    "segment_index": int(segment.segment_index),
                    "segment_status": str(result["status"]),
                    "completed_segments": passed_count + needs_revision_count,
                    "issue_count": len(all_issues),
                    "rewrite_segment_count": len(set(rewrite_version_ids)),
                },
            )

        return {
            "issues": all_issues,
            "passed_segment_count": passed_count,
            "needs_revision_segment_count": needs_revision_count,
            "rewrite_segment_count": len(set(rewrite_version_ids)),
            "rewrite_version_ids": rewrite_version_ids,
            "rounds": round_summaries,
            "token_usage": merge_token_usage_payloads(token_payloads),
        }

    def _run_segment_loop(
        self,
        *,
        project: TranslationProject,
        chapter: Chapter,
        segment: ChapterSegment,
        translation: SegmentTranslation | None,
        version: SegmentTranslationVersion | None,
        hard_issues: list[dict[str, object]],
        model_profile_id: str,
        provider_model_name: str,
        max_rewrite_rounds: int,
        progress_callback: Callable[[dict[str, object]], None] | None = None,
        heartbeat: Callable[[], None] | None = None,
        completed_segments: int = 0,
    ) -> dict[str, object]:
        if version is None or translation is None:
            return {"status": "needs_revision", "issues": hard_issues, "rewrite_version_ids": [], "rounds": []}

        issues = list(hard_issues)
        rewrite_version_ids: list[int] = []
        round_summaries: list[dict[str, object]] = []
        token_payloads: list[dict[str, int]] = []
        current_version = version
        current_translation = translation
        prior_blocking_issues = list(hard_issues)

        for round_index in range(max_rewrite_rounds + 1):
            if heartbeat is not None:
                heartbeat()
            source_text = Path(segment.source_text_path).read_text(encoding="utf-8").strip()
            glossary_entries = self._matched_glossary_entries(
                project_id=int(project.id),
                chapter_id=int(chapter.id),
                source_text=source_text,
            )
            self._emit_progress(
                progress_callback,
                {
                    "phase": "llm_review",
                    "segment_id": int(segment.id),
                    "chapter_index": int(chapter.chapter_index),
                    "segment_index": int(segment.segment_index),
                    "current_round": round_index,
                    "completed_segments": completed_segments,
                },
            )
            review_started = perf_counter()
            provider_result = self.provider.generate_text(
                prompt=self.prompts.build_quality_review_prompt(
                    source_language=str(project.source_language),
                    target_language=str(project.target_language),
                    chapter_index=int(chapter.chapter_index),
                    chapter_title=str(chapter.chapter_title),
                    segment_index=int(segment.segment_index),
                    round_index=round_index,
                    source_text=source_text,
                    translated_text=str(current_version.translated_text),
                    glossary_entries=glossary_entries,
                    prior_issues=prior_blocking_issues,
                ),
                model_name=provider_model_name,
                timeout_seconds=120,
            )
            token_payload = summarize_generation_results([provider_result])
            if token_payload is not None:
                token_payloads.append(token_payload)
            review_payload = self.prompts.parse_quality_review_response(provider_result.content)
            llm_issues = [
                self._issue_payload(
                    chapter=chapter,
                    segment=segment,
                    version=current_version,
                    issue=item,
                    provider_result=provider_result,
                    round_index=round_index,
                )
                for item in review_payload["issues"]
            ]
            issues.extend(llm_issues)
            current_hard_issues = hard_issues if round_index == 0 else []
            blocking_issues = [
                item
                for item in current_hard_issues + llm_issues
                if bool(item.get("requires_rewrite")) or str(item.get("severity")) == "high"
            ]
            round_summaries.append(
                {
                    "segment_id": int(segment.id),
                    "round_index": round_index,
                    "llm_review_elapsed_seconds": round(perf_counter() - review_started, 3),
                    "llm_issue_count": len(llm_issues),
                    "blocking_issue_count": len(blocking_issues),
                    "review_model": provider_result.model_name,
                }
            )
            if not blocking_issues:
                return {
                    "status": "reviewed",
                    "issues": issues,
                    "rewrite_version_ids": rewrite_version_ids,
                    "rounds": round_summaries,
                    "token_usage": merge_token_usage_payloads(token_payloads),
                }
            if round_index >= max_rewrite_rounds:
                return {
                    "status": "needs_revision",
                    "issues": issues,
                    "rewrite_version_ids": rewrite_version_ids,
                    "rounds": round_summaries,
                    "token_usage": merge_token_usage_payloads(token_payloads),
                }

            if heartbeat is not None:
                heartbeat()
            self._emit_progress(
                progress_callback,
                {
                    "phase": "rewrite",
                    "segment_id": int(segment.id),
                    "chapter_index": int(chapter.chapter_index),
                    "segment_index": int(segment.segment_index),
                    "current_round": round_index,
                    "completed_segments": completed_segments,
                    "blocking_issue_count": len(blocking_issues),
                },
            )
            rewrite_result = self._rewrite_segment(
                project=project,
                chapter=chapter,
                segment=segment,
                translation=current_translation,
                current_version=current_version,
                source_text=source_text,
                glossary_entries=glossary_entries,
                blocking_issues=blocking_issues,
                model_profile_id=model_profile_id,
                provider_model_name=provider_model_name,
            )
            current_version = rewrite_result["version"]
            current_translation.active_version_id = current_version.id
            rewrite_version_ids.append(int(current_version.id))
            prior_blocking_issues = blocking_issues
            if rewrite_result.get("token_usage") is not None:
                token_payloads.append(rewrite_result["token_usage"])

        return {
            "status": "needs_revision",
            "issues": issues,
            "rewrite_version_ids": rewrite_version_ids,
            "rounds": round_summaries,
            "token_usage": merge_token_usage_payloads(token_payloads),
        }

    def _emit_progress(
        self,
        progress_callback: Callable[[dict[str, object]], None] | None,
        event: dict[str, object],
    ) -> None:
        if progress_callback is not None:
            progress_callback(event)

    def _rewrite_segment(
        self,
        *,
        project: TranslationProject,
        chapter: Chapter,
        segment: ChapterSegment,
        translation: SegmentTranslation,
        current_version: SegmentTranslationVersion,
        source_text: str,
        glossary_entries: list[object],
        blocking_issues: list[dict[str, object]],
        model_profile_id: str,
        provider_model_name: str,
    ) -> dict[str, object]:
        provider_result = self.provider.generate_text(
            prompt=self.prompts.build_rewrite_prompt(
                source_language=str(project.source_language),
                target_language=str(project.target_language),
                chapter_index=int(chapter.chapter_index),
                chapter_title=str(chapter.chapter_title),
                segment_index=int(segment.segment_index),
                source_text=source_text,
                translated_text=str(current_version.translated_text),
                glossary_entries=glossary_entries,
                blocking_issues=blocking_issues,
            ),
            model_name=provider_model_name,
            timeout_seconds=180,
        )
        translated_text = self.prompts.parse_rewrite_response(provider_result.content)
        next_version_index = self.translations.get_next_version_index(int(translation.id))
        translation_root = ensure_directory(self.base_data_dir / str(project.project_key) / "translations")
        segment_output_dir = ensure_directory(translation_root / "segments" / f"{int(segment.id):08d}")
        version_path = segment_output_dir / f"v{next_version_index:04d}.txt"
        current_path = segment_output_dir / "current.txt"
        version_path.write_text(translated_text, encoding="utf-8")
        current_path.write_text(translated_text, encoding="utf-8")
        version = self.translations.create_version(
            project_id=int(project.id),
            segment_translation_id=int(translation.id),
            version_index=next_version_index,
            source_hash=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
            glossary_snapshot_id=self.translation_assets.compute_glossary_snapshot_id(glossary_entries),
            provider_name=provider_result.provider_name,
            model_profile_id=provider_result.model_profile_id or model_profile_id,
            model_name=provider_result.model_name,
            source_text=source_text,
            translated_text=translated_text,
            translated_text_path=str(version_path),
            status="completed",
        )
        segment.translation_status = "translated"
        segment.review_status = "pending"
        return {"version": version, "token_usage": summarize_generation_results([provider_result])}

    def _matched_glossary_entries(self, *, project_id: int, chapter_id: int, source_text: str) -> list[object]:
        entries = self.glossary.list_active_entries_for_matching(
            project_id,
            scope_level="chapter_term",
            scope_chapter_id=chapter_id,
            include_project_scope=True,
        )
        return self.translation_assets.build_prompt_glossary_entries(
            glossary_entries=entries,
            source_text=source_text,
        )

    def _issue_payload(
        self,
        *,
        chapter: Chapter,
        segment: ChapterSegment,
        version: SegmentTranslationVersion,
        issue: dict[str, object],
        provider_result,
        round_index: int,
    ) -> dict[str, object]:
        return {
            "project_id": int(chapter.project_id),
            "chapter_id": int(chapter.id),
            "segment_id": int(segment.id),
            "version_id": int(version.id),
            "issue_type": str(issue["issue_type"]),
            "severity": str(issue["severity"]),
            "message": str(issue["message"]),
            "status": "open",
            "issue_source": "llm",
            "round_index": round_index,
            "requires_rewrite": bool(issue["requires_rewrite"]),
            "structured_payload": {
                "source_evidence": issue.get("source_evidence"),
                "translation_evidence": issue.get("translation_evidence"),
                "rewrite_instruction": issue.get("rewrite_instruction"),
                "raw_issue": issue.get("raw_issue"),
                "reviewer_model": provider_result.model_name,
                "reviewer_model_profile_id": provider_result.model_profile_id,
                "fallback_depth": int(provider_result.fallback_depth or 0),
            },
        }
