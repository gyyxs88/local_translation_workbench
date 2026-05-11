from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


def test_run_translation_pipeline_action_builds_pipeline_and_commits(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from tools.local_translation_workbench.app.stage_action_support import (
        StageProviderContext,
        run_translation_pipeline_action,
    )

    captured: dict[str, object] = {"committed": False}

    class FakeSession:
        def commit(self) -> None:
            captured["committed"] = True

    def fake_resolve_stage_provider_context(*, session, stage: str, arguments: dict[str, str]) -> StageProviderContext:
        assert stage == "translation"
        assert arguments["workflow_run_id"] == "17"
        return StageProviderContext(
            config=SimpleNamespace(data_dir=tmp_path),
            provider="provider-object",
            resolved_profile_id="profile-resolved",
            resolved_model_name="model-resolved",
        )

    class FakeTranslationPipelineService:
        def __init__(self, session, *, base_data_dir, provider):  # type: ignore[no-untyped-def]
            captured["session"] = session
            captured["base_data_dir"] = base_data_dir
            captured["provider"] = provider

    monkeypatch.setattr(
        "tools.local_translation_workbench.app.stage_action_support.resolve_stage_provider_context",
        fake_resolve_stage_provider_context,
    )
    monkeypatch.setattr(
        "tools.local_translation_workbench.app.stage_action_support.TranslationPipelineService",
        FakeTranslationPipelineService,
    )

    result = run_translation_pipeline_action(
        session=FakeSession(),
        arguments={"workflow_run_id": "17"},
        action_name="translation.review_draft",
        runner=lambda pipeline, context: {
            "pipeline": pipeline.__class__.__name__,
            "profile": context.resolved_profile_id,
            "model": context.resolved_model_name,
        },
    )

    assert result == {
        "ok": True,
        "action": "translation.review_draft",
        "data": {
            "pipeline": "FakeTranslationPipelineService",
            "profile": "profile-resolved",
            "model": "model-resolved",
        },
    }
    assert captured["committed"] is True
    assert captured["base_data_dir"] == tmp_path
    assert captured["provider"] == "provider-object"
