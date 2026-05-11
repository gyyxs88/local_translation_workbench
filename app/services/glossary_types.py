from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GlossaryExtraction:
    source_term: str
    suggested_term: str
    category: str
    note: str | None
    term_group_key: str
    relation_role: str
    gender: str | None
    age_group: str | None


@dataclass(frozen=True)
class MatchedExistingGlossaryTerm:
    source_term: str
    target_term: str
    category: str
    note: str | None
    gender: str | None
    age_group: str | None
    term_group_key: str
    relation_role: str
    scope_level: str
    scope_chapter_id: int | None

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "source_term": self.source_term,
            "target_term": self.target_term,
            "category": self.category,
            "term_group_key": self.term_group_key,
            "relation_role": self.relation_role,
            "scope_level": self.scope_level,
            "scope_chapter_id": self.scope_chapter_id,
        }
        if self.note is not None:
            payload["note"] = self.note
        if self.gender is not None:
            payload["gender"] = self.gender
        if self.age_group is not None:
            payload["age_group"] = self.age_group
        return payload


@dataclass(frozen=True)
class GlossaryExtractionEnvelope:
    extraction_status: str
    terms: list[GlossaryExtraction]
    reason: str | None
    repaired: bool = False


@dataclass(frozen=True)
class GlossaryExtractionQualityIssue:
    issue_type: str
    severity: str
    message: str
    source_term: str | None = None
    source_evidence: str | None = None
    suggested_action: str | None = None

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "issue_type": self.issue_type,
            "severity": self.severity,
            "message": self.message,
        }
        if self.source_term is not None:
            payload["source_term"] = self.source_term
        if self.source_evidence is not None:
            payload["source_evidence"] = self.source_evidence
        if self.suggested_action is not None:
            payload["suggested_action"] = self.suggested_action
        return payload


@dataclass(frozen=True)
class GlossaryChapterExtractionResult:
    chapter_id: int
    chapter_index: int
    chapter_title: str
    status: str
    terms: list[GlossaryExtraction]
    matched_existing_terms: list[MatchedExistingGlossaryTerm]
    reason: str | None
    quality_issues: list[GlossaryExtractionQualityIssue]
    llm_quality_review: dict[str, object] | None = None

    def as_payload(self) -> dict[str, object]:
        return {
            "chapter_id": self.chapter_id,
            "chapter_index": self.chapter_index,
            "chapter_title": self.chapter_title,
            "status": self.status,
            "term_count": len(self.terms),
            "matched_existing_term_count": len(self.matched_existing_terms),
            "matched_existing_terms": [item.as_payload() for item in self.matched_existing_terms],
            "reason": self.reason,
            "quality_issues": [issue.as_payload() for issue in self.quality_issues],
            "llm_quality_review": self.llm_quality_review,
        }


@dataclass(frozen=True)
class GlossaryLlmQualityReview:
    passed: bool
    issues: list[GlossaryExtractionQualityIssue]

    def as_payload(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "issues": [issue.as_payload() for issue in self.issues],
        }
