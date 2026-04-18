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


def test_translation_assets_service_renders_group_blocks_in_match_order() -> None:
    service = TranslationAssetsService()
    glossary_entries = [
        SimpleNamespace(
            source_term="林溪",
            target_term="Lin Xi",
            category="character",
            note=None,
            gender="female",
            age_group="teen",
            status="active",
            locked=0,
            term_group_key="char_linxi",
            relation_role="canonical",
        ),
        SimpleNamespace(
            source_term="小溪",
            target_term="Little Xi",
            category="character",
            note=None,
            gender="female",
            age_group="teen",
            status="active",
            locked=0,
            term_group_key="char_linxi",
            relation_role="alias",
        ),
        SimpleNamespace(
            source_term="秦大人",
            target_term="Lord Qin",
            category="character",
            note=None,
            gender=None,
            age_group=None,
            status="active",
            locked=0,
            term_group_key="title_lord_qin",
            relation_role="title",
        ),
    ]

    prompt = service.build_translation_prompt(
        source_language="zh",
        target_language="en",
        chapter_index=1,
        segment_index=1,
        source_text="小溪向秦大人行礼，林溪没有说话。",
        glossary_entries=service.build_prompt_glossary_entries(
            glossary_entries=glossary_entries,
            source_text="小溪向秦大人行礼，林溪没有说话。",
        ),
    )

    assert "[group char_linxi]" in prompt
    assert "[group title_lord_qin]" in prompt
    assert prompt.index("[group char_linxi]") < prompt.index("[group title_lord_qin]")
    assert prompt.index("- 林溪 => Lin Xi") < prompt.index("- 小溪 => Little Xi")


def test_translation_assets_service_does_not_inject_unmatched_canonical_from_same_group() -> None:
    service = TranslationAssetsService()
    glossary_entries = [
        SimpleNamespace(
            source_term="林溪",
            target_term="Lin Xi",
            category="character",
            note=None,
            gender="female",
            age_group="teen",
            status="active",
            locked=0,
            term_group_key="char_linxi",
            relation_role="canonical",
        ),
        SimpleNamespace(
            source_term="小溪",
            target_term="Little Xi",
            category="character",
            note=None,
            gender="female",
            age_group="teen",
            status="active",
            locked=0,
            term_group_key="char_linxi",
            relation_role="alias",
        ),
    ]

    selected = service.build_prompt_glossary_entries(
        glossary_entries=glossary_entries,
        source_text="小溪笑了。",
    )

    assert [item.source_term for item in selected] == ["小溪"]
