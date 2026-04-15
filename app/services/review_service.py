from __future__ import annotations

import json
from dataclasses import dataclass
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
from ..repositories.review import ReviewRepository
from .scope_service import ensure_scope_supported, get_stage_scope_types, scope_matches_chapters


@dataclass(frozen=True)
class ReviewResult:
    issue_count: int
    run_id: int


class ReviewService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.reviews = ReviewRepository(session)

    def run(
        self,
        *,
        request_id: str,
        project_id: int,
        scope: dict[str, object],
        heartbeat: Callable[[], None] | None = None,
    ) -> ReviewResult:
        project = self.session.get(TranslationProject, project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)
        ensure_scope_supported(scope, stage="review", allowed_types=get_stage_scope_types("review"))

        rows = self._resolve_segment_rows(project_id=project_id, scope=scope)
        if not rows:
            raise ToolError(code="invalid_arguments", message="scope 范围内没有可校对的段落。", status=400)

        issues: list[dict[str, object]] = []
        affected_chapter_indexes = sorted({chapter.chapter_index for chapter, *_ in rows})
        for chapter, segment, _, version in rows:
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

        review_run = self.reviews.create_run(
            project_id=project_id,
            scope_type=str(scope["type"]),
            scope_value=json.dumps(scope, ensure_ascii=False),
            status="completed",
            summary=json.dumps(
                {
                    "request_id": request_id,
                    "issue_count": len(issues),
                    "segment_count": len(rows),
                },
                ensure_ascii=False,
            ),
        )
        for issue in issues:
            self.reviews.create_issue(review_run_id=review_run.id, **issue)
        for _, segment, _, _ in rows:
            segment.review_status = "reviewed"

        self._mark_related_exports_stale(
            project_id=project_id,
            affected_chapter_indexes=affected_chapter_indexes,
        )

        self.session.commit()
        return ReviewResult(issue_count=len(issues), run_id=review_run.id)

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
                "issue_type": "missing_translation",
                "severity": "high",
                "message": f"第{chapter.chapter_index}章第{segment.segment_index}段没有可用的生效译文。",
                "status": "open",
            }

        translated_text = version.translated_text.strip()
        if translated_text == "":
            return {
                "project_id": chapter.project_id,
                "chapter_id": chapter.id,
                "issue_type": "missing_translation",
                "severity": "high",
                "message": f"第{chapter.chapter_index}章第{segment.segment_index}段的译文为空。",
                "status": "open",
            }

        if translated_text == source_text.strip():
            return {
                "project_id": chapter.project_id,
                "chapter_id": chapter.id,
                "issue_type": "unchanged_translation",
                "severity": "medium",
                "message": f"第{chapter.chapter_index}章第{segment.segment_index}段的译文与原文一致。",
                "status": "open",
            }

        return None

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
