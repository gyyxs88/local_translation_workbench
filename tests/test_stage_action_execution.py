from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tools.local_translation_workbench.app.providers.router import ResolvedProviderProfile
from tools.local_translation_workbench.app.services.translation_run_service import TranslationResult


def test_execute_stage_command_resolves_provider_and_builds_stage_command(
    db_session,
    project_workspace: Path,
    monkeypatch,
) -> None:
    from tools.local_translation_workbench.app import action_router as action_router_module
    from tools.local_translation_workbench.app.action_handlers.stage_execution import (
        execute_stage_command,
    )

    fake_provider = object()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        action_router_module,
        "_resolve_model_stage_provider",
        lambda *, session, config, stage, model_profile_id: ResolvedProviderProfile(
            provider=fake_provider,
            profile_key="profile-resolved",
            model_name="model-resolved",
        ),
    )

    class FakeStageService:
        def __init__(self, session, *, base_data_dir, provider):  # type: ignore[no-untyped-def]
            captured["session"] = session
            captured["base_data_dir"] = base_data_dir
            captured["provider"] = provider

        def run(self, command):  # type: ignore[no-untyped-def]
            captured["command"] = command
            return TranslationResult(translated_segments=3, active_version_ids=[1, 2, 3], synopsis_summary=None)

    monkeypatch.setattr(
        "tools.local_translation_workbench.app.action_handlers.stage_execution.StageService",
        FakeStageService,
    )

    result = execute_stage_command(
        session=db_session,
        config=SimpleNamespace(data_dir=project_workspace),
        request_id="req-stage-helper",
        project_id=17,
        stage="translation",
        scope={"type": "all"},
        model_profile_id="profile-requested",
        workflow_key="translation_multi_llm_v1",
        resume=True,
        rerun=False,
    )

    assert result == TranslationResult(translated_segments=3, active_version_ids=[1, 2, 3], synopsis_summary=None)
    assert captured["session"] is db_session
    assert captured["base_data_dir"] == project_workspace
    assert captured["provider"] is fake_provider
    command = captured["command"]
    assert command.request_id == "req-stage-helper"
    assert command.project_id == 17
    assert command.stage == "translation"
    assert command.scope == {"type": "all"}
    assert command.model_profile_id == "profile-resolved"
    assert command.workflow_key == "translation_multi_llm_v1"
    assert command.provider_model_name == "model-resolved"
    assert command.resume is True
    assert command.rerun is False
