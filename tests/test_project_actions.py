from __future__ import annotations

from pathlib import Path

import json
import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from tools.local_translation_workbench.app.action_router import route_action
from tools.local_translation_workbench.app.cli import main
from tools.local_translation_workbench.app.config import load_config
from tools.local_translation_workbench.app.db.models import (
    OperationRequest,
    ProjectSynopsis,
    StageRun,
    TranslationProject,
    WorkflowRun,
    WorkflowStepRun,
)
from tools.local_translation_workbench.app.providers.base import TextGenerationResult
from tools.local_translation_workbench.app.repositories.projects import ProjectService


def _assert_project_directories(project_root: Path) -> None:
    assert (project_root / "source").is_dir()
    assert (project_root / "translation").is_dir()
    assert (project_root / "artifacts").is_dir()


class FakeProvider:
    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        prompt_text = str(prompt)
        if "术语抽取器" in prompt_text:
            return TextGenerationResult(
                content='{"extraction_status":"no_new_terms","terms":[],"reason":"fake no new terms"}',
                provider_name="project-actions-fake",
                model_name=model_name,
            )
        if "小说翻译质检员" in prompt_text:
            return TextGenerationResult(
                content='{"passed":true,"issues":[]}',
                provider_name="project-actions-fake",
                model_name=model_name,
            )
        source_text = prompt_text.split("\n\n", maxsplit=1)[-1]
        return TextGenerationResult(
            content=f"[{model_name}] {source_text}",
            provider_name="project-actions-fake",
            model_name=model_name,
        )


