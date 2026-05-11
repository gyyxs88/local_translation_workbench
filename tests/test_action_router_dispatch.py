from __future__ import annotations

import json
from pathlib import Path

from tools.local_translation_workbench.app import action_router


def test_route_action_uses_dispatch_table(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_handler(arguments: dict[str, str]) -> dict[str, object]:
        captured.update(arguments)
        return {"ok": True, "action": "test.fake", "data": {"handled": True}}

    monkeypatch.setitem(action_router.ACTION_HANDLERS, "test.fake", fake_handler)

    payload = action_router.route_action({"action": "test.fake", "example": "value"})

    assert payload == {"ok": True, "action": "test.fake", "data": {"handled": True}}
    assert captured["example"] == "value"


def test_resolve_model_stage_provider_uses_action_router_provider_builder(monkeypatch) -> None:
    expected = object()
    captured: dict[str, object] = {}

    def fake_build_provider_from_profile(session, config, model_profile_id):
        captured["session"] = session
        captured["config"] = config
        captured["model_profile_id"] = model_profile_id
        return expected

    monkeypatch.setattr(action_router, "build_provider_from_profile", fake_build_provider_from_profile)

    resolved = action_router._resolve_model_stage_provider(
        session="session-value",
        config="config-value",
        stage="translation",
        model_profile_id="profile-translation",
    )

    assert resolved is expected
    assert captured == {
        "session": "session-value",
        "config": "config-value",
        "model_profile_id": "profile-translation",
    }


def test_annotation_actions_are_registered() -> None:
    assert "annotation.extract" in action_router.ACTION_HANDLERS
    assert "annotation.inspect" in action_router.ACTION_HANDLERS
    assert "annotation.approve" in action_router.ACTION_HANDLERS
    assert "annotation.reject" in action_router.ACTION_HANDLERS


def test_tool_json_action_enum_matches_registered_handlers() -> None:
    tool_root = Path(__file__).resolve().parents[1]
    payload = json.loads((tool_root / "TOOL.json").read_text(encoding="utf-8"))
    enum_values = set(payload["argsSchema"]["properties"]["action"]["enum"])

    assert enum_values == set(action_router.ACTION_HANDLERS)
