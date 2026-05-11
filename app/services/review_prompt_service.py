from __future__ import annotations

import json

from ..errors import ToolError
from .json_response_parser import load_json_payload, strip_json_code_fence


class ReviewPromptService:
    ALLOWED_ISSUE_TYPES = {
        "omission",
        "mistranslation",
        "glossary_mismatch",
        "character_voice",
        "tone_style",
        "fluency",
        "formatting",
        "other",
    }
    ALLOWED_SEVERITIES = {"low", "medium", "high"}

    def build_quality_review_prompt(
        self,
        *,
        source_language: str,
        target_language: str,
        chapter_index: int,
        chapter_title: str,
        segment_index: int,
        round_index: int,
        source_text: str,
        translated_text: str,
        glossary_entries: list[object],
        prior_issues: list[dict[str, object]],
    ) -> str:
        glossary_lines = [self._format_glossary_entry(entry) for entry in glossary_entries]
        prior_issue_lines = [
            f"- {item.get('issue_type', 'other')} | {item.get('severity', 'medium')} | {item.get('message', '')}"
            for item in prior_issues
        ]
        return (
            "你是小说翻译质检员。请只基于原文、译文和术语表判断是否存在需要重译的问题。\n"
            f"源语言: {source_language}\n"
            f"目标语言: {target_language}\n"
            f"章节: {chapter_index} {chapter_title}\n"
            f"分片: {segment_index}\n"
            f"质检轮次: {round_index}\n"
            "规则:\n"
            "- 只报告有原文或译文证据支持的问题。\n"
            "- 不因个人风格偏好触发重译。\n"
            "- 轻微润色建议使用 severity=low 且 requires_rewrite=false。\n"
            "- 漏译、误译、术语错译和人物语气严重偏离使用 requires_rewrite=true。\n"
            "- 每条 issue 必须写明 message、source_evidence、translation_evidence、rewrite_instruction；给不出证据时不要输出该 issue。\n"
            "- 只返回 JSON，不要 Markdown，不要解释。\n"
            'JSON 结构: {"passed": true, "score": 0.0, "issues": [{"issue_type":"mistranslation","severity":"high","requires_rewrite":true,"message":"...","source_evidence":"...","translation_evidence":"...","rewrite_instruction":"..."}]}\n'
            "术语表:\n"
            f"{chr(10).join(glossary_lines) if glossary_lines else '(无命中术语)'}\n"
            "上一轮未解决问题:\n"
            f"{chr(10).join(prior_issue_lines) if prior_issue_lines else '(无)'}\n\n"
            "原文:\n"
            f"{source_text}\n\n"
            "当前译文:\n"
            f"{translated_text}"
        )

    def build_rewrite_prompt(
        self,
        *,
        source_language: str,
        target_language: str,
        chapter_index: int,
        chapter_title: str,
        segment_index: int,
        source_text: str,
        translated_text: str,
        glossary_entries: list[object],
        blocking_issues: list[dict[str, object]],
    ) -> str:
        glossary_lines = [self._format_glossary_entry(entry) for entry in glossary_entries]
        issue_lines = [
            (
                f"- {item.get('issue_type', 'other')} | {item.get('severity', 'medium')} | "
                f"{item.get('message', '')} | instruction: {item.get('rewrite_instruction', '')}"
            )
            for item in blocking_issues
        ]
        return (
            "你是小说翻译引擎。请根据质检问题重译当前分片。\n"
            f"源语言: {source_language}\n"
            f"目标语言: {target_language}\n"
            f"章节: {chapter_index} {chapter_title}\n"
            f"分片: {segment_index}\n"
            "要求:\n"
            "- 修复所有质检问题。\n"
            "- 保留没有问题的译文信息。\n"
            "- 优先遵守术语表 target_term。\n"
            '- 只返回修订后的译文文本；也可以返回 JSON: {"translated_text":"..."}。\n'
            "术语表:\n"
            f"{chr(10).join(glossary_lines) if glossary_lines else '(无命中术语)'}\n"
            "质检问题:\n"
            f"{chr(10).join(issue_lines)}\n\n"
            "原文:\n"
            f"{source_text}\n\n"
            "当前译文:\n"
            f"{translated_text}"
        )

    def parse_quality_review_response(self, content: str) -> dict[str, object]:
        try:
            payload = load_json_payload(content)
        except json.JSONDecodeError as exc:
            raise ToolError(code="provider_error", message="LLM 质检必须返回 JSON。", status=502) from exc
        if not isinstance(payload, dict):
            raise ToolError(code="provider_error", message="LLM 质检必须返回 JSON 对象。", status=502)
        issues = payload.get("issues", [])
        if not isinstance(issues, list):
            raise ToolError(code="provider_error", message="LLM 质检 JSON 的 issues 必须是数组。", status=502)
        normalized_issues = [
            normalized_issue
            for item in issues
            if isinstance(item, dict)
            for normalized_issue in [self._normalize_issue(item)]
            if self._is_actionable_issue(normalized_issue)
        ]
        passed = bool(payload.get("passed", not normalized_issues))
        return {
            "passed": passed and not any(bool(item["requires_rewrite"]) for item in normalized_issues),
            "score": self._parse_float(payload.get("score")),
            "issues": normalized_issues,
        }

    def parse_rewrite_response(self, content: str) -> str:
        stripped = content.strip()
        if stripped == "":
            raise ToolError(code="provider_error", message="重译返回为空。", status=502)
        normalized = strip_json_code_fence(stripped).strip()
        if normalized == "":
            raise ToolError(code="provider_error", message="重译返回为空。", status=502)
        if "{" not in normalized and "[" not in normalized:
            return normalized
        try:
            payload = load_json_payload(stripped)
        except json.JSONDecodeError:
            return normalized
        if isinstance(payload, dict):
            translated_text = str(payload.get("translated_text") or "").strip()
            if translated_text:
                return translated_text
        raise ToolError(code="provider_error", message="重译 JSON 必须包含 translated_text。", status=502)

    def _normalize_issue(self, item: dict[str, object]) -> dict[str, object]:
        issue_type = str(item.get("issue_type") or "other").strip()
        if issue_type not in self.ALLOWED_ISSUE_TYPES:
            issue_type = "other"
        severity = str(item.get("severity") or "medium").strip().lower()
        if severity not in self.ALLOWED_SEVERITIES:
            severity = "medium"
        requires_rewrite = bool(item.get("requires_rewrite") or severity == "high")
        source_evidence = self._first_text(
            item,
            (
                "source_evidence",
                "source_quote",
                "original_evidence",
                "original_quote",
                "source",
                "原文证据",
                "原文依据",
                "原文片段",
            ),
        )
        translation_evidence = self._first_text(
            item,
            (
                "translation_evidence",
                "translated_evidence",
                "target_evidence",
                "translation_quote",
                "translated_quote",
                "target_quote",
                "translation",
                "译文证据",
                "译文依据",
                "译文片段",
            ),
        )
        rewrite_instruction = self._first_text(
            item,
            (
                "rewrite_instruction",
                "fix_instruction",
                "suggested_fix",
                "rewrite_suggestion",
                "revision_instruction",
                "修订建议",
                "重译建议",
                "改写建议",
                "修复建议",
            ),
        )
        message = self._first_text(
            item,
            (
                "message",
                "reason",
                "description",
                "problem",
                "issue",
                "问题",
                "原因",
                "说明",
            ),
        )
        if not message:
            message = rewrite_instruction or self._build_evidence_message(
                source_evidence=source_evidence,
                translation_evidence=translation_evidence,
            )
        return {
            "issue_type": issue_type,
            "severity": severity,
            "requires_rewrite": requires_rewrite,
            "message": message,
            "source_evidence": source_evidence,
            "translation_evidence": translation_evidence,
            "rewrite_instruction": rewrite_instruction,
            "raw_issue": dict(item),
        }

    def _is_actionable_issue(self, issue: dict[str, object]) -> bool:
        return any(
            str(issue.get(field) or "").strip()
            for field in ("message", "source_evidence", "translation_evidence", "rewrite_instruction")
        )

    def _first_text(self, item: dict[str, object], keys: tuple[str, ...]) -> str:
        for key in keys:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        evidence = item.get("evidence")
        if isinstance(evidence, dict):
            for key in keys:
                value = evidence.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    def _build_evidence_message(self, *, source_evidence: str, translation_evidence: str) -> str:
        for value in (translation_evidence, source_evidence):
            if value:
                snippet = value[:80]
                return f"LLM 质检发现问题：{snippet}"
        return ""

    def _format_glossary_entry(self, entry: object) -> str:
        return (
            f"- {entry.source_term} => {entry.target_term}"
            f" | role: {entry.relation_role}"
            f" | group: {entry.term_group_key}"
        )

    def _parse_float(self, value: object) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
