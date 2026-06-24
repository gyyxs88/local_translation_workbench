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
