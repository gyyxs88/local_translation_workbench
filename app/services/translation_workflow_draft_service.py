from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..db.models import Chapter, ChapterSegment
from ..errors import ToolError
from ..repositories.translation_workflows import TranslationWorkflowRepository
from .json_response_parser import load_json_payload, strip_json_code_fence


class TranslationWorkflowDraftService:
    def __init__(self, session) -> None:
        self.session = session
        self.translation_workflows = TranslationWorkflowRepository(session)

    def inspect_pipeline(self, *, workflow_run_id: int) -> dict[str, object]:
        draft_versions = self.translation_workflows.list_draft_versions(workflow_run_id=workflow_run_id)
        reviews = self.translation_workflows.list_draft_reviews(workflow_run_id=workflow_run_id)
        final_candidates = []
        drafts_by_segment = self.group_drafts_by_segment(draft_versions)
        reviews_by_draft = self.group_reviews_by_draft(reviews)
        for segment_id in sorted(drafts_by_segment):
            selected = self.select_final_draft(
                drafts=drafts_by_segment[segment_id],
                reviews_by_draft=reviews_by_draft,
            )
            final_candidates.append(
                {
                    "segment_id": segment_id,
                    "selected_draft_role": None if selected is None else selected.draft_role,
                    "selected_draft_id": None if selected is None else selected.id,
                }
            )
        return {
            "workflow_run_id": workflow_run_id,
            "drafts": [
                {
                    "id": draft.id,
                    "segment_id": draft.segment_id,
                    "draft_role": draft.draft_role,
                    "parent_draft_id": draft.parent_draft_id,
                    "model_profile_id": draft.model_profile_id,
                    "model_name": draft.model_name,
                    "status": draft.status,
                    "translated_text": draft.translated_text,
                }
                for draft in draft_versions
            ],
            "reviews": [
                {
                    "id": review.id,
                    "draft_version_id": review.draft_version_id,
                    "step_run_id": review.step_run_id,
                    "review_type": review.review_type,
                    "decision": review.decision,
                    "score": review.score,
                    "reason_codes": review.reason_codes,
                    "structured_payload": review.structured_payload,
                }
                for review in reviews
            ],
            "final_candidates": final_candidates,
        }

    def build_review_prompt_for_segment(
        self,
        *,
        segment_id: int,
        drafts: list[Any],
        segment_map: dict[int, tuple[Chapter, ChapterSegment]],
    ) -> str:
        _, segment = segment_map[segment_id]
        payload = {
            "segment_id": segment_id,
            "source_text": Path(segment.source_text_path).read_text(encoding="utf-8"),
            "drafts": [
                {
                    "draft_role": draft.draft_role,
                    "translated_text": draft.translated_text,
                    "model_name": draft.model_name,
                }
                for draft in drafts
            ],
        }
        return (
            "你是小说翻译审核器。请比较当前段落的多个 draft，输出结构化审核意见。"
            "只返回 JSON：{\"reviews\":[{\"segment_id\":1,\"draft_role\":\"primary\",\"decision\":\"keep\",\"score\":0.9,\"reason_codes\":[\"faithful\"],\"issues\":[]}]}。\n\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

    def build_rewrite_prompt_for_segment(
        self,
        *,
        segment_id: int,
        drafts: list[Any],
        reviews_by_draft: dict[int, list[Any]],
        segment_map: dict[int, tuple[Chapter, ChapterSegment]],
    ) -> str:
        _, segment = segment_map[segment_id]
        payload = {
            "segment_id": segment_id,
            "source_text": Path(segment.source_text_path).read_text(encoding="utf-8"),
            "drafts": [
                {
                    "draft_role": draft.draft_role,
                    "translated_text": draft.translated_text,
                    "reviews": [
                        {
                            "decision": review.decision,
                            "score": review.score,
                            "reason_codes": review.reason_codes,
                            "structured_payload": review.structured_payload,
                        }
                        for review in reviews_by_draft.get(draft.id, [])
                    ],
                }
                for draft in drafts
            ],
        }
        return (
            "你是小说翻译重写器。请综合当前段落的多个 draft 及其 review，输出更稳的 rewrite 版本。"
            "只返回 JSON：{\"drafts\":[{\"segment_id\":1,\"translated_text\":\"...\",\"parent_draft_role\":\"primary\"}]}。\n\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

    def parse_json_response(self, content: str) -> dict[str, object]:
        normalized = strip_json_code_fence(content).strip()
        if normalized == "":
            return {}
        try:
            payload = load_json_payload(content)
        except json.JSONDecodeError as exc:
            raise ToolError(code="provider_error", message=f"translation workflow 返回了无效 JSON：{exc}", status=502) from exc
        if not isinstance(payload, dict):
            raise ToolError(code="provider_error", message="translation workflow 返回结果必须是对象 JSON。", status=502)
        return payload

    def group_drafts_by_segment(self, draft_versions: list[Any]) -> dict[int, list[Any]]:
        grouped: dict[int, list[Any]] = {}
        for draft in draft_versions:
            grouped.setdefault(int(draft.segment_id), []).append(draft)
        for drafts in grouped.values():
            drafts.sort(key=lambda item: item.id)
        return grouped

    def group_reviews_by_draft(self, reviews: list[Any]) -> dict[int, list[Any]]:
        grouped: dict[int, list[Any]] = {}
        for review in reviews:
            grouped.setdefault(int(review.draft_version_id), []).append(review)
        for items in grouped.values():
            items.sort(
                key=lambda item: (
                    float(item.score) if item.score is not None else float("-inf"),
                    self._review_priority(item.decision),
                    item.id,
                ),
                reverse=True,
            )
        return grouped

    def select_final_draft(self, *, drafts: list[Any], reviews_by_draft: dict[int, list[Any]]) -> Any | None:
        rewrite_drafts = [draft for draft in drafts if draft.draft_role == "rewrite"]
        if rewrite_drafts:
            return rewrite_drafts[-1]

        scored_candidates: list[tuple[float, int, int, Any]] = []
        for draft in drafts:
            draft_reviews = reviews_by_draft.get(int(draft.id), [])
            if not draft_reviews:
                continue
            best_review = draft_reviews[0]
            score = float(best_review.score) if best_review.score is not None else 0.0
            scored_candidates.append((score, self._review_priority(best_review.decision), draft.id, draft))
        if scored_candidates:
            scored_candidates.sort(reverse=True)
            return scored_candidates[0][3]
        return drafts[-1] if drafts else None

    def parse_int(self, value: object) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def parse_float(self, value: object) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def normalize_reason_codes(self, value: object) -> list[str] | None:
        if not isinstance(value, list):
            return None
        normalized = [str(item).strip() for item in value if str(item).strip()]
        return normalized or None

    def _review_priority(self, decision: str | None) -> int:
        normalized = str(decision or "").strip().lower()
        if normalized == "keep":
            return 3
        if normalized == "revise":
            return 2
        if normalized == "reject":
            return 1
        return 0

    def _strip_code_fence(self, content: str) -> str:
        return strip_json_code_fence(content)
