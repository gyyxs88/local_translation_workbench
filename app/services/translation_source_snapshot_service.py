from __future__ import annotations

from typing import Iterable

from ..db.models import Chapter, ChapterSegment, SegmentTranslation, SegmentTranslationVersion

TranslationSourceRow = tuple[
    Chapter,
    ChapterSegment,
    SegmentTranslation | None,
    SegmentTranslationVersion | None,
]


class TranslationSourceSnapshotService:
    def build_snapshot(self, *, rows: Iterable[TranslationSourceRow]) -> dict[str, object]:
        segments: list[dict[str, object]] = []
        version_ids: set[int] = set()

        for chapter, segment, _, version in rows:
            if version is not None:
                version_ids.add(int(version.id))
            segments.append(
                {
                    "segment_id": int(segment.id),
                    "chapter_id": int(chapter.id),
                    "chapter_index": int(chapter.chapter_index),
                    "segment_index": int(segment.segment_index),
                    "translation_status": str(segment.translation_status),
                    "review_status": str(segment.review_status),
                    "version": None if version is None else self._build_version_payload(version),
                }
            )

        ordered_version_ids = sorted(version_ids)
        return {
            "segment_count": len(segments),
            "version_count": len(ordered_version_ids),
            "version_ids": ordered_version_ids,
            "segments": segments,
        }

    def _build_version_payload(self, version: SegmentTranslationVersion) -> dict[str, object]:
        return {
            "id": int(version.id),
            "version_index": int(version.version_index),
            "provider_name": str(version.provider_name),
            "model_profile_id": str(version.model_profile_id),
            "model_name": str(version.model_name),
            "status": str(version.status),
            "source_hash": str(version.source_hash),
            "glossary_snapshot_id": str(version.glossary_snapshot_id),
        }
