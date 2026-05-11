from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from tools.local_translation_workbench.app.cli import main
from tools.local_translation_workbench.app.db.models import (
    Chapter,
    ChapterSegment,
    ExportRun,
    ProjectLease,
    ReviewRun,
    StageRun,
    TranslationProject,
    WorkflowRun,
    WorkflowStepRun,
)
from tools.local_translation_workbench.app.errors import ToolError
from tools.local_translation_workbench.app.providers.base import TextGenerationResult
from tools.local_translation_workbench.app.repositories.projects import ProjectService
from tools.local_translation_workbench.app.repositories.synopsis import ProjectSynopsisRepository
from tools.local_translation_workbench.app.repositories.translation_workflows import TranslationWorkflowRepository
from tools.local_translation_workbench.app.services.chaptering_service import ChapteringService
from tools.local_translation_workbench.app.services.export_service import ExportService
from tools.local_translation_workbench.app.services.glossary_service import GlossaryService
from tools.local_translation_workbench.app.services.lease_service import LeaseRecord, LeaseService
from tools.local_translation_workbench.app.services.project_query_service import ProjectQueryService
from tools.local_translation_workbench.app.services.review_service import ReviewService
from tools.local_translation_workbench.app.services.stage_service import StageCommand, StageService
from tools.local_translation_workbench.app.services.translation_service import TranslationService


class FakeProvider:
    def __init__(self, prefix: str = "fake-provider") -> None:
        self.prefix = prefix
        self.calls: list[dict[str, object]] = []

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        self.calls.append(
            {
                "prompt": prompt,
                "model_name": model_name,
                "timeout_seconds": timeout_seconds,
            }
        )
        if "提取术语" in str(prompt):
            terms = []
            glossary_map = {
                "程风": ("Cheng Feng", "character", "Character name"),
                "青石镇": ("Qingshi Town", "location", "Town name"),
            }
            for source_term, (translated_term, category, note) in glossary_map.items():
                if source_term in str(prompt):
                    terms.append(
                        {
                            "source_term": source_term,
                            "translated_term": translated_term,
                            "category": category,
                            "note": note,
                        }
                    )
            return TextGenerationResult(
                content=json.dumps({"terms": terms}, ensure_ascii=False),
                provider_name=self.prefix,
                model_name=model_name,
            )
        source_text = str(prompt).split("\n\n", maxsplit=1)[-1]
        return TextGenerationResult(
            content=f"[{model_name}] {source_text}",
            provider_name=self.prefix,
            model_name=model_name,
        )


class FailingProvider:
    def __init__(self) -> None:
        self.call_count = 0

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        self.call_count += 1
        raise ToolError(code="provider_error", message="模拟翻译失败。", status=502)


class SpyLeaseService:
    def __init__(self) -> None:
        self.acquire_calls: list[dict[str, object]] = []
        self.refresh_calls: list[dict[str, object]] = []
        self.release_calls: list[dict[str, object]] = []

    def acquire(self, *, project_id: int, lease_owner: str, ttl_seconds: int) -> LeaseRecord:
        self.acquire_calls.append(
            {
                "project_id": project_id,
                "lease_owner": lease_owner,
                "ttl_seconds": ttl_seconds,
            }
        )
        return LeaseRecord(
            project_id=project_id,
            lease_owner=lease_owner,
            lease_token="spy-lease-token",
            lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
        )

    def refresh(self, *, project_id: int, lease_owner: str, lease_token: str, ttl_seconds: int) -> LeaseRecord:
        self.refresh_calls.append(
            {
                "project_id": project_id,
                "lease_owner": lease_owner,
                "lease_token": lease_token,
                "ttl_seconds": ttl_seconds,
            }
        )
        return LeaseRecord(
            project_id=project_id,
            lease_owner=lease_owner,
            lease_token=lease_token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
        )

    def release(self, *, project_id: int, lease_owner: str, lease_token: str) -> bool:
        self.release_calls.append(
            {
                "project_id": project_id,
                "lease_owner": lease_owner,
                "lease_token": lease_token,
            }
        )
        return True


def _prepare_project_with_chapters(
    *,
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> int:
    source_file = project_workspace / "stage-conflict-source.txt"
    source_file.write_text(
        "第1章 开始\n第一段。\n\n第2章 继续\n第二段。",
        encoding="utf-8",
    )

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("stage-conflict-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("stage-conflict-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )
    return project.id


def _prepare_project_with_translation_review_and_export(
    *,
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> int:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    GlossaryService(db_session, provider=FakeProvider(prefix="glossary-initial-provider")).run(
        request_id=request_id_factory("stage-conflict-glossary"),
        project_id=project_id,
        scope={"type": "all"},
        model_profile_id="profile-glossary-initial",
    )

    TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=FakeProvider(prefix="initial-provider"),
    ).run(
        request_id=request_id_factory("stage-conflict-translation"),
        project_id=project_id,
        scope={"type": "all"},
        model_profile_id="profile-initial",
    )

    ReviewService(db_session).run(
        request_id=request_id_factory("stage-conflict-review"),
        project_id=project_id,
        scope={"type": "all"},
        review_mode="hard_only",
    )
    ExportService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("stage-conflict-export"),
        project_id=project_id,
        scope={"type": "all"},
    )
    return project_id


