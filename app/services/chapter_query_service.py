from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..db.models import Chapter, ChapterSegment, SegmentTranslation, SegmentTranslationVersion
from ..errors import ToolError
from ..repositories.projects import ProjectRepository
from .scope_service import ensure_scope_supported, get_stage_scope_types


class ChapterQueryService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.projects = ProjectRepository(session)

    def inspect_chapter(
        self,
        *,
        project_id: int,
        chapter_id: int | None = None,
        chapter_index: int | None = None,
    ) -> dict[str, object]:
        self._ensure_project_exists(project_id)
        if (chapter_id is None and chapter_index is None) or (chapter_id is not None and chapter_index is not None):
            raise ToolError(
                code="invalid_arguments",
                message="inspect.chapter 必须且只能提供 chapter_id 或 chapter_index 其中一个。",
                status=400,
            )

        chapter = self._resolve_single_chapter(
            project_id=project_id,
            chapter_id=chapter_id,
            chapter_index=chapter_index,
        )
        rows = self._list_segment_rows(project_id=project_id, chapter_ids=[chapter.id])
        grouped_rows = self._group_rows_by_chapter(rows)
        return {
            "chapter": self._build_chapter_payload(
                chapter=chapter,
                rows=grouped_rows.get(chapter.id, []),
                include_segments=True,
            )
        }

    def inspect_chapters(
        self,
        *,
        project_id: int,
        scope: dict[str, object],
        include_segments: bool,
    ) -> dict[str, object]:
        self._ensure_project_exists(project_id)
        ensure_scope_supported(scope, stage="chaptering", allowed_types=get_stage_scope_types("chaptering"))

        chapters = self._list_chapters(project_id=project_id, scope=scope)
        chapter_ids = [item.id for item in chapters]
        rows = self._list_segment_rows(project_id=project_id, chapter_ids=chapter_ids)
        grouped_rows = self._group_rows_by_chapter(rows)
        return {
            "project_id": project_id,
            "scope": scope,
            "include_segments": include_segments,
            "chapters": [
                self._build_chapter_payload(
                    chapter=chapter,
                    rows=grouped_rows.get(chapter.id, []),
                    include_segments=include_segments,
                )
                for chapter in chapters
            ],
        }

    def inspect_segment(
        self,
        *,
        project_id: int,
        segment_id: int | None = None,
        chapter_index: int | None = None,
        segment_index: int | None = None,
    ) -> dict[str, object]:
        self._ensure_project_exists(project_id)
        if segment_id is not None and (chapter_index is not None or segment_index is not None):
            raise ToolError(
                code="invalid_arguments",
                message="inspect.segment 不能同时提供 segment_id 与 chapter_index/segment_index。",
                status=400,
            )
        if segment_id is None and chapter_index is None and segment_index is None:
            raise ToolError(
                code="invalid_arguments",
                message="inspect.segment 必须提供 segment_id，或同时提供 chapter_index 和 segment_index。",
                status=400,
            )
        if segment_id is None and (chapter_index is None or segment_index is None):
            raise ToolError(
                code="invalid_arguments",
                message="inspect.segment 使用章节定位时必须同时提供 chapter_index 和 segment_index。",
                status=400,
            )

        chapter, segment, translation, version = self._resolve_single_segment_row(
            project_id=project_id,
            segment_id=segment_id,
            chapter_index=chapter_index,
            segment_index=segment_index,
        )
        return {
            "segment": self._build_single_segment_payload(
                chapter=chapter,
                segment=segment,
                translation=translation,
                version=version,
            )
        }

    def _ensure_project_exists(self, project_id: int) -> None:
        project = self.projects.get_by_id(project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

    def _resolve_single_chapter(
        self,
        *,
        project_id: int,
        chapter_id: int | None,
        chapter_index: int | None,
    ) -> Chapter:
        statement = select(Chapter).where(Chapter.project_id == project_id)
        if chapter_id is not None:
            statement = statement.where(Chapter.id == chapter_id)
        if chapter_index is not None:
            statement = statement.where(Chapter.chapter_index == chapter_index)
        chapter = self.session.execute(statement).scalar_one_or_none()
        if chapter is None:
            if chapter_id is not None:
                message = f"找不到 project_id={project_id} 下的 chapter_id={chapter_id}。"
            else:
                message = f"找不到 project_id={project_id} 下的 chapter_index={chapter_index}。"
            raise ToolError(code="not_found", message=message, status=404)
        return chapter

    def _resolve_single_segment_row(
        self,
        *,
        project_id: int,
        segment_id: int | None,
        chapter_index: int | None,
        segment_index: int | None,
    ) -> tuple[Chapter, ChapterSegment, SegmentTranslation | None, SegmentTranslationVersion | None]:
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
        if segment_id is not None:
            statement = statement.where(ChapterSegment.id == segment_id)
        else:
            statement = statement.where(
                Chapter.chapter_index == int(chapter_index),
                ChapterSegment.segment_index == int(segment_index),
            )
        row = self.session.execute(statement).one_or_none()
        if row is None:
            if segment_id is not None:
                message = f"找不到 project_id={project_id} 下的 segment_id={segment_id}。"
            else:
                message = (
                    f"找不到 project_id={project_id} 下的 "
                    f"chapter_index={chapter_index}, segment_index={segment_index}。"
                )
            raise ToolError(code="not_found", message=message, status=404)
        return row

    def _list_chapters(self, *, project_id: int, scope: dict[str, object]) -> list[Chapter]:
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

    def _list_segment_rows(
        self,
        *,
        project_id: int,
        chapter_ids: list[int],
    ) -> list[tuple[Chapter, ChapterSegment, SegmentTranslation | None, SegmentTranslationVersion | None]]:
        if not chapter_ids:
            return []

        statement = (
            select(Chapter, ChapterSegment, SegmentTranslation, SegmentTranslationVersion)
            .join(ChapterSegment, ChapterSegment.chapter_id == Chapter.id)
            .outerjoin(
                SegmentTranslation,
                and_(SegmentTranslation.segment_id == ChapterSegment.id, SegmentTranslation.project_id == project_id),
            )
            .outerjoin(SegmentTranslationVersion, SegmentTranslationVersion.id == SegmentTranslation.active_version_id)
            .where(
                Chapter.project_id == project_id,
                ChapterSegment.project_id == project_id,
                Chapter.id.in_(chapter_ids),
            )
            .order_by(Chapter.chapter_index.asc(), ChapterSegment.segment_index.asc())
        )
        return list(self.session.execute(statement).all())

    def _group_rows_by_chapter(
        self,
        rows: list[tuple[Chapter, ChapterSegment, SegmentTranslation | None, SegmentTranslationVersion | None]],
    ) -> dict[int, list[tuple[ChapterSegment, SegmentTranslation | None, SegmentTranslationVersion | None]]]:
        grouped: dict[int, list[tuple[ChapterSegment, SegmentTranslation | None, SegmentTranslationVersion | None]]] = defaultdict(list)
        for chapter, segment, translation, version in rows:
            grouped[chapter.id].append((segment, translation, version))
        return grouped

    def _build_chapter_payload(
        self,
        *,
        chapter: Chapter,
        rows: list[tuple[ChapterSegment, SegmentTranslation | None, SegmentTranslationVersion | None]],
        include_segments: bool,
    ) -> dict[str, object]:
        payload = {
            "chapter_id": chapter.id,
            "chapter_index": chapter.chapter_index,
            "chapter_title": chapter.chapter_title,
            "stage_status": chapter.stage_status,
            "source_path": chapter.source_path,
            "normalized_path": chapter.normalized_path,
            "summary": self._build_summary(rows),
        }
        if include_segments:
            payload["segments"] = [
                self._build_segment_payload(segment=segment, translation=translation, version=version)
                for segment, translation, version in rows
            ]
        return payload

    def _build_summary(
        self,
        rows: list[tuple[ChapterSegment, SegmentTranslation | None, SegmentTranslationVersion | None]],
    ) -> dict[str, object]:
        segment_count = len(rows)
        translated_segment_count = sum(1 for segment, _, _ in rows if segment.translation_status == "translated")
        failed_segment_count = sum(1 for segment, _, _ in rows if segment.translation_status == "failed")
        stale_segment_count = sum(1 for segment, _, _ in rows if segment.translation_status == "stale")
        pending_segment_count = sum(1 for segment, _, _ in rows if segment.translation_status == "pending")
        reviewed_segment_count = sum(1 for segment, _, _ in rows if segment.review_status == "reviewed")
        pending_review_segment_count = sum(1 for segment, _, _ in rows if segment.review_status != "reviewed")
        active_version_segment_count = sum(
            1 for _, translation, _ in rows if translation is not None and translation.active_version_id is not None
        )
        return {
            "segment_count": segment_count,
            "translated_segment_count": translated_segment_count,
            "failed_segment_count": failed_segment_count,
            "stale_segment_count": stale_segment_count,
            "pending_segment_count": pending_segment_count,
            "reviewed_segment_count": reviewed_segment_count,
            "pending_review_segment_count": pending_review_segment_count,
            "active_version_segment_count": active_version_segment_count,
            "is_translation_dirty": translated_segment_count != segment_count,
            "is_review_dirty": reviewed_segment_count != segment_count,
        }

    def _build_segment_payload(
        self,
        *,
        segment: ChapterSegment,
        translation: SegmentTranslation | None,
        version: SegmentTranslationVersion | None,
    ) -> dict[str, object]:
        return {
            "segment_id": segment.id,
            "segment_index": segment.segment_index,
            "source_text_path": segment.source_text_path,
            "translation_status": segment.translation_status,
            "review_status": segment.review_status,
            "active_version_id": None if translation is None else translation.active_version_id,
            "current_version": self._build_current_version(version),
        }

    def _build_current_version(self, version: SegmentTranslationVersion | None) -> dict[str, object] | None:
        if version is None:
            return None
        return {
            "id": version.id,
            "version_index": version.version_index,
            "provider_name": version.provider_name,
            "model_profile_id": version.model_profile_id,
            "model_name": version.model_name,
            "status": version.status,
            "source_hash": version.source_hash,
            "glossary_snapshot_id": version.glossary_snapshot_id,
            "translated_text": version.translated_text,
            "translated_text_path": version.translated_text_path,
        }

    def _build_single_segment_payload(
        self,
        *,
        chapter: Chapter,
        segment: ChapterSegment,
        translation: SegmentTranslation | None,
        version: SegmentTranslationVersion | None,
    ) -> dict[str, object]:
        return {
            "segment_id": segment.id,
            "chapter_id": chapter.id,
            "chapter_index": chapter.chapter_index,
            "chapter_title": chapter.chapter_title,
            "segment_index": segment.segment_index,
            "source_text_path": segment.source_text_path,
            "translation_status": segment.translation_status,
            "review_status": segment.review_status,
            "active_version_id": None if translation is None else translation.active_version_id,
            "source_text": Path(segment.source_text_path).read_text(encoding="utf-8").strip(),
            "translated_text": None if version is None else version.translated_text,
            "current_version": self._build_current_version(version),
        }
