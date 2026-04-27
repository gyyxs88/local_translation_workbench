from __future__ import annotations

import json

import pytest

from tools.local_translation_workbench.app.errors import ToolError
from tools.local_translation_workbench.app.services.glossary_prompt_service import GlossaryPromptService


def test_parse_terms_found_envelope() -> None:
    service = GlossaryPromptService()

    parsed = service.parse_extraction_response(
        json.dumps(
            {
                "extraction_status": "terms_found",
                "terms": [
                    {
                        "source_term": "时羽",
                        "translated_term": "Shi Yu",
                        "category": "character",
                        "note": "新登场人物",
                        "gender": "female",
                        "age_group": None,
                        "term_group_key": "char_shiyu",
                        "relation_role": "canonical",
                    }
                ],
                "reason": "发现新增主要人物。",
            },
            ensure_ascii=False,
        )
    )

    assert parsed.extraction_status == "terms_found"
    assert parsed.reason == "发现新增主要人物。"
    assert parsed.repaired is False
    assert len(parsed.terms) == 1
    assert parsed.terms[0].source_term == "时羽"
    assert parsed.terms[0].suggested_term == "Shi Yu"
    assert parsed.terms[0].gender == "female"


def test_parse_no_new_terms_envelope() -> None:
    service = GlossaryPromptService()

    parsed = service.parse_extraction_response(
        json.dumps(
            {
                "extraction_status": "no_new_terms",
                "terms": [],
                "reason": "本章没有新增专名。",
            },
            ensure_ascii=False,
        )
    )

    assert parsed.extraction_status == "no_new_terms"
    assert parsed.terms == []
    assert parsed.reason == "本章没有新增专名。"


@pytest.mark.parametrize("content", ["", "null", "[]", "{}", '{"terms":[]}'])
def test_parse_rejects_ambiguous_empty_outputs(content: str) -> None:
    service = GlossaryPromptService()

    with pytest.raises(ToolError, match="extraction_status"):
        service.parse_extraction_response(content)


def test_parse_rejects_no_new_terms_with_non_empty_terms() -> None:
    service = GlossaryPromptService()

    with pytest.raises(ToolError, match="no_new_terms"):
        service.parse_extraction_response(
            json.dumps(
                {
                    "extraction_status": "no_new_terms",
                    "terms": [
                        {
                            "source_term": "时羽",
                            "translated_term": "Shi Yu",
                            "category": "character",
                        }
                    ],
                    "reason": "冲突输出。",
                },
                ensure_ascii=False,
            )
        )


def test_parse_rejects_terms_found_with_empty_terms() -> None:
    service = GlossaryPromptService()

    with pytest.raises(ToolError, match="terms_found"):
        service.parse_extraction_response(
            json.dumps(
                {
                    "extraction_status": "terms_found",
                    "terms": [],
                    "reason": "冲突输出。",
                },
                ensure_ascii=False,
            )
        )
