from __future__ import annotations

import json
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..db.models import (
    Chapter,
    ChapterSegment,
    SegmentTranslation,
    SegmentTranslationVersion,
    TranslationDraftReview,
    TranslationDraftVersion,
    WorkflowStepRun,
)
from ..errors import ToolError
from ..repositories.translations import TranslationRepository


class TranslationInspectionService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.translations = TranslationRepository(session)

    def inspect(
        self,
        *,
        project_id: int,
        segment_id: int | None = None,
        chapter_index: int | None = None,
        segment_index: int | None = None,
        compare_version_id: int | None = None,
    ) -> dict[str, list[dict[str, object]]]:
        self._validate_inspect_translation_locator(
            segment_id=segment_id,
            chapter_index=chapter_index,
            segment_index=segment_index,
            compare_version_id=compare_version_id,
        )
        if segment_id is None and chapter_index is None and segment_index is None:
            return self._inspect_project_translations(project_id=project_id)

        chapter, segment, segment_translation, version = self._resolve_single_translation_row(
            project_id=project_id,
            segment_id=segment_id,
            chapter_index=chapter_index,
            segment_index=segment_index,
        )
        active_versions = [] if version is None else [version]
        provenance_by_version_id = self._build_translation_provenance_map(active_versions=active_versions)
        timeline_by_version_id = self._build_translation_timeline_map(active_versions=active_versions)
        translation_row = self._build_translation_row_payload(
            project_id=project_id,
            chapter=chapter,
            segment=segment,
            segment_translation=segment_translation,
            version=version,
            provenance_by_version_id=provenance_by_version_id,
            timeline_by_version_id=timeline_by_version_id,
        )
        if compare_version_id is not None:
            translation_row["compare"] = self._build_translation_compare_payload(
                project_id=project_id,
                translation=segment_translation,
                current_version=version,
                compare_version_id=compare_version_id,
            )

        versions = []
        if segment_translation is not None:
            versions = [
                self._build_translation_version_list_payload(item)
                for item in self.translations.list_versions_for_translation(int(segment_translation.id))
            ]
        return {"translations": [translation_row], "versions": versions}

    def _inspect_project_translations(self, *, project_id: int) -> dict[str, list[dict[str, object]]]:
        statement = (
            select(Chapter, ChapterSegment, SegmentTranslation, SegmentTranslationVersion)
            .join(ChapterSegment, ChapterSegment.chapter_id == Chapter.id)
            .outerjoin(
                SegmentTranslation,
                SegmentTranslation.segment_id == ChapterSegment.id,
            )
            .outerjoin(SegmentTranslationVersion, SegmentTranslationVersion.id == SegmentTranslation.active_version_id)
            .where(
                Chapter.project_id == project_id,
                ChapterSegment.project_id == project_id,
            )
            .where((SegmentTranslation.project_id == project_id) | (SegmentTranslation.project_id.is_(None)))
            .order_by(Chapter.chapter_index.asc(), ChapterSegment.segment_index.asc())
        )
        rows = self.session.execute(statement).all()
        active_versions = [version for *_, version in rows if version is not None]
        provenance_by_version_id = self._build_translation_provenance_map(active_versions=active_versions)
        timeline_by_version_id = self._build_translation_timeline_map(active_versions=active_versions)
        translations = [
            self._build_translation_row_payload(
                project_id=project_id,
                chapter=chapter,
                segment=segment,
                segment_translation=segment_translation,
                version=version,
                provenance_by_version_id=provenance_by_version_id,
                timeline_by_version_id=timeline_by_version_id,
            )
            for chapter, segment, segment_translation, version in rows
        ]
        versions = [
            self._build_translation_version_list_payload(version)
            for version in self.translations.list_segment_translation_versions(project_id)
        ]
        return {"translations": translations, "versions": versions}

    def _validate_inspect_translation_locator(
        self,
        *,
        segment_id: int | None,
        chapter_index: int | None,
        segment_index: int | None,
        compare_version_id: int | None,
    ) -> None:
        if segment_id is not None and (chapter_index is not None or segment_index is not None):
            raise ToolError(
                code="invalid_arguments",
                message="inspect.translation 不能同时提供 segment_id 与 chapter_index/segment_index。",
                status=400,
            )
        if compare_version_id is not None and segment_id is None and chapter_index is None and segment_index is None:
            raise ToolError(
                code="invalid_arguments",
                message="inspect.translation 使用 compare_version_id 时必须先定位到单个 segment。",
                status=400,
            )
        if segment_id is None and (chapter_index is None) != (segment_index is None):
            raise ToolError(
                code="invalid_arguments",
                message="inspect.translation 使用章节定位时必须同时提供 chapter_index 和 segment_index。",
                status=400,
            )

    def _resolve_single_translation_row(
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
                and_(
                    SegmentTranslation.segment_id == ChapterSegment.id,
                    SegmentTranslation.project_id == project_id,
                ),
            )
            .outerjoin(SegmentTranslationVersion, SegmentTranslationVersion.id == SegmentTranslation.active_version_id)
            .where(Chapter.project_id == project_id, ChapterSegment.project_id == project_id)
        )
        if segment_id is not None:
            statement = statement.where(ChapterSegment.id == segment_id)
        else:
            statement = statement.where(
                Chapter.chapter_index == chapter_index,
                ChapterSegment.segment_index == segment_index,
            )
        row = self.session.execute(statement).one_or_none()
        if row is None:
            raise ToolError(code="not_found", message="找不到目标段落。", status=404)
        return row

    def _build_translation_version_payload(self, version: SegmentTranslationVersion) -> dict[str, object]:
        return {
            "id": int(version.id),
            "version_index": int(version.version_index),
            "source_hash": str(version.source_hash),
            "glossary_snapshot_id": str(version.glossary_snapshot_id),
            "provider_name": str(version.provider_name),
            "model_profile_id": str(version.model_profile_id),
            "model_name": str(version.model_name),
            "source_text": str(version.source_text),
            "translated_text": str(version.translated_text),
            "translated_text_path": str(version.translated_text_path),
            "status": str(version.status),
        }

    def _build_translation_version_list_payload(self, version: SegmentTranslationVersion) -> dict[str, object]:
        payload = self._build_translation_version_payload(version)
        return {
            "id": int(version.id),
            "project_id": int(version.project_id),
            "segment_translation_id": int(version.segment_translation_id),
            **payload,
        }

    def _build_translation_row_payload(
        self,
        *,
        project_id: int,
        chapter: Chapter,
        segment: ChapterSegment,
        segment_translation: SegmentTranslation | None,
        version: SegmentTranslationVersion | None,
        provenance_by_version_id: dict[int, dict[str, object]],
        timeline_by_version_id: dict[int, list[dict[str, object]]],
    ) -> dict[str, object]:
        return {
            "project_id": project_id,
            "chapter_id": int(chapter.id),
            "chapter_index": int(chapter.chapter_index),
            "chapter_title": str(chapter.chapter_title),
            "segment_id": int(segment.id),
            "segment_index": int(segment.segment_index),
            "translation_status": str(segment.translation_status),
            "review_status": str(segment.review_status),
            "active_version_id": (
                None
                if segment_translation is None or segment_translation.active_version_id is None
                else int(segment_translation.active_version_id)
            ),
            "version": None if version is None else self._build_translation_version_payload(version),
            "provenance": None if version is None else provenance_by_version_id.get(int(version.id)),
            "timeline": [] if version is None else list(timeline_by_version_id.get(int(version.id), [])),
        }

    def _build_translation_compare_payload(
        self,
        *,
        project_id: int,
        translation: SegmentTranslation | None,
        current_version: SegmentTranslationVersion | None,
        compare_version_id: int,
    ) -> dict[str, object]:
        if translation is None or current_version is None or translation.active_version_id is None:
            raise ToolError(code="not_found", message="当前段落没有 active version，无法执行 compare。", status=404)
        if int(current_version.id) == compare_version_id:
            raise ToolError(
                code="invalid_arguments",
                message="compare_version_id 不能指向当前 active version。",
                status=400,
            )

        base_version = self.translations.get_version_by_id(compare_version_id)
        if (
            base_version is None
            or int(base_version.project_id) != project_id
            or int(base_version.segment_translation_id) != int(translation.id)
        ):
            raise ToolError(
                code="not_found",
                message=f"找不到可比较的历史正式版本 {compare_version_id}。",
                status=404,
            )

        summary = {
            "translated_text_changed": str(base_version.translated_text) != str(current_version.translated_text),
            "source_hash_changed": str(base_version.source_hash) != str(current_version.source_hash),
            "glossary_snapshot_changed": (
                str(base_version.glossary_snapshot_id) != str(current_version.glossary_snapshot_id)
            ),
            "model_profile_changed": str(base_version.model_profile_id) != str(current_version.model_profile_id),
            "model_name_changed": str(base_version.model_name) != str(current_version.model_name),
            "status_changed": str(base_version.status) != str(current_version.status),
        }
        return {
            "base_version": self._build_translation_version_payload(base_version),
            "current_version": self._build_translation_version_payload(current_version),
            "changed": any(summary.values()),
            "summary": summary,
        }

    def _build_translation_provenance_map(
        self,
        *,
        active_versions: list[SegmentTranslationVersion],
    ) -> dict[int, dict[str, object]]:
        tracked_versions = [
            version
            for version in active_versions
            if version.origin_step_run_id is not None and version.origin_draft_version_id is not None
        ]
        if not tracked_versions:
            return {}

        step_ids = sorted({int(version.origin_step_run_id) for version in tracked_versions})
        draft_ids = sorted({int(version.origin_draft_version_id) for version in tracked_versions})

        step_rows = {
            int(row.id): row
            for row in self.session.execute(
                select(WorkflowStepRun).where(WorkflowStepRun.id.in_(step_ids))
            ).scalars().all()
        }
        draft_rows = {
            int(row.id): row
            for row in self.session.execute(
                select(TranslationDraftVersion).where(TranslationDraftVersion.id.in_(draft_ids))
            ).scalars().all()
        }
        review_rows = self.session.execute(
            select(TranslationDraftReview)
            .where(TranslationDraftReview.draft_version_id.in_(draft_ids))
            .order_by(TranslationDraftReview.id.asc())
        ).scalars().all()

        reviews_by_draft: dict[int, list[TranslationDraftReview]] = {}
        for review in review_rows:
            reviews_by_draft.setdefault(int(review.draft_version_id), []).append(review)

        payload: dict[int, dict[str, object]] = {}
        for version in tracked_versions:
            step = step_rows.get(int(version.origin_step_run_id))
            draft = draft_rows.get(int(version.origin_draft_version_id))
            if step is None or draft is None:
                continue
            payload[int(version.id)] = {
                "finalize_step": {
                    "step_run_id": int(step.id),
                    "step_key": str(step.step_key),
                    "action": str(step.action),
                },
                "selected_draft": {
                    "id": int(draft.id),
                    "workflow_run_id": int(draft.workflow_run_id),
                    "step_run_id": int(draft.step_run_id),
                    "draft_role": str(draft.draft_role),
                    "parent_draft_id": None if draft.parent_draft_id is None else int(draft.parent_draft_id),
                    "provider_name": str(draft.provider_name),
                    "model_profile_id": str(draft.model_profile_id),
                    "model_name": str(draft.model_name),
                    "translated_text_path": str(draft.translated_text_path),
                    "status": str(draft.status),
                    "evidence_payload": draft.evidence_payload,
                    "reviews": [
                        {
                            "id": int(review.id),
                            "step_run_id": int(review.step_run_id),
                            "review_type": str(review.review_type),
                            "decision": str(review.decision),
                            "score": review.score,
                            "reason_codes": review.reason_codes,
                            "structured_payload": review.structured_payload,
                        }
                        for review in reviews_by_draft.get(int(draft.id), [])
                    ],
                },
            }
        return payload

    def _build_translation_timeline_map(
        self,
        *,
        active_versions: list[SegmentTranslationVersion],
    ) -> dict[int, list[dict[str, object]]]:
        tracked_versions = [version for version in active_versions if version.origin_draft_version_id is not None]
        if not tracked_versions:
            return {}

        context = self._load_translation_history_context(active_versions=tracked_versions)
        timeline_by_version_id: dict[int, list[dict[str, object]]] = {}
        for version in tracked_versions:
            assert version.origin_draft_version_id is not None

            events: list[dict[str, object]] = []
            draft = context["draft_rows"].get(int(version.origin_draft_version_id))
            if draft is not None:
                draft_step = context["step_rows"].get(int(draft.step_run_id))
                events.append(self._build_draft_timeline_event(draft=draft, step=draft_step))
                for review in context["reviews_by_draft"].get(int(draft.id), []):
                    review_step = context["step_rows"].get(int(review.step_run_id))
                    events.append(self._build_review_timeline_event(review=review, step=review_step))
            events.append(
                self._build_finalize_timeline_event(
                    version=version,
                    step=(
                        None
                        if version.origin_step_run_id is None
                        else context["step_rows"].get(int(version.origin_step_run_id))
                    ),
                )
            )
            timeline_by_version_id[int(version.id)] = self._sort_translation_timeline(events)
        return timeline_by_version_id

    def _load_translation_history_context(
        self,
        *,
        active_versions: list[SegmentTranslationVersion],
    ) -> dict[str, object]:
        tracked_versions = [version for version in active_versions if version.origin_draft_version_id is not None]
        draft_ids = sorted(
            {
                int(version.origin_draft_version_id)
                for version in tracked_versions
                if version.origin_draft_version_id is not None
            }
        )

        draft_rows = {
            int(row.id): row
            for row in self.session.execute(
                select(TranslationDraftVersion).where(TranslationDraftVersion.id.in_(draft_ids))
            ).scalars().all()
        }
        review_rows = self.session.execute(
            select(TranslationDraftReview)
            .where(TranslationDraftReview.draft_version_id.in_(draft_ids))
            .order_by(TranslationDraftReview.id.asc())
        ).scalars().all()
        reviews_by_draft: dict[int, list[TranslationDraftReview]] = {}
        for review in review_rows:
            reviews_by_draft.setdefault(int(review.draft_version_id), []).append(review)

        step_ids = sorted(
            {
                int(step_id)
                for step_id in (
                    [version.origin_step_run_id for version in tracked_versions]
                    + [draft.step_run_id for draft in draft_rows.values()]
                    + [review.step_run_id for review in review_rows]
                )
                if step_id is not None
            }
        )
        step_rows = {
            int(row.id): row
            for row in self.session.execute(
                select(WorkflowStepRun).where(WorkflowStepRun.id.in_(step_ids))
            ).scalars().all()
        }
        return {
            "tracked_versions": tracked_versions,
            "draft_rows": draft_rows,
            "reviews_by_draft": reviews_by_draft,
            "step_rows": step_rows,
        }

    def _build_draft_timeline_event(
        self,
        *,
        draft: TranslationDraftVersion,
        step: WorkflowStepRun | None,
    ) -> dict[str, object]:
        return {
            "type": "draft_created",
            "occurred_at": None,
            "step_run_id": int(draft.step_run_id),
            "step_key": None if step is None else str(step.step_key),
            "action": None if step is None else str(step.action),
            "model_profile_id": str(draft.model_profile_id),
            "model_name": str(draft.model_name),
            "payload": {
                "draft_version_id": int(draft.id),
                "draft_role": str(draft.draft_role),
                "parent_draft_id": None if draft.parent_draft_id is None else int(draft.parent_draft_id),
                "status": str(draft.status),
            },
        }

    def _build_review_timeline_event(
        self,
        *,
        review: TranslationDraftReview,
        step: WorkflowStepRun | None,
    ) -> dict[str, object]:
        return {
            "type": "review_created",
            "occurred_at": None,
            "step_run_id": int(review.step_run_id),
            "step_key": None if step is None else str(step.step_key),
            "action": None if step is None else str(step.action),
            "model_profile_id": None if step is None else str(step.model_profile_id),
            "model_name": self._resolve_timeline_step_model_name(step=step),
            "payload": {
                "review_id": int(review.id),
                "review_type": str(review.review_type),
                "decision": str(review.decision),
                "score": review.score,
                "reason_codes": review.reason_codes,
            },
        }

    def _build_finalize_timeline_event(
        self,
        *,
        version: SegmentTranslationVersion,
        step: WorkflowStepRun | None,
    ) -> dict[str, object]:
        return {
            "type": "finalize_committed",
            "occurred_at": None,
            "step_run_id": None if version.origin_step_run_id is None else int(version.origin_step_run_id),
            "step_key": None if step is None else str(step.step_key),
            "action": None if step is None else str(step.action),
            "model_profile_id": str(version.model_profile_id),
            "model_name": str(version.model_name),
            "payload": {
                "translation_version_id": int(version.id),
                "version_index": int(version.version_index),
                "status": str(version.status),
            },
        }

    def _sort_translation_timeline(self, events: list[dict[str, object]]) -> list[dict[str, object]]:
        priority = {
            "draft_created": 0,
            "review_created": 1,
            "finalize_committed": 2,
        }
        return sorted(
            events,
            key=lambda item: (
                int(priority.get(str(item["type"]), 99)),
                int(self._translation_timeline_tie_breaker(item)),
            ),
        )

    def _translation_timeline_tie_breaker(self, event: dict[str, object]) -> int:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return 0
        event_type = str(event.get("type"))
        if event_type == "draft_created":
            return int(payload.get("draft_version_id") or 0)
        if event_type == "review_created":
            return int(payload.get("review_id") or 0)
        if event_type == "finalize_committed":
            return int(payload.get("translation_version_id") or 0)
        return 0

    def _resolve_timeline_step_model_name(self, *, step: WorkflowStepRun | None) -> str | None:
        if step is None:
            return None
        if isinstance(step.output_payload, dict):
            actual_model_name = step.output_payload.get("actual_model_name")
            if isinstance(actual_model_name, str) and actual_model_name.strip() != "":
                return actual_model_name
        if isinstance(step.summary, str) and step.summary.strip() != "":
            try:
                summary_payload = json.loads(step.summary)
            except json.JSONDecodeError:
                summary_payload = {}
            provider_model_name = summary_payload.get("provider_model_name")
            if isinstance(provider_model_name, str) and provider_model_name.strip() != "":
                return provider_model_name
        return None
