from __future__ import annotations

import pytest

from tools.local_translation_workbench.app.services.translation_service import TranslationService


def test_translation_service_run_delegates_to_run_service(
    db_session,
    project_workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.local_translation_workbench.app.services.translation_run_service import (
        TranslationResult,
        TranslationRunService,
    )

    captured: dict[str, object] = {}

    def fake_run(self, **kwargs):
        captured.update(kwargs)
        return TranslationResult(
            translated_segments=2,
            active_version_ids=[7, 8],
            synopsis_summary={"source": {"status": "ready"}},
        )

    monkeypatch.setattr(TranslationRunService, "run", fake_run)

    service = TranslationService(db_session, base_data_dir=project_workspace, provider=None)

    result = service.run(
        request_id="req-translation-delegate",
        project_id=11,
        scope={"type": "all"},
        model_profile_id="profile-run",
        workflow_key="translation_single_llm_v1",
        provider_model_name="model-run",
        stage_run_id=22,
        heartbeat=None,
    )

    assert result == TranslationResult(
        translated_segments=2,
        active_version_ids=[7, 8],
        synopsis_summary={"source": {"status": "ready"}},
    )
    assert captured == {
        "request_id": "req-translation-delegate",
        "project_id": 11,
        "scope": {"type": "all"},
        "model_profile_id": "profile-run",
        "workflow_key": "translation_single_llm_v1",
        "provider_model_name": "model-run",
        "stage_run_id": 22,
        "heartbeat": None,
    }


def test_translation_service_inspect_delegates_to_inspection_service(
    db_session,
    project_workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.local_translation_workbench.app.services.translation_inspection_service import (
        TranslationInspectionService,
    )

    captured: dict[str, object] = {}

    def fake_inspect(self, **kwargs):
        captured.update(kwargs)
        return {"translations": [], "versions": []}

    monkeypatch.setattr(TranslationInspectionService, "inspect", fake_inspect)

    service = TranslationService(db_session, base_data_dir=project_workspace, provider=None)

    payload = service.inspect(
        project_id=11,
        segment_id=22,
        chapter_index=None,
        segment_index=None,
        compare_version_id=33,
    )

    assert payload == {"translations": [], "versions": []}
    assert captured == {
        "project_id": 11,
        "segment_id": 22,
        "chapter_index": None,
        "segment_index": None,
        "compare_version_id": 33,
    }


def test_translation_inspection_service_rejects_compare_without_locator(db_session) -> None:
    from tools.local_translation_workbench.app.errors import ToolError
    from tools.local_translation_workbench.app.services.translation_inspection_service import (
        TranslationInspectionService,
    )

    service = TranslationInspectionService(db_session)

    with pytest.raises(ToolError, match="compare_version_id"):
        service.inspect(project_id=7, compare_version_id=9)
