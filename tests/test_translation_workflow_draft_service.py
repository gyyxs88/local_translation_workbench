from __future__ import annotations

from types import SimpleNamespace

import pytest

from tools.local_translation_workbench.app.services.translation_pipeline_service import (
    TranslationPipelineService,
)


def test_translation_workflow_draft_service_prefers_rewrite_draft_for_final_candidate(db_session) -> None:
    from tools.local_translation_workbench.app.services.translation_workflow_draft_service import (
        TranslationWorkflowDraftService,
    )

    service = TranslationWorkflowDraftService(db_session)
    service.translation_workflows.list_draft_versions = lambda workflow_run_id: [
        SimpleNamespace(
            id=1,
            segment_id=10,
            draft_role="primary",
            parent_draft_id=None,
            model_profile_id="profile-a",
            model_name="model-a",
            status="completed",
            translated_text="Primary draft",
        ),
        SimpleNamespace(
            id=2,
            segment_id=10,
            draft_role="rewrite",
            parent_draft_id=1,
            model_profile_id="profile-b",
            model_name="model-b",
            status="completed",
            translated_text="Rewrite draft",
        ),
    ]
    service.translation_workflows.list_draft_reviews = lambda workflow_run_id: []

    payload = service.inspect_pipeline(workflow_run_id=9)

    assert payload["final_candidates"] == [
        {
            "segment_id": 10,
            "selected_draft_role": "rewrite",
            "selected_draft_id": 2,
        }
    ]


def test_translation_pipeline_inspect_pipeline_delegates_to_draft_service(
    db_session,
    project_workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.local_translation_workbench.app.services.translation_workflow_draft_service import (
        TranslationWorkflowDraftService,
    )

    captured: dict[str, object] = {}

    def fake_inspect_pipeline(self, *, workflow_run_id: int) -> dict[str, object]:
        captured["workflow_run_id"] = workflow_run_id
        return {"workflow_run_id": workflow_run_id, "drafts": [], "reviews": [], "final_candidates": []}

    monkeypatch.setattr(TranslationWorkflowDraftService, "inspect_pipeline", fake_inspect_pipeline)

    pipeline = TranslationPipelineService(db_session, base_data_dir=project_workspace)

    payload = pipeline.inspect_pipeline(workflow_run_id=17)

    assert payload == {
        "workflow_run_id": 17,
        "drafts": [],
        "reviews": [],
        "final_candidates": [],
    }
    assert captured == {"workflow_run_id": 17}
