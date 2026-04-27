from __future__ import annotations

import json

from sqlalchemy import select

from ..db.models import (
    Chapter,
    ChapterSegment,
    ExportRun,
    ReviewRun,
    SegmentTranslation,
    SegmentTranslationVersion,
    StageRun,
)
from .scope_service import scope_matches_chapters


class ProjectStalenessService:
    def __init__(self, session) -> None:
        self.session = session

    def mark_translation_downstream_stale(
        self,
        *,
        project_id: int,
        affected_chapter_indexes: list[int],
    ) -> None:
        if not affected_chapter_indexes:
            return
        segments = self.session.execute(
            select(ChapterSegment)
            .join(Chapter, Chapter.id == ChapterSegment.chapter_id)
            .where(
                Chapter.project_id == project_id,
                Chapter.chapter_index.in_(affected_chapter_indexes),
                ChapterSegment.project_id == project_id,
            )
        ).scalars().all()
        for segment in segments:
            if segment.review_status != "pending":
                segment.review_status = "pending"
        self._mark_downstream_runs_stale(
            project_id=project_id,
            chapter_indexes=affected_chapter_indexes,
            stage_names=["review", "export"],
        )

    def mark_glossary_downstream_stale(
        self,
        *,
        project_id: int,
        chapters: list[Chapter],
    ) -> None:
        if not chapters:
            return

        chapter_ids = [chapter.id for chapter in chapters]
        chapter_indexes = [chapter.chapter_index for chapter in chapters]

        segments = self.session.execute(
            select(ChapterSegment)
            .where(
                ChapterSegment.project_id == project_id,
                ChapterSegment.chapter_id.in_(chapter_ids),
            )
            .order_by(ChapterSegment.id.asc())
        ).scalars().all()
        segment_ids = [segment.id for segment in segments]

        for segment in segments:
            if segment.translation_status == "translated":
                segment.translation_status = "stale"
            if segment.review_status != "pending":
                segment.review_status = "pending"

        if segment_ids:
            active_versions = self.session.execute(
                select(SegmentTranslationVersion)
                .join(SegmentTranslation, SegmentTranslation.id == SegmentTranslationVersion.segment_translation_id)
                .where(
                    SegmentTranslation.project_id == project_id,
                    SegmentTranslation.segment_id.in_(segment_ids),
                    SegmentTranslation.active_version_id == SegmentTranslationVersion.id,
                )
            ).scalars().all()
            for version in active_versions:
                if version.status == "completed":
                    version.status = "stale"

        self._mark_downstream_runs_stale(
            project_id=project_id,
            chapter_indexes=chapter_indexes,
            stage_names=["translation", "review", "export"],
        )

    def _mark_downstream_runs_stale(
        self,
        *,
        project_id: int,
        chapter_indexes: list[int],
        stage_names: list[str],
    ) -> None:
        for stage_run in self.session.execute(
            select(StageRun).where(
                StageRun.project_id == project_id,
                StageRun.stage.in_(stage_names),
            )
        ).scalars().all():
            if self._scope_matches_chapters(self._decode_summary(stage_run.scope_value), chapter_indexes):
                stage_run.status = "stale"

        for review_run in self.session.execute(
            select(ReviewRun).where(ReviewRun.project_id == project_id)
        ).scalars().all():
            if self._scope_matches_chapters(self._decode_summary(review_run.scope_value), chapter_indexes):
                review_run.status = "stale"

        for export_run in self.session.execute(
            select(ExportRun).where(ExportRun.project_id == project_id)
        ).scalars().all():
            if self._scope_matches_chapters(self._decode_summary(export_run.scope_value), chapter_indexes):
                export_run.status = "stale"

    def _scope_matches_chapters(self, scope_value: object, chapter_indexes: list[int]) -> bool:
        return scope_matches_chapters(scope_value, chapter_indexes)

    def _decode_summary(self, value: str | None) -> object:
        if value is None or value == "":
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
