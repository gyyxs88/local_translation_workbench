# LTW Editorial Runtime Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first working vertical slice of LTW Editorial Runtime: local document projects, workstation records, chapter state validation, accepted-only TM/export/cache, and Codex-facing actions without external model or MySQL dependency in the new runtime code.

**Architecture:** Add a new `app/editorial_runtime/` module beside the legacy MySQL pipeline. The module owns document-backed project operations and exposes thin action handlers; documents are the source of truth, SQLite is rebuildable cache, and legacy CLI/database actions are not compatibility constraints.

**Tech Stack:** Python 3.10+, pathlib, dataclasses, json, sqlite3, PyYAML, pytest, existing `ToolError`, existing `route_action` dispatch table.

---

## Scope Check

This plan implements Phase 1 only. It deliberately avoids real autonomous translation, external provider calls, UI, old MySQL migration, and old CLI compatibility preservation.

Phase 1 produces working software for these spec requirements:

- Create Editorial Runtime project directories.
- Prepare source manifest and chapter files.
- Write and validate five resident workstation records.
- Run one chapter through term pack -> raw -> bilingual review -> adjudication -> revised -> accepted.
- Derive TM only from accepted text.
- Rebuild SQLite cache only from document source of truth.
- Build export only from accepted chapters and approved annotations.
- Expose Codex-facing actions through the current action router while keeping the runtime code independent from MySQL.

The current repository test harness has a session-level MySQL fixture. Until that fixture is refactored in a separate cleanup, run pytest commands with the existing `LTW_TEST_DATABASE_URL` test database configured. The new `app/editorial_runtime/` code must not read `LTW_DATABASE_URL`, open SQLAlchemy sessions, or import legacy repositories.

## File Structure

Create:

- `app/editorial_runtime/__init__.py`
  - Public exports for the new runtime.
- `app/editorial_runtime/constants.py`
  - Workstation names, chapter states, term states, annotation states, and allowed transitions.
- `app/editorial_runtime/io.py`
  - UTF-8 text IO, YAML/JSONL helpers, project key validation, SHA-256 hashing.
- `app/editorial_runtime/config.py`
  - Resolve `LTW_EDITORIAL_HOME`; default to `data/editorial_projects`.
- `app/editorial_runtime/service.py`
  - Document-backed project, source, workstation, accepted, memory, export, cache, and inspection operations.
- `app/action_handlers/editorial_runtime_handlers.py`
  - Thin action handlers that parse arguments and call `EditorialRuntimeService`.
- `tests/test_editorial_runtime_io.py`
  - Pure helper tests.
- `tests/test_editorial_runtime_project.py`
  - Project init, source preparation, chapter assignment tests.
- `tests/test_editorial_runtime_workflow.py`
  - Single chapter workstation and accepted/TM/export/cache tests.
- `tests/test_editorial_runtime_actions.py`
  - Action-router tests for the new Codex-facing actions.

Modify:

- `pyproject.toml`
  - Add `PyYAML==6.0.2`.
- `requirements.txt`
  - Add `PyYAML==6.0.2`.
- `app/action_handlers/__init__.py`
  - Register Editorial Runtime handlers.
- `app/cli.py`
  - Add argument aliases for new action parameters.
- `TOOL.json`
  - Add action enum values and argument descriptions for the new actions.
- `codex_skill/local_translation_workbench/SKILL.md`
  - Add Editorial Runtime protocol and workstation boundaries.
- `README.md`
  - Add a short note that new Editorial Runtime projects use document facts and `LTW_EDITORIAL_HOME`.
- `docs/operations/runbook.md`
  - Add one single-chapter dry-run example.

Do not modify:

- `app/db/models.py`
- `migrations/`
- Legacy provider/profile/workflow services
- Legacy stage runner

---

### Task 1: Add Editorial Runtime IO Primitives

**Files:**
- Modify: `pyproject.toml`
- Modify: `requirements.txt`
- Create: `app/editorial_runtime/__init__.py`
- Create: `app/editorial_runtime/constants.py`
- Create: `app/editorial_runtime/io.py`
- Test: `tests/test_editorial_runtime_io.py`

- [ ] **Step 1: Write the failing IO tests**

Create `tests/test_editorial_runtime_io.py`:

```python
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
```

- [ ] **Step 2: Run the failing IO tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_editorial_runtime_io.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tools.local_translation_workbench.app.editorial_runtime'`.

- [ ] **Step 3: Add PyYAML dependency**

Modify `pyproject.toml` dependency list:

```toml
dependencies = [
  "SQLAlchemy==2.0.39",
  "alembic==1.15.1",
  "PyMySQL==1.1.1",
  "cryptography==44.0.2",
  "pydantic==2.10.6",
  "json-repair==0.59.5",
  "PyYAML==6.0.2"
]
```

Modify `requirements.txt`:

```text
SQLAlchemy==2.0.39
alembic==1.15.1
PyMySQL==1.1.1
cryptography==44.0.2
pydantic==2.10.6
pytest==8.3.5
json-repair==0.59.5
PyYAML==6.0.2
```

- [ ] **Step 4: Create runtime package and constants**

Create `app/editorial_runtime/__init__.py`:

```python
from __future__ import annotations

from .service import EditorialRuntimeService

__all__ = ["EditorialRuntimeService"]
```

Create `app/editorial_runtime/constants.py`:

```python
from __future__ import annotations

RESIDENT_DECISION_DESKS = ("chief_translation_editor", "terminology_editor")
RESIDENT_PRODUCTION_DESKS = ("main_translator", "bilingual_reviewer", "line_editor")
EVENT_DESKS = ("structure_secretary", "archive_exporter", "external_reference_reviewer")

CHAPTER_STATES = (
    "planned",
    "term_ready",
    "raw_ready",
    "review_ready",
    "revision_ready",
    "accepted",
    "stale",
    "blocked",
    "cancelled",
)

TERM_STATES = ("candidate", "approved", "locked", "rejected", "deprecated")
ANNOTATION_STATES = ("candidate", "approved", "rejected", "locked")
RUN_STATES = ("queued", "running", "completed", "failed", "cancelled")

RAW_WRITER = "main_translator"
REVIEW_WRITER = "bilingual_reviewer"
REVISION_WRITER = "line_editor"
ACCEPTANCE_WRITER = "chief_translation_editor"
TERMS_WRITER = "terminology_editor"
```

- [ ] **Step 5: Implement IO helpers**

Create `app/editorial_runtime/io.py`:

```python
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

import yaml

from ..errors import ToolError

_PROJECT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")


def normalize_project_key(value: str) -> str:
    normalized = str(value).strip().lower()
    if not _PROJECT_KEY_RE.fullmatch(normalized):
        raise ToolError(
            code="invalid_arguments",
            message="project_key 只能使用 3-64 位小写字母、数字、下划线或连字符，且不能包含路径分隔符。",
            status=400,
        )
    return normalized


def ensure_within_root(root: Path, path: Path) -> Path:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise ToolError(code="invalid_arguments", message=f"路径越过项目根目录: {path}", status=400)
    return resolved_path


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ToolError(code="not_found", message=f"文件不可读: {path}", status=404) from exc


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ToolError(code="invalid_state", message=f"YAML 必须是对象: {path}", status=409)
    return payload


def write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )


def append_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")
```

