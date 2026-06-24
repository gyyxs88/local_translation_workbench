from __future__ import annotations

from pathlib import Path

import pytest

from tools.local_translation_workbench.app.editorial_runtime.io import read_yaml
from tools.local_translation_workbench.app.editorial_runtime.service import EditorialRuntimeService
from tools.local_translation_workbench.app.errors import ToolError


def _prepared_service(tmp_path: Path) -> EditorialRuntimeService:
    service = EditorialRuntimeService(tmp_path)
    service.init_project(
        project_key="lantern_demo",
        title="青灯小先生",
        source_language="zh",
        target_language="en",
    )
    service.prepare_source(
        project_key="lantern_demo",
        synopsis="",
        chapters=[{"chapter_key": "ch001", "title": "第一章", "source_text": "林溪点亮青灯。"}],
    )
    service.assign_chapter(project_key="lantern_demo", chapter_key="ch001", brief="Translate chapter 1.")
    service.prepare_term_pack(
        project_key="lantern_demo",
        chapter_key="ch001",
        terms=[{"source_term": "林溪", "target_term": "Lin Xi", "status": "approved"}],
    )
    return service


def test_workstation_outputs_advance_chapter_state(tmp_path: Path) -> None:
    service = _prepared_service(tmp_path)

    service.write_raw(
        project_key="lantern_demo",
        chapter_key="ch001",
        content="Lin Xi lit the blue lantern.",
        note="main translator draft",
    )
    service.write_bilingual_review(
        project_key="lantern_demo",
        chapter_key="ch001",
        content="- pass: terminology Lin Xi is consistent\n",
        needs_annotation=False,
    )
    service.adjudicate_review(
        project_key="lantern_demo",
        chapter_key="ch001",
        decision="accept_review_scope",
        content="Chief editor accepts the review scope.",
    )
    payload = service.write_revision(
        project_key="lantern_demo",
        chapter_key="ch001",
        content="Lin Xi lit the azure lamp.",
        annotations=[{"status": "approved", "text": "Azure lamp is a recurring artifact."}],
    )

    chapter_root = tmp_path / "lantern_demo" / "chapters" / "ch001"
    assert payload["status"] == "revision_ready"
    assert (chapter_root / "raw" / "main-translator.md").read_text(encoding="utf-8") == "Lin Xi lit the blue lantern.\n"
    assert (chapter_root / "review" / "bilingual-review.md").is_file()
    assert (chapter_root / "review" / "adjudication.md").is_file()
    assert (chapter_root / "revised" / "line-editor.md").read_text(encoding="utf-8") == "Lin Xi lit the azure lamp.\n"
    assert "Azure lamp" in (chapter_root / "annotations.md").read_text(encoding="utf-8")
    assert read_yaml(chapter_root / "record.yaml")["status"] == "revision_ready"


def test_review_cannot_run_before_raw(tmp_path: Path) -> None:
    service = _prepared_service(tmp_path)

    with pytest.raises(ToolError) as exc_info:
        service.write_bilingual_review(
            project_key="lantern_demo",
            chapter_key="ch001",
            content="review",
            needs_annotation=False,
        )

    assert exc_info.value.code == "conflict_error"
