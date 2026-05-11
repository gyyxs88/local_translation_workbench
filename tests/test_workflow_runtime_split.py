from __future__ import annotations

from tools.local_translation_workbench.app.services.workflow_group_executor_service import (
    WorkflowGroupExecutorService,
)
from tools.local_translation_workbench.app.services.workflow_step_executor_service import (
    WorkflowStepExecutorService,
)


def test_workflow_step_executor_decorates_requested_and_actual_model_fields(db_session) -> None:
    executor = WorkflowStepExecutorService(db_session)

    payload = executor.decorate_step_output_payload(
        output_payload={"model_name": "actual-model", "fallback_depth": 1},
        resolved_model_profile_id="requested-profile",
        resolved_model_name="resolved-model",
    )

    assert payload["requested_model_profile_id"] == "requested-profile"
    assert payload["actual_model_name"] == "actual-model"
    assert payload["fallback_depth"] == 1


def test_workflow_group_executor_reports_degraded_when_quorum_met_with_failures() -> None:
    executor = WorkflowGroupExecutorService()

    summary = executor.summarize_tolerant_group_result(
        executions=[
            {"succeeded": True, "step_log": {"step_key": "a"}},
            {"succeeded": False, "step_log": {"step_key": "b"}},
        ],
        action="translation.generate_draft",
        minimum_success=1,
    )

    assert summary["degraded"] is True
    assert summary["failed_step_keys"] == ["b"]
