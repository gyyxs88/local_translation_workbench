from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import TranslationDraftReview, TranslationDraftVersion


class TranslationWorkflowRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_draft_version(
        self,
        *,
        workflow_run_id: int,
        project_id: int,
        segment_id: int,
        step_run_id: int,
        parent_draft_id: int | None,
        draft_role: str,
        source_hash: str,
        glossary_snapshot_id: str,
        provider_name: str,
        model_profile_id: str,
        model_name: str,
        translated_text: str,
        translated_text_path: str,
        status: str = "completed",
        evidence_payload: dict[str, object] | None = None,
    ) -> TranslationDraftVersion:
        record = TranslationDraftVersion(
            workflow_run_id=workflow_run_id,
            project_id=project_id,
            segment_id=segment_id,
            step_run_id=step_run_id,
            parent_draft_id=parent_draft_id,
            draft_role=draft_role,
            source_hash=source_hash,
            glossary_snapshot_id=glossary_snapshot_id,
            provider_name=provider_name,
            model_profile_id=model_profile_id,
            model_name=model_name,
            translated_text=translated_text,
            translated_text_path=translated_text_path,
            status=status,
            evidence_payload=evidence_payload,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def list_draft_versions(self, *, workflow_run_id: int) -> list[TranslationDraftVersion]:
        statement = (
            select(TranslationDraftVersion)
            .where(TranslationDraftVersion.workflow_run_id == workflow_run_id)
            .order_by(TranslationDraftVersion.segment_id.asc(), TranslationDraftVersion.id.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def list_segment_draft_versions(self, *, workflow_run_id: int, segment_id: int) -> list[TranslationDraftVersion]:
        statement = (
            select(TranslationDraftVersion)
            .where(
                TranslationDraftVersion.workflow_run_id == workflow_run_id,
                TranslationDraftVersion.segment_id == segment_id,
            )
            .order_by(TranslationDraftVersion.id.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def create_draft_review(
        self,
        *,
        draft_version_id: int,
        step_run_id: int,
        review_type: str,
        decision: str,
        score: float | None,
        reason_codes: list[str] | None,
        structured_payload: dict[str, object] | None,
    ) -> TranslationDraftReview:
        record = TranslationDraftReview(
            draft_version_id=draft_version_id,
            step_run_id=step_run_id,
            review_type=review_type,
            decision=decision,
            score=score,
            reason_codes=reason_codes,
            structured_payload=structured_payload,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def list_draft_reviews(self, *, workflow_run_id: int) -> list[TranslationDraftReview]:
        statement = (
            select(TranslationDraftReview)
            .join(TranslationDraftVersion, TranslationDraftVersion.id == TranslationDraftReview.draft_version_id)
            .where(TranslationDraftVersion.workflow_run_id == workflow_run_id)
            .order_by(TranslationDraftVersion.segment_id.asc(), TranslationDraftReview.id.asc())
        )
        return list(self.session.execute(statement).scalars().all())
