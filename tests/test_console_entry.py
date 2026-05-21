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
