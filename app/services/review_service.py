from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..db.models import (
    Chapter,
    ChapterSegment,
    ExportRun,
    ReviewIssue,
    ReviewRun,
    SegmentTranslation,
    SegmentTranslationVersion,
    StageRun,
    TranslationProject,
)
from ..errors import ToolError
from ..providers.base import Provider
from ..repositories.glossary import GlossaryRepository
from ..repositories.review import ReviewRepository
from .review_quality_loop_service import ReviewQualityLoopService
from .scope_service import ensure_scope_supported, get_stage_scope_types, scope_matches_chapters
from .translation_assets_service import TranslationAssetsService
from .translation_source_snapshot_service import TranslationSourceSnapshotService


@dataclass(frozen=True)
class ReviewResult:
    issue_count: int
    run_id: int
    mode: str = "hard_only"
    passed_segment_count: int = 0
    needs_revision_segment_count: int = 0
    rewrite_segment_count: int = 0
    rewrite_version_ids: list[int] | None = None
    token_usage: dict[str, int] | None = None


class ReviewService:
    GLOSSARY_TEXT_TRANSLATION_TABLE = str.maketrans(
        "",
        "",
        " \t\r\n,.;:!?，。！？；：'\"“”‘’()[]{}（）【】《》-_‐‑‒–—―",
    )

    def __init__(self, session: Session, *, base_data_dir: Path | None = None, provider: Provider | None = None) -> None:
        self.session = session
        self.base_data_dir = Path(base_data_dir or "data/projects")
        self.provider = provider
        self.reviews = ReviewRepository(session)
        self.translation_source = TranslationSourceSnapshotService()
        self.glossary = GlossaryRepository(session)
        self.translation_assets = TranslationAssetsService()

    def run(
        self,
        *,
        request_id: str,
        project_id: int,
        scope: dict[str, object],
        model_profile_id: str = "default",
        provider_model_name: str | None = None,
        review_mode: str = "hybrid",
        max_rewrite_rounds: int = 2,
        stage_run_id: int | None = None,
        heartbeat: Callable[[], None] | None = None,
    ) -> ReviewResult:
        project = self.session.get(TranslationProject, project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)
        ensure_scope_supported(scope, stage="review", allowed_types=get_stage_scope_types("review"))

        rows = self._resolve_segment_rows(project_id=project_id, scope=scope)
        if not rows:
            raise ToolError(code="invalid_arguments", message="scope 范围内没有可校对的段落。", status=400)

        normalized_review_mode = review_mode.strip().lower()
        if normalized_review_mode not in {"hybrid", "hard_only"}:
            raise ToolError(
                code="invalid_arguments",
                message="review_mode 只支持 hybrid 或 hard_only。",
                status=400,
            )
        if normalized_review_mode == "hybrid" and self.provider is None:
            raise ToolError(code="invalid_arguments", message="review_mode=hybrid 需要可用 provider。", status=400)

        issues: list[dict[str, object]] = []
        affected_chapter_indexes = sorted({chapter.chapter_index for chapter, *_ in rows})
        progress = self._build_progress_payload(
            total_segments=len(rows),
            phase="starting",
        )
        review_run = self.reviews.create_run(
            project_id=project_id,
            scope_type=str(scope["type"]),
            scope_value=json.dumps(scope, ensure_ascii=False),
            status="running",
            summary=json.dumps(
                self._build_running_summary(
                    request_id=request_id,
                    mode=normalized_review_mode,
                    max_rewrite_rounds=max_rewrite_rounds,
                    segment_count=len(rows),
                    issue_count=0,
                    progress=progress,
                ),
                ensure_ascii=False,
            ),
        )
        self._merge_stage_run_summary(
            stage_run_id=stage_run_id,
            payload={
                "run_id": int(review_run.id),
                "issue_count": 0,
                "progress": progress,
            },
        )
        self.session.commit()

        try:
            hard_issues_by_segment: dict[int, list[dict[str, object]]] = {}
            for hard_checked_count, (chapter, segment, _, version) in enumerate(rows, start=1):
                if heartbeat is not None:
                    heartbeat()
                source_text = Path(segment.source_text_path).read_text(encoding="utf-8").strip()
                issue = self._build_issue(
                    chapter=chapter,
                    segment=segment,
                    source_text=source_text,
                    version=version,
                )
                if issue is not None:
                    issues.append(issue)
                    hard_issues_by_segment.setdefault(int(segment.id), []).append(issue)
                progress = self._build_progress_payload(
                    total_segments=len(rows),
                    phase="hard_check",
                    hard_checked_segments=hard_checked_count,
                    running_segment_id=int(segment.id),
                    running_chapter_index=int(chapter.chapter_index),
                    running_segment_index=int(segment.segment_index),
                    issue_count=len(issues),
                )
                self._persist_review_progress(
                    review_run=review_run,
                    stage_run_id=stage_run_id,
                    request_id=request_id,
                    mode=normalized_review_mode,
                    max_rewrite_rounds=max_rewrite_rounds,
                    segment_count=len(rows),
                    issue_count=len(issues),
                    progress=progress,
                )

            loop_summary: dict[str, object] = {
                "issues": issues,
                "passed_segment_count": sum(
                    1 for _, segment, _, _ in rows if int(segment.id) not in hard_issues_by_segment
                ),
                "needs_revision_segment_count": sum(
                    1 for _, segment, _, _ in rows if int(segment.id) in hard_issues_by_segment
                ),
                "rewrite_segment_count": 0,
                "rewrite_version_ids": [],
                "rounds": [],
                "token_usage": None,
            }
            if normalized_review_mode == "hybrid":
                progress_callback = self._build_hybrid_progress_callback(
                    review_run=review_run,
                    stage_run_id=stage_run_id,
                    request_id=request_id,
                    mode=normalized_review_mode,
                    max_rewrite_rounds=max_rewrite_rounds,
                    segment_count=len(rows),
                    hard_checked_segments=len(rows),
                )
                loop_summary = ReviewQualityLoopService(
                    self.session,
                    base_data_dir=self.base_data_dir,
                    provider=self.provider,
                ).run(
                    project_id=project_id,
                    rows=rows,
                    hard_issues_by_segment=hard_issues_by_segment,
                    model_profile_id=model_profile_id,
                    provider_model_name=provider_model_name,
                    max_rewrite_rounds=max_rewrite_rounds,
                    progress_callback=progress_callback,
                    heartbeat=heartbeat,
                )
                issues = list(loop_summary["issues"])
            else:
                for _, segment, _, _ in rows:
                    segment.review_status = "needs_revision" if hard_issues_by_segment.get(int(segment.id)) else "reviewed"
                progress = self._build_progress_payload(
                    total_segments=len(rows),
                    phase="hard_only_completed",
                    hard_checked_segments=len(rows),
                    completed_segments=len(rows),
                    issue_count=len(issues),
                )
                self._persist_review_progress(
                    review_run=review_run,
                    stage_run_id=stage_run_id,
                    request_id=request_id,
                    mode=normalized_review_mode,
                    max_rewrite_rounds=max_rewrite_rounds,
                    segment_count=len(rows),
                    issue_count=len(issues),
                    progress=progress,
                )

            snapshot_rows = self._resolve_segment_rows(project_id=project_id, scope=scope)
            final_progress = self._build_progress_payload(
                total_segments=len(rows),
                phase="completed",
                hard_checked_segments=len(rows),
                completed_segments=len(rows),
                issue_count=len(issues),
                rewrite_segment_count=int(loop_summary["rewrite_segment_count"]),
            )
            summary = {
                "request_id": request_id,
                "mode": normalized_review_mode,
                "max_rewrite_rounds": max_rewrite_rounds,
                "issue_count": len(issues),
                "segment_count": len(rows),
                "passed_segment_count": int(loop_summary["passed_segment_count"]),
                "needs_revision_segment_count": int(loop_summary["needs_revision_segment_count"]),
                "rewrite_segment_count": int(loop_summary["rewrite_segment_count"]),
                "rewrite_version_ids": list(loop_summary["rewrite_version_ids"]),
                "rounds": list(loop_summary["rounds"]),
                "progress": final_progress,
                "translation_source": self.translation_source.build_snapshot(rows=snapshot_rows),
            }
            if loop_summary.get("token_usage") is not None:
                summary["token_usage"] = loop_summary["token_usage"]

            review_run.status = "completed"
            review_run.summary = json.dumps(summary, ensure_ascii=False)
            for issue in issues:
                self.reviews.create_issue(review_run_id=review_run.id, **issue)

            self._mark_related_exports_stale(
                project_id=project_id,
                affected_chapter_indexes=affected_chapter_indexes,
            )
            self._merge_stage_run_summary(
                stage_run_id=stage_run_id,
                payload={
                    "run_id": int(review_run.id),
                    "issue_count": len(issues),
                    "progress": final_progress,
                },
            )

            self.session.commit()
            return ReviewResult(
                issue_count=len(issues),
                run_id=review_run.id,
                mode=normalized_review_mode,
                passed_segment_count=int(loop_summary["passed_segment_count"]),
                needs_revision_segment_count=int(loop_summary["needs_revision_segment_count"]),
                rewrite_segment_count=int(loop_summary["rewrite_segment_count"]),
                rewrite_version_ids=[int(item) for item in loop_summary["rewrite_version_ids"]],
                token_usage=loop_summary.get("token_usage"),
            )
        except Exception as exc:
            failed_progress = self._build_progress_payload(
                total_segments=len(rows),
                phase="failed",
                hard_checked_segments=self._read_progress_int(progress, "hard_checked_segments"),
                completed_segments=self._read_progress_int(progress, "completed_segments"),
                issue_count=len(issues),
            )
            review_run.status = "failed"
            review_run.summary = json.dumps(
                self._build_running_summary(
                    request_id=request_id,
                    mode=normalized_review_mode,
                    max_rewrite_rounds=max_rewrite_rounds,
                    segment_count=len(rows),
                    issue_count=len(issues),
                    progress=failed_progress,
                )
                | {
                    "error": {
                        "code": exc.code if isinstance(exc, ToolError) else "system_error",
                        "message": exc.message if isinstance(exc, ToolError) else str(exc),
                    }
                },
                ensure_ascii=False,
            )
            self._merge_stage_run_summary(
                stage_run_id=stage_run_id,
                payload={
                    "run_id": int(review_run.id),
                    "issue_count": len(issues),
                    "progress": failed_progress,
                },
            )
            self.session.commit()
            raise

    def _build_hybrid_progress_callback(
        self,
        *,
        review_run: ReviewRun,
        stage_run_id: int | None,
        request_id: str,
        mode: str,
        max_rewrite_rounds: int,
        segment_count: int,
        hard_checked_segments: int,
    ) -> Callable[[dict[str, object]], None]:
        def persist(event: dict[str, object]) -> None:
            progress = self._build_progress_payload(
                total_segments=segment_count,
                phase=str(event.get("phase") or "hybrid"),
                hard_checked_segments=hard_checked_segments,
                completed_segments=self._read_progress_int(event, "completed_segments"),
                running_segment_id=self._read_optional_int(event.get("segment_id")),
                running_chapter_index=self._read_optional_int(event.get("chapter_index")),
                running_segment_index=self._read_optional_int(event.get("segment_index")),
                current_round=self._read_optional_int(event.get("current_round")),
                issue_count=self._read_progress_int(event, "issue_count"),
                rewrite_segment_count=self._read_progress_int(event, "rewrite_segment_count"),
                blocking_issue_count=self._read_optional_int(event.get("blocking_issue_count")),
                segment_status=None if event.get("segment_status") is None else str(event["segment_status"]),
            )
            self._persist_review_progress(
                review_run=review_run,
                stage_run_id=stage_run_id,
                request_id=request_id,
                mode=mode,
                max_rewrite_rounds=max_rewrite_rounds,
                segment_count=segment_count,
                issue_count=self._read_progress_int(progress, "issue_count"),
                progress=progress,
            )

        return persist

    def _persist_review_progress(
        self,
        *,
        review_run: ReviewRun,
        stage_run_id: int | None,
        request_id: str,
        mode: str,
        max_rewrite_rounds: int,
        segment_count: int,
        issue_count: int,
        progress: dict[str, object],
    ) -> None:
        review_run.summary = json.dumps(
            self._build_running_summary(
                request_id=request_id,
                mode=mode,
                max_rewrite_rounds=max_rewrite_rounds,
                segment_count=segment_count,
                issue_count=issue_count,
                progress=progress,
            ),
            ensure_ascii=False,
        )
        self._merge_stage_run_summary(
            stage_run_id=stage_run_id,
            payload={
                "run_id": int(review_run.id),
                "issue_count": issue_count,
                "progress": progress,
            },
        )
        self.session.commit()

    def _build_running_summary(
        self,
        *,
        request_id: str,
        mode: str,
        max_rewrite_rounds: int,
        segment_count: int,
        issue_count: int,
        progress: dict[str, object],
    ) -> dict[str, object]:
        return {
            "request_id": request_id,
            "mode": mode,
            "max_rewrite_rounds": max_rewrite_rounds,
            "issue_count": issue_count,
            "segment_count": segment_count,
            "progress": progress,
        }

    def _build_progress_payload(
        self,
        *,
        total_segments: int,
        phase: str,
        hard_checked_segments: int = 0,
        completed_segments: int = 0,
        running_segment_id: int | None = None,
        running_chapter_index: int | None = None,
        running_segment_index: int | None = None,
        current_round: int | None = None,
        issue_count: int = 0,
        rewrite_segment_count: int = 0,
        blocking_issue_count: int | None = None,
        segment_status: str | None = None,
    ) -> dict[str, object]:
        progress: dict[str, object] = {
            "phase": phase,
            "total_segments": int(total_segments),
            "hard_checked_segments": int(hard_checked_segments),
            "completed_segments": int(completed_segments),
            "pending_segments": max(int(total_segments) - int(completed_segments), 0),
            "issue_count": int(issue_count),
            "rewrite_segment_count": int(rewrite_segment_count),
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        optional_values = {
            "running_segment_id": running_segment_id,
            "running_chapter_index": running_chapter_index,
            "running_segment_index": running_segment_index,
            "current_round": current_round,
            "blocking_issue_count": blocking_issue_count,
            "segment_status": segment_status,
        }
        for key, value in optional_values.items():
            if value is not None:
                progress[key] = value
        return progress

    def _merge_stage_run_summary(self, *, stage_run_id: int | None, payload: dict[str, object]) -> None:
        if stage_run_id is None:
            return
        stage_run = self.session.get(StageRun, stage_run_id)
        if stage_run is None:
            return
        summary = self._decode_summary(stage_run.summary)
        summary_payload = dict(summary) if isinstance(summary, dict) else {}
        summary_payload.update(payload)
        stage_run.summary = json.dumps(summary_payload, ensure_ascii=False)

    def _read_progress_int(self, payload: dict[str, object], key: str) -> int:
        value = payload.get(key)
        parsed = self._read_optional_int(value)
        return 0 if parsed is None else parsed

    def _read_optional_int(self, value: object) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def inspect(self, *, project_id: int) -> dict[str, list[dict[str, object]]]:
        chapter_rows = self.session.execute(
            select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.chapter_index.asc())
        ).scalars().all()
        chapter_map = {chapter.id: chapter for chapter in chapter_rows}

        runs = []
        for review_run in self.reviews.list_runs(project_id):
            summary = self._decode_summary(review_run.summary)
            issues_for_run = self.reviews.list_issues_for_run(review_run.id)
            runs.append(
                {
                    "id": review_run.id,
                    "project_id": review_run.project_id,
                    "scope_type": review_run.scope_type,
                    "scope_value": self._decode_summary(review_run.scope_value),
                    "status": review_run.status,
                    "summary": summary,
                    "translation_source": None if not isinstance(summary, dict) else summary.get("translation_source"),
                    "issue_count": len(issues_for_run),
                }
            )

        issues = []
        for issue in self.reviews.list_issues(project_id):
            chapter = chapter_map.get(issue.chapter_id)
            issues.append(
                {
                    "id": issue.id,
                    "project_id": issue.project_id,
                    "review_run_id": issue.review_run_id,
                    "chapter_id": issue.chapter_id,
                    "chapter_index": None if chapter is None else chapter.chapter_index,
                    "chapter_title": None if chapter is None else chapter.chapter_title,
                    "issue_type": issue.issue_type,
                    "severity": issue.severity,
                    "message": issue.message,
                    "status": issue.status,
                    "segment_id": issue.segment_id,
                    "version_id": issue.version_id,
                    "issue_source": issue.issue_source,
                    "round_index": issue.round_index,
                    "requires_rewrite": issue.requires_rewrite,
                    "structured_payload": issue.structured_payload,
                }
            )

        return {"runs": runs, "issues": issues}

    def _resolve_segment_rows(
        self,
        *,
        project_id: int,
        scope: dict[str, object],
    ) -> list[tuple[Chapter, ChapterSegment, SegmentTranslation | None, SegmentTranslationVersion | None]]:
        statement = (
            select(Chapter, ChapterSegment, SegmentTranslation, SegmentTranslationVersion)
            .join(ChapterSegment, ChapterSegment.chapter_id == Chapter.id)
            .outerjoin(
                SegmentTranslation,
                and_(SegmentTranslation.segment_id == ChapterSegment.id, SegmentTranslation.project_id == project_id),
            )
            .outerjoin(SegmentTranslationVersion, SegmentTranslationVersion.id == SegmentTranslation.active_version_id)
            .where(Chapter.project_id == project_id, ChapterSegment.project_id == project_id)
        )
        scope_type = str(scope["type"])
        if scope_type == "chapter_range":
            statement = statement.where(
                Chapter.chapter_index >= int(scope["start"]),
                Chapter.chapter_index <= int(scope["end"]),
            )
        if scope_type == "chapter_list":
            statement = statement.where(Chapter.chapter_index.in_(list(scope["chapters"])))
        if scope_type == "missing_only":
            statement = statement.where(
                SegmentTranslation.active_version_id.is_not(None),
                ChapterSegment.review_status != "reviewed",
            )
        statement = statement.order_by(Chapter.chapter_index.asc(), ChapterSegment.segment_index.asc())
        rows = self.session.execute(statement).all()
        return [(chapter, segment, translation, version) for chapter, segment, translation, version in rows]

    def _build_issue(
        self,
        *,
        chapter: Chapter,
        segment: ChapterSegment,
        source_text: str,
        version: SegmentTranslationVersion | None,
    ) -> dict[str, object] | None:
        if version is None:
            return {
                "project_id": chapter.project_id,
                "chapter_id": chapter.id,
                "segment_id": int(segment.id),
                "version_id": None,
                "issue_type": "missing_translation",
                "severity": "high",
                "message": f"第{chapter.chapter_index}章第{segment.segment_index}段没有可用的生效译文。",
                "status": "open",
                "issue_source": "hard",
                "round_index": 0,
                "requires_rewrite": True,
                "structured_payload": None,
            }

        translated_text = version.translated_text.strip()
        if translated_text == "":
            return {
                "project_id": chapter.project_id,
                "chapter_id": chapter.id,
                "segment_id": int(segment.id),
                "version_id": int(version.id),
                "issue_type": "missing_translation",
                "severity": "high",
                "message": f"第{chapter.chapter_index}章第{segment.segment_index}段的译文为空。",
                "status": "open",
                "issue_source": "hard",
                "round_index": 0,
                "requires_rewrite": True,
                "structured_payload": None,
            }

        if translated_text == source_text.strip():
            return {
                "project_id": chapter.project_id,
                "chapter_id": chapter.id,
                "segment_id": int(segment.id),
                "version_id": int(version.id),
                "issue_type": "unchanged_translation",
                "severity": "medium",
                "message": f"第{chapter.chapter_index}章第{segment.segment_index}段的译文与原文一致。",
                "status": "open",
                "issue_source": "hard",
                "round_index": 0,
                "requires_rewrite": True,
                "structured_payload": None,
            }

        glossary_entries = self.glossary.list_active_entries_for_matching(
            chapter.project_id,
            scope_level="chapter_term",
            scope_chapter_id=chapter.id,
            include_project_scope=True,
        )
        matched_entries = self.translation_assets.build_prompt_glossary_entries(
            glossary_entries=glossary_entries,
            source_text=source_text,
        )
        normalized_translation = self._normalize_glossary_text(translated_text)
        for entry in matched_entries:
            normalized_target = self._normalize_glossary_text(str(entry.target_term))
            if normalized_target == "":
                continue
            if normalized_target not in normalized_translation:
                return {
                    "project_id": chapter.project_id,
                    "chapter_id": chapter.id,
                    "segment_id": int(segment.id),
                    "version_id": int(version.id),
                    "issue_type": "glossary_term_missing",
                    "severity": "medium",
                    "message": (
                        f"第{chapter.chapter_index}章第{segment.segment_index}分片命中了术语"
                        f"“{entry.source_term}”，但译文里未发现约定译法“{entry.target_term}”。"
                    ),
                    "status": "open",
                    "issue_source": "hard",
                    "round_index": 0,
                    "requires_rewrite": True,
                    "structured_payload": {
                        "source_term": entry.source_term,
                        "target_term": entry.target_term,
                    },
                }

        return None

    def _normalize_glossary_text(self, value: str) -> str:
        return value.lower().translate(self.GLOSSARY_TEXT_TRANSLATION_TABLE)

    def _decode_summary(self, value: str | None) -> object:
        if value is None or value == "":
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    def _mark_related_exports_stale(self, *, project_id: int, affected_chapter_indexes: list[int]) -> None:
        if not affected_chapter_indexes:
            return

        for export_run in self.session.execute(
            select(ExportRun).where(ExportRun.project_id == project_id)
        ).scalars().all():
            if self._scope_matches_chapters(self._decode_summary(export_run.scope_value), affected_chapter_indexes):
                export_run.status = "stale"

        for stage_run in self.session.execute(
            select(StageRun).where(
                StageRun.project_id == project_id,
                StageRun.stage == "export",
            )
        ).scalars().all():
            if self._scope_matches_chapters(self._decode_summary(stage_run.scope_value), affected_chapter_indexes):
                stage_run.status = "stale"

    def _scope_matches_chapters(self, scope_value: object, chapter_indexes: list[int]) -> bool:
        return scope_matches_chapters(scope_value, chapter_indexes)
