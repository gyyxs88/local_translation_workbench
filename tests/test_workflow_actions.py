from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from tools.local_translation_workbench.app.action_router import route_action
from tools.local_translation_workbench.app.cli import main
from tools.local_translation_workbench.app.db.models import GlossaryDraftCandidate
from tools.local_translation_workbench.app.db.models import ModelProfile, ProviderConfig, TranslationProject, WorkflowProfile, WorkflowRun, WorkflowStepRun
from tools.local_translation_workbench.app.errors import ToolError
from tools.local_translation_workbench.app.providers.base import TextGenerationResult
from tools.local_translation_workbench.app.repositories.workflows import WorkflowRepository
from tools.local_translation_workbench.app.repositories.projects import ProjectService
from tools.local_translation_workbench.app.services.chaptering_service import ChapteringService
from tools.local_translation_workbench.app.services.glossary_pipeline_service import GlossaryPipelineService
from tools.local_translation_workbench.app.services.glossary_service import GlossaryService
from tools.local_translation_workbench.app.services.workflow_profile_service import WorkflowProfileService
from tools.local_translation_workbench.app.services.workflow_runtime_service import WorkflowRuntimeService


def test_workflow_repository_creates_profile_run_and_step(db_session) -> None:
    repository = WorkflowRepository(db_session)
    project = TranslationProject(
        request_id="workflow-project-request-001",
        project_key="workflow-project-001",
        source_path="source.txt",
        source_language="ja",
        target_language="zh-CN",
        status="created",
    )
    db_session.add(project)
    db_session.flush()

    profile = repository.create_profile(
        workflow_key="translation_workflow",
        stage="translation",
        status="active",
        is_default=True,
        definition_json={"steps": ["translation", "review"]},
    )
    run = repository.create_run(
        workflow_key=profile.workflow_key,
        project_id=project.id,
        stage="translation",
        scope_type="all",
        scope_value="{}",
        request_id="workflow-request-001",
        status="running",
        summary="开始执行 workflow",
    )
    step_run = repository.create_step_run(
        workflow_run_id=run.id,
        step_key="translate_chapter_001",
        action="translate",
        llm_role="translator",
        model_profile_id="model-profile-001",
        status="running",
        input_ref="chapter-001",
        output_payload={"translated": False},
        summary="开始执行 step",
    )

    stored_profile = db_session.execute(
        select(WorkflowProfile).where(WorkflowProfile.id == profile.id)
    ).scalar_one()
    stored_run = db_session.execute(select(WorkflowRun).where(WorkflowRun.id == run.id)).scalar_one()
    stored_step_run = db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.id == step_run.id)
    ).scalar_one()

    assert stored_profile.workflow_key == "translation_workflow"
    assert stored_run.workflow_key == "translation_workflow"
    assert stored_step_run.step_key == "translate_chapter_001"


def test_set_default_for_stage_switches_default(db_session) -> None:
    repository = WorkflowRepository(db_session)
    first = repository.create_profile(
        workflow_key="translation_workflow_a",
        stage="translation",
        status="active",
        is_default=True,
        definition_json={"steps": ["translation"]},
    )
    second = repository.create_profile(
        workflow_key="translation_workflow_b",
        stage="translation",
        status="active",
        is_default=False,
        definition_json={"steps": ["translation", "review"]},
    )

    repository.set_default_for_stage("translation_workflow_b", "translation")

    stored_first = db_session.execute(
        select(WorkflowProfile).where(WorkflowProfile.id == first.id)
    ).scalar_one()
    stored_second = db_session.execute(
        select(WorkflowProfile).where(WorkflowProfile.id == second.id)
    ).scalar_one()

    assert stored_first.is_default == 0
    assert stored_second.is_default == 1


def test_set_default_for_stage_raises_for_missing_workflow_and_keeps_existing_default(db_session) -> None:
    repository = WorkflowRepository(db_session)
    first = repository.create_profile(
        workflow_key="translation_workflow_a",
        stage="translation",
        status="active",
        is_default=True,
        definition_json={"steps": ["translation"]},
    )

    with pytest.raises(ValueError):
        repository.set_default_for_stage("missing_workflow", "translation")

    stored_first = db_session.execute(
        select(WorkflowProfile).where(WorkflowProfile.id == first.id)
    ).scalar_one()
    assert stored_first.is_default == 1