- [ ] **Step 6: Run IO tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .[test]
.\.venv\Scripts\python.exe -m pytest tests/test_editorial_runtime_io.py -q
```

Expected: PASS for all tests in `tests/test_editorial_runtime_io.py`.

- [ ] **Step 7: Commit**

```powershell
git add pyproject.toml requirements.txt app/editorial_runtime/__init__.py app/editorial_runtime/constants.py app/editorial_runtime/io.py tests/test_editorial_runtime_io.py
git commit -m "feat: add editorial runtime io primitives"
```

---

### Task 2: Create Document-Backed Project Template

**Files:**
- Create: `app/editorial_runtime/config.py`
- Create: `app/editorial_runtime/service.py`
- Test: `tests/test_editorial_runtime_project.py`

- [ ] **Step 1: Write failing project init tests**

Create `tests/test_editorial_runtime_project.py`:

```python
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
```

- [ ] **Step 2: Run failing project tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_editorial_runtime_project.py -q
```

Expected: FAIL with `ModuleNotFoundError` or missing `EditorialRuntimeService`.

- [ ] **Step 3: Implement runtime home resolution**

Create `app/editorial_runtime/config.py`:

```python
from __future__ import annotations

import os
from pathlib import Path


def default_editorial_home() -> Path:
    value = os.getenv("LTW_EDITORIAL_HOME")
    if value:
        return Path(value).expanduser()
    return Path(__file__).resolve().parents[2] / "data" / "editorial_projects"
```

- [ ] **Step 4: Implement project initialization service**

Create `app/editorial_runtime/service.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..errors import ToolError
from .constants import (
    ACCEPTANCE_WRITER,
    RAW_WRITER,
    REVIEW_WRITER,
    REVISION_WRITER,
    TERMS_WRITER,
)
from .io import compute_sha256, ensure_within_root, normalize_project_key, read_text, read_yaml, write_text, write_yaml


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class EditorialRuntimeService:
    def __init__(self, projects_root: Path) -> None:
        self.projects_root = Path(projects_root)

    def project_root(self, project_key: str) -> Path:
        safe_key = normalize_project_key(project_key)
        return ensure_within_root(self.projects_root, self.projects_root / safe_key)

    def init_project(
        self,
        *,
        project_key: str,
        title: str,
        source_language: str,
        target_language: str,
    ) -> dict[str, Any]:
        safe_key = normalize_project_key(project_key)
        root = self.project_root(safe_key)
        manifest_path = root / "manifest.yaml"
        if manifest_path.exists():
            manifest = read_yaml(manifest_path)
            return {"project_key": safe_key, "project_root": str(root), "manifest": manifest}

        for relative_dir in (
            "source/chapters",
            "source/segments",
            "rules",
            "memory",
            "chapters",
            "exports",
            ".ltw-cache",
        ):
            (root / relative_dir).mkdir(parents=True, exist_ok=True)

        created_at = _utc_now()
        manifest = {
            "runtime": "editorial",
            "compatibility": "not_backward_compatible",
            "project_key": safe_key,
            "title": title,
            "source_language": source_language,
            "target_language": target_language,
            "created_at": created_at,
            "updated_at": created_at,
        }
        write_yaml(manifest_path, manifest)
        write_yaml(
            root / "editorial-ledger.yaml",
            {
                "project_key": safe_key,
                "runs": [],
                "decisions": [],
            },
        )
        write_yaml(root / "source" / "manifest.yaml", {"project_key": safe_key, "chapters": [], "synopsis": None})
        write_text(root / "rules" / "style-guide.md", "# Style Guide\n\n")
        write_yaml(root / "rules" / "glossary.yaml", {"terms": []})
        write_yaml(root / "rules" / "glossary-candidates.yaml", {"candidates": []})
        write_text(root / "memory" / "tm.accepted.jsonl", "")
        return {"project_key": safe_key, "project_root": str(root), "manifest": manifest}
```

- [ ] **Step 5: Run project init tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_editorial_runtime_project.py -q
```

Expected: PASS for the two project initialization tests.

- [ ] **Step 6: Commit**

```powershell
git add app/editorial_runtime/config.py app/editorial_runtime/service.py tests/test_editorial_runtime_project.py
git commit -m "feat: initialize editorial runtime projects"
```

---

### Task 3: Prepare Source, Assign Chapters, And Prepare Term Packs

**Files:**
- Modify: `app/editorial_runtime/service.py`
- Modify: `tests/test_editorial_runtime_project.py`

- [ ] **Step 1: Add failing source and assignment tests**

Append to `tests/test_editorial_runtime_project.py`:

```python
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
```

- [ ] **Step 2: Run failing source tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_editorial_runtime_project.py -q
```

Expected: FAIL with `AttributeError` for `prepare_source`, `assign_chapter`, or `prepare_term_pack`.

- [ ] **Step 3: Add source and chapter helpers**

Modify `app/editorial_runtime/service.py` by adding these methods inside `EditorialRuntimeService`:

```python
    def _require_project(self, project_key: str) -> Path:
        root = self.project_root(project_key)
        if not (root / "manifest.yaml").exists():
            raise ToolError(code="not_found", message=f"找不到 Editorial Runtime 项目: {project_key}", status=404)
        return root

    def _chapter_root(self, project_root: Path, chapter_key: str) -> Path:
        safe_chapter_key = str(chapter_key).strip().lower()
        if not safe_chapter_key.startswith("ch") or "/" in safe_chapter_key or "\\" in safe_chapter_key:
            raise ToolError(code="invalid_arguments", message=f"chapter_key 不合法: {chapter_key}", status=400)
        return ensure_within_root(project_root, project_root / "chapters" / safe_chapter_key)

    def prepare_source(
        self,
        *,
        project_key: str,
        synopsis: str,
        chapters: list[dict[str, Any]],
    ) -> dict[str, Any]:
        root = self._require_project(project_key)
        if not chapters:
            raise ToolError(code="invalid_arguments", message="chapters 不能为空。", status=400)

        synopsis_path = root / "source" / "synopsis.md"
        write_text(synopsis_path, (synopsis or "").rstrip() + "\n")
        manifest_chapters: list[dict[str, Any]] = []
        for index, chapter in enumerate(chapters, start=1):
            chapter_key = str(chapter.get("chapter_key") or f"ch{index:03d}").strip().lower()
            title = str(chapter.get("title") or f"Chapter {index}")
            source_text = str(chapter.get("source_text") or "").rstrip()
            if not source_text:
                raise ToolError(code="invalid_arguments", message=f"{chapter_key} source_text 不能为空。", status=400)
            source_path = root / "source" / "chapters" / f"{chapter_key}.md"
            write_text(source_path, source_text + "\n")
            manifest_chapters.append(
                {
                    "chapter_key": chapter_key,
                    "chapter_index": index,
                    "title": title,
                    "source_path": f"source/chapters/{chapter_key}.md",
                    "source_sha256": compute_sha256(source_path),
                }
            )

        manifest = {
            "project_key": normalize_project_key(project_key),
            "synopsis": {
                "path": "source/synopsis.md",
                "sha256": compute_sha256(synopsis_path),
            },
            "chapters": manifest_chapters,
            "updated_at": _utc_now(),
        }
        write_yaml(root / "source" / "manifest.yaml", manifest)
        return {"project_key": normalize_project_key(project_key), "chapter_count": len(manifest_chapters)}

    def _source_chapter(self, root: Path, chapter_key: str) -> dict[str, Any]:
        source_manifest = read_yaml(root / "source" / "manifest.yaml")
        for chapter in source_manifest.get("chapters", []):
            if chapter.get("chapter_key") == chapter_key:
                return chapter
        raise ToolError(code="not_found", message=f"找不到源章节: {chapter_key}", status=404)

    def assign_chapter(self, *, project_key: str, chapter_key: str, brief: str) -> dict[str, Any]:
        root = self._require_project(project_key)
        source_chapter = self._source_chapter(root, chapter_key)
        chapter_root = self._chapter_root(root, chapter_key)
        for relative_dir in ("raw", "review", "revised", "accepted"):
            (chapter_root / relative_dir).mkdir(parents=True, exist_ok=True)
        write_text(
            chapter_root / "task.md",
            f"# {chapter_key} Task\n\n"
            f"- title: {source_chapter['title']}\n"
            f"- source_path: {source_chapter['source_path']}\n"
            f"- source_sha256: {source_chapter['source_sha256']}\n\n"
            f"{brief.rstrip()}\n",
        )
        record = {
            "chapter_key": chapter_key,
            "status": "planned",
            "source_sha256": source_chapter["source_sha256"],
            "runs": [],
            "updated_at": _utc_now(),
        }
        write_yaml(chapter_root / "record.yaml", record)
        write_text(chapter_root / "annotations.md", "# Annotations\n\n")
        return {"project_key": normalize_project_key(project_key), "chapter_key": chapter_key, "status": "planned"}

    def prepare_term_pack(
        self,
        *,
        project_key: str,
        chapter_key: str,
        terms: list[dict[str, Any]],
    ) -> dict[str, Any]:
        root = self._require_project(project_key)
        chapter_root = self._chapter_root(root, chapter_key)
        record_path = chapter_root / "record.yaml"
        record = read_yaml(record_path)
        if record.get("status") not in {"planned", "term_ready"}:
            raise ToolError(code="conflict_error", message="只有 planned 章节可以准备术语包。", status=409)
        lines = ["# Term Pack", ""]
        for term in terms:
            lines.append(
                f"- {term.get('source_term', '')} => {term.get('target_term', '')} "
                f"({term.get('status', 'candidate')})"
            )
        write_text(chapter_root / "term-pack.md", "\n".join(lines).rstrip() + "\n")
        record["status"] = "term_ready"
        record["term_pack_sha256"] = compute_sha256(chapter_root / "term-pack.md")
        record["updated_at"] = _utc_now()
        record.setdefault("runs", []).append(
            {
                "desk": TERMS_WRITER,
                "status": "completed",
                "outputs": [{"path": "term-pack.md", "sha256": record["term_pack_sha256"]}],
                "finished_at": _utc_now(),
            }
        )
        write_yaml(record_path, record)
        return {"project_key": normalize_project_key(project_key), "chapter_key": chapter_key, "status": "term_ready"}
```

- [ ] **Step 4: Run project tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_editorial_runtime_project.py -q
```

Expected: PASS for all tests in `tests/test_editorial_runtime_project.py`.

- [ ] **Step 5: Commit**

```powershell
git add app/editorial_runtime/service.py tests/test_editorial_runtime_project.py
git commit -m "feat: prepare editorial source and chapter inputs"
```

---

### Task 4: Enforce Workstation State Boundaries

**Files:**
- Modify: `app/editorial_runtime/service.py`
- Test: `tests/test_editorial_runtime_workflow.py`

- [ ] **Step 1: Write failing workstation workflow tests**

Create `tests/test_editorial_runtime_workflow.py`:

```python
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
```

- [ ] **Step 2: Run failing workflow tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_editorial_runtime_workflow.py -q
```

Expected: FAIL with `AttributeError` for the new workstation methods.

- [ ] **Step 3: Add record and transition helpers**

Modify `app/editorial_runtime/service.py` by adding these private helpers inside `EditorialRuntimeService`:

```python
    def _record_path(self, root: Path, chapter_key: str) -> Path:
        return self._chapter_root(root, chapter_key) / "record.yaml"

    def _require_status(self, record: dict[str, Any], allowed: set[str], message: str) -> None:
        if record.get("status") not in allowed:
            raise ToolError(code="conflict_error", message=message, status=409)

    def _record_run(
        self,
        *,
        record: dict[str, Any],
        desk: str,
        inputs: list[dict[str, str]],
        outputs: list[dict[str, str]],
        note: str,
    ) -> None:
        record.setdefault("runs", []).append(
            {
                "desk": desk,
                "status": "completed",
                "inputs": inputs,
                "outputs": outputs,
                "note": note,
                "finished_at": _utc_now(),
            }
        )
        record["updated_at"] = _utc_now()
```

- [ ] **Step 4: Add raw, review, adjudication, and revision methods**

Modify `app/editorial_runtime/service.py` by adding these methods inside `EditorialRuntimeService`:

```python
    def write_raw(self, *, project_key: str, chapter_key: str, content: str, note: str) -> dict[str, Any]:
        root = self._require_project(project_key)
        chapter_root = self._chapter_root(root, chapter_key)
        record_path = self._record_path(root, chapter_key)
        record = read_yaml(record_path)
        self._require_status(record, {"term_ready", "raw_ready"}, "只有 term_ready 章节可以写 raw。")
        output_path = chapter_root / "raw" / "main-translator.md"
        write_text(output_path, content.rstrip() + "\n")
        record["status"] = "raw_ready"
        self._record_run(
            record=record,
            desk=RAW_WRITER,
            inputs=[
                {"path": "task.md", "sha256": compute_sha256(chapter_root / "task.md")},
                {"path": "term-pack.md", "sha256": compute_sha256(chapter_root / "term-pack.md")},
            ],
            outputs=[{"path": "raw/main-translator.md", "sha256": compute_sha256(output_path)}],
            note=note,
        )
        write_yaml(record_path, record)
        return {"project_key": normalize_project_key(project_key), "chapter_key": chapter_key, "status": "raw_ready"}

    def write_bilingual_review(
        self,
        *,
        project_key: str,
        chapter_key: str,
        content: str,
        needs_annotation: bool,
    ) -> dict[str, Any]:
        root = self._require_project(project_key)
        chapter_root = self._chapter_root(root, chapter_key)
        record_path = self._record_path(root, chapter_key)
        record = read_yaml(record_path)
        self._require_status(record, {"raw_ready", "review_ready"}, "只有 raw_ready 章节可以写双语审校。")
        output_path = chapter_root / "review" / "bilingual-review.md"
        header = "# Bilingual Review\n\n"
        annotation_line = f"needs_annotation: {str(needs_annotation).lower()}\n\n"
        write_text(output_path, header + annotation_line + content.rstrip() + "\n")
        record["status"] = "review_ready"
        record["needs_annotation"] = bool(needs_annotation)
        self._record_run(
            record=record,
            desk=REVIEW_WRITER,
            inputs=[{"path": "raw/main-translator.md", "sha256": compute_sha256(chapter_root / "raw" / "main-translator.md")}],
            outputs=[{"path": "review/bilingual-review.md", "sha256": compute_sha256(output_path)}],
            note="bilingual review",
        )
        write_yaml(record_path, record)
        return {"project_key": normalize_project_key(project_key), "chapter_key": chapter_key, "status": "review_ready"}

    def adjudicate_review(
        self,
        *,
        project_key: str,
        chapter_key: str,
        decision: str,
        content: str,
    ) -> dict[str, Any]:
        root = self._require_project(project_key)
        chapter_root = self._chapter_root(root, chapter_key)
        record_path = self._record_path(root, chapter_key)
        record = read_yaml(record_path)
        self._require_status(record, {"review_ready"}, "只有 review_ready 章节可以裁决审校范围。")
        output_path = chapter_root / "review" / "adjudication.md"
        write_text(output_path, f"# Adjudication\n\n- decision: {decision}\n\n{content.rstrip()}\n")
        record["adjudication"] = {"decision": decision, "path": "review/adjudication.md", "sha256": compute_sha256(output_path)}
        self._record_run(
            record=record,
            desk=ACCEPTANCE_WRITER,
            inputs=[{"path": "review/bilingual-review.md", "sha256": compute_sha256(chapter_root / "review" / "bilingual-review.md")}],
            outputs=[{"path": "review/adjudication.md", "sha256": compute_sha256(output_path)}],
            note=decision,
        )
        write_yaml(record_path, record)
        return {"project_key": normalize_project_key(project_key), "chapter_key": chapter_key, "status": "review_ready"}

    def write_revision(
        self,
        *,
        project_key: str,
        chapter_key: str,
        content: str,
        annotations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        root = self._require_project(project_key)
        chapter_root = self._chapter_root(root, chapter_key)
        record_path = self._record_path(root, chapter_key)
        record = read_yaml(record_path)
        self._require_status(record, {"review_ready", "revision_ready"}, "只有 review_ready 章节可以写责编修订。")
        if "adjudication" not in record:
            raise ToolError(code="conflict_error", message="缺少总译审裁决，责编不能写 revised。", status=409)
        output_path = chapter_root / "revised" / "line-editor.md"
        write_text(output_path, content.rstrip() + "\n")
        annotation_lines = ["# Annotations", ""]
        for annotation in annotations:
            annotation_lines.append(f"- status: {annotation.get('status', 'candidate')}")
            annotation_lines.append(f"  text: {annotation.get('text', '')}")
        write_text(chapter_root / "annotations.md", "\n".join(annotation_lines).rstrip() + "\n")
        record["status"] = "revision_ready"
        self._record_run(
            record=record,
            desk=REVISION_WRITER,
            inputs=[
                {"path": "review/bilingual-review.md", "sha256": compute_sha256(chapter_root / "review" / "bilingual-review.md")},
                {"path": "review/adjudication.md", "sha256": compute_sha256(chapter_root / "review" / "adjudication.md")},
            ],
            outputs=[
                {"path": "revised/line-editor.md", "sha256": compute_sha256(output_path)},
                {"path": "annotations.md", "sha256": compute_sha256(chapter_root / "annotations.md")},
            ],
            note="line edit revision",
        )
        write_yaml(record_path, record)
        return {"project_key": normalize_project_key(project_key), "chapter_key": chapter_key, "status": "revision_ready"}
```

- [ ] **Step 5: Run workflow tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_editorial_runtime_workflow.py -q
```

Expected: PASS for workstation boundary tests.

- [ ] **Step 6: Commit**

```powershell
git add app/editorial_runtime/service.py tests/test_editorial_runtime_workflow.py
git commit -m "feat: enforce editorial workstation transitions"
```

---

### Task 5: Accept Chapters, Derive TM, Rebuild Cache, And Export Accepted Text

**Files:**
- Modify: `app/editorial_runtime/service.py`
- Modify: `tests/test_editorial_runtime_workflow.py`

- [ ] **Step 1: Add failing accepted-only tests**

Append to `tests/test_editorial_runtime_workflow.py`:

```python
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
        annotations=[{"status": "approved", "text": "Azure lamp is a recurring artifact."}],
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
    assert cache_payload["chapter_count"] == 1
    assert (project_root / ".ltw-cache" / "index.sqlite").is_file()
    assert export_payload["chapter_count"] == 1
    assert "Lin Xi lit the accepted azure lamp." in (project_root / "exports" / "export.md").read_text(encoding="utf-8")
    assert read_yaml(project_root / "exports" / "manifest.yaml")["chapters"][0]["chapter_key"] == "ch001"
```

- [ ] **Step 2: Run failing accepted-only tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_editorial_runtime_workflow.py -q
```

Expected: FAIL with `AttributeError` for `accept_chapter`, `derive_memory_from_accepted`, `rebuild_cache`, or `build_export`.

- [ ] **Step 3: Add accepted, memory, export, cache, and inspect methods**

Modify `app/editorial_runtime/service.py` imports:

```python
import json
import sqlite3
```

Modify `app/editorial_runtime/service.py` to import `append_jsonl`:

```python
from .io import append_jsonl, compute_sha256, ensure_within_root, normalize_project_key, read_text, read_yaml, write_text, write_yaml
```

Add these methods inside `EditorialRuntimeService`:

