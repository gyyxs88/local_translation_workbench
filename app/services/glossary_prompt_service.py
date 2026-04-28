from __future__ import annotations

import json
import re
from collections.abc import Sequence

from json_repair import loads as repair_json_loads

from ..db.models import GlossaryDraftCandidate
from ..errors import ToolError
from .glossary_types import (
    GlossaryExtraction,
    GlossaryExtractionEnvelope,
    GlossaryExtractionQualityIssue,
    GlossaryLlmQualityReview,
    MatchedExistingGlossaryTerm,
)


class GlossaryPromptService:
    _structure_scaffold_pattern = re.compile(r"^第[0-9零一二三四五六七八九十百千万两]+[章节卷部篇集话回]$")

    def build_extraction_prompt(
        self,
        *,
        chapter_text: str,
        chapter_index: int,
        chapter_title: str,
        source_language: str,
        target_language: str,
        matched_existing_terms: list[MatchedExistingGlossaryTerm],
        risk_signals: list[str],
        previous_extraction: dict[str, object] | None,
    ) -> str:
        existing_terms_payload = [
            {
                "source_term": item.source_term,
                "target_term": item.target_term,
                "category": item.category,
                "note": item.note,
                "gender": item.gender,
                "age_group": item.age_group,
                "term_group_key": item.term_group_key,
                "relation_role": item.relation_role,
                "scope_level": item.scope_level,
                "scope_chapter_id": item.scope_chapter_id,
            }
            for item in matched_existing_terms
        ]
        output_contract = {
            "extraction_status": "terms_found",
            "terms": [
                {
                    "source_term": "时羽",
                    "translated_term": "Shi Yu",
                    "category": "character",
                    "note": None,
                    "gender": "female",
                    "age_group": None,
                    "term_group_key": "char_shiyu",
                    "relation_role": "canonical",
                }
            ],
            "reason": "发现新增主要人物。",
        }
        empty_contract = {
            "extraction_status": "no_new_terms",
            "terms": [],
            "reason": "本章只出现已知人物和普通叙事，没有新增专名或固定称谓。",
        }
        return (
            "你是小说翻译平台的术语抽取器。请只根据给定章节正文，提取后续翻译需要保持一致的新增术语。\n"
            f"源语言: {source_language}\n"
            f"目标语言: {target_language}\n"
            f"章节号: {chapter_index}\n"
            f"章节标题: {chapter_title}\n"
            "优先提取：人名、地名、组织/势力、专有物件、固定称谓、世界观术语、俚语/梗。\n"
            "不要输出普通代词、泛化名词、完整句子或解释性段落。\n"
            "已有术语的译名和关系组必须沿用。\n"
            "完全相同的已有 source_term 不要作为新增术语重复输出。\n"
            "如果章节中出现已有实体的新别名、称号、变体，可以作为新增术语输出，并绑定已有 term_group_key。\n"
            "如果你认为没有新增术语，必须明确返回 no_new_terms，不能返回空字符串、null、空数组或只有 terms 的对象。\n"
            "请直接返回 JSON，不要 Markdown，不要额外说明。\n"
            "每个术语对象字段：source_term, translated_term, category, note, term_group_key, relation_role, gender, age_group。\n"
            "category 推荐使用 character/location/organization/item/title/slang/term/other。\n"
            "relation_role 仅允许 canonical/alias/title/variant/independent。\n"
            "gender 仅在 category=character 且正文有明确线索时填写 female/male/nonbinary，否则返回 null。\n"
            "age_group 仅在 category=character 且正文或术语里有明确年龄段线索时填写 child/teen/adult/elderly，否则返回 null。\n"
            "不要根据先生、小姐、哥、姐、阿姨等敬称猜测年龄层。\n"
            "translated_term 必须给出建议译名；note 可为空。\n\n"
            f"已有且命中本章的术语：\n{json.dumps(existing_terms_payload, ensure_ascii=False, indent=2)}\n\n"
            f"风险信号：\n{json.dumps(risk_signals, ensure_ascii=False, indent=2)}\n\n"
            f"上一轮抽取结果：\n{json.dumps(previous_extraction, ensure_ascii=False, indent=2) if previous_extraction is not None else 'null'}\n\n"
            f"有新增术语时返回示例：\n{json.dumps(output_contract, ensure_ascii=False, indent=2)}\n\n"
            f"无新增术语时返回示例：\n{json.dumps(empty_contract, ensure_ascii=False, indent=2)}\n\n"
            "待提取章节正文：\n"
            f"{chapter_text}"
        )

    def build_decision_prompt(
        self,
        *,
        source_language: str,
        target_language: str,
        chapter_index: int,
        chapter_title: str,
        existing_entries: list[dict[str, object]],
        extracted_terms: list[GlossaryExtraction],
    ) -> str:
        candidates = [
            {
                "source_term": item.source_term,
                "translated_term": item.suggested_term,
                "category": item.category,
                "term_group_key": item.term_group_key,
                "relation_role": item.relation_role,
                "note": item.note,
                "gender": item.gender,
                "age_group": item.age_group,
            }
            for item in extracted_terms
        ]
        return (
            "你是小说翻译平台的术语裁决器。请对候选术语做保守裁决，只保留真正值得进入术语表的项目。\n"
            f"源语言: {source_language}\n"
            f"目标语言: {target_language}\n"
            f"章节号: {chapter_index}\n"
            f"章节标题: {chapter_title}\n"
            "规则：\n"
            "1. 允许正式名、简称、称号共存，不要按子串关系删词。\n"
            "2. 像“第1章”“第一卷”这类纯结构壳应剔除。\n"
            "3. 如果候选应与已有术语同组，请给出正确的 term_group_key 和 relation_role。\n"
            "4. 如果没有充分理由，不要改动已存在术语的目标写法。\n"
            "只返回 JSON：{\"decisions\":[{\"source_term\":\"...\",\"keep\":true,\"term_group_key\":\"...\",\"relation_role\":\"...\",\"reason\":\"...\"}]}\n\n"
            f"已有术语：\n{json.dumps(existing_entries, ensure_ascii=False)}\n\n"
            f"待裁决候选：\n{json.dumps(candidates, ensure_ascii=False)}"
        )

    def build_relationship_review_prompt(self, draft_items: Sequence[GlossaryDraftCandidate]) -> str:
        payload = [
            {
                "draft_candidate_id": item.id,
                "source_term": item.source_term,
                "suggested_term": item.suggested_term,
                "category": item.category,
                "term_group_key": item.term_group_key,
                "relation_role": item.relation_role,
            }
            for item in draft_items
        ]
        return (
            "你是小说术语关系审核器。请判断每个候选是 canonical/alias/title/variant/independent 中哪一种。"
            "只返回 JSON：{\"items\":[{\"draft_candidate_id\":1,\"term_group_key\":\"char_linxi\",\"relation_role\":\"alias\",\"score\":0.9,\"reason_codes\":[\"same_entity\"]}]}\n\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

    def build_scope_review_prompt(self, draft_items: Sequence[GlossaryDraftCandidate]) -> str:
        payload = [
            {
                "draft_candidate_id": item.id,
                "source_term": item.source_term,
                "chapter_id": item.chapter_id,
                "category": item.category,
            }
            for item in draft_items
        ]
        return (
            "你是小说术语 scope 审核器。请判断候选应为 project_term、chapter_term 或 discard。"
            "只返回 JSON：{\"items\":[{\"draft_candidate_id\":1,\"scope_level\":\"chapter_term\",\"scope_chapter_id\":1,\"score\":0.85,\"reason_codes\":[\"single_chapter_epithet\"]}]}\n\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

    def build_consistency_review_prompt(
        self,
        *,
        draft_items: Sequence[GlossaryDraftCandidate],
        active_entries: Sequence[object],
        deterministic_reviews: Sequence[dict[str, object]],
    ) -> str:
        draft_payload = [
            {
                "draft_candidate_id": item.id,
                "source_term": item.source_term,
                "suggested_term": item.suggested_term,
                "category": item.category,
                "gender": item.gender,
                "age_group": item.age_group,
                "term_group_key": item.term_group_key,
                "relation_role": item.relation_role,
                "chapter_id": item.chapter_id,
            }
            for item in draft_items
        ]
        active_payload = [
            {
                "source_term": getattr(item, "source_term", ""),
                "target_term": getattr(item, "target_term", ""),
                "category": getattr(item, "category", ""),
                "gender": getattr(item, "gender", None),
                "age_group": getattr(item, "age_group", None),
                "term_group_key": getattr(item, "term_group_key", ""),
                "relation_role": getattr(item, "relation_role", "independent"),
                "scope_level": getattr(item, "scope_level", "project_term"),
                "locked": int(getattr(item, "locked", 0) or 0),
            }
            for item in active_entries
        ]
        return (
            "你是小说术语一致性审核器。请检查本批暂存术语是否与已有正式术语和本批内部保持一致。\n"
            "硬规则：\n"
            "1. 风格检查必须以已有正式术语风格基准为准，不能把本批 draft 自己当成风格基准。\n"
            "2. 同一 category 已有正式术语时，候选译名应贴合该 category 的既有译名风格。\n"
            "3. 同一 source_term 不应在同一批内产生多个互斥译名；locked 正式术语优先级最高。\n"
            "4. 只返回 JSON，不要 Markdown，不要解释。\n"
            "返回格式：{\"items\":[{\"draft_candidate_id\":1,\"decision\":\"pass|warning|revise|discard|conflict\","
            "\"suggested_term\":\"...\",\"score\":0.9,\"reason_codes\":[\"style_mismatch\"],"
            "\"issues\":[{\"code\":\"category_style_mismatch\",\"severity\":\"warning\",\"message\":\"...\"}]}]}\n\n"
            f"已有正式术语风格基准：\n{json.dumps(active_payload, ensure_ascii=False)}\n\n"
            f"本批暂存术语：\n{json.dumps(draft_payload, ensure_ascii=False)}\n\n"
            f"确定性预检结果：\n{json.dumps(list(deterministic_reviews), ensure_ascii=False)}"
        )

    def build_finalize_prompt(
        self,
        *,
        draft_candidates: list[dict[str, object]],
        review_items: list[dict[str, object]],
    ) -> str:
        return (
            "你是小说术语终审器。请综合 draft candidates 和 review 记录，只保留最终应进入 glossary 的项目。"
            "其中 consistency review 是一致性约束；风格取舍必须以已有正式术语基准为优先。"
            "只返回 JSON：{\"terms\":[{\"source_term\":\"林溪\",\"target_term\":\"Lin Xi\",\"category\":\"character\",\"note\":null,\"gender\":\"female\",\"age_group\":\"teen\",\"term_group_key\":\"char_linxi\",\"relation_role\":\"canonical\",\"scope_level\":\"project_term\",\"scope_chapter_id\":null}]}\n\n"
            f"draft={json.dumps(draft_candidates, ensure_ascii=False)}\n"
            f"reviews={json.dumps(review_items, ensure_ascii=False)}"
        )

    def build_extraction_json_repair_prompt(self, *, broken_content: str) -> str:
        return (
            "你是 JSON 修复器。下面是一段术语抽取模型输出，它应该是合法 JSON，但当前无法解析。\n"
            "请只修复 JSON 语法，不新增术语、不删除术语、不改写字段含义。\n"
            "输出必须是合法 JSON，格式为 {\"extraction_status\":\"terms_found\",\"terms\":[...],\"reason\":\"...\"} 或 {\"extraction_status\":\"no_new_terms\",\"terms\":[],\"reason\":\"...\"}，不要 Markdown，不要解释。\n\n"
            "待修复内容：\n"
            f"{broken_content}"
        )

    def build_extraction_quality_review_prompt(
        self,
        *,
        chapter_text: str,
        chapter_index: int,
        chapter_title: str,
        extraction_payload: dict[str, object],
        quality_issues: list[dict[str, object]],
    ) -> str:
        return (
            "你是小说术语抽取质检器。请判断当前章节的术语抽取结果是否可信。\n"
            "只返回 JSON，不要 Markdown，不要解释。\n"
            "格式：{\"passed\":true,\"issues\":[]} 或 {\"passed\":false,\"issues\":[{\"issue_type\":\"suspicious_empty\",\"severity\":\"medium\",\"message\":\"...\",\"source_evidence\":\"...\",\"suggested_action\":\"targeted_reextract\"}]}\n"
            "只有发现确实需要重新抽取时，suggested_action 才能是 targeted_reextract。\n\n"
            f"章节号: {chapter_index}\n"
            f"章节标题: {chapter_title}\n"
            f"硬质检问题：\n{json.dumps(quality_issues, ensure_ascii=False, indent=2)}\n\n"
            f"当前抽取结果：\n{json.dumps(extraction_payload, ensure_ascii=False, indent=2)}\n\n"
            "章节正文：\n"
            f"{chapter_text}"
        )

    def parse_extraction_quality_review_response(self, content: str) -> GlossaryLlmQualityReview:
        normalized = self.strip_code_fence(content).strip()
        if normalized == "":
            return GlossaryLlmQualityReview(passed=False, issues=[])
        try:
            payload = self.load_json_payload(normalized)
        except json.JSONDecodeError:
            return GlossaryLlmQualityReview(passed=False, issues=[])
        if not isinstance(payload, dict):
            return GlossaryLlmQualityReview(passed=False, issues=[])
        raw_issues = payload.get("issues", [])
        issues: list[GlossaryExtractionQualityIssue] = []
        if isinstance(raw_issues, list):
            for item in raw_issues:
                if not isinstance(item, dict):
                    continue
                issues.append(
                    GlossaryExtractionQualityIssue(
                        issue_type=self.normalize_text(item.get("issue_type")) or "llm_quality_issue",
                        severity=self.normalize_text(item.get("severity")) or "medium",
                        message=self.normalize_text(item.get("message")) or "LLM 质检发现风险。",
                        source_term=self.normalize_optional_text(item.get("source_term")),
                        source_evidence=self.normalize_optional_text(item.get("source_evidence")),
                        suggested_action=self.normalize_optional_text(item.get("suggested_action")),
                    )
                )
        return GlossaryLlmQualityReview(
            passed=bool(payload.get("passed")) and not issues,
            issues=issues,
        )

    def parse_extraction_response(self, content: str) -> GlossaryExtractionEnvelope:
        normalized = self.strip_code_fence(content).strip()
        if normalized == "":
            raise ToolError(
                code="provider_error",
                message="术语提取返回格式错误：必须返回包含 extraction_status 的 JSON 对象。",
                status=502,
            )
        try:
            payload = self.load_json_payload(normalized)
        except json.JSONDecodeError as exc:
            raise ToolError(
                code="provider_error",
                message=f"术语提取返回了无效 JSON：{exc}",
                status=502,
            ) from exc

        if not isinstance(payload, dict):
            raise ToolError(
                code="provider_error",
                message="术语提取返回格式错误：必须返回包含 extraction_status 的 JSON 对象。",
                status=502,
            )

        extraction_status = self.normalize_text(payload.get("extraction_status"))
        if extraction_status not in {"terms_found", "no_new_terms"}:
            raise ToolError(
                code="provider_error",
                message="术语提取返回格式错误：extraction_status 必须是 terms_found 或 no_new_terms。",
                status=502,
            )

        raw_terms = payload.get("terms")
        if not isinstance(raw_terms, list):
            raise ToolError(
                code="provider_error",
                message="术语提取返回格式错误：terms 必须是数组。",
                status=502,
            )

        results = self._parse_extraction_terms(raw_terms)
        if extraction_status == "terms_found" and not results:
            raise ToolError(
                code="provider_error",
                message="术语提取返回格式错误：terms_found 必须包含至少一个有效术语。",
                status=502,
            )
        if extraction_status == "no_new_terms" and results:
            raise ToolError(
                code="provider_error",
                message="术语提取返回格式错误：no_new_terms 必须搭配空 terms 数组。",
                status=502,
            )
        return GlossaryExtractionEnvelope(
            extraction_status=extraction_status,
            terms=results,
            reason=self.normalize_optional_text(payload.get("reason")),
        )

    def _parse_extraction_terms(self, raw_terms: list[object]) -> list[GlossaryExtraction]:
        results: list[GlossaryExtraction] = []
        seen_terms: set[str] = set()
        for item in raw_terms:
            if not isinstance(item, dict):
                continue
            source_term = self.normalize_text(item.get("source_term"))
            suggested_term = self.normalize_text(
                item.get("translated_term") or item.get("target_term") or item.get("suggested_term")
            )
            if source_term == "" or suggested_term == "":
                continue
            if source_term in seen_terms:
                continue
            category = self.normalize_text(item.get("category")) or "term"
            note = self.normalize_optional_text(item.get("note"))
            gender = self.normalize_gender(category=category, gender=item.get("gender"))
            age_group = self.normalize_age_group(category=category, age_group=item.get("age_group"))
            term_group_key = self.normalize_text(item.get("term_group_key")) or source_term
            relation_role = self.normalize_text(item.get("relation_role")) or "independent"
            results.append(
                GlossaryExtraction(
                    source_term=source_term,
                    suggested_term=suggested_term,
                    category=category,
                    note=note,
                    term_group_key=term_group_key,
                    relation_role=relation_role,
                    gender=gender,
                    age_group=age_group,
                )
            )
            seen_terms.add(source_term)
        return results

    def should_run_decision_stage(self, extracted_terms: list[GlossaryExtraction]) -> bool:
        return any(
            item.term_group_key != item.source_term or item.relation_role != "independent"
            for item in extracted_terms
        )

    def filter_extracted_terms(self, extracted_terms: list[GlossaryExtraction]) -> list[GlossaryExtraction]:
        return [
            item
            for item in extracted_terms
            if not self._structure_scaffold_pattern.fullmatch(item.source_term.strip())
        ]

    def apply_decisions(
        self,
        extracted_terms: list[GlossaryExtraction],
        content: str,
    ) -> list[GlossaryExtraction]:
        normalized = self.strip_code_fence(content).strip()
        if normalized == "":
            return extracted_terms
        try:
            payload = self.load_json_payload(normalized)
        except json.JSONDecodeError:
            return extracted_terms
        if not isinstance(payload, dict):
            return extracted_terms
        raw_decisions = payload.get("decisions")
        if not isinstance(raw_decisions, list):
            return extracted_terms

        decisions_by_term: dict[str, dict[str, object]] = {}
        for item in raw_decisions:
            if not isinstance(item, dict):
                continue
            source_term = self.normalize_text(item.get("source_term"))
            if source_term == "":
                continue
            decisions_by_term[source_term] = item

        decided_terms: list[GlossaryExtraction] = []
        for extracted in extracted_terms:
            decision = decisions_by_term.get(extracted.source_term)
            if decision is None:
                decided_terms.append(extracted)
                continue
            if bool(decision.get("keep")) is False:
                continue
            decided_terms.append(
                GlossaryExtraction(
                    source_term=extracted.source_term,
                    suggested_term=extracted.suggested_term,
                    category=extracted.category,
                    note=extracted.note,
                    term_group_key=(self.normalize_text(decision.get("term_group_key")) or extracted.term_group_key),
                    relation_role=(self.normalize_text(decision.get("relation_role")) or extracted.relation_role),
                    gender=extracted.gender,
                    age_group=extracted.age_group,
                )
            )
        return decided_terms

    def parse_review_items(self, content: str, key: str) -> list[dict[str, object]]:
        normalized = self.strip_code_fence(content).strip()
        if normalized == "":
            return []
        try:
            payload = self.load_json_payload(normalized)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, dict):
            return []
        raw_items = payload.get(key, [])
        if not isinstance(raw_items, list):
            return []
        return [dict(item) for item in raw_items if isinstance(item, dict)]

    def merge_review_items_with_defaults(
        self,
        *,
        draft_items: list[GlossaryDraftCandidate],
        parsed_items: list[dict[str, object]],
        default_items: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        draft_ids = {item.id for item in draft_items}
        parsed_by_id: dict[int, dict[str, object]] = {}
        for item in parsed_items:
            draft_candidate_id = item.get("draft_candidate_id")
            if isinstance(draft_candidate_id, int) and draft_candidate_id in draft_ids:
                parsed_by_id[draft_candidate_id] = item
        merged_items: list[dict[str, object]] = []
        for default_item in default_items:
            draft_candidate_id = int(default_item["draft_candidate_id"])
            merged_items.append(parsed_by_id.get(draft_candidate_id, default_item))
        return merged_items

    def strip_code_fence(self, content: str) -> str:
        stripped = content.strip()
        if not stripped.startswith("```"):
            fenced = self._extract_fenced_block(stripped)
            return fenced if fenced is not None else stripped

        lines = stripped.splitlines()
        if not lines:
            return stripped
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)

    def load_json_payload(self, content: str) -> object:
        normalized = content.strip()
        try:
            return json.loads(normalized)
        except json.JSONDecodeError as first_error:
            decoder = json.JSONDecoder()
            for start_index in self._json_start_indexes(normalized):
                candidate = normalized[start_index:].lstrip()
                try:
                    payload, _ = decoder.raw_decode(candidate)
                except json.JSONDecodeError:
                    continue
                return payload
            try:
                return repair_json_loads(normalized)
            except Exception:
                pass
            raise first_error

    def _extract_fenced_block(self, content: str) -> str | None:
        lines = content.splitlines()
        start_index = None
        for index, line in enumerate(lines):
            if line.strip().startswith("```"):
                start_index = index + 1
                break
        if start_index is None:
            return None
        end_index = len(lines)
        for index in range(start_index, len(lines)):
            if lines[index].strip() == "```":
                end_index = index
                break
        return "\n".join(lines[start_index:end_index])

    def _json_start_indexes(self, content: str) -> list[int]:
        indexes: list[int] = []
        for marker in ("{", "["):
            index = content.find(marker)
            if index >= 0:
                indexes.append(index)
        return sorted(set(indexes))

    def normalize_text(self, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def normalize_optional_text(self, value: object) -> str | None:
        normalized = self.normalize_text(value)
        return normalized or None

    def normalize_gender(self, *, category: str, gender: object) -> str | None:
        normalized_category = self.normalize_text(category) or "term"
        if normalized_category != "character":
            return None
        normalized_gender = self.normalize_optional_text(gender)
        if normalized_gender is None:
            return None
        canonical = normalized_gender.strip().lower()
        if canonical in {"female", "male", "nonbinary"}:
            return canonical
        return None

    def normalize_age_group(self, *, category: str, age_group: object) -> str | None:
        normalized_category = self.normalize_text(category) or "term"
        if normalized_category != "character":
            return None
        normalized_age_group = self.normalize_optional_text(age_group)
        if normalized_age_group is None:
            return None
        canonical = normalized_age_group.strip().lower()
        if canonical in {"child", "teen", "adult", "elderly"}:
            return canonical
        return None