def test_create_run_raises_for_missing_workflow(db_session) -> None:
    repository = WorkflowRepository(db_session)

    with pytest.raises(ValueError):
        repository.create_run(
            workflow_key="missing_workflow",
            project_id=1,
            stage="translation",
            scope_type="all",
            scope_value="{}",
            request_id="workflow-request-002",
            status="running",
            summary=None,
        )


def test_create_run_raises_for_stage_mismatch(db_session) -> None:
    repository = WorkflowRepository(db_session)
    project = TranslationProject(
        request_id="workflow-project-request-002",
        project_key="workflow-project-002",
        source_path="source.txt",
        source_language="ja",
        target_language="zh-CN",
        status="created",
    )
    db_session.add(project)
    db_session.flush()
    repository.create_profile(
        workflow_key="translation_workflow",
        stage="translation",
        status="active",
        is_default=True,
        definition_json={"steps": ["translation"]},
    )

    with pytest.raises(ValueError):
        repository.create_run(
            workflow_key="translation_workflow",
            project_id=project.id,
            stage="review",
            scope_type="all",
            scope_value="{}",
            request_id="workflow-request-003",
            status="running",
            summary=None,
        )


def test_update_run_and_step_run_updates_key_fields(db_session) -> None:
    repository = WorkflowRepository(db_session)
    project = TranslationProject(
        request_id="workflow-project-request-003",
        project_key="workflow-project-003",
        source_path="source.txt",
        source_language="ja",
        target_language="zh-CN",
        status="created",
    )
    db_session.add(project)
    db_session.flush()
    repository.create_profile(
        workflow_key="translation_workflow",
        stage="translation",
        status="active",
        is_default=True,
        definition_json={"steps": ["translation", "review"]},
    )
    run = repository.create_run(
        workflow_key="translation_workflow",
        project_id=project.id,
        stage="translation",
        scope_type="all",
        scope_value="{}",
        request_id="workflow-request-004",
        status="running",
        summary="开始执行 workflow",
    )
    step_run = repository.create_step_run(
        workflow_run_id=run.id,
        step_key="translate_chapter_001",
        action="translate",
        llm_role="translator",
        model_profile_id="model-profile-001",
        status="running",
        input_ref="chapter-001",
        output_payload={"translated": False},
        summary="开始执行 step",
    )

    updated_run = repository.update_run(run.id, status="completed", summary="workflow completed")
    updated_step_run = repository.update_step_run(
        step_run.id,
        status="completed",
        output_payload={"translated": True},
    )

    assert updated_run.status == "completed"
    assert updated_run.summary == "workflow completed"
    assert updated_step_run.status == "completed"
    assert updated_step_run.output_payload == {"translated": True}