def _prepare_project_with_glossary_terms(
    *,
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> int:
    source_file = project_workspace / "stage-stale-source.txt"
    source_file.write_text(
        "第1章 开始\n程风走进青石镇。\n\n第2章 继续\n第二段。",
        encoding="utf-8",
    )

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("stage-stale-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("stage-stale-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )
    return project.id


def _create_running_stage_workflow(
    db_session,
    *,
    project_id: int,
    request_id: str,
    stage: str = "translation",
) -> tuple[StageRun, WorkflowRun, WorkflowStepRun]:
    scope = {"type": "all"}
    stage_run = StageRun(
        project_id=project_id,
        stage=stage,
        scope_type="all",
        scope_value=json.dumps(scope, ensure_ascii=False),
        status="running",
        summary=json.dumps({"request_id": request_id, "workflow_key": f"{stage}_single_llm_v1"}, ensure_ascii=False),
    )
    db_session.add(stage_run)
    db_session.flush()
    workflow_run = WorkflowRun(
        workflow_key=f"{stage}_single_llm_v1",
        project_id=project_id,
        stage=stage,
        scope_type="all",
        scope_value=json.dumps(scope, ensure_ascii=False),
        request_id=request_id,
        status="running",
        summary=json.dumps(
            {
                "request_id": request_id,
                "workflow_key": f"{stage}_single_llm_v1",
                "stage_run_id": stage_run.id,
            },
            ensure_ascii=False,
        ),
    )
    db_session.add(workflow_run)
    db_session.flush()
    step_run = WorkflowStepRun(
        workflow_run_id=workflow_run.id,
        step_key="generate_primary" if stage == "translation" else "extract",
        action="translation.generate_draft" if stage == "translation" else "glossary.extract",
        llm_role="primary",
        model_profile_id="profile-running",
        status="running",
        input_ref=json.dumps({"project_id": project_id}, ensure_ascii=False),
        output_payload=None,
        summary=json.dumps({"step_key": "running"}, ensure_ascii=False),
    )
    db_session.add(step_run)
    db_session.flush()
    return stage_run, workflow_run, step_run


def test_project_cancel_marks_running_runs_and_releases_lease(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    stage_run, workflow_run, step_run = _create_running_stage_workflow(
        db_session,
        project_id=project_id,
        request_id=request_id_factory("cancel-running-workflow"),
    )
    lease = LeaseService(db_session).acquire(project_id=project_id, lease_owner="stage.run:translation:running", ttl_seconds=300)
    assert lease.lease_token

    payload = ProjectQueryService(db_session).cancel_project(
        project_id=project_id,
        request_id=request_id_factory("cancel-running-project"),
    )

    db_session.expire_all()
    project = db_session.get(TranslationProject, project_id)
    refreshed_stage_run = db_session.get(StageRun, stage_run.id)
    refreshed_workflow_run = db_session.get(WorkflowRun, workflow_run.id)
    refreshed_step_run = db_session.get(WorkflowStepRun, step_run.id)
    active_leases = db_session.execute(select(ProjectLease).where(ProjectLease.project_id == project_id)).scalars().all()

    assert project is not None
    assert project.status == "cancelled"
    assert refreshed_stage_run is not None
    assert refreshed_stage_run.status == "cancelled"
    assert refreshed_workflow_run is not None
    assert refreshed_workflow_run.status == "cancelled"
    assert refreshed_step_run is not None
    assert refreshed_step_run.status == "cancelled"
    assert active_leases == []
    assert payload["cancelled_stage_run_count"] == 1
    assert payload["cancelled_workflow_run_count"] == 1
    assert payload["cancelled_workflow_step_count"] == 1
    assert payload["released_lease_count"] == 1


def test_cli_stage_cancel_marks_running_stage_without_cancelling_project(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    capsys,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    stage_run, workflow_run, step_run = _create_running_stage_workflow(
        db_session,
        project_id=project_id,
        request_id=request_id_factory("stage-cancel-running-workflow"),
    )
    lease = LeaseService(db_session).acquire(project_id=project_id, lease_owner="stage.run:translation:running", ttl_seconds=300)
    assert lease.lease_token

    exit_code = main(
        [
            "-Action",
            "stage.cancel",
            "-ProjectId",
            str(project_id),
            "-StageRunId",
            str(stage_run.id),
            "-RequestId",
            request_id_factory("stage-cancel-action"),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    db_session.expire_all()
    project = db_session.get(TranslationProject, project_id)
    refreshed_stage_run = db_session.get(StageRun, stage_run.id)
    refreshed_workflow_run = db_session.get(WorkflowRun, workflow_run.id)
    refreshed_step_run = db_session.get(WorkflowStepRun, step_run.id)
    active_leases = db_session.execute(select(ProjectLease).where(ProjectLease.project_id == project_id)).scalars().all()

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["action"] == "stage.cancel"
    assert payload["data"]["cancelled_stage_run_count"] == 1
    assert project is not None
    assert project.status != "cancelled"
    assert refreshed_stage_run is not None
    assert refreshed_stage_run.status == "cancelled"
    assert refreshed_workflow_run is not None
    assert refreshed_workflow_run.status == "cancelled"
    assert refreshed_step_run is not None
    assert refreshed_step_run.status == "cancelled"
    assert active_leases == []


def test_stage_service_heartbeat_stops_after_project_cancel(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    service = StageService(
        db_session,
        base_data_dir=project_workspace,
        provider=FakeProvider(prefix="cancel-heartbeat"),
    )

    def cancel_then_heartbeat(*, project, command, stage_run_id, heartbeat):  # type: ignore[no-untyped-def]
        ProjectQueryService(db_session).cancel_project(
            project_id=command.project_id,
            request_id=request_id_factory("cancel-during-heartbeat"),
        )
        heartbeat()

    monkeypatch.setattr(service, "_dispatch", cancel_then_heartbeat)

    with pytest.raises(ToolError) as exc:
        service.run(
            StageCommand(
                request_id=request_id_factory("stage-cancel-heartbeat"),
                project_id=project_id,
                stage="translation",
                scope={"type": "all"},
                model_profile_id="profile-cancel-heartbeat",
            )
        )

    db_session.rollback()
    stage_run = db_session.execute(
        select(StageRun)
        .where(StageRun.project_id == project_id, StageRun.stage == "translation")
        .order_by(StageRun.id.desc())
    ).scalar_one()
    active_leases = db_session.execute(select(ProjectLease).where(ProjectLease.project_id == project_id)).scalars().all()

    assert exc.value.code == "cancelled"
    assert stage_run.status == "cancelled"
    assert active_leases == []


def test_stage_run_translation_rejects_second_writer(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    leases = LeaseService(db_session)
    lease = leases.acquire(project_id=project_id, lease_owner="agent-a", ttl_seconds=300)
    assert lease.project_id == project_id

    from tools.local_translation_workbench.app import action_router as action_router_module
    from tools.local_translation_workbench.app.providers.router import ResolvedProviderProfile

    monkeypatch.setattr(
        action_router_module,
        "build_provider_from_profile",
        lambda session, config, model_profile_id: ResolvedProviderProfile(
            provider=FakeProvider(prefix="cli-provider"),
            profile_key=str(model_profile_id or "profile-cli-provider"),
            model_name="resolved-cli-provider-model",
        ),
    )
    try:
        exit_code = main(
            [
                "-Action",
                "stage.run",
                "-ProjectId",
                str(project_id),
                "-Stage",
                "translation",
                "-ScopeType",
                "all",
                "-ModelProfileId",
                "profile-conflict",
                "-RequestId",
                request_id_factory("stage-conflict-run"),
            ]
        )
        payload = json.loads(capsys.readouterr().err)

        assert exit_code == 1
        assert payload["ok"] is False
        assert payload["error"]["code"] == "conflict_error"
    finally:
        leases.release(project_id=project_id, lease_owner="agent-a", lease_token=lease.lease_token)


def test_translation_rerun_marks_previous_review_and_export_stale(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_translation_review_and_export(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    rerun_result = TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=FakeProvider(prefix="rerun-provider"),
    ).run(
        request_id=request_id_factory("stage-conflict-translation-rerun"),
        project_id=project_id,
        scope={"type": "all"},
        model_profile_id="profile-rerun",
    )

    assert rerun_result.translated_segments == 2
    assert len(rerun_result.active_version_ids) == 2

    review_runs = db_session.execute(
        select(ReviewRun).where(ReviewRun.project_id == project_id).order_by(ReviewRun.id.asc())
    ).scalars().all()
    export_runs = db_session.execute(
        select(ExportRun).where(ExportRun.project_id == project_id).order_by(ExportRun.id.asc())
    ).scalars().all()

    assert len(review_runs) == 1
    assert len(export_runs) == 1
    assert review_runs[0].status == "stale"
    assert export_runs[0].status == "stale"

    review_inspect = ReviewService(db_session).inspect(project_id=project_id)
    export_inspect = ExportService(db_session, base_data_dir=project_workspace).inspect(project_id=project_id)

    assert review_inspect["runs"][0]["status"] == "stale"
    assert export_inspect["runs"][0]["status"] == "stale"


def test_cli_stage_run_resume_requires_previous_incomplete_run(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    from tools.local_translation_workbench.app import action_router as action_router_module
    from tools.local_translation_workbench.app.providers.router import ResolvedProviderProfile

    monkeypatch.setattr(
        action_router_module,
        "build_provider_from_profile",
        lambda session, config, model_profile_id: ResolvedProviderProfile(
            provider=FakeProvider(prefix="resume-cli"),
            profile_key=str(model_profile_id or "profile-resume-cli"),
            model_name="resolved-resume-cli-model",
        ),
    )

    exit_code = main(
        [
            "-Action",
            "stage.run",
            "-ProjectId",
            str(project_id),
            "-Stage",
            "translation",
            "-ScopeType",
            "all",
            "-Resume",
            "-ModelProfileId",
            "profile-resume-cli",
            "-RequestId",
            request_id_factory("stage-resume-cli"),
        ]
    )
    payload = json.loads(capsys.readouterr().err)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_arguments"
    assert "resume" in payload["error"]["message"]


def test_stage_service_resume_records_failed_run_and_retries_successfully(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    with pytest.raises(ToolError) as exc:
        StageService(
            db_session,
            base_data_dir=project_workspace,
            provider=FailingProvider(),
        ).run(
            StageCommand(
                request_id=request_id_factory("stage-resume-failed"),
                project_id=project_id,
                stage="translation",
                scope={"type": "all"},
                model_profile_id="profile-failed",
                workflow_key="translation_single_llm_v1",
            )
        )

    assert exc.value.code == "provider_error"
    db_session.rollback()

    failed_runs = db_session.execute(
        select(StageRun)
        .where(StageRun.project_id == project_id, StageRun.stage == "translation")
        .order_by(StageRun.id.asc())
    ).scalars().all()
    assert len(failed_runs) == 1
    assert failed_runs[0].status == "failed"

    resume_provider = FakeProvider(prefix="resume-provider")
    result = StageService(
        db_session,
        base_data_dir=project_workspace,
        provider=resume_provider,
    ).run(
        StageCommand(
            request_id=request_id_factory("stage-resume-success"),
            project_id=project_id,
            stage="translation",
            scope={"type": "all"},
            model_profile_id="profile-resume-success",
            workflow_key="translation_single_llm_v1",
            resume=True,
        )
    )

    assert result.translated_segments == 2
    assert len(resume_provider.calls) == 4

    stage_runs = db_session.execute(
        select(StageRun)
        .where(StageRun.project_id == project_id, StageRun.stage == "translation")
        .order_by(StageRun.id.asc())
    ).scalars().all()
    assert len(stage_runs) == 2
    assert stage_runs[0].status == "failed"
    assert stage_runs[1].status == "completed"

    summary = json.loads(stage_runs[1].summary)
    assert summary["resume"] is True
    assert summary["resume_from_run_id"] == stage_runs[0].id


def test_stage_service_resume_auto_finalizes_existing_translation_drafts(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    synopsis = ProjectSynopsisRepository(db_session).ensure(project_id)
    synopsis.source_synopsis_text = "Source synopsis"
    synopsis.source_synopsis_status = "ready"
    synopsis.source_synopsis_origin = "manual"
    synopsis.target_synopsis_text = "Target synopsis"
    synopsis.target_synopsis_status = "ready"
    synopsis.target_synopsis_origin = "manual"

    failed_stage_run = StageRun(
        project_id=project_id,
        stage="translation",
        scope_type="all",
        scope_value=json.dumps({"type": "all"}, ensure_ascii=False),
        status="failed",
        summary=json.dumps(
            {
                "request_id": "translation-draft-only-request",
                "model_profile_id": "profile-draft-only",
                "workflow_key": "translation_single_llm_v1",
                "error": {"code": "system_error", "message": "interrupted before finalize"},
            },
            ensure_ascii=False,
        ),
    )
    db_session.add(failed_stage_run)
    db_session.flush()
    workflow_run = WorkflowRun(
        workflow_key="translation_single_llm_v1",
        project_id=project_id,
        stage="translation",
        scope_type="all",
        scope_value=json.dumps({"type": "all"}, ensure_ascii=False),
        request_id="translation-draft-only-request",
        status="failed",
        summary=json.dumps(
            {
                "request_id": "translation-draft-only-request",
                "stage_run_id": failed_stage_run.id,
                "error": "interrupted before finalize",
            },
            ensure_ascii=False,
        ),
    )
    db_session.add(workflow_run)
    db_session.flush()
    generate_step = WorkflowStepRun(
        workflow_run_id=workflow_run.id,
        step_key="generate_primary",
        action="translation.generate_draft",
        llm_role="translator",
        model_profile_id="profile-draft-only",
        status="completed",
        input_ref=json.dumps({"project_id": project_id}, ensure_ascii=False),
        output_payload={"translated_segments": 2},
        summary=None,
    )
    db_session.add(generate_step)
    db_session.flush()

    rows = db_session.execute(
        select(Chapter, ChapterSegment)
        .join(ChapterSegment, ChapterSegment.chapter_id == Chapter.id)
        .where(Chapter.project_id == project_id)
        .order_by(Chapter.chapter_index.asc(), ChapterSegment.segment_index.asc())
    ).all()
    workflow_repo = TranslationWorkflowRepository(db_session)
    for chapter, segment in rows:
        workflow_repo.create_draft_version(
            workflow_run_id=workflow_run.id,
            project_id=project_id,
            segment_id=segment.id,
            step_run_id=generate_step.id,
            parent_draft_id=None,
            draft_role="primary",
            source_hash="a" * 64,
            glossary_snapshot_id="b" * 64,
            provider_name="recovered-provider",
            model_profile_id="profile-draft-only",
            model_name="model-draft-only",
            translated_text=f"Recovered chapter {chapter.chapter_index}",
            translated_text_path=f"draft-{segment.id}.txt",
            status="completed",
            evidence_payload={"chapter_index": int(chapter.chapter_index), "fallback_depth": 0},
        )
    db_session.commit()

    resume_provider = FakeProvider(prefix="resume-should-not-call-llm")
    result = StageService(
        db_session,
        base_data_dir=project_workspace,
        provider=resume_provider,
    ).run(
        StageCommand(
            request_id=request_id_factory("stage-resume-auto-finalize"),
            project_id=project_id,
            stage="translation",
            scope={"type": "all"},
            model_profile_id="profile-resume-auto-finalize",
            workflow_key="translation_single_llm_v1",
            resume=True,
        )
    )

    workflow_steps = db_session.execute(
        select(WorkflowStepRun)
        .where(WorkflowStepRun.workflow_run_id == workflow_run.id)
        .order_by(WorkflowStepRun.id.asc())
    ).scalars().all()
    stage_runs = db_session.execute(
        select(StageRun)
        .where(StageRun.project_id == project_id, StageRun.stage == "translation")
        .order_by(StageRun.id.asc())
    ).scalars().all()

    assert result.translated_segments == 2
    assert len(result.active_version_ids) == 2
    assert resume_provider.calls == []
    assert db_session.get(WorkflowRun, workflow_run.id).status == "completed"
    assert [step.step_key for step in workflow_steps] == ["generate_primary", "finalize_segments"]
    assert workflow_steps[-1].status == "completed"
    assert stage_runs[-1].status == "completed"
    assert json.loads(stage_runs[-1].summary)["workflow_run_id"] == workflow_run.id


def test_stage_service_completed_run_summary_includes_timing_metadata(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    result = StageService(
        db_session,
        base_data_dir=project_workspace,
        provider=FakeProvider(prefix="timing-provider"),
    ).run(
        StageCommand(
            request_id=request_id_factory("stage-summary-timing"),
            project_id=project_id,
            stage="translation",
            scope={"type": "all"},
            model_profile_id="profile-summary-timing",
            workflow_key="translation_single_llm_v1",
        )
    )

    assert result.translated_segments == 2

    stage_run = db_session.execute(
        select(StageRun)
        .where(StageRun.project_id == project_id, StageRun.stage == "translation")
        .order_by(StageRun.id.desc())
    ).scalar_one()

    summary = json.loads(stage_run.summary)
    assert summary["started_at"]
    assert summary["finished_at"]
    assert isinstance(summary["duration_ms"], int)
    assert summary["duration_ms"] >= 0


def test_stage_service_keeps_lease_alive_during_translation(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    spy_leases = SpyLeaseService()
    service = StageService(
        db_session,
        base_data_dir=project_workspace,
        provider=FakeProvider(prefix="lease-refresh"),
    )
    service.leases = spy_leases

    result = service.run(
        StageCommand(
            request_id=request_id_factory("stage-lease-refresh"),
            project_id=project_id,
            stage="translation",
            scope={"type": "all"},
            model_profile_id="profile-lease-refresh",
        )
    )

    assert result.translated_segments == 2
    assert spy_leases.acquire_calls
    assert len(spy_leases.refresh_calls) >= 2
    assert spy_leases.release_calls


def test_stage_service_resume_after_process_level_interruption(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    crashing_service = StageService(
        db_session,
        base_data_dir=project_workspace,
        provider=FakeProvider(prefix="crash-provider"),
    )

    def crash_dispatch(*, project, command, stage_run_id, heartbeat):  # type: ignore[no-untyped-def]
        raise SystemExit("simulate-process-crash")

    monkeypatch.setattr(crashing_service, "_dispatch", crash_dispatch)

    with pytest.raises(SystemExit):
        crashing_service.run(
            StageCommand(
                request_id=request_id_factory("stage-crash"),
                project_id=project_id,
                stage="translation",
                scope={"type": "all"},
                model_profile_id="profile-crash",
                workflow_key="translation_single_llm_v1",
            )
        )

    db_session.rollback()
    stage_runs = db_session.execute(
        select(StageRun)
        .where(StageRun.project_id == project_id, StageRun.stage == "translation")
        .order_by(StageRun.id.asc())
    ).scalars().all()
    assert len(stage_runs) == 1
    assert stage_runs[0].status == "running"

    resume_provider = FakeProvider(prefix="resume-after-crash")
    resume_result = StageService(
        db_session,
        base_data_dir=project_workspace,
        provider=resume_provider,
    ).run(
        StageCommand(
            request_id=request_id_factory("stage-resume-after-crash"),
            project_id=project_id,
            stage="translation",
            scope={"type": "all"},
            model_profile_id="profile-resume-after-crash",
            workflow_key="translation_single_llm_v1",
            resume=True,
        )
    )

    assert resume_result.translated_segments == 2
    refreshed_stage_runs = db_session.execute(
        select(StageRun)
        .where(StageRun.project_id == project_id, StageRun.stage == "translation")
        .order_by(StageRun.id.asc())
    ).scalars().all()
    assert len(refreshed_stage_runs) == 2
    assert refreshed_stage_runs[0].status == "running"
    assert refreshed_stage_runs[1].status == "completed"


def test_glossary_rerun_marks_translations_stale_and_stale_only_scope_retranslates_only_stale_segments(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_glossary_terms(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    GlossaryService(db_session, provider=FakeProvider(prefix="glossary-stale-initial")).run(
        request_id=request_id_factory("stage-stale-glossary-first"),
        project_id=project_id,
        scope={"type": "all"},
        model_profile_id="profile-stale-glossary-first",
    )
    TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=FakeProvider(prefix="stale-initial"),
    ).run(
        request_id=request_id_factory("stage-stale-translation-first"),
        project_id=project_id,
        scope={"type": "all"},
        model_profile_id="profile-stale-initial",
    )

    GlossaryService(db_session, provider=FakeProvider(prefix="glossary-stale-rerun")).run(
        request_id=request_id_factory("stage-stale-glossary-rerun"),
        project_id=project_id,
        scope={"type": "chapter_list", "chapters": [1]},
        model_profile_id="profile-stale-glossary-rerun",
    )

    segment_rows = db_session.execute(
        select(Chapter.chapter_index, ChapterSegment.translation_status)
        .join(ChapterSegment, ChapterSegment.chapter_id == Chapter.id)
        .where(Chapter.project_id == project_id)
        .order_by(Chapter.chapter_index.asc())
    ).all()
    assert segment_rows == [(1, "stale"), (2, "translated")]

    stale_provider = FakeProvider(prefix="stale-rerun")
    rerun_result = TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=stale_provider,
    ).run(
        request_id=request_id_factory("stage-stale-translation-rerun"),
        project_id=project_id,
        scope={"type": "stale_only"},
        model_profile_id="profile-stale-rerun",
    )

    assert rerun_result.translated_segments == 1
    assert len(stale_provider.calls) == 1


def test_review_rerun_marks_previous_export_stale(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_translation_review_and_export(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    rerun_result = ReviewService(db_session).run(
        request_id=request_id_factory("stage-review-rerun"),
        project_id=project_id,
        scope={"type": "all"},
        review_mode="hard_only",
    )

    assert rerun_result.run_id >= 1

    export_runs = db_session.execute(
        select(ExportRun).where(ExportRun.project_id == project_id).order_by(ExportRun.id.asc())
    ).scalars().all()
    assert len(export_runs) == 1
    assert export_runs[0].status == "stale"


def test_chaptering_rerun_marks_previous_review_and_export_stale(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_translation_review_and_export(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    project = db_session.get(TranslationProject, project_id)
    assert project is not None

    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("stage-chaptering-rerun"),
        project_id=project_id,
        source_file_path=Path(project.source_path),
        scope={"type": "all"},
    )

    review_runs = db_session.execute(
        select(ReviewRun).where(ReviewRun.project_id == project_id).order_by(ReviewRun.id.asc())
    ).scalars().all()
    export_runs = db_session.execute(
        select(ExportRun).where(ExportRun.project_id == project_id).order_by(ExportRun.id.asc())
    ).scalars().all()

    assert len(review_runs) == 1
    assert len(export_runs) == 1
    assert review_runs[0].status == "stale"
    assert export_runs[0].status == "stale"


def test_lease_service_returns_token_and_keeps_single_project_lease_row(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    leases = LeaseService(db_session)
    first = leases.acquire(project_id=project_id, lease_owner="agent-a", ttl_seconds=300)
    second = leases.acquire(project_id=project_id, lease_owner="agent-a", ttl_seconds=300)

    assert first.project_id == project_id
    assert second.project_id == project_id
    assert first.lease_token
    assert second.lease_token
    assert first.lease_token != second.lease_token

    active_leases = db_session.execute(
        select(ProjectLease).where(ProjectLease.project_id == project_id).order_by(ProjectLease.id.asc())
    ).scalars().all()
    assert len(active_leases) == 1


def test_stage_run_rejects_cross_stage_writer_when_request_id_reused(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    capsys,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    shared_request_id = request_id_factory("stage-cross-lock")
    leases = LeaseService(db_session)
    lease = leases.acquire(
        project_id=project_id,
        lease_owner=f"stage.run:{shared_request_id}",
        ttl_seconds=300,
    )

    try:
        exit_code = main(
            [
                "-Action",
                "stage.run",
                "-ProjectId",
                str(project_id),
                "-Stage",
                "review",
                "-ScopeType",
                "all",
                "-RequestId",
                shared_request_id,
                "-ReviewMode",
                "hard_only",
            ]
        )
        payload = json.loads(capsys.readouterr().err)

        assert exit_code == 1
        assert payload["ok"] is False
        assert payload["error"]["code"] == "conflict_error"
    finally:
        leases.release(
            project_id=project_id,
            lease_owner=f"stage.run:{shared_request_id}",
            lease_token=lease.lease_token,
        )


def test_lease_release_requires_matching_token_to_preserve_newer_lease(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    leases = LeaseService(db_session)
    first = leases.acquire(project_id=project_id, lease_owner="agent-a", ttl_seconds=300)
    second = leases.acquire(project_id=project_id, lease_owner="agent-a", ttl_seconds=300)

    released = leases.release(
        project_id=project_id,
        lease_owner="agent-a",
        lease_token=first.lease_token,
    )

    assert released is False
    active_leases = db_session.execute(
        select(ProjectLease).where(ProjectLease.project_id == project_id).order_by(ProjectLease.id.asc())
    ).scalars().all()
    assert len(active_leases) == 1
    assert active_leases[0].lease_token == second.lease_token


def test_lease_acquire_translates_unique_conflict_to_conflict_error(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    def raise_integrity_error() -> None:
        raise IntegrityError("insert into ltw_project_leases ...", {}, Exception("duplicate"))

    monkeypatch.setattr(db_session, "commit", raise_integrity_error)

    with pytest.raises(ToolError) as exc:
        LeaseService(db_session).acquire(project_id=project_id, lease_owner="agent-a", ttl_seconds=300)

    assert exc.value.code == "conflict_error"


@pytest.mark.parametrize("stage", ["chaptering", "glossary", "review", "export"])
def test_stage_run_rejects_stale_only_for_unsupported_stages(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    if stage == "translation":
        from tools.local_translation_workbench.app import action_router as action_router_module

        monkeypatch.setattr(action_router_module, "build_provider", lambda config: FakeProvider(prefix="stale-only"))

    exit_code = main(
        [
            "-Action",
            "stage.run",
            "-ProjectId",
            str(project_id),
            "-Stage",
            stage,
            "-ScopeType",
            "stale_only",
            "-RequestId",
            request_id_factory(f"stage-stale-only-{stage}"),
        ]
    )
    payload = json.loads(capsys.readouterr().err)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_arguments"
    assert "stale_only" in payload["error"]["message"]


@pytest.mark.parametrize("stage", ["chaptering", "glossary", "review", "export"])
def test_stage_run_rejects_failed_only_for_unsupported_stages(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    capsys,
    stage: str,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    exit_code = main(
        [
            "-Action",
            "stage.run",
            "-ProjectId",
            str(project_id),
            "-Stage",
            stage,
            "-ScopeType",
            "failed_only",
            "-RequestId",
            request_id_factory(f"stage-failed-only-{stage}"),
        ]
    )
    payload = json.loads(capsys.readouterr().err)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_arguments"
    assert "failed_only" in payload["error"]["message"]


@pytest.mark.parametrize("stage", ["chaptering", "glossary", "export"])
def test_stage_run_rejects_missing_only_for_unsupported_stages(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    capsys,
    stage: str,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    exit_code = main(
        [
            "-Action",
            "stage.run",
            "-ProjectId",
            str(project_id),
            "-Stage",
            stage,
            "-ScopeType",
            "missing_only",
            "-RequestId",
            request_id_factory(f"stage-missing-only-{stage}"),
        ]
    )
    payload = json.loads(capsys.readouterr().err)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_arguments"
    assert "missing_only" in payload["error"]["message"]


@pytest.mark.parametrize("stage", ["chaptering", "glossary", "review", "export"])
def test_stage_service_rejects_stale_only_for_unsupported_stages(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    stage: str,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    with pytest.raises(ToolError) as exc:
        StageService(
            db_session,
            base_data_dir=project_workspace,
        ).run(
            StageCommand(
                request_id=request_id_factory(f"stage-service-stale-only-{stage}"),
                project_id=project_id,
                stage=stage,
                scope={"type": "stale_only"},
            )
        )

    assert exc.value.code == "invalid_arguments"
    assert "stale_only" in exc.value.message


@pytest.mark.parametrize("stage", ["chaptering", "glossary", "review", "export"])
def test_stage_service_rejects_failed_only_for_unsupported_stages(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    stage: str,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    with pytest.raises(ToolError) as exc:
        StageService(
            db_session,
            base_data_dir=project_workspace,
        ).run(
            StageCommand(
                request_id=request_id_factory(f"stage-service-failed-only-{stage}"),
                project_id=project_id,
                stage=stage,
                scope={"type": "failed_only"},
            )
        )

    assert exc.value.code == "invalid_arguments"
    assert "failed_only" in exc.value.message


@pytest.mark.parametrize("stage", ["chaptering", "glossary", "export"])
def test_stage_service_rejects_missing_only_for_unsupported_stages(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    stage: str,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    with pytest.raises(ToolError) as exc:
        StageService(
            db_session,
            base_data_dir=project_workspace,
        ).run(
            StageCommand(
                request_id=request_id_factory(f"stage-service-missing-only-{stage}"),
                project_id=project_id,
                stage=stage,
                scope={"type": "missing_only"},
            )
        )

    assert exc.value.code == "invalid_arguments"
    assert "missing_only" in exc.value.message


@pytest.mark.parametrize("stage", ["chaptering", "glossary", "review", "export"])
def test_direct_stage_services_reject_stale_only_scope(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    stage: str,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    project = db_session.get(TranslationProject, project_id)
    assert project is not None

    with pytest.raises(ToolError) as exc:
        if stage == "chaptering":
            ChapteringService(db_session, base_data_dir=project_workspace).run(
                request_id=request_id_factory("direct-stage-stale-only-chaptering"),
                project_id=project_id,
                source_file_path=Path(project.source_path),
                scope={"type": "stale_only"},
            )
        elif stage == "glossary":
            GlossaryService(db_session).run(
                request_id=request_id_factory("direct-stage-stale-only-glossary"),
                project_id=project_id,
                scope={"type": "stale_only"},
            )
        elif stage == "review":
            ReviewService(db_session).run(
                request_id=request_id_factory("direct-stage-stale-only-review"),
                project_id=project_id,
                scope={"type": "stale_only"},
            )
        else:
            ExportService(db_session, base_data_dir=project_workspace).run(
                request_id=request_id_factory("direct-stage-stale-only-export"),
                project_id=project_id,
                scope={"type": "stale_only"},
            )

    assert exc.value.code == "invalid_arguments"
    assert "stale_only" in exc.value.message


@pytest.mark.parametrize("stage", ["chaptering", "glossary", "review", "export"])
def test_direct_stage_services_reject_failed_only_scope(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    stage: str,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    project = db_session.get(TranslationProject, project_id)
    assert project is not None

    with pytest.raises(ToolError) as exc:
        if stage == "chaptering":
            ChapteringService(db_session, base_data_dir=project_workspace).run(
                request_id=request_id_factory("direct-stage-failed-only-chaptering"),
                project_id=project_id,
                source_file_path=Path(project.source_path),
                scope={"type": "failed_only"},
            )
        elif stage == "glossary":
            GlossaryService(db_session).run(
                request_id=request_id_factory("direct-stage-failed-only-glossary"),
                project_id=project_id,
                scope={"type": "failed_only"},
            )
        elif stage == "review":
            ReviewService(db_session).run(
                request_id=request_id_factory("direct-stage-failed-only-review"),
                project_id=project_id,
                scope={"type": "failed_only"},
            )
        else:
            ExportService(db_session, base_data_dir=project_workspace).run(
                request_id=request_id_factory("direct-stage-failed-only-export"),
                project_id=project_id,
                scope={"type": "failed_only"},
            )

    assert exc.value.code == "invalid_arguments"
    assert "failed_only" in exc.value.message


@pytest.mark.parametrize("stage", ["chaptering", "glossary", "export"])
def test_direct_stage_services_reject_missing_only_scope(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    stage: str,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    project = db_session.get(TranslationProject, project_id)
    assert project is not None

    with pytest.raises(ToolError) as exc:
        if stage == "chaptering":
            ChapteringService(db_session, base_data_dir=project_workspace).run(
                request_id=request_id_factory("direct-stage-missing-only-chaptering"),
                project_id=project_id,
                source_file_path=Path(project.source_path),
                scope={"type": "missing_only"},
            )
        elif stage == "glossary":
            GlossaryService(db_session).run(
                request_id=request_id_factory("direct-stage-missing-only-glossary"),
                project_id=project_id,
                scope={"type": "missing_only"},
            )
        else:
            ExportService(db_session, base_data_dir=project_workspace).run(
                request_id=request_id_factory("direct-stage-missing-only-export"),
                project_id=project_id,
                scope={"type": "missing_only"},
            )

    assert exc.value.code == "invalid_arguments"
    assert "missing_only" in exc.value.message
