from __future__ import annotations

from pathlib import Path

import pytest

from tools.local_translation_workbench.app.editorial_runtime.io import (
    append_jsonl,
    compute_sha256,
    normalize_project_key,
    read_yaml,
    write_text,
    write_yaml,
)
from tools.local_translation_workbench.app.errors import ToolError


def test_normalize_project_key_accepts_safe_keys() -> None:
    assert normalize_project_key("novel_001") == "novel_001"
    assert normalize_project_key("novel-001") == "novel-001"


@pytest.mark.parametrize("value", ["../escape", "Novel 001", "a", "中文项目", "novel/001"])
def test_normalize_project_key_rejects_unsafe_keys(value: str) -> None:
    with pytest.raises(ToolError) as exc_info:
        normalize_project_key(value)

    assert exc_info.value.code == "invalid_arguments"


def test_write_text_creates_parent_and_hashes_file(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b" / "chapter.md"

    write_text(path, "第一章\n")

    assert path.read_text(encoding="utf-8") == "第一章\n"
    assert compute_sha256(path) == "678f414c39e432e3b6f54228e2dde7a691fab5924430cd962bdf8f1cf13a8d96"


def test_yaml_round_trip_preserves_unicode_and_order(tmp_path: Path) -> None:
    path = tmp_path / "manifest.yaml"

    write_yaml(
        path,
        {
            "project_key": "demo",
            "title": "青灯小先生",
            "chapters": [{"chapter_key": "ch001", "status": "planned"}],
        },
    )

    assert read_yaml(path) == {
        "project_key": "demo",
        "title": "青灯小先生",
        "chapters": [{"chapter_key": "ch001", "status": "planned"}],
    }


def test_append_jsonl_writes_utf8_records(tmp_path: Path) -> None:
    path = tmp_path / "memory" / "tm.accepted.jsonl"

    append_jsonl(path, [{"chapter_key": "ch001", "target_text": "Lantern"}])

    assert path.read_text(encoding="utf-8") == '{"chapter_key": "ch001", "target_text": "Lantern"}\n'
