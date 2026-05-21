from __future__ import annotations

import json

from local_translation_workbench import console


def test_console_help_delegates_to_existing_cli(capsys):
    exit_code = console.main(["help"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "project.create" in captured.out
    assert captured.err == ""


def test_console_unknown_action_keeps_structured_error(capsys):
    exit_code = console.main(["-Action", "project.remove"])
    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert exit_code == 1
    assert payload["error"]["code"] == "invalid_arguments"
    assert "project.remove" in payload["error"]["message"]


def test_console_doctor_returns_json_without_revealing_database_url(monkeypatch, capsys):
    monkeypatch.setenv("LTW_DATABASE_URL", "mysql+pymysql://user:secret@example/db")
    monkeypatch.setenv("LTW_DATA_DIR", "D:/tmp/ltw-data")

    exit_code = console.main(["doctor"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["ok"] in {True, False}
    assert payload["checks"]["database_url"]["configured"] is True
    assert "secret" not in captured.out
    assert captured.err == ""


def test_console_migrate_requires_database_url(monkeypatch, capsys):
    monkeypatch.delenv("LTW_DATABASE_URL", raising=False)

    exit_code = console.main(["migrate"])
    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert exit_code == 1
    assert payload["error"]["code"] == "missing_config"
    assert "LTW_DATABASE_URL" in payload["error"]["message"]