```python
    def accept_chapter(self, *, project_key: str, chapter_key: str, note: str) -> dict[str, Any]:
        root = self._require_project(project_key)
        chapter_root = self._chapter_root(root, chapter_key)
        record_path = self._record_path(root, chapter_key)
        record = read_yaml(record_path)
        self._require_status(record, {"revision_ready", "accepted"}, "只有 revision_ready 章节可以验收 accepted。")
        revised_path = chapter_root / "revised" / "line-editor.md"
        accepted_path = chapter_root / "accepted" / "accepted.md"
        write_text(accepted_path, read_text(revised_path).rstrip() + "\n")
        record["status"] = "accepted"
        record["accepted_sha256"] = compute_sha256(accepted_path)
        self._record_run(
            record=record,
            desk=ACCEPTANCE_WRITER,
            inputs=[{"path": "revised/line-editor.md", "sha256": compute_sha256(revised_path)}],
            outputs=[{"path": "accepted/accepted.md", "sha256": record["accepted_sha256"]}],
            note=note,
        )
        write_yaml(record_path, record)
        return {"project_key": normalize_project_key(project_key), "chapter_key": chapter_key, "status": "accepted"}

    def _accepted_chapters(self, root: Path) -> list[dict[str, Any]]:
        chapters: list[dict[str, Any]] = []
        for record_path in sorted((root / "chapters").glob("*/record.yaml")):
            record = read_yaml(record_path)
            chapter_key = str(record.get("chapter_key"))
            if record.get("status") == "accepted":
                chapter_root = record_path.parent
                chapters.append(
                    {
                        "chapter_key": chapter_key,
                        "record": record,
                        "chapter_root": chapter_root,
                        "accepted_path": chapter_root / "accepted" / "accepted.md",
                    }
                )
        return chapters

    def derive_memory_from_accepted(self, *, project_key: str) -> dict[str, Any]:
        root = self._require_project(project_key)
        tm_path = root / "memory" / "tm.accepted.jsonl"
        write_text(tm_path, "")
        records: list[dict[str, Any]] = []
        for chapter in self._accepted_chapters(root):
            target_text = read_text(chapter["accepted_path"]).strip()
            records.append(
                {
                    "project_key": normalize_project_key(project_key),
                    "chapter_key": chapter["chapter_key"],
                    "target_text": target_text,
                    "accepted_sha256": compute_sha256(chapter["accepted_path"]),
                }
            )
        append_jsonl(tm_path, records)
        return {"project_key": normalize_project_key(project_key), "entry_count": len(records), "path": "memory/tm.accepted.jsonl"}

    def rebuild_cache(self, *, project_key: str) -> dict[str, Any]:
        root = self._require_project(project_key)
        cache_path = root / ".ltw-cache" / "index.sqlite"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        if cache_path.exists():
            cache_path.unlink()
        connection = sqlite3.connect(cache_path)
        try:
            connection.execute("CREATE TABLE files (path TEXT PRIMARY KEY, sha256 TEXT NOT NULL)")
            connection.execute("CREATE TABLE chapters (chapter_key TEXT PRIMARY KEY, status TEXT NOT NULL, accepted_sha256 TEXT)")
            file_count = 0
            for path in sorted(root.rglob("*")):
                if path.is_file() and ".ltw-cache" not in path.parts:
                    relative = path.relative_to(root).as_posix()
                    connection.execute("INSERT INTO files(path, sha256) VALUES (?, ?)", (relative, compute_sha256(path)))
                    file_count += 1
            chapter_count = 0
            for record_path in sorted((root / "chapters").glob("*/record.yaml")):
                record = read_yaml(record_path)
                connection.execute(
                    "INSERT INTO chapters(chapter_key, status, accepted_sha256) VALUES (?, ?, ?)",
                    (record.get("chapter_key"), record.get("status"), record.get("accepted_sha256")),
                )
                chapter_count += 1
            connection.commit()
        finally:
            connection.close()
        return {"project_key": normalize_project_key(project_key), "file_count": file_count, "chapter_count": chapter_count}

    def build_export(self, *, project_key: str) -> dict[str, Any]:
        root = self._require_project(project_key)
        accepted_chapters = self._accepted_chapters(root)
        if not accepted_chapters:
            raise ToolError(code="conflict_error", message="没有 accepted 章节，不能导出。", status=409)
        lines = [f"# Export: {normalize_project_key(project_key)}", ""]
        manifest_chapters: list[dict[str, Any]] = []
        for chapter in accepted_chapters:
            accepted_text = read_text(chapter["accepted_path"]).strip()
            lines.extend([f"## {chapter['chapter_key']}", "", accepted_text, ""])
            manifest_chapters.append(
                {
                    "chapter_key": chapter["chapter_key"],
                    "accepted_path": f"chapters/{chapter['chapter_key']}/accepted/accepted.md",
                    "accepted_sha256": compute_sha256(chapter["accepted_path"]),
                }
            )
        export_path = root / "exports" / "export.md"
        write_text(export_path, "\n".join(lines).rstrip() + "\n")
        manifest = {
            "project_key": normalize_project_key(project_key),
            "chapters": manifest_chapters,
            "export_path": "exports/export.md",
            "export_sha256": compute_sha256(export_path),
            "created_at": _utc_now(),
        }
        write_yaml(root / "exports" / "manifest.yaml", manifest)
        return {"project_key": normalize_project_key(project_key), "chapter_count": len(manifest_chapters), "path": "exports/export.md"}

    def inspect_status(self, *, project_key: str) -> dict[str, Any]:
        root = self._require_project(project_key)
        chapters: list[dict[str, Any]] = []
        for record_path in sorted((root / "chapters").glob("*/record.yaml")):
            record = read_yaml(record_path)
            chapters.append(
                {
                    "chapter_key": record.get("chapter_key"),
                    "status": record.get("status"),
                    "accepted_sha256": record.get("accepted_sha256"),
                    "run_count": len(record.get("runs", [])),
                }
            )
        return {"project_key": normalize_project_key(project_key), "chapter_count": len(chapters), "chapters": chapters}
```

- [ ] **Step 4: Run workflow tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_editorial_runtime_workflow.py -q
```

Expected: PASS for all workflow tests.

- [ ] **Step 5: Commit**

```powershell
git add app/editorial_runtime/service.py tests/test_editorial_runtime_workflow.py
git commit -m "feat: accept editorial chapters and derive artifacts"
```

---

### Task 6: Expose Codex-Facing Actions

**Files:**
- Create: `app/action_handlers/editorial_runtime_handlers.py`
- Modify: `app/action_handlers/__init__.py`
- Modify: `app/cli.py`
- Modify: `TOOL.json`
- Test: `tests/test_editorial_runtime_actions.py`
- Modify: `tests/test_action_router_dispatch.py`

- [ ] **Step 1: Write failing action tests**

Create `tests/test_editorial_runtime_actions.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from tools.local_translation_workbench.app.action_router import route_action


