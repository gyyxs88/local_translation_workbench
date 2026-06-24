from __future__ import annotations

from pathlib import Path

from tools.local_translation_workbench.app.editorial_runtime.io import read_yaml
from tools.local_translation_workbench.app.editorial_runtime.service import EditorialRuntimeService


def test_init_project_creates_editorial_document_tree(tmp_path: Path) -> None:
    service = EditorialRuntimeService(tmp_path)

    payload = service.init_project(
        project_key="lantern_demo",
        title="青灯小先生",
        source_language="zh",
        target_language="en",
    )

    project_root = tmp_path / "lantern_demo"
    assert payload["project_key"] == "lantern_demo"
    assert payload["project_root"] == str(project_root)
    assert (project_root / "manifest.yaml").is_file()
    assert (project_root / "editorial-ledger.yaml").is_file()
    assert (project_root / "source" / "manifest.yaml").is_file()
    assert (project_root / "source" / "chapters").is_dir()
    assert (project_root / "source" / "segments").is_dir()
    assert (project_root / "rules" / "style-guide.md").is_file()
    assert (project_root / "rules" / "glossary.yaml").is_file()
    assert (project_root / "rules" / "glossary-candidates.yaml").is_file()
    assert (project_root / "memory" / "tm.accepted.jsonl").is_file()
    assert (project_root / "chapters").is_dir()
    assert (project_root / "exports").is_dir()
    assert (project_root / ".ltw-cache").is_dir()

    manifest = read_yaml(project_root / "manifest.yaml")
    assert manifest["project_key"] == "lantern_demo"
    assert manifest["title"] == "青灯小先生"
    assert manifest["source_language"] == "zh"
    assert manifest["target_language"] == "en"
    assert manifest["runtime"] == "editorial"
    assert manifest["compatibility"] == "not_backward_compatible"


def test_init_project_is_idempotent_for_existing_project(tmp_path: Path) -> None:
    service = EditorialRuntimeService(tmp_path)

    first = service.init_project(
        project_key="lantern_demo",
        title="青灯小先生",
        source_language="zh",
        target_language="en",
    )
    second = service.init_project(
        project_key="lantern_demo",
        title="ignored title",
        source_language="ja",
        target_language="fr",
    )

    manifest = read_yaml(tmp_path / "lantern_demo" / "manifest.yaml")
    assert first["project_key"] == second["project_key"]
    assert manifest["title"] == "青灯小先生"
    assert manifest["source_language"] == "zh"
    assert manifest["target_language"] == "en"


def test_prepare_source_writes_manifest_and_chapter_files(tmp_path: Path) -> None:
    service = EditorialRuntimeService(tmp_path)
    service.init_project(
        project_key="lantern_demo",
        title="青灯小先生",
        source_language="zh",
        target_language="en",
    )

    payload = service.prepare_source(
        project_key="lantern_demo",
        synopsis="这是一个关于青灯的故事。",
        chapters=[
            {"chapter_key": "ch001", "title": "第一章", "source_text": "林溪点亮青灯。"},
            {"chapter_key": "ch002", "title": "第二章", "source_text": "赵馨宁推开门。"},
        ],
    )

    project_root = tmp_path / "lantern_demo"
    manifest = read_yaml(project_root / "source" / "manifest.yaml")
    assert payload["chapter_count"] == 2
    assert (project_root / "source" / "synopsis.md").read_text(encoding="utf-8") == "这是一个关于青灯的故事。\n"
    assert (project_root / "source" / "chapters" / "ch001.md").read_text(encoding="utf-8") == "林溪点亮青灯。\n"
    assert manifest["chapters"][0]["chapter_key"] == "ch001"
    assert manifest["chapters"][0]["title"] == "第一章"
    assert len(manifest["chapters"][0]["source_sha256"]) == 64


def test_assign_chapter_and_term_pack_create_workstation_inputs(tmp_path: Path) -> None:
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

    service.assign_chapter(
        project_key="lantern_demo",
        chapter_key="ch001",
        brief="保持古典但清爽的英文表达。",
    )
    payload = service.prepare_term_pack(
        project_key="lantern_demo",
        chapter_key="ch001",
        terms=[{"source_term": "林溪", "target_term": "Lin Xi", "status": "approved"}],
    )

    chapter_root = tmp_path / "lantern_demo" / "chapters" / "ch001"
    assert (chapter_root / "task.md").read_text(encoding="utf-8").startswith("# ch001 Task")
    assert "Lin Xi" in (chapter_root / "term-pack.md").read_text(encoding="utf-8")
    assert payload["status"] == "term_ready"
    assert read_yaml(chapter_root / "record.yaml")["status"] == "term_ready"
