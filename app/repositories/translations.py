from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import SegmentTranslation, SegmentTranslationVersion


class TranslationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_translation(self, *, project_id: int, segment_id: int) -> SegmentTranslation | None:
        statement = select(SegmentTranslation).where(
            SegmentTranslation.project_id == project_id,
            SegmentTranslation.segment_id == segment_id,
        )
        return self.session.execute(statement).scalar_one_or_none()

    def get_or_create_translation(self, *, project_id: int, segment_id: int) -> SegmentTranslation:
        translation = self.get_translation(project_id=project_id, segment_id=segment_id)
        if translation is not None:
            return translation

        translation = SegmentTranslation(project_id=project_id, segment_id=segment_id, active_version_id=None)
        self.session.add(translation)
        self.session.flush()
        return translation

    def get_next_version_index(self, translation_id: int) -> int:
        statement = select(func.max(SegmentTranslationVersion.version_index)).where(
            SegmentTranslationVersion.segment_translation_id == translation_id
        )
        current_max = self.session.execute(statement).scalar_one()
        return int(current_max or 0) + 1

    def create_version(
        self,
        *,
        project_id: int,
        segment_translation_id: int,
        version_index: int,
        source_hash: str,
        glossary_snapshot_id: str,
        provider_name: str,
        model_profile_id: str,
        model_name: str,
        source_text: str,
        translated_text: str,
        translated_text_path: str,
        status: str = "completed",
    ) -> SegmentTranslationVersion:
        version = SegmentTranslationVersion(
            project_id=project_id,
            segment_translation_id=segment_translation_id,
            version_index=version_index,
            source_hash=source_hash,
            glossary_snapshot_id=glossary_snapshot_id,
            provider_name=provider_name,
            model_profile_id=model_profile_id,
            model_name=model_name,
            source_text=source_text,
            translated_text=translated_text,
            translated_text_path=translated_text_path,
            status=status,
        )
        self.session.add(version)
        self.session.flush()
        return version

    def list_segment_translations(self, project_id: int) -> list[SegmentTranslation]:
        statement = (
            select(SegmentTranslation)
            .where(SegmentTranslation.project_id == project_id)
            .order_by(SegmentTranslation.segment_id.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def list_segment_translation_versions(self, project_id: int) -> list[SegmentTranslationVersion]:
        statement = (
            select(SegmentTranslationVersion)
            .where(SegmentTranslationVersion.project_id == project_id)
            .order_by(
                SegmentTranslationVersion.segment_translation_id.asc(),
                SegmentTranslationVersion.version_index.asc(),
            )
        )
        return list(self.session.execute(statement).scalars().all())

    def list_versions_for_translation(self, segment_translation_id: int) -> list[SegmentTranslationVersion]:
        statement = (
            select(SegmentTranslationVersion)
            .where(SegmentTranslationVersion.segment_translation_id == segment_translation_id)
            .order_by(SegmentTranslationVersion.version_index.asc())
        )
        return list(self.session.execute(statement).scalars().all())