def test_cli_workflow_profile_lifecycle(capsys, db_session) -> None:
    workflow_key = "workflow_cli_glossary_custom_v1"
    workflow_definition = json.dumps(
        {
            "name": "CLI glossary workflow",
            "steps": [
                {
                    "step_key": "extract_primary",
                    "action": "glossary.extract",
                    "llm_role": "extractor",
                    "model_profile_id": "$request.default",
                },
                {
                    "step_key": "normalize_candidates",
                    "action": "glossary.normalize",
                    "llm_role": "normalizer",
                    "model_profile_id": "$request.default",
                },
            ],
        },
        ensure_ascii=False,
    )

    exit_code = main(
        [
            "-Action",
            "workflow.create",
            "-WorkflowKey",
            workflow_key,
            "-Stage",
            "glossary",
            "-Status",
            "active",
            "-DefinitionJson",
            workflow_definition,
        ]
    )
    create_payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert create_payload["ok"] is True
    assert create_payload["action"] == "workflow.create"
    assert create_payload["data"]["workflow_key"] == workflow_key

    exit_code = main(["-Action", "workflow.list"])
    list_payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert list_payload["ok"] is True
    assert list_payload["action"] == "workflow.list"
    assert any(item["workflow_key"] == "glossary_single_llm_v1" for item in list_payload["data"]["workflows"])
    assert any(item["workflow_key"] == workflow_key for item in list_payload["data"]["workflows"])

    builtin_payload = main(["-Action", "workflow.inspect", "-WorkflowKey", "glossary_single_llm_v1"])
    builtin_inspect = json.loads(capsys.readouterr().out)

    assert builtin_payload == 0
    assert builtin_inspect["ok"] is True
    assert builtin_inspect["action"] == "workflow.inspect"
    builtin_steps = builtin_inspect["data"]["definition_json"]["steps"]
    assert [item["action"] for item in builtin_steps] == [
        "glossary.extract",
        "glossary.normalize",
        "glossary.review_relations",
        "glossary.review_scope",
        "glossary.finalize",
    ]
    assert [item["llm_role"] for item in builtin_steps] == [
        "extractor",
        "normalizer",
        "relation_reviewer",
        "scope_reviewer",
        "final_judge",
    ]

    exit_code = main(
        [
            "-Action",
            "workflow.inspect",
            "-WorkflowKey",
            workflow_key,
        ]
    )
    inspect_payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert inspect_payload["ok"] is True
    assert inspect_payload["action"] == "workflow.inspect"
    assert inspect_payload["data"]["workflow_key"] == workflow_key
    assert inspect_payload["data"]["definition_json"]["steps"][0]["step_key"] == "extract_primary"

    try:
        exit_code = main(
            [
                "-Action",
                "workflow.set_default",
                "-WorkflowKey",
                workflow_key,
                "-Stage",
                "glossary",
            ]
        )
        set_default_payload = json.loads(capsys.readouterr().out)

        assert exit_code == 0
        assert set_default_payload["ok"] is True
        assert set_default_payload["action"] == "workflow.set_default"
        assert set_default_payload["data"]["workflow_key"] == workflow_key
        assert set_default_payload["data"]["is_default"] is True

        refreshed_workflow = db_session.execute(
            select(WorkflowProfile).where(WorkflowProfile.workflow_key == workflow_key)
        ).scalar_one()
        assert refreshed_workflow.is_default == 1
        restore_exit_code = main(
            [
                "-Action",
                "workflow.set_default",
                "-WorkflowKey",
                "glossary_single_llm_v1",
                "-Stage",
                "glossary",
            ]
        )
        restore_payload = json.loads(capsys.readouterr().out)

        assert restore_exit_code == 0
        assert restore_payload["ok"] is True
        assert restore_payload["data"]["workflow_key"] == "glossary_single_llm_v1"
        assert restore_payload["data"]["is_default"] is True
    finally:
        WorkflowProfileService(db_session).set_default(
            workflow_key="glossary_single_llm_v1",
            stage="glossary",
        )
        temporary_profile = db_session.execute(
            select(WorkflowProfile).where(WorkflowProfile.workflow_key == workflow_key)
        ).scalar_one_or_none()
        if temporary_profile is not None:
            db_session.delete(temporary_profile)
        db_session.commit()

    assert db_session.execute(
        select(WorkflowProfile).where(WorkflowProfile.workflow_key == workflow_key)
    ).scalar_one_or_none() is None


def test_workflow_create_rejects_unsupported_glossary_action(db_session) -> None:
    with pytest.raises(ToolError) as exc:
        WorkflowProfileService(db_session).create_workflow(
            workflow_key="glossary_invalid_action_v1",
            stage="glossary",
            definition_json={
                "name": "invalid glossary workflow",
                "steps": [
                    {
                        "step_key": "extract_primary",
                        "action": "extract",
                        "llm_role": "extractor",
                        "model_profile_id": "$request.default",
                    }
                ],
            },
        )

    assert exc.value.code == "invalid_arguments"
    assert "不支持" in exc.value.message


