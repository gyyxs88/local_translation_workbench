from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import update

from tools.local_translation_workbench.app.db.models import ModelRoutePreset
from tools.local_translation_workbench.app.providers.router import ResolvedProviderProfile
from tools.local_translation_workbench.app.services.provider_profile_service import ProviderProfileService
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


def test_stage_run_review_passes_review_loop_options(
    monkeypatch,
    project_workspace: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakeSession:
        def close(self) -> None:
            captured["closed"] = True

    def fake_execute_stage_command(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)

        class Result:
            issue_count = 0
            run_id = 1
            mode = "hard_only"
            passed_segment_count = 1
            needs_revision_segment_count = 0
            rewrite_segment_count = 0
            rewrite_version_ids: list[int] = []
            token_usage = None

        return Result()

    monkeypatch.setattr(
        "tools.local_translation_workbench.app.action_handlers.stage_handlers.load_config",
        lambda: SimpleNamespace(data_dir=project_workspace),
    )
    monkeypatch.setattr(
        "tools.local_translation_workbench.app.action_handlers.stage_handlers.support._open_session",
        lambda: FakeSession(),
    )
    monkeypatch.setattr(
        "tools.local_translation_workbench.app.action_handlers.stage_handlers.support._bootstrap_workflow_profiles",
        lambda session: None,
    )
    monkeypatch.setattr(
        "tools.local_translation_workbench.app.action_handlers.stage_handlers.assert_database_schema_current",
        lambda session: None,
    )
    monkeypatch.setattr(
        "tools.local_translation_workbench.app.action_handlers.stage_handlers.execute_stage_command",
        fake_execute_stage_command,
    )

    from tools.local_translation_workbench.app.cli import main

    exit_code = main(
        [
            "-Action",
            "stage.run",
            "-Stage",
            "review",
            "-ProjectId",
            "123",
            "-RequestId",
            "review-cli-options",
            "-ReviewMode",
            "hard_only",
            "-MaxRewriteRounds",
            "1",
        ]
    )

    assert exit_code == 0
    assert captured["stage"] == "review"
    assert captured["review_mode"] == "hard_only"
    assert captured["max_rewrite_rounds"] == 1
    assert captured["closed"] is True


def test_execute_stage_command_skips_provider_for_hard_only_review(
    db_session,
    project_workspace: Path,
    monkeypatch,
) -> None:
    from tools.local_translation_workbench.app import action_router as action_router_module
    from tools.local_translation_workbench.app.action_handlers.stage_execution import (
        execute_stage_command,
    )

    captured: dict[str, object] = {}

    def fail_provider_resolution(**kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("hard_only review should not resolve provider")

    monkeypatch.setattr(
        action_router_module,
        "_resolve_model_stage_provider",
        fail_provider_resolution,
    )

    class FakeStageService:
        def __init__(self, session, *, base_data_dir, provider):  # type: ignore[no-untyped-def]
            captured["provider"] = provider

        def run(self, command):  # type: ignore[no-untyped-def]
            captured["command"] = command
            return command

    monkeypatch.setattr(
        "tools.local_translation_workbench.app.action_handlers.stage_execution.StageService",
        FakeStageService,
    )

    command = execute_stage_command(
        session=db_session,
        config=SimpleNamespace(data_dir=project_workspace),
        request_id="req-hard-review",
        project_id=17,
        stage="review",
        scope={"type": "all"},
        review_mode="hard_only",
    )

    assert captured["provider"] is None
    assert command.stage == "review"
    assert command.review_mode == "hard_only"
    assert command.max_rewrite_rounds == 2


def test_execute_stage_command_uses_default_route_preset_when_omitted(
    db_session,
    project_workspace: Path,
    monkeypatch,
) -> None:
    from tools.local_translation_workbench.app import action_router as action_router_module
    from tools.local_translation_workbench.app.action_handlers.stage_execution import (
        execute_stage_command,
    )

    service = ProviderProfileService(db_session)
    service.create_provider(
        provider_key="default_route_provider",
        provider_type="openai_compatible",
        display_name="Default Route Provider",
        base_url="https://default-route.example.com/v1",
        api_key_value="sk-default-route",
        status="active",
        note=None,
    )
    service.create_profile(
        profile_key="default_route_primary",
        provider_key="default_route_provider",
        model_name="gpt-5.5",
        timeout_seconds=60,
        temperature=0,
        is_default=True,
        status="active",
        note=None,
    )
    service.set_route_preset(
        preset_key="default_route_stack",
        display_name="Default Route Stack",
        bindings=[
            {
                "stage": "translation",
                "step_key": "generate_primary",
                "model_profile_id": "default_route_primary",
            }
        ],
        is_default=True,
        status="active",
        note=None,
    )

    captured: dict[str, object] = {}

    def fake_resolve_model_stage_provider(**kwargs):  # type: ignore[no-untyped-def]
        captured["model_profile_id"] = kwargs["model_profile_id"]
        return ResolvedProviderProfile(
            provider=object(),
            profile_key=str(kwargs["model_profile_id"]),
            model_name="resolved-default-route-model",
        )

    class FakeStageService:
        def __init__(self, session, *, base_data_dir, provider):  # type: ignore[no-untyped-def]
            captured["provider"] = provider

        def run(self, command):  # type: ignore[no-untyped-def]
            captured["command"] = command
            return command

    monkeypatch.setattr(action_router_module, "_resolve_model_stage_provider", fake_resolve_model_stage_provider)
    monkeypatch.setattr(
        "tools.local_translation_workbench.app.action_handlers.stage_execution.StageService",
        FakeStageService,
    )

    try:
        command = execute_stage_command(
            session=db_session,
            config=SimpleNamespace(data_dir=project_workspace),
            request_id="default-route-run",
            project_id=17,
            stage="translation",
            scope={"type": "all"},
        )
    finally:
        db_session.execute(update(ModelRoutePreset).values(is_default=0))
        db_session.commit()

    assert captured["model_profile_id"] == "default_route_primary"
    assert command.route_preset_key == "default_route_stack"
    assert command.model_profile_id == "default_route_primary"


def test_execute_stage_command_honors_explicit_model_profile_when_default_route_exists(
    db_session,
    project_workspace: Path,
    monkeypatch,
) -> None:
    from tools.local_translation_workbench.app import action_router as action_router_module
    from tools.local_translation_workbench.app.action_handlers.stage_execution import (
        execute_stage_command,
    )

    service = ProviderProfileService(db_session)
    service.create_provider(
        provider_key="explicit_model_route_provider",
        provider_type="openai_compatible",
        display_name="Explicit Model Route Provider",
        base_url="https://explicit-model-route.example.com/v1",
        api_key_value="sk-explicit-model-route",
        status="active",
        note=None,
    )
    service.create_profile(
        profile_key="explicit_model_route_primary",
        provider_key="explicit_model_route_provider",
        model_name="gpt-5.5",
        timeout_seconds=60,
        temperature=0,
        is_default=True,
        status="active",
        note=None,
    )
    service.set_route_preset(
        preset_key="explicit_model_default_route_stack",
        display_name="Explicit Model Default Route Stack",
        bindings=[
            {
                "stage": "translation",
                "step_key": "generate_primary",
                "model_profile_id": "explicit_model_route_primary",
            }
        ],
        is_default=True,
        status="active",
        note=None,
    )

    captured: dict[str, object] = {}

    def fake_resolve_model_stage_provider(**kwargs):  # type: ignore[no-untyped-def]
        captured["model_profile_id"] = kwargs["model_profile_id"]
        return ResolvedProviderProfile(
            provider=object(),
            profile_key=str(kwargs["model_profile_id"]),
            model_name="resolved-explicit-model",
        )

    class FakeStageService:
        def __init__(self, session, *, base_data_dir, provider):  # type: ignore[no-untyped-def]
            captured["provider"] = provider

        def run(self, command):  # type: ignore[no-untyped-def]
            captured["command"] = command
            return command

    monkeypatch.setattr(action_router_module, "_resolve_model_stage_provider", fake_resolve_model_stage_provider)
    monkeypatch.setattr(
        "tools.local_translation_workbench.app.action_handlers.stage_execution.StageService",
        FakeStageService,
    )

    try:
        command = execute_stage_command(
            session=db_session,
            config=SimpleNamespace(data_dir=project_workspace),
            request_id="explicit-model-route-run",
            project_id=17,
            stage="translation",
            scope={"type": "all"},
            model_profile_id="profile-cli",
        )
    finally:
        db_session.execute(update(ModelRoutePreset).values(is_default=0))
        db_session.commit()

    assert captured["model_profile_id"] == "profile-cli"
    assert command.route_preset_key is None
    assert command.model_profile_id == "profile-cli"
