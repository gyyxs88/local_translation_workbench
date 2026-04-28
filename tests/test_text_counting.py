from __future__ import annotations

from tools.local_translation_workbench.app.db.models import ProjectSynopsis
from tools.local_translation_workbench.app.services.synopsis_service import SynopsisService
from tools.local_translation_workbench.app.text_counting import build_text_count_payload, count_text_units


def test_count_text_units_counts_cjk_non_whitespace_characters() -> None:
    assert count_text_units("江湖！\n何谓江湖？") == 8


def test_count_text_units_counts_non_cjk_words() -> None:
    assert count_text_units("The Evil Doctor returns to the jianghu.") == 7


def test_build_text_count_payload_reports_unit() -> None:
    assert build_text_count_payload("The Shennong Ruler's Spirit returns.") == {
        "length": 5,
        "length_unit": "words",
    }


def test_synopsis_summary_counts_translated_non_cjk_text_as_words() -> None:
    synopsis = ProjectSynopsis(
        project_id=1,
        source_synopsis_text="二十年前叱咤风云",
        source_synopsis_status="ready",
        source_synopsis_origin="extracted",
        target_synopsis_text="The Evil Doctor returns to the jianghu.",
        target_synopsis_status="ready",
        target_synopsis_origin="translated",
    )

    summary = SynopsisService(None).build_summary(synopsis)

    assert summary["source"]["length"] == 8
    assert summary["source"]["length_unit"] == "characters"
    assert summary["target"]["length"] == 7
    assert summary["target"]["length_unit"] == "words"
