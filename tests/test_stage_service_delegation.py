from __future__ import annotations

from tools.local_translation_workbench.app.services.stage_run_orchestrator_service import (
    StageRunOrchestratorService,
)
from tools.local_translation_workbench.app.services.stage_service import StageCommand, StageService
from tools.local_translation_workbench.app.services.translation_run_service import TranslationResult


def test_stage_service_run_delegates_to_orchestrator_service(
    db_session,
    project_workspace,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(self, *, command, dispatch):  # type: ignore[no-untyped-def]
        captured["command"] = command
        captured["dispatch"] = dispatch
        return TranslationResult(translated_segments=1, active_version_ids=[9], synopsis_summary=None)

    monkeypatch.setattr(StageRunOrchestratorService, "run", fake_run)

    service = StageService(db_session, base_data_dir=project_workspace)
    command = StageCommand(
        request_id="req-stage-delegate",
        project_id=7,
        stage="translation",
        scope={"type": "all"},
        model_profile_id="profile-stage",
    )

    result = service.run(command)

    assert result == TranslationResult(translated_segments=1, active_version_ids=[9], synopsis_summary=None)
    assert captured["command"] == command
    assert captured["dispatch"] == service._dispatch


def test_stage_service_leases_property_proxies_to_orchestrator(db_session, project_workspace) -> None:
    service = StageService(db_session, base_data_dir=project_workspace)
    sentinel = object()

    service.leases = sentinel

    assert service.runner.leases is sentinel
    assert service.leases is sentinel