def test_editorial_actions_run_single_chapter_dry_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LTW_EDITORIAL_HOME", str(tmp_path))

    init_payload = route_action(
        {
            "action": "project.init_editorial",
            "project_key": "lantern_demo",
            "title": "青灯小先生",
            "source_language": "zh",
            "target_language": "en",
        }
    )
    assert init_payload["ok"] is True

    route_action(
        {
            "action": "source.prepare",
            "project_key": "lantern_demo",
            "synopsis": "简介",
            "chapters_json": json.dumps(
                [{"chapter_key": "ch001", "title": "第一章", "source_text": "林溪点亮青灯。"}],
                ensure_ascii=False,
            ),
        }
    )
    route_action(
        {
            "action": "chapter.assign",
            "project_key": "lantern_demo",
            "chapter_key": "ch001",
            "brief": "Translate chapter 1.",
        }
    )
    route_action(
        {
            "action": "terms.prepare_pack",
            "project_key": "lantern_demo",
            "chapter_key": "ch001",
            "terms_json": json.dumps([{"source_term": "林溪", "target_term": "Lin Xi", "status": "approved"}], ensure_ascii=False),
        }
    )
    route_action(
        {
            "action": "chapter.translate_raw",
            "project_key": "lantern_demo",
            "chapter_key": "ch001",
            "content": "raw draft",
            "note": "main translator",
        }
    )
    route_action(
        {
            "action": "chapter.review_bilingual",
            "project_key": "lantern_demo",
            "chapter_key": "ch001",
            "content": "review",
            "needs_annotation": "true",
        }
    )
    route_action(
        {
            "action": "review.adjudicate",
            "project_key": "lantern_demo",
            "chapter_key": "ch001",
            "decision": "accept_with_annotation",
            "content": "accepted review scope",
        }
    )
    route_action(
        {
            "action": "chapter.revise",
            "project_key": "lantern_demo",
            "chapter_key": "ch001",
            "content": "accepted revision",
            "annotations_json": json.dumps([{"status": "approved", "text": "note"}], ensure_ascii=False),
        }
    )
    route_action(
        {
            "action": "chapter.accept",
            "project_key": "lantern_demo",
            "chapter_key": "ch001",
            "note": "accepted",
        }
    )
    route_action({"action": "memory.derive_from_accepted", "project_key": "lantern_demo"})
    route_action({"action": "cache.rebuild", "project_key": "lantern_demo"})
    export_payload = route_action({"action": "export.build", "project_key": "lantern_demo"})
    status_payload = route_action({"action": "inspect.status", "project_key": "lantern_demo"})

    assert export_payload["data"]["chapter_count"] == 1
    assert status_payload["data"]["chapters"][0]["status"] == "accepted"
    assert "accepted revision" in (tmp_path / "lantern_demo" / "memory" / "tm.accepted.jsonl").read_text(encoding="utf-8")
```

Append to `tests/test_action_router_dispatch.py`:

```python
def test_editorial_runtime_actions_are_registered() -> None:
    assert "project.init_editorial" in action_router.ACTION_HANDLERS
    assert "source.prepare" in action_router.ACTION_HANDLERS
    assert "chapter.assign" in action_router.ACTION_HANDLERS
    assert "terms.prepare_pack" in action_router.ACTION_HANDLERS
    assert "chapter.translate_raw" in action_router.ACTION_HANDLERS
    assert "chapter.review_bilingual" in action_router.ACTION_HANDLERS
    assert "review.adjudicate" in action_router.ACTION_HANDLERS
    assert "chapter.revise" in action_router.ACTION_HANDLERS
    assert "chapter.accept" in action_router.ACTION_HANDLERS
    assert "memory.derive_from_accepted" in action_router.ACTION_HANDLERS
    assert "export.build" in action_router.ACTION_HANDLERS
    assert "cache.rebuild" in action_router.ACTION_HANDLERS
    assert "inspect.status" in action_router.ACTION_HANDLERS
```

- [ ] **Step 2: Run failing action tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_editorial_runtime_actions.py tests/test_action_router_dispatch.py::test_editorial_runtime_actions_are_registered -q
```

Expected: FAIL because action handlers are not registered.

- [ ] **Step 3: Implement action handlers**

Create `app/action_handlers/editorial_runtime_handlers.py`:

```python
from __future__ import annotations

import json
from typing import Any

from .. import action_support as support
from ..editorial_runtime.config import default_editorial_home
from ..editorial_runtime.service import EditorialRuntimeService
from ..errors import ToolError


def _service() -> EditorialRuntimeService:
    return EditorialRuntimeService(default_editorial_home())


def _parse_json_list(value: str | None, *, argument_name: str) -> list[dict[str, Any]]:
    if value is None or not value.strip():
        return []
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ToolError(code="invalid_arguments", message=f"{argument_name} 不是有效 JSON。", status=400) from exc
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ToolError(code="invalid_arguments", message=f"{argument_name} 必须是对象数组。", status=400)
    return payload


def handle_project_init_editorial(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().init_project(
        project_key=support._require_argument(arguments, "project_key"),
        title=support._require_argument(arguments, "title"),
        source_language=support._require_argument(arguments, "source_language"),
        target_language=support._require_argument(arguments, "target_language"),
    )
    return {"ok": True, "action": "project.init_editorial", "data": data}


def handle_source_prepare(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().prepare_source(
        project_key=support._require_argument(arguments, "project_key"),
        synopsis=support._read_optional_argument(arguments, "synopsis") or "",
        chapters=_parse_json_list(support._require_argument(arguments, "chapters_json"), argument_name="chapters_json"),
    )
    return {"ok": True, "action": "source.prepare", "data": data}


def handle_chapter_assign(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().assign_chapter(
        project_key=support._require_argument(arguments, "project_key"),
        chapter_key=support._require_argument(arguments, "chapter_key"),
        brief=support._read_optional_argument(arguments, "brief") or "",
    )
    return {"ok": True, "action": "chapter.assign", "data": data}


def handle_terms_prepare_pack(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().prepare_term_pack(
        project_key=support._require_argument(arguments, "project_key"),
        chapter_key=support._require_argument(arguments, "chapter_key"),
        terms=_parse_json_list(support._read_optional_argument(arguments, "terms_json"), argument_name="terms_json"),
    )
    return {"ok": True, "action": "terms.prepare_pack", "data": data}


def handle_chapter_translate_raw(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().write_raw(
        project_key=support._require_argument(arguments, "project_key"),
        chapter_key=support._require_argument(arguments, "chapter_key"),
        content=support._require_argument(arguments, "content"),
        note=support._read_optional_argument(arguments, "note") or "",
    )
    return {"ok": True, "action": "chapter.translate_raw", "data": data}


def handle_chapter_review_bilingual(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().write_bilingual_review(
        project_key=support._require_argument(arguments, "project_key"),
        chapter_key=support._require_argument(arguments, "chapter_key"),
        content=support._require_argument(arguments, "content"),
        needs_annotation=support._parse_bool(support._read_optional_argument(arguments, "needs_annotation")),
    )
    return {"ok": True, "action": "chapter.review_bilingual", "data": data}


def handle_review_adjudicate(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().adjudicate_review(
        project_key=support._require_argument(arguments, "project_key"),
        chapter_key=support._require_argument(arguments, "chapter_key"),
        decision=support._require_argument(arguments, "decision"),
        content=support._require_argument(arguments, "content"),
    )
    return {"ok": True, "action": "review.adjudicate", "data": data}


def handle_chapter_revise(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().write_revision(
        project_key=support._require_argument(arguments, "project_key"),
        chapter_key=support._require_argument(arguments, "chapter_key"),
        content=support._require_argument(arguments, "content"),
        annotations=_parse_json_list(support._read_optional_argument(arguments, "annotations_json"), argument_name="annotations_json"),
    )
    return {"ok": True, "action": "chapter.revise", "data": data}


def handle_chapter_accept(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().accept_chapter(
        project_key=support._require_argument(arguments, "project_key"),
        chapter_key=support._require_argument(arguments, "chapter_key"),
        note=support._read_optional_argument(arguments, "note") or "",
    )
    return {"ok": True, "action": "chapter.accept", "data": data}


def handle_memory_derive_from_accepted(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().derive_memory_from_accepted(project_key=support._require_argument(arguments, "project_key"))
    return {"ok": True, "action": "memory.derive_from_accepted", "data": data}


def handle_export_build(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().build_export(project_key=support._require_argument(arguments, "project_key"))
    return {"ok": True, "action": "export.build", "data": data}


def handle_cache_rebuild(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().rebuild_cache(project_key=support._require_argument(arguments, "project_key"))
    return {"ok": True, "action": "cache.rebuild", "data": data}


def handle_inspect_status(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().inspect_status(project_key=support._require_argument(arguments, "project_key"))
    return {"ok": True, "action": "inspect.status", "data": data}


EDITORIAL_RUNTIME_ACTION_HANDLERS = {
    "project.init_editorial": handle_project_init_editorial,
    "source.prepare": handle_source_prepare,
    "chapter.assign": handle_chapter_assign,
    "terms.prepare_pack": handle_terms_prepare_pack,
    "chapter.translate_raw": handle_chapter_translate_raw,
    "chapter.review_bilingual": handle_chapter_review_bilingual,
    "review.adjudicate": handle_review_adjudicate,
    "chapter.revise": handle_chapter_revise,
    "chapter.accept": handle_chapter_accept,
    "memory.derive_from_accepted": handle_memory_derive_from_accepted,
    "export.build": handle_export_build,
    "cache.rebuild": handle_cache_rebuild,
    "inspect.status": handle_inspect_status,
}
```

