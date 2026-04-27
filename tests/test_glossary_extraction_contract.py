from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.local_translation_workbench.app.db.models import Chapter, TranslationProject
from tools.local_translation_workbench.app.errors import ToolError
from tools.local_translation_workbench.app.repositories.glossary import GlossaryRepository
from tools.local_translation_workbench.app.services.glossary_existing_term_context_service import (
    GlossaryExistingTermContextService,
)
from tools.local_translation_workbench.app.services.glossary_extraction_quality_service import (
    GlossaryExtractionQualityService,
)
from tools.local_translation_workbench.app.services.glossary_prompt_service import GlossaryPromptService
from tools.local_translation_workbench.app.services.glossary_types import (
    GlossaryExtraction,
    GlossaryExtractionEnvelope,
    MatchedExistingGlossaryTerm,
)


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


def test_existing_term_context_only_returns_terms_matched_in_current_chapter(db_session, tmp_path: Path) -> None:
    project = TranslationProject(
        request_id="glossary-context-project-request",
        project_key="glossary-context-project",
        source_path="source.txt",
        source_language="zh",
        target_language="en",
        status="created",
    )
    db_session.add(project)
    db_session.flush()
    chapter = Chapter(
        project_id=project.id,
        chapter_index=1,
        chapter_title="第1章 林溪的来信",
        source_path=str(tmp_path / "chapter-source.txt"),
        normalized_path=str(tmp_path / "chapter-normalized.txt"),
        stage_status="ready",
    )
    db_session.add(chapter)
    db_session.flush()

    repository = GlossaryRepository(db_session)
    repository.create_entry(
        project_id=project.id,
        source_term="林溪",
        target_term="Lin Xi",
        category="character",
        term_group_key="char_linxi",
        relation_role="canonical",
        scope_level="project_term",
    )
    repository.create_entry(
        project_id=project.id,
        source_term="深蓝公寓",
        target_term="Deep Blue Apartments",
        category="location",
        term_group_key="loc_deep_blue",
        relation_role="canonical",
        scope_level="project_term",
    )
    repository.create_entry(
        project_id=project.id,
        source_term="溪溪",
        target_term="Xixi",
        category="character",
        term_group_key="char_linxi",
        relation_role="alias",
        scope_level="chapter_term",
        scope_chapter_id=chapter.id,
    )

    matched = GlossaryExistingTermContextService(repository).list_matched_terms_for_chapter(
        project_id=project.id,
        chapter_id=chapter.id,
        chapter_title=chapter.chapter_title,
        chapter_text="溪溪把信交给林溪。",
    )

    assert [item.source_term for item in matched] == ["溪溪", "林溪"]
    assert {item.term_group_key for item in matched} == {"char_linxi"}


def test_extraction_prompt_includes_matched_existing_terms_and_requires_explicit_empty() -> None:
    service = GlossaryPromptService()

    prompt = service.build_extraction_prompt(
        chapter_text="溪溪把信交给林溪。",
        chapter_index=1,
        chapter_title="第1章 林溪的来信",
        source_language="zh",
        target_language="en",
        matched_existing_terms=[
            MatchedExistingGlossaryTerm(
                source_term="林溪",
                target_term="Lin Xi",
                category="character",
                note=None,
                gender="female",
                age_group=None,
                term_group_key="char_linxi",
                relation_role="canonical",
                scope_level="project_term",
                scope_chapter_id=None,
            )
        ],
        risk_signals=["possible_alias_without_group"],
        previous_extraction=None,
    )

    assert '"source_term": "林溪"' in prompt
    assert '"target_term": "Lin Xi"' in prompt
    assert "已有术语的译名和关系组必须沿用" in prompt
    assert "完全相同的已有 source_term 不要作为新增术语重复输出" in prompt
    assert '"extraction_status": "no_new_terms"' in prompt
    assert "不能返回空字符串、null、空数组或只有 terms 的对象" in prompt
    assert "possible_alias_without_group" in prompt


def test_quality_filters_duplicate_existing_terms() -> None:
    service = GlossaryExtractionQualityService()
    matched = [
        MatchedExistingGlossaryTerm(
            source_term="林溪",
            target_term="Lin Xi",
            category="character",
            note=None,
            gender="female",
            age_group=None,
            term_group_key="char_linxi",
            relation_role="canonical",
            scope_level="project_term",
            scope_chapter_id=None,
        )
    ]
    envelope = GlossaryExtractionEnvelope(
        extraction_status="terms_found",
        terms=[
            GlossaryExtraction(
                source_term="林溪",
                suggested_term="Lin Xi",
                category="character",
                note=None,
                term_group_key="char_linxi",
                relation_role="canonical",
                gender="female",
                age_group=None,
            )
        ],
        reason="模型重复输出已有术语。",
    )

    result = service.evaluate(
        chapter_id=10,
        chapter_index=1,
        chapter_title="第1章",
        chapter_text="林溪打开窗。",
        envelope=envelope,
        matched_existing_terms=matched,
    )

    assert result.status == "no_new_terms"
    assert result.terms == []
    assert [issue.issue_type for issue in result.quality_issues] == ["duplicate_existing"]


def test_quality_marks_suspicious_empty_when_name_like_terms_exist() -> None:
    service = GlossaryExtractionQualityService()
    envelope = GlossaryExtractionEnvelope(
        extraction_status="no_new_terms",
        terms=[],
        reason="没有新增术语。",
    )

    result = service.evaluate(
        chapter_id=10,
        chapter_index=1,
        chapter_title="第1章",
        chapter_text="时羽小姐推开门。望月同学站在走廊尽头。",
        envelope=envelope,
        matched_existing_terms=[],
    )

    assert result.status == "suspicious_empty"
    assert any(issue.issue_type == "suspicious_empty" for issue in result.quality_issues)


def test_quality_filters_terms_not_present_in_chapter() -> None:
    service = GlossaryExtractionQualityService()
    envelope = GlossaryExtractionEnvelope(
        extraction_status="terms_found",
        terms=[
            GlossaryExtraction(
                source_term="不存在的人名",
                suggested_term="Missing Name",
                category="character",
                note=None,
                term_group_key="char_missing",
                relation_role="canonical",
                gender=None,
                age_group=None,
            )
        ],
        reason="模型幻觉。",
    )

    result = service.evaluate(
        chapter_id=10,
        chapter_index=1,
        chapter_title="第1章",
        chapter_text="林溪打开窗。",
        envelope=envelope,
        matched_existing_terms=[],
    )

    assert result.status == "skipped"
    assert result.terms == []
    assert any(issue.issue_type == "source_not_in_chapter" for issue in result.quality_issues)
