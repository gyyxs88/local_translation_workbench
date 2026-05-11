from __future__ import annotations

from ..repositories.glossary import GlossaryRepository
from .glossary_types import MatchedExistingGlossaryTerm
from .translation_assets_service import TranslationAssetsService


class GlossaryExistingTermContextService:
    def __init__(
        self,
        glossary: GlossaryRepository,
        *,
        translation_assets: TranslationAssetsService | None = None,
    ) -> None:
        self.glossary = glossary
        self.translation_assets = translation_assets or TranslationAssetsService()

    def list_matched_terms_for_chapter(
        self,
        *,
        project_id: int,
        chapter_id: int,
        chapter_title: str,
        chapter_text: str,
    ) -> list[MatchedExistingGlossaryTerm]:
        active_entries = self.glossary.list_active_entries_for_matching(
            project_id,
            scope_level="chapter_term",
            scope_chapter_id=chapter_id,
            include_project_scope=True,
        )
        matched_entries = self.translation_assets.build_prompt_glossary_entries(
            glossary_entries=active_entries,
            source_text=f"{chapter_title}\n{chapter_text}",
        )
        return [
            MatchedExistingGlossaryTerm(
                source_term=str(entry.source_term),
                target_term=str(entry.target_term),
                category=str(entry.category),
                note=entry.note,
                gender=entry.gender,
                age_group=entry.age_group,
                term_group_key=str(entry.term_group_key),
                relation_role=str(entry.relation_role),
                scope_level=str(entry.scope_level),
                scope_chapter_id=entry.scope_chapter_id,
            )
            for entry in sorted(
                matched_entries,
                key=lambda item: (
                    str(item.scope_level),
                    int(item.scope_chapter_id or 0),
                    str(item.term_group_key),
                    str(item.relation_role),
                    str(item.source_term),
                ),
            )
        ]
