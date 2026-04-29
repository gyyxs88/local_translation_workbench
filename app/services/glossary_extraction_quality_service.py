from __future__ import annotations

import re

from .glossary_types import (
    GlossaryChapterExtractionResult,
    GlossaryExtraction,
    GlossaryExtractionEnvelope,
    GlossaryExtractionQualityIssue,
    MatchedExistingGlossaryTerm,
)


class GlossaryExtractionQualityService:
    _structure_scaffold_pattern = re.compile(r"^第[0-9零一二三四五六七八九十百千万两]+[章节卷部篇集话回]$")
    _name_like_pattern = re.compile(r"[一-龥]{2,4}(?:小姐|同学|老师|前辈|殿下|大人|阁下)")
    _quoted_possessive_context_pattern = re.compile(
        r"^[\"'“‘「『][^\"'”’」』]{1,12}[\"'”’」』]的[\"'“‘「『][^\"'”’」』]{1,20}[\"'”’」』]$"
    )
    _ordinal_context_phrase_pattern = re.compile(
        r"^(?:第)?[0-9零一二三四五六七八九十百千万两]+届的[一-龥]{1,12}$"
    )
    _descriptive_persona_pattern = re.compile(
        r"^(?=.{5,14}$)(?=.*(?:天才|美少女|美女|少女|学姐|学妹|校花|剑术|术法|知性|冷艳|漂亮|可爱))[一-龥]+"
        r"(?:美少女|美女|少女|学姐|学妹|校花|天才)$"
    )

    def evaluate(
        self,
        *,
        chapter_id: int,
        chapter_index: int,
        chapter_title: str,
        chapter_text: str,
        envelope: GlossaryExtractionEnvelope,
        matched_existing_terms: list[MatchedExistingGlossaryTerm],
    ) -> GlossaryChapterExtractionResult:
        combined_text = f"{chapter_title}\n{chapter_text}"
        issues: list[GlossaryExtractionQualityIssue] = []
        accepted_terms: list[GlossaryExtraction] = []
        existing_by_source = {item.source_term: item for item in matched_existing_terms}

        for term in envelope.terms:
            if term.source_term in existing_by_source:
                issues.append(
                    GlossaryExtractionQualityIssue(
                        issue_type="duplicate_existing",
                        severity="low",
                        message="候选与当前章节命中的已有术语完全重复，已过滤。",
                        source_term=term.source_term,
                    )
                )
                continue
            if self._structure_scaffold_pattern.fullmatch(term.source_term.strip()):
                issues.append(
                    GlossaryExtractionQualityIssue(
                        issue_type="structure_scaffold",
                        severity="low",
                        message="候选是章节结构壳，已过滤。",
                        source_term=term.source_term,
                    )
                )
                continue
            if term.source_term not in combined_text:
                issues.append(
                    GlossaryExtractionQualityIssue(
                        issue_type="source_not_in_chapter",
                        severity="high",
                        message="候选 source_term 未出现在章节标题或正文中，已过滤。",
                        source_term=term.source_term,
                        suggested_action="skip_candidate",
                    )
                )
                continue
            if self._is_non_glossary_context_phrase(term):
                issues.append(
                    GlossaryExtractionQualityIssue(
                        issue_type="non_glossary_context_phrase",
                        severity="low",
                        message="候选是上下文描述短语，已过滤，不进入主术语表。",
                        source_term=term.source_term,
                        suggested_action="skip_candidate",
                    )
                )
                continue
            relation_issue = self._build_relation_issue(term=term, matched_existing_terms=matched_existing_terms)
            if relation_issue is not None:
                issues.append(relation_issue)
            accepted_terms.append(term)

        if len(envelope.terms) > 40:
            issues.append(
                GlossaryExtractionQualityIssue(
                    issue_type="too_many_candidates",
                    severity="medium",
                    message="单章候选数量异常偏多，需要质检确认。",
                    suggested_action="llm_quality_review",
                )
            )

        status = self._resolve_status(
            envelope=envelope,
            accepted_terms=accepted_terms,
            issues=issues,
            combined_text=combined_text,
        )
        return GlossaryChapterExtractionResult(
            chapter_id=chapter_id,
            chapter_index=chapter_index,
            chapter_title=chapter_title,
            status=status,
            terms=accepted_terms,
            matched_existing_terms=matched_existing_terms,
            reason=envelope.reason,
            quality_issues=issues,
        )

    def should_run_llm_quality_review(self, result: GlossaryChapterExtractionResult) -> bool:
        if result.status == "suspicious_empty":
            return True
        return any(issue.severity in {"medium", "high"} for issue in result.quality_issues)

    def _resolve_status(
        self,
        *,
        envelope: GlossaryExtractionEnvelope,
        accepted_terms: list[GlossaryExtraction],
        issues: list[GlossaryExtractionQualityIssue],
        combined_text: str,
    ) -> str:
        if accepted_terms:
            return "terms_found"
        if any(issue.issue_type == "source_not_in_chapter" and issue.severity == "high" for issue in issues):
            return "skipped"
        if envelope.extraction_status == "no_new_terms":
            if self._is_suspicious_empty(combined_text=combined_text):
                issues.append(
                    GlossaryExtractionQualityIssue(
                        issue_type="suspicious_empty",
                        severity="medium",
                        message="章节存在疑似专名形态，但抽取结果为 no_new_terms。",
                        suggested_action="targeted_reextract",
                    )
                )
                return "suspicious_empty"
            return "no_new_terms"
        return "no_new_terms"

    def _is_suspicious_empty(self, *, combined_text: str) -> bool:
        if len(combined_text) >= 1200:
            return True
        return len(self._name_like_pattern.findall(combined_text)) >= 2

    def _is_non_glossary_context_phrase(self, term: GlossaryExtraction) -> bool:
        source_term = term.source_term.strip()
        if self._quoted_possessive_context_pattern.fullmatch(source_term):
            return True
        if self._ordinal_context_phrase_pattern.fullmatch(source_term):
            return True
        if term.category == "character" and self._descriptive_persona_pattern.fullmatch(source_term):
            return True
        return False

    def _build_relation_issue(
        self,
        *,
        term: GlossaryExtraction,
        matched_existing_terms: list[MatchedExistingGlossaryTerm],
    ) -> GlossaryExtractionQualityIssue | None:
        if term.term_group_key != term.source_term:
            return None
        for existing in matched_existing_terms:
            if existing.category != term.category:
                continue
            if term.source_term in existing.source_term or existing.source_term in term.source_term:
                return GlossaryExtractionQualityIssue(
                    issue_type="relation_risk",
                    severity="medium",
                    message="候选疑似已有实体的别名或变体，但没有绑定已有 term_group_key。",
                    source_term=term.source_term,
                    suggested_action="llm_quality_review",
                )
        return None