def test_workflow_create_accepts_supported_glossary_actions(db_session) -> None:
    payload = WorkflowProfileService(db_session).create_workflow(
        workflow_key="glossary_valid_action_v1",
        stage="glossary",
        definition_json={
            "name": "valid glossary workflow",
            "steps": [
                {
                    "step_key": "extract_primary",
                    "action": "glossary.extract",
                    "llm_role": "extractor",
                    "model_profile_id": "$request.default",
                },
                {
                    "step_key": "finalize_terms",
                    "action": "glossary.finalize",
                    "llm_role": "final_judge",
                    "model_profile_id": "$request.default",
                },
            ],
        },
    )

    assert payload["workflow_key"] == "glossary_valid_action_v1"
    assert payload["definition_json"]["steps"][1]["action"] == "glossary.finalize"


def test_workflow_runtime_resolves_request_default_profile_id(db_session) -> None:
    service = WorkflowProfileService(db_session)
    service.ensure_builtin_profiles()
    runtime_service = WorkflowRuntimeService(db_session)

    resolved_profile_id = runtime_service.resolve_step_model_profile_id(
        {
            "step_key": "extract_primary",
            "model_profile_id": "$request.default",
        },
        {
            "request_id": "workflow-runtime-request-001",
            "model_profile_id": "profile-request-default",
        },
    )

    assert resolved_profile_id == "profile-request-default"


def test_cli_workflow_set_default_rejects_stage_mismatch(capsys, db_session) -> None:
    service = WorkflowProfileService(db_session)
    service.ensure_builtin_profiles()

    exit_code = main(
        [
            "-Action",
            "workflow.set_default",
            "-WorkflowKey",
            "glossary_single_llm_v1",
            "-Stage",
            "translation",
        ]
    )
    payload = json.loads(capsys.readouterr().err)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_arguments"
    assert "stage" in payload["error"]["message"]


def test_workflow_runtime_does_not_require_external_stage_and_wraps_repository_errors(db_session) -> None:
    project = TranslationProject(
        request_id="workflow-runtime-project-002",
        project_key="workflow-runtime-project-002",
        source_path="source.txt",
        source_language="ja",
        target_language="zh-CN",
        status="created",
    )
    db_session.add(project)
    db_session.flush()

    profile_service = WorkflowProfileService(db_session)
    profile_service.ensure_builtin_profiles()
    runtime_service = WorkflowRuntimeService(db_session)

    profile = runtime_service.resolve_workflow_profile("glossary_single_llm_v1")
    assert profile["workflow_key"] == "glossary_single_llm_v1"
    assert profile["stage"] == "glossary"
    assert profile["definition_json"]["steps"][0]["action"] == "glossary.extract"

    run = runtime_service.create_workflow_run(
        workflow_key="glossary_single_llm_v1",
        project_id=project.id,
        scope={"type": "all"},
        request_id="workflow-runtime-run-001",
    )
    assert run.stage == "glossary"
    assert run.workflow_key == "glossary_single_llm_v1"

    with pytest.raises(ToolError) as exc:
        runtime_service.create_workflow_run(
            workflow_key="missing_workflow",
            project_id=project.id,
            scope={"type": "all"},
            request_id="workflow-runtime-run-002",
        )
    assert exc.value.code == "not_found"

    with pytest.raises(ToolError) as exc:
        runtime_service.mark_run_status(999999, status="completed")
    assert exc.value.code == "not_found"

    with pytest.raises(ToolError) as exc:
        runtime_service.mark_step_status(999999, status="completed")
    assert exc.value.code == "not_found"


