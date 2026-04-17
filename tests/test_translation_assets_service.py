from __future__ import annotations

from types import SimpleNamespace

from tools.local_translation_workbench.app.services.translation_assets_service import (
    TranslationAssetsService,
)


def _entry(source_term: str, target_term: str, *, gender=None, age_group=None):
    return SimpleNamespace(
        source_term=source_term,
        target_term=target_term,
        category="character",
        note=None,
        gender=gender,
        age_group=age_group,
        status="active",
        locked=0,
        term_group_key=source_term,
        relation_role="independent",
    )


def test_translation_assets_service_prefers_longest_non_overlapping_terms() -> None:
    service = TranslationAssetsService()

    selected = service.build_prompt_glossary_entries(
        glossary_entries=[
            _entry("张望", "Zhang Wang"),
            _entry("张望月", "Zhang Wangyue"),
        ],
        source_text="张望月看着张望。",
    )

    assert [item.source_term for item in selected] == ["张望月", "张望"]


def test_translation_assets_service_snapshot_changes_when_gender_or_age_group_changes() -> None:
    service = TranslationAssetsService()

    baseline = service.compute_glossary_snapshot_id([_entry("林溪", "Lin Xi", gender="female")])
    changed = service.compute_glossary_snapshot_id([_entry("林溪", "Lin Xi", gender="female", age_group="teen")])

    assert changed != baseline