- [ ] **Step 4: Register handler group**

Modify `app/action_handlers/__init__.py`:

```python
from .editorial_runtime_handlers import EDITORIAL_RUNTIME_ACTION_HANDLERS
```

Add `EDITORIAL_RUNTIME_ACTION_HANDLERS` to `_merge_action_handlers(...)` after `PROJECT_ACTION_HANDLERS`:

```python
ACTION_HANDLERS = _merge_action_handlers(
    PROJECT_ACTION_HANDLERS,
    EDITORIAL_RUNTIME_ACTION_HANDLERS,
    PROVIDER_ACTION_HANDLERS,
    STAGE_ACTION_HANDLERS,
    GLOSSARY_MANAGEMENT_ACTION_HANDLERS,
    ANNOTATION_ACTION_HANDLERS,
    INSPECT_ACTION_HANDLERS,
    DIAGNOSTICS_ACTION_HANDLERS,
)
```

- [ ] **Step 5: Add CLI argument aliases**

Modify `_ARGUMENT_NAME_MAP` in `app/cli.py` by adding:

```python
    "projectkey": "project_key",
    "title": "title",
    "synopsis": "synopsis",
    "chaptersjson": "chapters_json",
    "chaptersjsonfile": "chapters_json_file",
    "chapterkey": "chapter_key",
    "brief": "brief",
    "content": "content",
    "contentfile": "content_file",
    "termsjson": "terms_json",
    "termsjsonfile": "terms_json_file",
    "annotationsjson": "annotations_json",
    "annotationsjsonfile": "annotations_json_file",
    "needsannotation": "needs_annotation",
    "decision": "decision",
```

- [ ] **Step 6: Update TOOL.json**

Add these action enum values to `TOOL.json`:

```json
"project.init_editorial",
"source.prepare",
"chapter.assign",
"terms.prepare_pack",
"chapter.translate_raw",
"chapter.review_bilingual",
"review.adjudicate",
"chapter.revise",
"chapter.accept",
"memory.derive_from_accepted",
"export.build",
"cache.rebuild",
"inspect.status"
```

Add these properties under `argsSchema.properties`:

```json
"project_key": {
  "type": "string",
  "description": "Editorial Runtime 项目 key。只允许小写字母、数字、下划线和连字符。"
},
"title": {
  "type": "string",
  "description": "Editorial Runtime 项目标题。project.init_editorial 必填。"
},
"synopsis": {
  "type": "string",
  "description": "Editorial Runtime 原文简介，可直接传文本或使用 @file。"
},
"chapters_json": {
  "type": "string",
  "description": "source.prepare 的章节数组 JSON。每项包含 chapter_key、title、source_text。"
},
"chapter_key": {
  "type": "string",
  "description": "Editorial Runtime 章节 key，例如 ch001。"
},
"brief": {
  "type": "string",
  "description": "chapter.assign 的总译审派章说明。"
},
"content": {
  "type": "string",
  "description": "Editorial Runtime 工位输出正文，可直接传文本或使用 @file。"
},
"terms_json": {
  "type": "string",
  "description": "terms.prepare_pack 的术语数组 JSON。"
},
"annotations_json": {
  "type": "string",
  "description": "chapter.revise 的注释数组 JSON。每项包含 status 与 text。"
},
"needs_annotation": {
  "type": "boolean",
  "description": "chapter.review_bilingual 是否认为本章需要注释。"
},
"decision": {
  "type": "string",
  "description": "review.adjudicate 的总译审裁决编码。"
}
```

- [ ] **Step 7: Run action tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_editorial_runtime_actions.py tests/test_action_router_dispatch.py::test_editorial_runtime_actions_are_registered tests/test_action_router_dispatch.py::test_tool_json_action_enum_matches_registered_handlers -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add app/action_handlers/editorial_runtime_handlers.py app/action_handlers/__init__.py app/cli.py TOOL.json tests/test_editorial_runtime_actions.py tests/test_action_router_dispatch.py
git commit -m "feat: expose editorial runtime actions"
```

---

### Task 7: Document Skill Protocol And Dry-Run Usage

**Files:**
- Modify: `codex_skill/local_translation_workbench/SKILL.md`
- Modify: `README.md`
- Modify: `docs/operations/runbook.md`

- [ ] **Step 1: Update Codex skill with Editorial Runtime protocol**

Add this section to `codex_skill/local_translation_workbench/SKILL.md` after the default strategy section:

```markdown
## Editorial Runtime

新架构入口是 Editorial Runtime。它不以旧 CLI/MySQL pipeline 为兼容目标，事实源是 `LTW_EDITORIAL_HOME` 下的项目文档目录，SQLite 只作为 `.ltw-cache/index.sqlite` 可重建缓存。

优先使用这些 action：

1. `project.init_editorial`
2. `source.prepare`
3. `chapter.assign`
4. `terms.prepare_pack`
5. `chapter.translate_raw`
6. `chapter.review_bilingual`
7. `review.adjudicate`
8. `chapter.revise`
9. `chapter.accept`
10. `memory.derive_from_accepted`
11. `cache.rebuild`
12. `export.build`
13. `inspect.status`

工位边界：

- 总译审：派章、裁决、验收 accepted、放行导出。
- 术语编辑：常驻岗位，准备术语包，维护候选、approved、locked、rejected、deprecated。
- 主译：只写 raw，不写 accepted，不批准术语。
- 双语审校：只写 review 和 needs_annotation，不改正文。
- 责编：只写 revised 和 annotation candidate，不宣布 accepted。
- 结构秘书：只在初始化、source 变化或结构异常时触发。

