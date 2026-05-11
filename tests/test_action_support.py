from __future__ import annotations


def test_action_support_resolves_stage_window() -> None:
    from tools.local_translation_workbench.app.action_support import _resolve_stage_window

    assert _resolve_stage_window(from_stage="glossary", until_stage="translation") == (
        "glossary",
        "translation",
    )


def test_action_support_builds_missing_synopsis_summary() -> None:
    from tools.local_translation_workbench.app.action_support import _build_synopsis_summary

    assert _build_synopsis_summary(None) == {
        "source": {"status": "missing", "origin": None, "length": 0, "length_unit": "characters"},
        "target": {"status": "missing", "origin": None, "length": 0, "length_unit": "characters"},
    }
