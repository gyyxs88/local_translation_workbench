from __future__ import annotations

import json

from local_translation_workbench import console


def test_console_help_delegates_to_existing_cli(capsys):
    exit_code = console.main(["help"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "project.create" in captured.out
    assert "update-check" in captured.out
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
    monkeypatch.setenv("LTW_DISABLE_UPDATE_CHECK", "1")

    exit_code = console.main(["doctor"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["ok"] in {True, False}
    assert payload["checks"]["database_url"]["configured"] is True
    assert payload["checks"]["update"]["status"] == "disabled"
    assert "secret" not in captured.out
    assert captured.err == ""


def test_console_doctor_includes_non_blocking_update_check(monkeypatch, capsys):
    from local_translation_workbench import update_check

    monkeypatch.setenv("LTW_DATABASE_URL", "mysql+pymysql://user:secret@example/db")
    monkeypatch.setenv("LTW_DATA_DIR", "D:/tmp/ltw-data")
    monkeypatch.delenv("LTW_DISABLE_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(
        update_check,
        "maybe_check_for_update",
        lambda: {
            "status": "ok",
            "current_version": "0.1.3",
            "latest_version": "0.1.4",
            "update_available": True,
            "release_url": "https://github.com/gyyxs88/local_translation_workbench-releases/releases/tag/v0.1.4",
            "download_url": "https://example.test/local_translation_workbench-0.1.4.zip",
            "sha256_url": "https://example.test/local_translation_workbench-0.1.4.zip.sha256",
        },
    )

    exit_code = console.main(["doctor"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["checks"]["update"]["update_available"] is True
    assert payload["checks"]["update"]["latest_version"] == "0.1.4"
    assert captured.err == ""


def test_console_update_check_prints_json(monkeypatch, capsys):
    from local_translation_workbench import update_check

    monkeypatch.setattr(
        update_check,
        "check_for_update",
        lambda: {
            "status": "ok",
            "current_version": "0.1.3",
            "latest_version": "0.1.3",
            "update_available": False,
            "release_url": "https://github.com/gyyxs88/local_translation_workbench-releases/releases/tag/v0.1.3",
            "download_url": "https://example.test/local_translation_workbench-0.1.3.zip",
            "sha256_url": "https://example.test/local_translation_workbench-0.1.3.zip.sha256",
        },
    )

    exit_code = console.main(["update-check"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["update_available"] is False
    assert captured.err == ""


def test_console_migrate_requires_database_url(monkeypatch, capsys):
    monkeypatch.delenv("LTW_DATABASE_URL", raising=False)

    exit_code = console.main(["migrate"])
    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert exit_code == 1
    assert payload["error"]["code"] == "missing_config"
    assert "LTW_DATABASE_URL" in payload["error"]["message"]