硬规则：

- raw、review、revised 都不能进入 TM。
- `memory.derive_from_accepted` 只能读取 accepted。
- `export.build` 只能读取 accepted 和 approved annotation。
- `.ltw-cache/index.sqlite` 可删除重建；与文档冲突时文档获胜。
- 子 Agent 不能自证合规，主线程或总译审必须验收。
```

- [ ] **Step 2: Update README with new runtime note**

Add this section near the Codex skill section in `README.md`:

````markdown
## Editorial Runtime

LTW 正在新增不向后兼容的 Editorial Runtime。新运行层以本地文档目录为事实源，默认项目根为 `data/editorial_projects`，也可以通过 `LTW_EDITORIAL_HOME` 指定。

第一阶段入口是 Codex-facing actions：

```powershell
.\.venv\Scripts\ltw.exe -Action project.init_editorial -ProjectKey lantern_demo -Title "青灯小先生" -SourceLanguage zh -TargetLanguage en
```

Editorial Runtime 不依赖旧 MySQL pipeline；SQLite 只作为 `.ltw-cache/index.sqlite` 可重建缓存。旧 `project.create` / `stage.run` 仍属于 legacy pipeline，新项目默认优先使用 Editorial Runtime。
````

- [ ] **Step 3: Add runbook dry-run example**

Add this section to `docs/operations/runbook.md`:

````markdown
## Editorial Runtime 单章 dry-run

以下示例只验证本地文档事实源和工位状态，不调用外部 provider。

```powershell
$env:LTW_EDITORIAL_HOME = "D:/Project/local_translation_workbench/data/editorial_projects"

.\.venv\Scripts\ltw.exe -Action project.init_editorial -ProjectKey lantern_demo -Title "青灯小先生" -SourceLanguage zh -TargetLanguage en

$chapters = '[{"chapter_key":"ch001","title":"第一章","source_text":"林溪点亮青灯。"}]'
.\.venv\Scripts\ltw.exe -Action source.prepare -ProjectKey lantern_demo -Synopsis "简介" -ChaptersJson $chapters

.\.venv\Scripts\ltw.exe -Action chapter.assign -ProjectKey lantern_demo -ChapterKey ch001 -Brief "保持古典但清爽的英文表达。"
.\.venv\Scripts\ltw.exe -Action terms.prepare_pack -ProjectKey lantern_demo -ChapterKey ch001 -TermsJson '[{"source_term":"林溪","target_term":"Lin Xi","status":"approved"}]'
.\.venv\Scripts\ltw.exe -Action chapter.translate_raw -ProjectKey lantern_demo -ChapterKey ch001 -Content "Lin Xi lit the blue lantern." -Note "main translator"
.\.venv\Scripts\ltw.exe -Action chapter.review_bilingual -ProjectKey lantern_demo -ChapterKey ch001 -Content "术语一致。" -NeedsAnnotation false
.\.venv\Scripts\ltw.exe -Action review.adjudicate -ProjectKey lantern_demo -ChapterKey ch001 -Decision accept_review_scope -Content "采纳审校范围。"
.\.venv\Scripts\ltw.exe -Action chapter.revise -ProjectKey lantern_demo -ChapterKey ch001 -Content "Lin Xi lit the azure lamp." -AnnotationsJson '[{"status":"approved","text":"Azure lamp is a recurring artifact."}]'
.\.venv\Scripts\ltw.exe -Action chapter.accept -ProjectKey lantern_demo -ChapterKey ch001 -Note "accepted by chief translation editor"
.\.venv\Scripts\ltw.exe -Action memory.derive_from_accepted -ProjectKey lantern_demo
.\.venv\Scripts\ltw.exe -Action cache.rebuild -ProjectKey lantern_demo
.\.venv\Scripts\ltw.exe -Action export.build -ProjectKey lantern_demo
.\.venv\Scripts\ltw.exe -Action inspect.status -ProjectKey lantern_demo
```
````

- [ ] **Step 4: Run docs-adjacent tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_editorial_runtime_actions.py tests/test_action_router_dispatch.py::test_tool_json_action_enum_matches_registered_handlers -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add codex_skill/local_translation_workbench/SKILL.md README.md docs/operations/runbook.md
git commit -m "docs: document editorial runtime protocol"
```

---

### Task 8: Final Verification For Phase 1

**Files:**
- No new files.

- [ ] **Step 1: Run targeted Editorial Runtime tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_editorial_runtime_io.py tests/test_editorial_runtime_project.py tests/test_editorial_runtime_workflow.py tests/test_editorial_runtime_actions.py -q
```

Expected: PASS.

- [ ] **Step 2: Run action router schema tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_action_router_dispatch.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full regression if test database is available**

Run:

```powershell
if (-not $env:LTW_TEST_DATABASE_URL) { throw "LTW_TEST_DATABASE_URL is required for full regression." }
.\.venv\Scripts\python.exe -m pytest tests -q
```

Expected: PASS.

- [ ] **Step 4: Manually verify no MySQL import in new runtime**

Run:

```powershell
rg -n "SQLAlchemy|sqlalchemy|LTW_DATABASE_URL|ProjectRepository|get_session_factory|app\\.db|repositories" app\editorial_runtime tests\test_editorial_runtime_*.py
```

Expected: no output.

- [ ] **Step 5: Verify accepted-only artifact boundary**

Run:

```powershell
rg -n "raw draft must not enter TM|review text must not enter TM" data\editorial_projects
```

Expected: no matches in `memory/tm.accepted.jsonl`, `exports/export.md`, or `.ltw-cache/index.sqlite` query outputs. Matches inside `chapters/*/raw/` or `chapters/*/review/` are allowed.

- [ ] **Step 6: Commit verification notes if documentation changed during verification**

If verification reveals a command correction in docs, commit only the documentation correction:

```powershell
git add README.md docs/operations/runbook.md codex_skill/local_translation_workbench/SKILL.md
git commit -m "docs: refine editorial runtime verification notes"
```

If no documentation changed, do not create an empty commit.

---

## Self-Review Checklist

- Spec coverage:
  - Project directory template: Task 2.
  - Source manifest and chapter tasks: Task 3.
  - Five resident workstation record path: Tasks 3 and 4.
  - Single chapter dry-run: Tasks 4, 5, 6, and 7.
  - Accepted-only TM: Task 5.
  - SQLite rebuild from documents: Task 5.
  - Export from accepted: Task 5.
  - Codex skill entry: Tasks 6 and 7.
  - No old MySQL compatibility goal: Scope Check, Task 8 import scan.
- Placeholder scan:
  - No task uses deferred placeholders.
  - Every command has expected output.
  - Every code-writing step names exact files.
- Type and name consistency:
  - Service methods used by handlers match methods defined in service tasks.
  - Action names match the design spec.
  - File names match the document fact-source structure.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-24-ltw-editorial-runtime-phase-1.md`. Two execution options:

1. Subagent-Driven (recommended) - Dispatch a fresh subagent per task, review between tasks, fast iteration.
2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
