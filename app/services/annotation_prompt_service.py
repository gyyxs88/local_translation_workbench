from __future__ import annotations

import json
from typing import Any

from ..errors import ToolError


class AnnotationPromptService:
    ALLOWED_TYPES = {
        "idiom",
        "cultural_reference",
        "proper_noun",
        "worldbuilding",
        "item",
        "organization",
        "measurement_money",
        "pun",
        "other",
    }

    def build_extraction_prompt(
        self,
        *,
        source_text: str,
        translated_text: str,
        glossary_entries: list[dict[str, object]],
        review_issues: list[dict[str, object]],
        existing_annotations: list[dict[str, object]],
    ) -> str:
        return (
            "你是小说翻译注释助手。请找出需要作为独立脚注解释的中文俚语、文化梗、专有词、组织、物品或世界观概念。\n"
            "只返回 JSON 对象，格式为 {\"annotations\":[...]}。不要返回 Markdown。\n"
            "每个 annotations 项必须包含 source_anchor、target_anchor、annotation_type、explanation，可选 canonical_key。\n"
            "explanation 使用目标语言，解释为什么读者需要知道这个背景，不要改写译文。\n\n"
            f"已有术语：{json.dumps(glossary_entries, ensure_ascii=False)}\n"
            f"已有审校问题：{json.dumps(review_issues, ensure_ascii=False)}\n"
            f"已有注释：{json.dumps(existing_annotations, ensure_ascii=False)}\n\n"
            f"原文：\n{source_text}\n\n译文：\n{translated_text}"
        )

    def parse_extraction_response(self, content: str) -> list[dict[str, object]]:
        try:
            payload = json.loads(content.strip())
        except json.JSONDecodeError as exc:
            raise ToolError(code="provider_error", message="annotation.extract 必须返回 JSON。", status=502) from exc
        if not isinstance(payload, dict):
            raise ToolError(code="provider_error", message="annotation.extract 必须返回 JSON 对象。", status=502)
        raw_items = payload.get("annotations")
        if not isinstance(raw_items, list):
            raise ToolError(code="provider_error", message="annotation.extract 必须返回 annotations 数组。", status=502)

        candidates: list[dict[str, object]] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            candidate = self._normalize_candidate(raw_item)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    def _normalize_candidate(self, item: dict[str, Any]) -> dict[str, object] | None:
        source_anchor = self.normalize_text(item.get("source_anchor"))
        target_anchor = self.normalize_text(item.get("target_anchor"))
        explanation = self.normalize_text(item.get("explanation"))
        if not source_anchor or not target_anchor or not explanation:
            return None
        annotation_type = self.normalize_type(item.get("annotation_type"))
        canonical_key = self.normalize_text(item.get("canonical_key")) or f"{annotation_type}:{source_anchor}"
        return {
            "source_anchor": source_anchor,
            "target_anchor": target_anchor,
            "annotation_type": annotation_type,
            "canonical_key": canonical_key,
            "explanation": explanation,
            "status": "candidate",
            "source": self.normalize_text(item.get("source")) or "llm_annotation",
            "evidence_payload": item.get("evidence_payload") if isinstance(item.get("evidence_payload"), dict) else {},
        }

    def normalize_type(self, value: object) -> str:
        normalized = self.normalize_text(value).lower()
        if normalized in self.ALLOWED_TYPES:
            return normalized
        return "other"

    def normalize_text(self, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()
