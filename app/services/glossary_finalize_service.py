from __future__ import annotations

from ..db.models import GlossaryDraftCandidate
from ..errors import ToolError
from ..providers.base import Provider
from ..repositories.glossary import GlossaryRepository
from .glossary_prompt_service import GlossaryPromptService


class GlossaryFinalizeService:
    def __init__(
        self,
        *,
        glossary: GlossaryRepository,
        provider: Provider | None,
        prompts: GlossaryPromptService,
    ) -> None:
        self.glossary = glossary
        self.provider = provider
        self.prompts = prompts

    def build_finalized_terms(
        self,
        *,
        workflow_run_id: int,
        draft_items: list[GlossaryDraftCandidate],
        model_name: str,
    ) -> list[dict[str, object]]:
        if not draft_items:
            return []
        review_items = self.glossary.inspect_candidate_reviews(workflow_run_id=workflow_run_id)
        provider_terms = self.request_finalized_terms(
            workflow_run_id=workflow_run_id,
            review_items=review_items,
            model_name=model_name,
        )
        relation_reviews, scope_reviews = self.index_review_items(review_items)
        if provider_terms:
            hydrated_terms = self.hydrate_provider_final_terms(
                provider_terms=provider_terms,
                draft_items=draft_items,
                relation_reviews=relation_reviews,
                scope_reviews=scope_reviews,
            )
            if hydrated_terms:
                return hydrated_terms
        finalized_terms: list[dict[str, object]] = []
        for item in draft_items:
            relation_review = relation_reviews.get(item.id, {})
            scope_review = scope_reviews.get(item.id, {})
            scope_level = str(scope_review.get("scope_level") or item.scope_level)
            if scope_level == "discard":
                continue
            scope_chapter_id = scope_review.get("scope_chapter_id")
            if scope_level == "project_term":
                scope_chapter_id = None
            elif scope_chapter_id is None:
                scope_chapter_id = item.scope_chapter_id or item.chapter_id
            evidence_payload = item.evidence_payload if isinstance(item.evidence_payload, dict) else {}
            finalized_terms.append(
                {
                    "draft_candidate_id": item.id,
                    "chapter_id": item.chapter_id,
                    "source_term": item.source_term,
                    "target_term": item.suggested_term,
                    "category": item.category,
                    "note": evidence_payload.get("note"),
                    "gender": self.prompts.normalize_gender(
                        category=item.category,
                        gender=item.gender,
                    ),
                    "age_group": self.prompts.normalize_age_group(
                        category=item.category,
                        age_group=item.age_group,
                    ),
                    "term_group_key": str(relation_review.get("term_group_key") or item.term_group_key),
                    "relation_role": str(relation_review.get("relation_role") or item.relation_role),
                    "scope_level": scope_level,
                    "scope_chapter_id": scope_chapter_id,
                }
            )
        return finalized_terms

    def request_finalized_terms(
        self,
        *,
        workflow_run_id: int,
        review_items: list[dict[str, object]],
        model_name: str,
    ) -> list[dict[str, object]]:
        if self.provider is None:
            return []
        prompt = self.prompts.build_finalize_prompt(
            draft_candidates=self.glossary.inspect_draft_candidates(workflow_run_id=workflow_run_id),
            review_items=review_items,
        )
        try:
            response = self.provider.generate_text(prompt=prompt, model_name=model_name, timeout_seconds=120)
        except ToolError:
            return []
        return self.prompts.parse_review_items(response.content, "terms")

    def index_review_items(
        self,
        review_items: list[dict[str, object]],
    ) -> tuple[dict[int, dict[str, object]], dict[int, dict[str, object]]]:
        relation_reviews: dict[int, dict[str, object]] = {}
        scope_reviews: dict[int, dict[str, object]] = {}
        for item in review_items:
            draft_candidate_id = item.get("draft_candidate_id")
            if not isinstance(draft_candidate_id, int):
                continue
            if item.get("review_type") == "relation":
                relation_reviews[draft_candidate_id] = item
            elif item.get("review_type") == "scope":
                scope_reviews[draft_candidate_id] = item
        return relation_reviews, scope_reviews

    def hydrate_provider_final_terms(
        self,
        *,
        provider_terms: list[dict[str, object]],
        draft_items: list[GlossaryDraftCandidate],
        relation_reviews: dict[int, dict[str, object]],
        scope_reviews: dict[int, dict[str, object]],
    ) -> list[dict[str, object]]:
        draft_by_id = {item.id: item for item in draft_items}
        draft_by_source = {item.source_term: item for item in draft_items}
        hydrated_terms: list[dict[str, object]] = []
        for term in provider_terms:
            draft_candidate_id = term.get("draft_candidate_id")
            matched_draft = None
            if isinstance(draft_candidate_id, int):
                matched_draft = draft_by_id.get(draft_candidate_id)
            if matched_draft is None:
                matched_draft = draft_by_source.get(str(term.get("source_term") or ""))
            if matched_draft is None:
                continue
            relation_review = relation_reviews.get(matched_draft.id, {})
            scope_review = scope_reviews.get(matched_draft.id, {})
            scope_level = str(term.get("scope_level") or scope_review.get("scope_level") or matched_draft.scope_level)
            if scope_level == "discard":
                continue
            scope_chapter_id = term.get("scope_chapter_id", scope_review.get("scope_chapter_id"))
            if scope_level == "project_term":
                scope_chapter_id = None
            elif scope_chapter_id is None:
                scope_chapter_id = matched_draft.scope_chapter_id or matched_draft.chapter_id
            evidence_payload = matched_draft.evidence_payload if isinstance(matched_draft.evidence_payload, dict) else {}
            hydrated_terms.append(
                {
                    "draft_candidate_id": matched_draft.id,
                    "chapter_id": matched_draft.chapter_id,
                    "source_term": str(term.get("source_term") or matched_draft.source_term),
                    "target_term": str(
                        term.get("target_term") or term.get("suggested_term") or matched_draft.suggested_term
                    ),
                    "category": str(term.get("category") or matched_draft.category),
                    "note": term.get("note", evidence_payload.get("note")),
                    "gender": self.prompts.normalize_gender(
                        category=str(term.get("category") or matched_draft.category),
                        gender=term.get("gender", matched_draft.gender),
                    ),
                    "age_group": self.prompts.normalize_age_group(
                        category=str(term.get("category") or matched_draft.category),
                        age_group=term.get("age_group", matched_draft.age_group),
                    ),
                    "term_group_key": str(
                        term.get("term_group_key")
                        or relation_review.get("term_group_key")
                        or matched_draft.term_group_key
                    ),
                    "relation_role": str(
                        term.get("relation_role")
                        or relation_review.get("relation_role")
                        or matched_draft.relation_role
                    ),
                    "scope_level": scope_level,
                    "scope_chapter_id": scope_chapter_id,
                }
            )
        return hydrated_terms
