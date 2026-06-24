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


def _revision_ready_service(tmp_path: Path) -> EditorialRuntimeService:
    service = _prepared_service(tmp_path)
    service.write_raw(
        project_key="lantern_demo",
        chapter_key="ch001",
        content="raw draft must not enter TM",
        note="raw",
    )
    service.write_bilingual_review(
        project_key="lantern_demo",
        chapter_key="ch001",
        content="review text must not enter TM",
        needs_annotation=True,
    )
    service.adjudicate_review(
        project_key="lantern_demo",
        chapter_key="ch001",
        decision="accept_with_annotation",
        content="Use line editor revision.",
    )
    service.write_revision(
        project_key="lantern_demo",
        chapter_key="ch001",
        content="Lin Xi lit the accepted azure lamp.",
        annotations=[
            {"status": "approved", "text": "Azure lamp is a recurring artifact."},
            {"status": "candidate", "text": "Candidate-only note must not export."},
        ],
    )
    return service


def test_accept_chapter_and_tm_use_only_accepted_text(tmp_path: Path) -> None:
    service = _revision_ready_service(tmp_path)

    accepted_payload = service.accept_chapter(project_key="lantern_demo", chapter_key="ch001", note="accepted by chief")
    tm_payload = service.derive_memory_from_accepted(project_key="lantern_demo")

    project_root = tmp_path / "lantern_demo"
    tm_text = (project_root / "memory" / "tm.accepted.jsonl").read_text(encoding="utf-8")
    assert accepted_payload["status"] == "accepted"
    assert tm_payload["entry_count"] == 1
    assert "Lin Xi lit the accepted azure lamp." in tm_text
    assert "raw draft must not enter TM" not in tm_text
    assert "review text must not enter TM" not in tm_text


def test_export_and_cache_read_accepted_documents(tmp_path: Path) -> None:
    service = _revision_ready_service(tmp_path)
    service.accept_chapter(project_key="lantern_demo", chapter_key="ch001", note="accepted by chief")

    cache_payload = service.rebuild_cache(project_key="lantern_demo")
    export_payload = service.build_export(project_key="lantern_demo")

    project_root = tmp_path / "lantern_demo"
    export_text = (project_root / "exports" / "export.md").read_text(encoding="utf-8")
    assert cache_payload["chapter_count"] == 1
    assert (project_root / ".ltw-cache" / "index.sqlite").is_file()
    assert export_payload["chapter_count"] == 1
    assert "Lin Xi lit the accepted azure lamp." in export_text
    assert "Azure lamp is a recurring artifact." in export_text
    assert "Candidate-only note must not export." not in export_text
    assert read_yaml(project_root / "exports" / "manifest.yaml")["chapters"][0]["chapter_key"] == "ch001"