class FakeGlossaryWorkflowProvider:
    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        prompt_text = str(prompt)
        if "术语抽取器" in prompt_text:
            content = json.dumps(
                {
                    "extraction_status": "terms_found",
                    "terms": [
                        {
                            "source_term": "林溪",
                            "translated_term": "Lin Xi",
                            "category": "character",
                            "note": "主角名",
                        }
                    ],
                    "reason": "fake extraction",
                },
                ensure_ascii=False,
            )
        elif "关系审核器" in prompt_text:
            content = json.dumps(
                {
                    "items": [
                        {
                            "draft_candidate_id": 1,
                            "term_group_key": "char-linxi",
                            "relation_role": "canonical",
                            "score": 0.98,
                            "reason_codes": ["same_entity"],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        elif "scope 审核器" in prompt_text:
            content = json.dumps(
                {
                    "items": [
                        {
                            "draft_candidate_id": 1,
                            "scope_level": "project_term",
                            "scope_chapter_id": None,
                            "score": 0.95,
                            "reason_codes": ["cross_chapter_reuse"],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        elif "终审器" in prompt_text:
            content = json.dumps(
                {
                    "terms": [
                        {
                            "source_term": "林溪",
                            "target_term": "Lin Xi",
                            "category": "character",
                            "note": "主角名",
                            "term_group_key": "char-linxi",
                            "relation_role": "canonical",
                            "scope_level": "project_term",
                            "scope_chapter_id": None,
                        }
                    ]
                },
                ensure_ascii=False,
            )
        else:
            content = '{"items":[]}'
        return TextGenerationResult(
            content=content,
            provider_name="project-actions-glossary-workflow-fake",
            model_name=model_name,
        )


def test_create_project_creates_project_row_and_directories(
    database_url: str,
    project_workspace: Path,
    db_session: Session,
    request_id_factory: callable,
) -> None:
    request_id = request_id_factory("create")
    service = ProjectService(database_url)

    project = service.create_project(
        request_id=request_id,
        source_path="D:/inputs/source.txt",
        source_language="ja",
        target_language="zh-CN",
    )

    config = load_config()
    project_root = config.data_dir / project.project_key

    assert project.id is not None
    assert project.request_id == request_id
    assert project.source_path == "D:/inputs/source.txt"
    assert project.source_language == "ja"
    assert project.target_language == "zh-CN"
    assert project.project_key
    assert project_root == project_workspace / project.project_key
    _assert_project_directories(project_root)

    stored_project = db_session.execute(
        select(TranslationProject).where(TranslationProject.id == project.id)
    ).scalar_one()
    stored_synopsis = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project.id)
    ).scalar_one()
    assert stored_project.request_id == request_id
    assert stored_project.project_key == project.project_key
    assert stored_project.source_path == "D:/inputs/source.txt"
    assert stored_project.source_language == "ja"
    assert stored_project.target_language == "zh-CN"
    assert stored_synopsis.source_synopsis_status == "missing"
    assert stored_synopsis.target_synopsis_status == "missing"
    assert stored_synopsis.source_synopsis_text is None
    assert stored_synopsis.target_synopsis_text is None


def test_create_project_is_idempotent_for_same_request_id(
    database_url: str,
    project_workspace: Path,
    db_session: Session,
    request_id_factory: callable,
) -> None:
    request_id = request_id_factory("idempotent")
    service = ProjectService(database_url)

    first = service.create_project(
        request_id=request_id,
        source_path="D:/inputs/source.txt",
        source_language="ja",
        target_language="zh-CN",
    )
    second = service.create_project(
        request_id=request_id,
        source_path="D:/inputs/other.txt",
        source_language="en",
        target_language="fr",
    )

    assert first.id == second.id
    assert first.project_key == second.project_key
    assert second.source_path == "D:/inputs/source.txt"
    assert second.source_language == "ja"
    assert second.target_language == "zh-CN"
    _assert_project_directories(project_workspace / first.project_key)

    project_count = db_session.execute(
        select(func.count()).select_from(TranslationProject).where(
            TranslationProject.request_id == request_id
        )
    ).scalar_one()
    operation_count = db_session.execute(
        select(func.count()).select_from(OperationRequest).where(
            OperationRequest.request_id == request_id,
            OperationRequest.operation_name == "project.create",
        )
    ).scalar_one()

    assert project_count == 1
    assert operation_count == 1


def test_create_project_uses_explicit_database_url(
    database_url: str,
    db_session: Session,
    monkeypatch,
    request_id_factory: callable,
) -> None:
    request_id = request_id_factory("explicit-db")
    service = ProjectService(database_url)
    monkeypatch.setenv("LTW_DATABASE_URL", "mysql+pymysql://invalid:invalid@127.0.0.1:3306/invalid")

    project = service.create_project(
        request_id=request_id,
        source_path="D:/inputs/source.txt",
        source_language="ja",
        target_language="zh-CN",
    )

    stored_project = db_session.execute(
        select(TranslationProject).where(TranslationProject.id == project.id)
    ).scalar_one()
    assert stored_project.request_id == request_id


def test_create_project_recovers_from_existing_project_row_when_request_conflicts(
    database_url: str,
    db_session: Session,
    request_id_factory: callable,
) -> None:
    request_id = request_id_factory("conflict")
    project = TranslationProject(
        request_id=request_id,
        project_key=request_id.replace("pytest-", "prj-"),
        source_path="D:/inputs/source.txt",
        source_language="ja",
        target_language="zh-CN",
        status="created",
    )
    db_session.add(project)
    db_session.commit()

    service = ProjectService(database_url)
    result = service.create_project(
        request_id=request_id,
        source_path="D:/inputs/other.txt",
        source_language="en",
        target_language="fr",
    )

    project_count = db_session.execute(
        select(func.count()).select_from(TranslationProject).where(
            TranslationProject.request_id == request_id
        )
    ).scalar_one()
    operation_count = db_session.execute(
        select(func.count()).select_from(OperationRequest).where(
            OperationRequest.request_id == request_id,
            OperationRequest.operation_name == "project.create",
        )
    ).scalar_one()

    assert result.id == project.id
    assert result.source_path == "D:/inputs/source.txt"
    assert project_count == 1
    assert operation_count == 1


def test_initial_schema_sets_updated_at_mysql_on_update_clause() -> None:
    migration_file = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0001_initial_schema.py"
    migration_source = migration_file.read_text(encoding="utf-8")

    assert "CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP" in migration_source


def test_cli_inspect_project_returns_project_summary(
    database_url: str,
    request_id_factory: callable,
    capsys,
) -> None:
    request_id = request_id_factory("inspect-project")
    service = ProjectService(database_url)
    project = service.create_project(
        request_id=request_id,
        source_path="D:/inputs/source.txt",
        source_language="ja",
        target_language="zh-CN",
    )

    exit_code = main(
        [
            "-Action",
            "inspect.project",
            "-ProjectId",
            str(project.id),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["action"] == "inspect.project"
    assert payload["data"]["project"]["id"] == project.id
    assert payload["data"]["project"]["project_key"] == project.project_key


def test_cli_project_list_returns_projects(
    database_url: str,
    request_id_factory: callable,
    capsys,
) -> None:
    service = ProjectService(database_url)
    project = service.create_project(
        request_id=request_id_factory("project-list"),
        source_path="D:/inputs/source.txt",
        source_language="ja",
        target_language="zh-CN",
    )

    exit_code = main(["-Action", "project.list"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["action"] == "project.list"
    assert any(item["id"] == project.id for item in payload["data"]["projects"])


def test_cli_project_cancel_marks_cancelled_and_blocks_stage_run(
    database_url: str,
    db_session: Session,
    request_id_factory: callable,
    capsys,
) -> None:
    service = ProjectService(database_url)
    project = service.create_project(
        request_id=request_id_factory("project-cancel"),
        source_path="D:/inputs/source.txt",
        source_language="ja",
        target_language="zh-CN",
    )

    exit_code = main(
        [
            "-Action",
            "project.cancel",
            "-ProjectId",
            str(project.id),
            "-RequestId",
            request_id_factory("project-cancel-action"),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["action"] == "project.cancel"
    assert payload["data"]["status"] == "cancelled"

    stored_project = db_session.execute(
        select(TranslationProject).where(TranslationProject.id == project.id)
    ).scalar_one()
    assert stored_project.status == "cancelled"

    exit_code = main(
        [
            "-Action",
            "stage.run",
            "-ProjectId",
            str(project.id),
            "-Stage",
            "chaptering",
            "-ScopeType",
            "all",
            "-RequestId",
            request_id_factory("project-cancel-stage-run"),
        ]
    )
    error_payload = json.loads(capsys.readouterr().err)

    assert exit_code == 1
    assert error_payload["error"]["code"] == "conflict_error"
    assert "cancelled" in error_payload["error"]["message"]


def test_cli_project_run_full_runs_stage_sequence(
    database_url: str,
    project_workspace: Path,
    db_session: Session,
    request_id_factory: callable,
    monkeypatch,
    capsys,
) -> None:
    source_file = project_workspace / "project-run-full-source.txt"
    source_file.write_text(
        "第1章 开始\n第一段。\n\n第2章 继续\n第二段。",
        encoding="utf-8",
    )

    service = ProjectService(database_url)
    project = service.create_project(
        request_id=request_id_factory("project-run-full"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    from tools.local_translation_workbench.app import action_router as action_router_module
    from tools.local_translation_workbench.app.providers.router import ResolvedProviderProfile

    monkeypatch.setattr(
        action_router_module,
        "build_provider_from_profile",
        lambda session, config, model_profile_id: ResolvedProviderProfile(
            provider=FakeProvider(),
            profile_key=str(model_profile_id or "profile-run-full"),
            model_name="resolved-run-full-model",
        ),
    )

    exit_code = main(
        [
            "-Action",
            "project.run_full",
            "-ProjectId",
            str(project.id),
            "-RequestId",
            request_id_factory("project-run-full-action"),
            "-ModelProfileId",
            "profile-run-full",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["action"] == "project.run_full"
    assert payload["data"]["project_id"] == project.id
    assert payload["data"]["stages"] == [
        "chaptering",
        "glossary",
        "translation",
        "review",
        "export",
    ]

    stage_runs = db_session.execute(
        select(StageRun).where(StageRun.project_id == project.id).order_by(StageRun.id.asc())
    ).scalars().all()
    assert [item.stage for item in stage_runs] == [
        "chaptering",
        "glossary",
        "translation",
        "review",
        "export",
    ]


def test_cli_stage_inspect_runs_returns_filtered_runs(
    database_url: str,
    project_workspace: Path,
    request_id_factory: callable,
    capsys,
) -> None:
    source_file = project_workspace / "inspect-runs-source.txt"
    source_file.write_text(
        "第1章 开始\n第一段。",
        encoding="utf-8",
    )

    service = ProjectService(database_url)
    project = service.create_project(
        request_id=request_id_factory("inspect-runs-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    exit_code = main(
        [
            "-Action",
            "stage.run",
            "-ProjectId",
            str(project.id),
            "-Stage",
            "chaptering",
            "-ScopeType",
            "all",
            "-RequestId",
            request_id_factory("inspect-runs-stage"),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True

    exit_code = main(
        [
            "-Action",
            "stage.inspect_runs",
            "-ProjectId",
            str(project.id),
            "-Stage",
            "chaptering",
            "-Limit",
            "1",
        ]
    )
    inspect_payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert inspect_payload["ok"] is True
    assert inspect_payload["action"] == "stage.inspect_runs"
    assert len(inspect_payload["data"]["runs"]) == 1
    run = inspect_payload["data"]["runs"][0]
    assert run["stage"] == "chaptering"
    assert isinstance(run["summary"], dict)
    assert str(run["summary"]["request_id"]).startswith("pytest-")
    assert run["summary"]["chapter_count"] == 1
    assert run["diagnostics"] is None


def test_stage_inspect_runs_exposes_workflow_failed_diagnostics(
    database_url: str,
    db_session: Session,
    request_id_factory: callable,
) -> None:
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("inspect-runs-workflow-failed-project"),
        source_path="D:/inputs/source.txt",
        source_language="zh",
        target_language="en",
    )
    stage_run = StageRun(
        project_id=project.id,
        stage="translation",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":1}',
        status="failed",
        summary=json.dumps(
            {
                "request_id": "translation-failed-request",
                "model_profile_id": "profile-request",
                "workflow_key": "translation_multi_llm_v1",
                "error": {"code": "provider_error", "message": "review failed", "status": 502},
            },
            ensure_ascii=False,
        ),
    )
    db_session.add(stage_run)
    db_session.flush()

    workflow_run = WorkflowRun(
        workflow_key="translation_multi_llm_v1",
        project_id=project.id,
        stage="translation",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":1}',
        request_id="translation-failed-request",
        status="failed",
        summary=json.dumps(
            {
                "request_id": "translation-failed-request",
                "workflow_key": "translation_multi_llm_v1",
                "stage_run_id": stage_run.id,
            },
            ensure_ascii=False,
        ),
    )
    db_session.add(workflow_run)
    db_session.flush()

    db_session.add(
        WorkflowStepRun(
            workflow_run_id=workflow_run.id,
            step_key="review_drafts",
            action="translation.review_draft",
            llm_role="reviewer",
            model_profile_id="profile-review",
            status="failed",
            input_ref="segment:1",
            output_payload={"error": "review failed", "actual_model_name": "model-review"},
            summary=json.dumps({"provider_model_name": "model-review"}, ensure_ascii=False),
        )
    )
    db_session.commit()

    payload = route_action(
        {
            "action": "stage.inspect_runs",
            "project_id": str(project.id),
            "stage": "translation",
            "limit": "1",
        }
    )

    run = payload["data"]["runs"][0]
    assert run["diagnostics"]["error"]["code"] == "provider_error"
    assert run["diagnostics"]["failure_step"] == {
        "step_key": "review_drafts",
        "action": "translation.review_draft",
    }
    assert run["diagnostics"]["model_profile_id"] == "profile-review"
    assert run["diagnostics"]["model_name"] == "model-review"


def test_stage_inspect_runs_exposes_non_workflow_failed_diagnostics(
    database_url: str,
    db_session: Session,
    request_id_factory: callable,
) -> None:
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("inspect-runs-chaptering-failed-project"),
        source_path="D:/inputs/source.txt",
        source_language="zh",
        target_language="en",
    )
    db_session.add(
        StageRun(
            project_id=project.id,
            stage="chaptering",
            scope_type="all",
            scope_value='{"type":"all"}',
            status="failed",
            summary=json.dumps(
                {
                    "request_id": "chaptering-failed-request",
                    "model_profile_id": "profile-chaptering",
                    "error": {"code": "file_not_found", "message": "找不到章节源文件", "status": 404},
                },
                ensure_ascii=False,
            ),
        )
    )
    db_session.commit()

    payload = route_action(
        {
            "action": "stage.inspect_runs",
            "project_id": str(project.id),
            "stage": "chaptering",
            "limit": "1",
        }
    )

    run = payload["data"]["runs"][0]
    assert run["diagnostics"]["error"]["code"] == "file_not_found"
    assert run["diagnostics"]["failure_step"] is None
    assert run["diagnostics"]["model_profile_id"] == "profile-chaptering"
    assert run["diagnostics"]["model_name"] is None


def test_stage_inspect_runs_exposes_scope_context_and_result_for_non_workflow_stage(
    database_url: str,
    db_session: Session,
    request_id_factory: callable,
) -> None:
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("inspect-runs-base-view-project"),
        source_path="D:/inputs/source.txt",
        source_language="zh",
        target_language="en",
    )
    db_session.add(
        StageRun(
            project_id=project.id,
            stage="chaptering",
            scope_type="chapter_range",
            scope_value='{"type":"chapter_range","start":1,"end":2}',
            status="completed",
            summary=json.dumps(
                {
                    "request_id": "chaptering-base-view-request",
                    "model_profile_id": "profile-chaptering",
                    "chapter_count": 2,
                    "segment_count": 7,
                },
                ensure_ascii=False,
            ),
        )
    )
    db_session.commit()

    payload = route_action(
        {
            "action": "stage.inspect_runs",
            "project_id": str(project.id),
            "stage": "chaptering",
            "limit": "1",
        }
    )

    run = payload["data"]["runs"][0]
    assert run["scope_value"] == {"type": "chapter_range", "start": 1, "end": 2}
    assert run["context"] == {
        "request_id": "chaptering-base-view-request",
        "model_profile_id": "profile-chaptering",
        "workflow_key": None,
        "workflow_run_id": None,
    }
    assert run["result"] == {
        "chapter_count": 2,
        "segment_count": 7,
    }
    assert run["workflow"] is None


def test_stage_inspect_runs_uses_first_failed_step_when_multiple_steps_failed(
    database_url: str,
    db_session: Session,
    request_id_factory: callable,
) -> None:
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("inspect-runs-multi-failed-project"),
        source_path="D:/inputs/source.txt",
        source_language="zh",
        target_language="en",
    )
    stage_run = StageRun(
        project_id=project.id,
        stage="translation",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":1}',
        status="failed",
        summary=json.dumps(
            {
                "request_id": "translation-failed-fallback-request",
                "model_profile_id": "profile-request-fallback",
                "workflow_key": "translation_multi_llm_v1",
                "error": {"code": "workflow_quorum_failed", "message": "too many failed steps", "status": 502},
            },
            ensure_ascii=False,
        ),
    )
    db_session.add(stage_run)
    db_session.flush()

    workflow_run = WorkflowRun(
        workflow_key="translation_multi_llm_v1",
        project_id=project.id,
        stage="translation",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":1}',
        request_id="translation-failed-fallback-request",
        status="failed",
        summary=json.dumps({"request_id": "translation-failed-fallback-request"}, ensure_ascii=False),
    )
    db_session.add(workflow_run)
    db_session.flush()

    db_session.add_all(
        [
            WorkflowStepRun(
                workflow_run_id=workflow_run.id,
                step_key="generate_primary",
                action="translation.generate_draft",
                llm_role="translator",
                model_profile_id="profile-primary",
                status="failed",
                input_ref="segment:1",
                output_payload={"error": "primary failed", "actual_model_name": "model-primary"},
                summary=None,
            ),
            WorkflowStepRun(
                workflow_run_id=workflow_run.id,
                step_key="generate_secondary",
                action="translation.generate_draft",
                llm_role="translator",
                model_profile_id="profile-secondary",
                status="failed",
                input_ref="segment:1",
                output_payload={"error": "secondary failed", "actual_model_name": "model-secondary"},
                summary=None,
            ),
        ]
    )
    db_session.commit()

    payload = route_action(
        {
            "action": "stage.inspect_runs",
            "project_id": str(project.id),
            "stage": "translation",
            "limit": "1",
        }
    )

    run = payload["data"]["runs"][0]
    assert run["diagnostics"]["failure_step"]["step_key"] == "generate_primary"
    assert run["diagnostics"]["model_profile_id"] == "profile-primary"
    assert run["diagnostics"]["model_name"] == "model-primary"


def test_stage_inspect_runs_exposes_observability_metadata(
    database_url: str,
    db_session: Session,
    request_id_factory: callable,
) -> None:
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("inspect-runs-observability-project"),
        source_path="D:/inputs/source.txt",
        source_language="zh",
        target_language="en",
    )
    stage_run = StageRun(
        project_id=project.id,
        stage="translation",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":1}',
        status="completed",
        summary=json.dumps(
            {
                "request_id": "translation-observability-request",
                "model_profile_id": "profile-observability",
                "workflow_key": "translation_multi_llm_v1",
                "resume": True,
                "rerun": False,
                "resume_from_run_id": 41,
                "started_at": "2026-04-18T10:00:00+00:00",
                "finished_at": "2026-04-18T10:00:03+00:00",
                "duration_ms": 3123,
                "token_usage": {
                    "input_tokens": 120,
                    "output_tokens": 48,
                    "total_tokens": 168,
                    "call_count": 3,
                    "measured_call_count": 3,
                },
            },
            ensure_ascii=False,
        ),
    )
    db_session.add(stage_run)
    db_session.flush()

    workflow_run = WorkflowRun(
        workflow_key="translation_multi_llm_v1",
        project_id=project.id,
        stage="translation",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":1}',
        request_id="translation-observability-request",
        status="completed",
        summary=json.dumps(
            {
                "request_id": "translation-observability-request",
                "stage_run_id": stage_run.id,
            },
            ensure_ascii=False,
        ),
    )
    db_session.add(workflow_run)
    db_session.flush()

    db_session.add_all(
        [
            WorkflowStepRun(
                workflow_run_id=workflow_run.id,
                step_key="generate_primary",
                action="translation.generate_draft",
                llm_role="translator",
                model_profile_id="profile-primary",
                status="completed",
                input_ref="segment:1",
                output_payload={
                    "fallback_depth": 1,
                    "token_usage": {
                        "input_tokens": 80,
                        "output_tokens": 30,
                        "total_tokens": 110,
                        "call_count": 2,
                        "measured_call_count": 2,
                    },
                },
                summary=None,
            ),
            WorkflowStepRun(
                workflow_run_id=workflow_run.id,
                step_key="review_drafts",
                action="translation.review_draft",
                llm_role="reviewer",
                model_profile_id="profile-review",
                status="completed",
                input_ref="segment:1",
                output_payload={
                    "max_fallback_depth": 2,
                    "token_usage": {
                        "input_tokens": 40,
                        "output_tokens": 18,
                        "total_tokens": 58,
                        "call_count": 1,
                        "measured_call_count": 1,
                    },
                },
                summary=None,
            ),
        ]
    )
    db_session.commit()

    payload = route_action(
        {
            "action": "stage.inspect_runs",
            "project_id": str(project.id),
            "stage": "translation",
            "limit": "1",
        }
    )

    run = payload["data"]["runs"][0]
    assert run["observability"]["timing"] == {
        "started_at": "2026-04-18T10:00:00+00:00",
        "finished_at": "2026-04-18T10:00:03+00:00",
        "duration_ms": 3123,
    }
    assert run["observability"]["recovery"] == {
        "resume": True,
        "rerun": False,
        "resume_from_run_id": 41,
        "rerun_from_run_id": None,
    }
    assert run["observability"]["fallback"] == {
        "triggered": True,
        "max_depth": 2,
    }
    assert run["observability"]["usage"] == {
        "input_tokens": 120,
        "output_tokens": 48,
        "total_tokens": 168,
        "call_count": 3,
        "measured_call_count": 3,
    }
    assert run["workflow"]["steps"][0]["token_usage"] == {
        "input_tokens": 80,
        "output_tokens": 30,
        "total_tokens": 110,
        "call_count": 2,
        "measured_call_count": 2,
    }
    assert run["workflow"]["steps"][1]["token_usage"] == {
        "input_tokens": 40,
        "output_tokens": 18,
        "total_tokens": 58,
        "call_count": 1,
        "measured_call_count": 1,
    }


def test_stage_inspect_runs_exposes_workflow_step_progress(
    database_url: str,
    db_session: Session,
    request_id_factory: callable,
) -> None:
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("inspect-runs-step-progress-project"),
        source_path="D:/inputs/source.txt",
        source_language="zh",
        target_language="en",
    )
    stage_run = StageRun(
        project_id=project.id,
        stage="glossary",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":2}',
        status="running",
        summary=json.dumps(
            {
                "request_id": "glossary-progress-request",
                "model_profile_id": "profile-glossary-progress",
                "workflow_key": "glossary_single_llm_v1",
            },
            ensure_ascii=False,
        ),
    )
    db_session.add(stage_run)
    db_session.flush()
    workflow_run = WorkflowRun(
        workflow_key="glossary_single_llm_v1",
        project_id=project.id,
        stage="glossary",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":2}',
        request_id="glossary-progress-request",
        status="running",
        summary=json.dumps(
            {
                "request_id": "glossary-progress-request",
                "stage_run_id": stage_run.id,
            },
            ensure_ascii=False,
        ),
    )
    db_session.add(workflow_run)
    db_session.flush()
    progress = {
        "kind": "glossary.extract",
        "total_chapters": 2,
        "queued_chapters": 0,
        "running_chapters": 1,
        "completed_chapters": 1,
        "failed_chapters": 0,
        "skipped_chapters": 0,
        "finished_chapters": 1,
        "max_parallel_workers": 2,
        "chapters": [
            {"chapter_id": 101, "chapter_index": 1, "chapter_title": "第1章", "status": "completed"},
            {"chapter_id": 102, "chapter_index": 2, "chapter_title": "第2章", "status": "running"},
        ],
        "started_at": "2026-04-28T10:00:00+00:00",
        "updated_at": "2026-04-28T10:00:05+00:00",
    }
    db_session.add(
        WorkflowStepRun(
            workflow_run_id=workflow_run.id,
            step_key="extract_primary",
            action="glossary.extract",
            llm_role="extractor",
            model_profile_id="profile-glossary-progress",
            status="running",
            input_ref="chapter:1-2",
            output_payload={"progress": progress},
            summary=None,
        )
    )
    db_session.commit()

    payload = route_action(
        {
            "action": "stage.inspect_runs",
            "project_id": str(project.id),
            "stage": "glossary",
            "limit": "1",
        }
    )

    step = payload["data"]["runs"][0]["workflow"]["steps"][0]
    assert step["progress"] == progress


def test_stage_inspect_runs_does_not_sort_with_large_step_output_payload(
    database_url: str,
    db_session: Session,
    request_id_factory: callable,
) -> None:
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("inspect-runs-large-payload-project"),
        source_path="D:/inputs/source.txt",
        source_language="zh",
        target_language="en",
    )
    stage_run = StageRun(
        project_id=project.id,
        stage="glossary",
        scope_type="all",
        scope_value='{"type":"all"}',
        status="completed",
        summary=json.dumps(
            {
                "request_id": "glossary-large-payload-request",
                "model_profile_id": "profile-large-payload",
                "workflow_key": "glossary_single_llm_v1",
            },
            ensure_ascii=False,
        ),
    )
    db_session.add(stage_run)
    db_session.flush()
    workflow_run = WorkflowRun(
        workflow_key="glossary_single_llm_v1",
        project_id=project.id,
        stage="glossary",
        scope_type="all",
        scope_value='{"type":"all"}',
        request_id="glossary-large-payload-request",
        status="completed",
        summary=json.dumps({"request_id": "glossary-large-payload-request", "stage_run_id": stage_run.id}),
    )
    db_session.add(workflow_run)
    db_session.flush()
    db_session.add(
        WorkflowStepRun(
            workflow_run_id=workflow_run.id,
            step_key="extract",
            action="glossary.extract",
            llm_role="extractor",
            model_profile_id="profile-large-payload",
            status="completed",
            input_ref="chapter:all",
            output_payload={
                "actual_model_name": "model-large-payload",
                "chapter_results": [{"source": "x" * 2000} for _ in range(20)],
            },
            summary=None,
        )
    )
    db_session.commit()

    ordered_step_queries: list[str] = []

    def capture_ordered_step_query(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        lowered = statement.lower()
        if "ltw_workflow_step_runs" in lowered and "order by" in lowered and ".id" in lowered:
            ordered_step_queries.append(lowered)

    event.listen(db_session.bind, "before_cursor_execute", capture_ordered_step_query)
    try:
        payload = route_action(
            {
                "action": "stage.inspect_runs",
                "project_id": str(project.id),
                "stage": "glossary",
                "limit": "1",
            }
        )
    finally:
        event.remove(db_session.bind, "before_cursor_execute", capture_ordered_step_query)

    assert payload["data"]["runs"][0]["workflow"]["steps"][0]["actual_model_name"] == "model-large-payload"
    assert ordered_step_queries
    assert all("output_payload" not in statement for statement in ordered_step_queries)


def test_stage_inspect_runs_exposes_workflow_summary_for_translation_runs(
    database_url: str,
    db_session: Session,
    request_id_factory: callable,
) -> None:
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("inspect-runs-workflow-summary-project"),
        source_path="D:/inputs/source.txt",
        source_language="zh",
        target_language="en",
    )
    stage_run = StageRun(
        project_id=project.id,
        stage="translation",
        scope_type="chapter_list",
        scope_value='{"type":"chapter_list","chapters":[1,2]}',
        status="completed",
        summary=json.dumps(
            {
                "request_id": "translation-workflow-summary-request",
                "model_profile_id": "profile-translation",
                "workflow_key": "translation_multi_llm_v1",
                "translated_segments": 5,
                "active_version_ids": [11, 12, 13, 14, 15],
            },
            ensure_ascii=False,
        ),
    )
    db_session.add(stage_run)
    db_session.flush()

    workflow_run = WorkflowRun(
        workflow_key="translation_multi_llm_v1",
        project_id=project.id,
        stage="translation",
        scope_type="chapter_list",
        scope_value='{"type":"chapter_list","chapters":[1,2]}',
        request_id="translation-workflow-summary-request",
        status="completed",
        summary=json.dumps(
            {
                "request_id": "translation-workflow-summary-request",
                "stage_run_id": stage_run.id,
            },
            ensure_ascii=False,
        ),
    )
    db_session.add(workflow_run)
    db_session.flush()

    db_session.add_all(
        [
            WorkflowStepRun(
                workflow_run_id=workflow_run.id,
                step_key="generate_primary",
                action="translation.generate_draft",
                llm_role="translator",
                model_profile_id="profile-primary",
                status="completed",
                input_ref="segment:1",
                output_payload={"fallback_depth": 1, "actual_model_name": "model-primary"},
                summary=None,
            ),
            WorkflowStepRun(
                workflow_run_id=workflow_run.id,
                step_key="review_drafts",
                action="translation.review_draft",
                llm_role="reviewer",
                model_profile_id="profile-review",
                status="running",
                input_ref="segment:1",
                output_payload=None,
                summary=json.dumps({"provider_model_name": "model-review"}, ensure_ascii=False),
            ),
        ]
    )
    db_session.commit()

    payload = route_action(
        {
            "action": "stage.inspect_runs",
            "project_id": str(project.id),
            "stage": "translation",
            "limit": "1",
        }
    )

    run = payload["data"]["runs"][0]
    assert run["context"] == {
        "request_id": "translation-workflow-summary-request",
        "model_profile_id": "profile-translation",
        "workflow_key": "translation_multi_llm_v1",
        "workflow_run_id": workflow_run.id,
    }
    assert run["result"] == {
        "translated_segments": 5,
        "active_version_count": 5,
    }
    assert run["workflow"]["id"] == workflow_run.id
    assert run["workflow"]["workflow_key"] == "translation_multi_llm_v1"
    assert run["workflow"]["status"] == "completed"
    assert run["workflow"]["step_counts"] == {
        "total": 2,
        "completed": 1,
        "failed": 0,
        "running": 1,
    }
    assert run["workflow"]["steps"][0]["fallback_depth"] == 1
    assert run["workflow"]["steps"][0]["actual_model_name"] == "model-primary"
    assert run["workflow"]["steps"][1]["actual_model_name"] == "model-review"


def test_stage_inspect_runs_keeps_diagnostics_and_workflow_view_together_for_failed_translation_run(
    database_url: str,
    db_session: Session,
    request_id_factory: callable,
) -> None:
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("inspect-runs-failed-workflow-view-project"),
        source_path="D:/inputs/source.txt",
        source_language="zh",
        target_language="en",
    )
    stage_run = StageRun(
        project_id=project.id,
        stage="translation",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":1}',
        status="failed",
        summary=json.dumps(
            {
                "request_id": "translation-failed-workflow-view-request",
                "model_profile_id": "profile-request-failed",
                "workflow_key": "translation_multi_llm_v1",
                "error": {"code": "provider_error", "message": "rewrite failed", "status": 502},
            },
            ensure_ascii=False,
        ),
    )
    db_session.add(stage_run)
    db_session.flush()

    workflow_run = WorkflowRun(
        workflow_key="translation_multi_llm_v1",
        project_id=project.id,
        stage="translation",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":1}',
        request_id="translation-failed-workflow-view-request",
        status="failed",
        summary=json.dumps(
            {
                "request_id": "translation-failed-workflow-view-request",
                "stage_run_id": stage_run.id,
            },
            ensure_ascii=False,
        ),
    )
    db_session.add(workflow_run)
    db_session.flush()

    db_session.add_all(
        [
            WorkflowStepRun(
                workflow_run_id=workflow_run.id,
                step_key="generate_primary",
                action="translation.generate_draft",
                llm_role="translator",
                model_profile_id="profile-primary",
                status="completed",
                input_ref="segment:1",
                output_payload={"fallback_depth": 1, "actual_model_name": "model-primary"},
                summary=None,
            ),
            WorkflowStepRun(
                workflow_run_id=workflow_run.id,
                step_key="rewrite_consensus",
                action="translation.rewrite_draft",
                llm_role="translator",
                model_profile_id="profile-rewrite",
                status="failed",
                input_ref="segment:1",
                output_payload={"actual_model_name": "model-rewrite"},
                summary=None,
            ),
        ]
    )
    db_session.commit()

    payload = route_action(
        {
            "action": "stage.inspect_runs",
            "project_id": str(project.id),
            "stage": "translation",
            "limit": "1",
        }
    )

    run = payload["data"]["runs"][0]
    assert run["diagnostics"]["failure_step"] == {
        "step_key": "rewrite_consensus",
        "action": "translation.rewrite_draft",
    }
    assert run["workflow"]["status"] == "failed"
    assert run["workflow"]["step_counts"] == {
        "total": 2,
        "completed": 1,
        "failed": 1,
        "running": 0,
    }
    assert [step["step_key"] for step in run["workflow"]["steps"]] == [
        "generate_primary",
        "rewrite_consensus",
    ]


def test_stage_run_glossary_uses_default_single_workflow_when_workflow_key_missing(
    project_workspace: Path,
    db_session: Session,
    request_id_factory: callable,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_file = project_workspace / "workflow-default-glossary.txt"
    source_file.write_text("第1章 相遇\n林溪看见赵馨宁。\n", encoding="utf-8")

    create_payload = route_action(
        {
            "action": "project.create",
            "request_id": request_id_factory("workflow-default-project"),
            "source_path": str(source_file),
            "source_language": "zh",
            "target_language": "en",
        }
    )
    project_id = create_payload["data"]["id"]

    route_action(
        {
            "action": "stage.run",
            "project_id": str(project_id),
            "stage": "chaptering",
            "scope_type": "all",
            "request_id": request_id_factory("workflow-default-chaptering"),
        }
    )

    from tools.local_translation_workbench.app import action_router as action_router_module
    from tools.local_translation_workbench.app.providers.router import ResolvedProviderProfile

    monkeypatch.setattr(
        action_router_module,
        "build_provider_from_profile",
        lambda session, config, model_profile_id: ResolvedProviderProfile(
            provider=FakeGlossaryWorkflowProvider(),
            profile_key=str(model_profile_id or "profile-workflow-default"),
            model_name="resolved-workflow-default-model",
        ),
    )

    payload = route_action(
        {
            "action": "stage.run",
            "project_id": str(project_id),
            "stage": "glossary",
            "scope_type": "chapter_range",
            "scope_start": "1",
            "scope_end": "1",
            "request_id": request_id_factory("workflow-default-glossary"),
            "model_profile_id": "gpt_5_4_aicodelink",
        }
    )

    assert payload["data"]["stage"] == "glossary"
    assert payload["data"]["candidate_count"] >= 1
    workflow_runs = db_session.execute(
        select(WorkflowRun)
        .where(WorkflowRun.project_id == project_id, WorkflowRun.stage == "glossary")
        .order_by(WorkflowRun.id.asc())
    ).scalars().all()
    assert len(workflow_runs) == 1
    assert workflow_runs[0].workflow_key == "glossary_single_llm_v1"
