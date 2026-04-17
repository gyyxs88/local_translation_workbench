from __future__ import annotations

import pytest

from tools.local_translation_workbench.app.services.translation_pipeline_service import (
    TranslationPipelineService,
)


@pytest.mark.parametrize(
    ("method_name", "kwargs"),
    [
        (
            "generate_draft",
            {
                "workflow_run_id": 10,
                "workflow_step_run_id": 20,
                "project_id": 30,
                "scope": {"type": "all"},
                "model_profile_id": "profile-generate",
                "provider_model_name": "model-generate",
                "draft_role": "primary",
            },
        ),
        (
            "review_draft",
            {
                "workflow_run_id": 11,
                "workflow_step_run_id": 21,
                "model_profile_id": "profile-review",
                "provider_model_name": "model-review",
            },
        ),
        (
            "rewrite_draft",
            {
                "workflow_run_id": 12,
                "workflow_step_run_id": 22,
                "model_profile_id": "profile-rewrite",
                "provider_model_name": "model-rewrite",
            },
        ),
        (
            "finalize",
            {
                "workflow_run_id": 13,
                "workflow_step_run_id": 23,
                "project_id": 33,
                "model_profile_id": "profile-finalize",
                "provider_model_name": "model-finalize",
            },
        ),
    ],
)
def test_translation_pipeline_execution_methods_delegate_to_execution_service(
    db_session,
    project_workspace,
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
    kwargs: dict[str, object],
) -> None:
    from tools.local_translation_workbench.app.services.translation_workflow_execution_service import (
        TranslationWorkflowExecutionService,
    )

    captured: dict[str, object] = {}

    def fake_handler(self, **handler_kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        captured.update(handler_kwargs)
        return {"method": method_name, "delegated": True}

    monkeypatch.setattr(TranslationWorkflowExecutionService, method_name, fake_handler)

    pipeline = TranslationPipelineService(db_session, base_data_dir=project_workspace)

    payload = getattr(pipeline, method_name)(**kwargs)

    assert payload == {"method": method_name, "delegated": True}
    assert captured == {**kwargs, "heartbeat": None}
