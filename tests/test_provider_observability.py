from __future__ import annotations

from uuid import uuid4

from tools.local_translation_workbench.app import action_router
from tools.local_translation_workbench.app.db.models import TranslationProject
from tools.local_translation_workbench.app.services.provider_call_log_service import ProviderCallLogService


def _create_project(db_session) -> TranslationProject:
    project = TranslationProject(
        request_id=f"pytest-provider-observability-{uuid4().hex[:10]}",
        project_key=f"provider-observability-{uuid4().hex[:10]}",
        source_path="provider-observability.txt",
        source_language="zh",
        target_language="en",
        status="created",
    )
    db_session.add(project)
    db_session.flush()
    return project


def test_provider_observability_actions_are_registered() -> None:
    assert "inspect.provider_calls" in action_router.ACTION_HANDLERS
    assert "inspect.provider_costs" in action_router.ACTION_HANDLERS


def test_provider_call_log_service_records_lists_and_summarizes_usage(db_session) -> None:
    project = _create_project(db_session)
    service = ProviderCallLogService(db_session)

    service.record_call(
        project_id=project.id,
        stage="translation",
        action="translation.generate_draft",
        step_key="generate_primary",
        llm_role="translator",
        requested_model_profile_id="main_profile",
        actual_model_profile_id="backup_profile",
        provider_name="fake_provider",
        model_name="gpt-5.4",
        fallback_depth=1,
        status="ok",
        token_usage={"input_tokens": 100, "output_tokens": 40, "total_tokens": 140},
        latency_ms=321,
    )
    service.record_call(
        project_id=project.id,
        stage="glossary",
        action="glossary.extract",
        step_key="extract_primary",
        llm_role="extractor",
        requested_model_profile_id="main_profile",
        actual_model_profile_id="main_profile",
        provider_name="fake_provider",
        model_name="gpt-5.4",
        fallback_depth=0,
        status="failed",
        error_code="provider_error",
        error_type="rate_limit",
        error_message="429 rate limit exceeded",
    )
    db_session.commit()

    calls = service.list_calls(project_id=project.id)
    assert [item["stage"] for item in calls] == ["glossary", "translation"]
    assert calls[0]["error_type"] == "rate_limit"
    assert calls[1]["actual_model_profile_id"] == "backup_profile"

    summary = service.summarize_costs(project_id=project.id)
    assert summary["totals"]["call_count"] == 2
    assert summary["totals"]["failed_call_count"] == 1
    assert summary["totals"]["input_tokens"] == 100
    assert summary["totals"]["output_tokens"] == 40
    assert summary["totals"]["total_tokens"] == 140
    assert summary["by_stage"]["translation"]["fallback_call_count"] == 1
