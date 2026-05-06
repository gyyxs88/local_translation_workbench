from __future__ import annotations

import pytest

from tools.local_translation_workbench.app.db.models import (
    Chapter,
    ChapterSegment,
    SegmentTranslation,
    SegmentTranslationVersion,
    TranslationDraftVersion,
    TranslationProject,
    WorkflowRun,
    WorkflowStepRun,
)
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
        "route_preset_key": None,
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
        version_id=None,
        compare_version_id=33,
    )

    assert payload == {"translations": [], "versions": []}
    assert captured == {
        "project_id": 11,
        "segment_id": 22,
        "chapter_index": None,
        "segment_index": None,
        "version_id": None,
        "compare_version_id": 33,
    }


def test_translation_service_inspect_delegates_version_id_to_inspection_service(
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
        version_id=44,
        compare_version_id=33,
    )

    assert payload == {"translations": [], "versions": []}
    assert captured == {
        "project_id": 11,
        "segment_id": 22,
        "chapter_index": None,
        "segment_index": None,
        "version_id": 44,
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


def test_translation_inspection_service_rejects_version_id_without_locator(db_session) -> None:
    from tools.local_translation_workbench.app.errors import ToolError
    from tools.local_translation_workbench.app.services.translation_inspection_service import (
        TranslationInspectionService,
    )

    service = TranslationInspectionService(db_session)

    with pytest.raises(ToolError, match="version_id"):
        service.inspect(project_id=7, version_id=9)


def test_translation_inspection_quality_samples_groups_active_versions_by_source(db_session) -> None:
    from tools.local_translation_workbench.app.services.translation_inspection_service import (
        TranslationInspectionService,
    )

    project = TranslationProject(
        request_id="translation-samples-project",
        project_key="translation-samples-project",
        source_path="source.txt",
        source_language="zh",
        target_language="en",
        status="created",
    )
    db_session.add(project)
    db_session.flush()
    workflow_run = WorkflowRun(
        workflow_key="translation_multi_llm_v1",
        project_id=project.id,
        stage="translation",
        scope_type="all",
        scope_value='{"type":"all"}',
        request_id="translation-samples-run",
        status="completed",
        summary=None,
    )
    db_session.add(workflow_run)
    db_session.flush()

    gpt_sample = _add_translation_sample(
        db_session,
        project_id=project.id,
        workflow_run_id=workflow_run.id,
        chapter_index=1,
        draft_role="primary",
        model_profile_id="gpt_5_5_aicodelink",
        model_name="gpt-5.5",
    )
    deepseek_sample = _add_translation_sample(
        db_session,
        project_id=project.id,
        workflow_run_id=workflow_run.id,
        chapter_index=2,
        draft_role="secondary",
        model_profile_id="deepseek_v4_pro",
        model_name="deepseek-v4-pro",
    )
    rewrite_sample = _add_translation_sample(
        db_session,
        project_id=project.id,
        workflow_run_id=workflow_run.id,
        chapter_index=3,
        draft_role="rewrite",
        model_profile_id="gpt_5_5_aicodelink",
        model_name="gpt-5.5",
    )
    db_session.commit()

    payload = TranslationInspectionService(db_session).inspect_quality_samples(
        project_id=project.id,
        limit_per_source=1,
    )

    assert payload["source_counts"] == {"gpt": 1, "deepseek": 1, "rewrite": 1, "other": 0}
    assert payload["missing_source_classes"] == []
    assert payload["samples"]["gpt"][0]["version_id"] == gpt_sample.id
    assert payload["samples"]["deepseek"][0]["version_id"] == deepseek_sample.id
    assert payload["samples"]["rewrite"][0]["version_id"] == rewrite_sample.id
    assert payload["samples"]["rewrite"][0]["draft_role"] == "rewrite"


def _add_translation_sample(
    db_session,
    *,
    project_id: int,
    workflow_run_id: int,
    chapter_index: int,
    draft_role: str,
    model_profile_id: str,
    model_name: str,
) -> SegmentTranslationVersion:
    chapter = Chapter(
        project_id=project_id,
        chapter_index=chapter_index,
        chapter_title=f"第{chapter_index}章",
        source_path=f"chapter-{chapter_index}.txt",
        normalized_path=f"chapter-{chapter_index}.normalized.txt",
        stage_status="ready",
    )
    db_session.add(chapter)
    db_session.flush()
    segment = ChapterSegment(
        project_id=project_id,
        chapter_id=chapter.id,
        segment_index=1,
        source_text_path=f"segment-{chapter_index}.txt",
        translation_status="translated",
        review_status="pending",
    )
    db_session.add(segment)
    db_session.flush()
    draft_step = WorkflowStepRun(
        workflow_run_id=workflow_run_id,
        step_key=f"{draft_role}-{chapter_index}",
        action="translation.generate_draft",
        llm_role="draft_generator",
        model_profile_id=model_profile_id,
        status="completed",
        input_ref="{}",
        output_payload=None,
        summary=None,
    )
    finalize_step = WorkflowStepRun(
        workflow_run_id=workflow_run_id,
        step_key=f"finalize-{chapter_index}",
        action="translation.finalize",
        llm_role="final_judge",
        model_profile_id=model_profile_id,
        status="completed",
        input_ref="{}",
        output_payload=None,
        summary=None,
    )
    db_session.add_all([draft_step, finalize_step])
    db_session.flush()
    draft = TranslationDraftVersion(
        workflow_run_id=workflow_run_id,
        project_id=project_id,
        segment_id=segment.id,
        step_run_id=draft_step.id,
        parent_draft_id=None,
        draft_role=draft_role,
        source_hash="source-hash",
        glossary_snapshot_id="glossary-hash",
        provider_name="openai_compatible",
        model_profile_id=model_profile_id,
        model_name=model_name,
        translated_text=f"{draft_role} draft translation",
        translated_text_path=f"draft-{chapter_index}.txt",
        status="completed",
        evidence_payload=None,
    )
    db_session.add(draft)
    db_session.flush()
    translation = SegmentTranslation(project_id=project_id, segment_id=segment.id)
    db_session.add(translation)
    db_session.flush()
    version = SegmentTranslationVersion(
        project_id=project_id,
        segment_translation_id=translation.id,
        origin_workflow_run_id=workflow_run_id,
        origin_step_run_id=finalize_step.id,
        origin_draft_version_id=draft.id,
        version_index=1,
        source_hash="source-hash",
        glossary_snapshot_id="glossary-hash",
        provider_name="openai_compatible",
        model_profile_id=model_profile_id,
        model_name=model_name,
        source_text=f"源文 {chapter_index}",
        translated_text=f"{draft_role} final translation",
        translated_text_path=f"version-{chapter_index}.txt",
        status="completed",
    )
    db_session.add(version)
    db_session.flush()
    translation.active_version_id = version.id
    return version