def _prepare_workflow_project_with_chapters(
    *,
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> int:
    source_file = project_workspace / "workflow-glossary-source.txt"
    source_file.write_text("第1章 相遇\n林溪看见赵馨宁。\n", encoding="utf-8")

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("workflow-glossary-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )
    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("workflow-glossary-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )
    return project.id


class FakeWorkflowGlossaryProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        self.calls.append(
            {
                "prompt": prompt,
                "model_name": model_name,
                "timeout_seconds": timeout_seconds,
            }
        )
        return TextGenerationResult(
            content=json.dumps(
                {
                    "terms": [
                        {
                            "source_term": "林溪",
                            "translated_term": "Lin Xi",
                            "category": "character",
                            "note": "主角名",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            provider_name="fake-workflow-glossary",
            model_name=model_name,
        )


class FakeSequencedWorkflowGlossaryProvider:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.calls: list[dict[str, object]] = []

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        self.calls.append(
            {
                "prompt": prompt,
                "model_name": model_name,
                "timeout_seconds": timeout_seconds,
            }
        )
        content = self.outputs.pop(0) if self.outputs else '{"terms":[]}'
        return TextGenerationResult(
            content=content,
            provider_name="fake-sequenced-workflow-glossary",
            model_name=model_name,
        )


class FakeRuntimePipelineGlossaryService:
    def inspect_result(self, *, project_id: int, workflow_run_id: int):
        _ = (project_id, workflow_run_id)
        return type("InspectResult", (), {"candidate_count": 99})()


class FakeRuntimeGlossaryPipeline:
    def __init__(self) -> None:
        self.glossary_service = FakeRuntimePipelineGlossaryService()

    def extract(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        scope: dict[str, object],
        model_profile_id: str,
        provider_model_name: str | None,
    ) -> dict[str, object]:
        _ = (
            workflow_run_id,
            workflow_step_run_id,
            project_id,
            scope,
            model_profile_id,
            provider_model_name,
        )
        return {"draft_candidate_count": 3}

    def finalize(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
    ) -> dict[str, object]:
        _ = (
            workflow_run_id,
            workflow_step_run_id,
            project_id,
            model_profile_id,
            provider_model_name,
        )
        return {"candidate_count": 2}

    def inspect_pipeline(self, *, workflow_run_id: int) -> dict[str, object]:
        _ = workflow_run_id
        return {"draft_candidates": [], "reviews": []}

    def normalize(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
    ) -> dict[str, object]:
        _ = (workflow_run_id, workflow_step_run_id)
        return {"normalized_candidate_count": 2}

    def review_relations(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
    ) -> dict[str, object]:
        _ = (
            workflow_run_id,
            workflow_step_run_id,
            model_profile_id,
            provider_model_name,
        )
        return {"reviewed_candidate_count": 2}

    def review_scope(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
    ) -> dict[str, object]:
        _ = (
            workflow_run_id,
            workflow_step_run_id,
            model_profile_id,
            provider_model_name,
        )
        return {"reviewed_candidate_count": 2}


class FakeQuorumRuntimeGlossaryPipeline(FakeRuntimeGlossaryPipeline):
    def __init__(self) -> None:
        super().__init__()
        self.extract_call_count = 0

    def extract(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        scope: dict[str, object],
        model_profile_id: str,
        provider_model_name: str | None,
    ) -> dict[str, object]:
        _ = (
            workflow_run_id,
            workflow_step_run_id,
            project_id,
            scope,
            model_profile_id,
            provider_model_name,
        )
        self.extract_call_count += 1
        if self.extract_call_count == 1:
            raise ToolError(code="provider_error", message="模拟首个 extractor 失败。", status=502)
        return {"draft_candidate_count": 2}


def test_glossary_extract_action_creates_draft_candidates(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = _prepare_workflow_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    workflow_run = WorkflowRun(
        workflow_key="glossary_single_llm_v1",
        project_id=project_id,
        stage="glossary",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":1}',
        request_id=request_id_factory("glossary-extract-workflow-run"),
        status="running",
        summary=None,
    )
    db_session.add(workflow_run)
    db_session.flush()
    workflow_step_run = WorkflowStepRun(
        workflow_run_id=workflow_run.id,
        step_key="extract_primary",
        action="glossary.extract",
        llm_role="extractor",
        model_profile_id="gpt_5_4_aicodelink",
        status="running",
        input_ref="chapter:1",
        output_payload=None,
        summary=None,
    )
    db_session.add(workflow_step_run)
    db_session.commit()

    from tools.local_translation_workbench.app import action_router as action_router_module
    from tools.local_translation_workbench.app.providers.router import ResolvedProviderProfile

    monkeypatch.setattr(
        action_router_module,
        "build_provider_from_profile",
        lambda session, config, model_profile_id: ResolvedProviderProfile(
            provider=FakeWorkflowGlossaryProvider(),
            profile_key=str(model_profile_id or "profile-workflow-glossary"),
            model_name="resolved-workflow-glossary-model",
        ),
    )

    payload = route_action(
        {
            "action": "glossary.extract",
            "project_id": str(project_id),
            "request_id": request_id_factory("glossary-extract-action"),
            "workflow_run_id": str(workflow_run.id),
            "workflow_step_run_id": str(workflow_step_run.id),
            "scope_type": "chapter_range",
            "scope_start": "1",
            "scope_end": "1",
            "model_profile_id": "gpt_5_4_aicodelink",
        }
    )

    stored_candidates = db_session.execute(
        select(GlossaryDraftCandidate).where(GlossaryDraftCandidate.workflow_run_id == workflow_run.id)
    ).scalars().all()

    assert payload["ok"] is True
    assert payload["data"]["draft_candidate_count"] >= 1
    assert len(stored_candidates) >= 1


def test_glossary_multi_llm_workflow_runs_two_extract_steps_before_finalize(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    request_id = request_id_factory("glossary-multi-llm")
    project_id = _prepare_workflow_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    provider = FakeSequencedWorkflowGlossaryProvider(
        outputs=[
            json.dumps(
                {
                    "terms": [
                        {
                            "source_term": "林溪",
                            "translated_term": "Lin Xi",
                            "category": "character",
                            "note": "canonical",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "terms": [
                        {
                            "source_term": "小溪",
                            "translated_term": "Xiaoxi",
                            "category": "character",
                            "note": "alias",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "items": [
                        {
                            "draft_candidate_id": 1,
                            "term_group_key": "char_linxi",
                            "relation_role": "canonical",
                            "score": 0.98,
                            "reason_codes": ["same_entity"],
                        },
                        {
                            "draft_candidate_id": 2,
                            "term_group_key": "char_linxi",
                            "relation_role": "alias",
                            "score": 0.96,
                            "reason_codes": ["same_entity"],
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "items": [
                        {
                            "draft_candidate_id": 1,
                            "scope_level": "project_term",
                            "scope_chapter_id": None,
                            "score": 0.93,
                            "reason_codes": ["cross_chapter_reuse"],
                        },
                        {
                            "draft_candidate_id": 2,
                            "scope_level": "chapter_term",
                            "scope_chapter_id": None,
                            "score": 0.88,
                            "reason_codes": ["chapter_alias"],
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "terms": [
                        {
                            "draft_candidate_id": 1,
                            "source_term": "林溪",
                            "target_term": "Lin Xi",
                            "category": "character",
                            "term_group_key": "char_linxi",
                            "relation_role": "canonical",
                            "scope_level": "project_term",
                            "scope_chapter_id": None,
                        },
                        {
                            "draft_candidate_id": 2,
                            "source_term": "小溪",
                            "target_term": "Xiaoxi",
                            "category": "character",
                            "term_group_key": "char_linxi",
                            "relation_role": "alias",
                            "scope_level": "chapter_term",
                        },
                    ]
                },
                ensure_ascii=False,
            ),
        ]
    )

    result = GlossaryService(db_session, provider=provider).run(
        request_id=request_id,
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="gpt_5_4_aicodelink",
        workflow_key="glossary_multi_llm_v1",
    )

    workflow_run = db_session.execute(
        select(WorkflowRun).where(
            WorkflowRun.workflow_key == "glossary_multi_llm_v1",
            WorkflowRun.request_id == request_id,
        )
    ).scalar_one()
    step_runs = db_session.execute(
        select(WorkflowStepRun)
        .where(WorkflowStepRun.workflow_run_id == workflow_run.id)
        .order_by(WorkflowStepRun.id.asc())
    ).scalars().all()

    assert result.candidate_count >= 1
    assert len(provider.calls) == 5
    assert [item.step_key for item in step_runs] == [
        "extract_primary",
        "extract_secondary",
        "normalize_candidates",
        "review_relations",
        "review_scope",
        "finalize_terms",
    ]
    assert [item.action for item in step_runs[:2]] == [
        "glossary.extract",
        "glossary.extract",
    ]
    assert step_runs[-1].action == "glossary.finalize"


def test_glossary_multi_llm_workflow_allows_one_extractor_failure_with_quorum(db_session) -> None:
    request_id = "workflow-runtime-quorum-run"
    project = TranslationProject(
        request_id="workflow-runtime-quorum-project",
        project_key="workflow-runtime-quorum-project",
        source_path="source.txt",
        source_language="ja",
        target_language="zh-CN",
        status="created",
    )
    db_session.add(project)
    db_session.flush()

    profile_service = WorkflowProfileService(db_session)
    profile_service.ensure_builtin_profiles()
    db_session.commit()

    runtime_service = WorkflowRuntimeService(db_session)
    result = runtime_service.run_glossary_workflow(
        workflow_definition=runtime_service.resolve_workflow_definition(
            stage="glossary",
            workflow_key="glossary_multi_llm_v1",
        ),
        workflow_key="glossary_multi_llm_v1",
        request_id=request_id,
        project_id=project.id,
        scope={"type": "all"},
        request_model_profile_id="default",
        provider_model_name="resolved-default-model",
        pipeline=FakeQuorumRuntimeGlossaryPipeline(),
    )

    workflow_run = db_session.execute(
        select(WorkflowRun).where(
            WorkflowRun.workflow_key == "glossary_multi_llm_v1",
            WorkflowRun.request_id == request_id,
        )
    ).scalar_one()
    step_runs = db_session.execute(
        select(WorkflowStepRun)
        .where(WorkflowStepRun.workflow_run_id == workflow_run.id)
        .order_by(WorkflowStepRun.id.asc())
    ).scalars().all()
    summary = json.loads(workflow_run.summary or "{}")

    assert result.candidate_count == 2
    assert workflow_run.status == "insufficient_evidence"
    assert [item.status for item in step_runs[:2]] == ["failed", "completed"]
    assert step_runs[-1].status == "completed"
    assert summary["degraded"] is True
    assert summary["degradation_reason"] == "low_confidence"


def test_glossary_extract_action_uses_resolved_provider_model_name(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = _prepare_workflow_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    workflow_run = WorkflowRun(
        workflow_key="glossary_single_llm_v1",
        project_id=project_id,
        stage="glossary",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":1}',
        request_id=request_id_factory("glossary-extract-model-run"),
        status="running",
        summary=None,
    )
    db_session.add(workflow_run)
    db_session.flush()
    workflow_step_run = WorkflowStepRun(
        workflow_run_id=workflow_run.id,
        step_key="extract_primary",
        action="glossary.extract",
        llm_role="extractor",
        model_profile_id="profile-key-only",
        status="running",
        input_ref="chapter:1",
        output_payload=None,
        summary=None,
    )
    db_session.add(workflow_step_run)
    db_session.commit()

    from tools.local_translation_workbench.app import action_router as action_router_module
    from tools.local_translation_workbench.app.providers.router import ResolvedProviderProfile

    provider = FakeWorkflowGlossaryProvider()
    monkeypatch.setattr(
        action_router_module,
        "build_provider_from_profile",
        lambda session, config, model_profile_id: ResolvedProviderProfile(
            provider=provider,
            profile_key="profile-key-only",
            model_name="resolved-real-model-name",
        ),
    )

    payload = route_action(
        {
            "action": "glossary.extract",
            "project_id": str(project_id),
            "request_id": request_id_factory("glossary-extract-model-action"),
            "workflow_run_id": str(workflow_run.id),
            "workflow_step_run_id": str(workflow_step_run.id),
            "scope_type": "chapter_range",
            "scope_start": "1",
            "scope_end": "1",
            "model_profile_id": "profile-key-only",
        }
    )

    assert payload["ok"] is True
    assert provider.calls[0]["model_name"] == "resolved-real-model-name"


def test_workflow_runtime_uses_finalize_result_as_final_summary(db_session) -> None:
    project = TranslationProject(
        request_id="workflow-runtime-finalize-project",
        project_key="workflow-runtime-finalize-project",
        source_path="source.txt",
        source_language="ja",
        target_language="zh-CN",
        status="created",
    )
    db_session.add(project)
    db_session.flush()
    WorkflowRepository(db_session).create_profile(
        workflow_key="glossary_finalize_result_test_v1",
        stage="glossary",
        status="active",
        is_default=False,
        definition_json={
            "name": "glossary_finalize_result_test_v1",
            "steps": [
                {
                    "step_key": "extract_primary",
                    "action": "glossary.extract",
                    "llm_role": "extractor",
                    "model_profile_id": "$request.default",
                },
                {
                    "step_key": "finalize_terms",
                    "action": "glossary.finalize",
                    "llm_role": "final_judge",
                    "model_profile_id": "$request.default",
                },
                {
                    "step_key": "inspect_snapshot",
                    "action": "glossary.inspect_pipeline",
                    "llm_role": "observer",
                    "model_profile_id": "$request.default",
                },
            ],
        },
    )
    db_session.commit()

    runtime_service = WorkflowRuntimeService(db_session)
    result = runtime_service.run_glossary_workflow(
        workflow_definition=runtime_service.resolve_workflow_definition(
            stage="glossary",
            workflow_key="glossary_finalize_result_test_v1",
        ),
        workflow_key="glossary_finalize_result_test_v1",
        request_id="workflow-runtime-finalize-run",
        project_id=project.id,
        scope={"type": "all"},
        request_model_profile_id="default",
        provider_model_name="resolved-default-model",
        pipeline=FakeRuntimeGlossaryPipeline(),
    )

    workflow_run = db_session.execute(
        select(WorkflowRun).where(WorkflowRun.workflow_key == "glossary_finalize_result_test_v1")
    ).scalar_one()
    summary = json.loads(workflow_run.summary or "{}")

    assert result.candidate_count == 2
    assert summary["candidate_count"] == 2


def test_workflow_runtime_step_uses_resolved_profile_model_name(
    database_url: str,
    db_session,
    project_workspace: Path,
    request_id_factory,
) -> None:
    source_file = project_workspace / "workflow-step-model-source.txt"
    source_file.write_text("第1章 相遇\n林溪看见赵馨宁。\n", encoding="utf-8")
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("workflow-step-model-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )
    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("workflow-step-model-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    provider_config = ProviderConfig(
        provider_key="provider-step-model",
        provider_type="openai_compatible",
        display_name="Provider Step Model",
        base_url="https://example.invalid",
        api_key_env_name="DUMMY_STEP_MODEL",
        status="active",
    )
    db_session.add(provider_config)
    db_session.flush()
    model_profile = ModelProfile(
        profile_key="profile-step-model",
        provider_id=provider_config.id,
        model_name="resolved-step-model-name",
        is_default=0,
        status="active",
    )
    db_session.add(model_profile)
    db_session.flush()

    workflow_repository = WorkflowRepository(db_session)
    workflow_repository.create_profile(
        workflow_key="glossary_step_model_test_v1",
        stage="glossary",
        status="active",
        is_default=False,
        definition_json={
            "name": "glossary_step_model_test_v1",
            "steps": [
                {
                    "step_key": "extract_explicit",
                    "action": "glossary.extract",
                    "llm_role": "extractor",
                    "model_profile_id": "profile-step-model",
                }
            ],
        },
    )
    db_session.commit()

    provider = FakeWorkflowGlossaryProvider()
    runtime_service = WorkflowRuntimeService(db_session)
    workflow_definition = runtime_service.resolve_workflow_definition(
        stage="glossary",
        workflow_key="glossary_step_model_test_v1",
    )

    result = runtime_service.run_glossary_workflow(
        workflow_definition=workflow_definition,
        workflow_key="glossary_step_model_test_v1",
        request_id=request_id_factory("workflow-step-model-run"),
        project_id=project.id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        request_model_profile_id="request-profile-key",
        provider_model_name="request-run-model-name",
        pipeline=GlossaryPipelineService(db_session, provider=provider),
    )

    workflow_run = db_session.execute(
        select(WorkflowRun).where(WorkflowRun.workflow_key == "glossary_step_model_test_v1")
    ).scalar_one()
    summary = json.loads(workflow_run.summary or "{}")

    assert result.candidate_count == 0
    assert provider.calls[0]["model_name"] == "resolved-step-model-name"
    assert summary["result_source"] == "final_candidates_fallback"
    assert summary["fallback_reason"] == "workflow_missing_finalize_step"
