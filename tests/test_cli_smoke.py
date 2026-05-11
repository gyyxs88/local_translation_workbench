from __future__ import annotations

import importlib
import json
import inspect
import os
import subprocess
from pathlib import Path

import pytest

from tools.local_translation_workbench.app.cli import build_help_text, main


def _resolve_python_exe(tool_root: Path) -> Path:
    for candidate_root in (tool_root, *tool_root.parents):
        python_exe = candidate_root / ".venv" / "Scripts" / "python.exe"
        if python_exe.exists():
            return python_exe
    return tool_root / ".venv" / "Scripts" / "python.exe"


def test_help_text_mentions_stage_model() -> None:
    text = build_help_text()
    assert "project.create" in text
    assert "project.list" in text
    assert "project.cancel" in text
    assert "project.run_full" in text
    assert "stage.run" in text
    assert "stage.inspect_runs" in text
    assert "translation" in text
    assert "review" in text
    assert "export" in text
    assert "inspect.project" in text
    assert "inspect.glossary" in text
    assert "inspect.translation" in text
    assert "inspect.review" in text
    assert "inspect.export" in text


def test_main_supports_help_keyword(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["help"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "project.create" in captured.out
    assert "project.list" in captured.out
    assert "project.cancel" in captured.out
    assert "project.run_full" in captured.out
    assert "stage.run" in captured.out
    assert "stage.inspect_runs" in captured.out
    assert "translation" in captured.out
    assert "review" in captured.out
    assert "export" in captured.out
    assert "inspect.project" in captured.out
    assert "inspect.glossary" in captured.out
    assert "inspect.translation" in captured.out
    assert "inspect.review" in captured.out
    assert "inspect.export" in captured.out


def test_main_rejects_unsupported_action(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["-Action", "project.remove"])
    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert exit_code == 1
    assert payload["error"]["code"] == "invalid_arguments"
    assert "project.remove" in payload["error"]["message"]


def test_run_ps1_invokes_cli_successfully() -> None:
    tool_root = Path(__file__).resolve().parents[1]
    python_exe = _resolve_python_exe(tool_root)
    script_path = tool_root / "scripts" / "run.ps1"

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "help",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
    )

    assert python_exe.exists()
    assert completed.returncode == 0
    assert "project.create" in completed.stdout
    assert "project.list" in completed.stdout
    assert "project.cancel" in completed.stdout
    assert "project.run_full" in completed.stdout
    assert "stage.run" in completed.stdout
    assert "stage.inspect_runs" in completed.stdout
    assert "translation" in completed.stdout
    assert "review" in completed.stdout
    assert "export" in completed.stdout
    assert "inspect.project" in completed.stdout
    assert "inspect.glossary" in completed.stdout
    assert "inspect.translation" in completed.stdout
    assert "inspect.review" in completed.stdout
    assert "inspect.export" in completed.stdout
    assert completed.stderr == ""


def test_cli_module_does_not_embed_startup_bootstrap() -> None:
    module = importlib.import_module("tools.local_translation_workbench.app.cli")
    source = inspect.getsource(module)
    assert "sys.path.insert" not in source
    assert "if __package__ is None" not in source


def test_standalone_repo_import_path_supports_tools_namespace() -> None:
    tool_root = Path(__file__).resolve().parents[1]
    python_exe = _resolve_python_exe(tool_root)

    completed = subprocess.run(
        [
            str(python_exe),
            "-c",
            "import tools.local_translation_workbench.app.cli as cli; print(cli.build_help_text())",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tool_root,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
    )

    assert python_exe.exists()
    assert completed.returncode == 0
    assert "project.create" in completed.stdout
    assert completed.stderr == ""


def test_standalone_repo_pytest_smoke_passes() -> None:
    tool_root = Path(__file__).resolve().parents[1]
    python_exe = _resolve_python_exe(tool_root)

    completed = subprocess.run(
        [
            str(python_exe),
            "-m",
            "pytest",
            "tests/test_cli_smoke.py::test_help_text_mentions_stage_model",
            "-q",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tool_root,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
    )

    assert python_exe.exists()
    assert completed.returncode == 0
    assert "1 passed" in completed.stdout
    assert completed.stderr == ""


def test_main_returns_invalid_arguments_without_action(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([])
    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert exit_code == 1
    assert payload["error"]["code"] == "invalid_arguments"
    assert "action" in payload["error"]["message"]


def test_main_returns_structured_error_for_invalid_scope_chapters(
    database_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "-Action",
            "stage.run",
            "-ProjectId",
            "1",
            "-Stage",
            "review",
            "-ScopeType",
            "chapter_list",
            "-ScopeChapters",
            "1,a",
            "-RequestId",
            "req-invalid-scope",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert exit_code == 1
    assert payload["error"]["code"] == "invalid_arguments"
    assert "scope_chapters" in payload["error"]["message"]


def test_main_returns_structured_error_for_invalid_integer_argument(
    database_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["-Action", "stage.inspect_runs", "-ProjectId", "abc"])
    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert exit_code == 1
    assert captured.out == ""
    assert payload["error"]["code"] == "invalid_arguments"
    assert "project_id" in payload["error"]["message"]
