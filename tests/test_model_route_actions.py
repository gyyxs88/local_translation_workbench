from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select, update

from tools.local_translation_workbench.app.action_router import route_action
from tools.local_translation_workbench.app.db.models import (
    ModelProfile,
    ModelRouteBinding,
    ModelRoutePreset,
    ProviderConfig,
    TranslationProject,
    WorkflowProfile,
)
from tools.local_translation_workbench.app.providers.router import ResolvedProviderProfile
from tools.local_translation_workbench.app.repositories.workflows import WorkflowRepository
from tools.local_translation_workbench.app.services.provider_profile_service import ProviderProfileService
from tools.local_translation_workbench.app.services.provider_resolution_service import ProviderResolutionService
from tools.local_translation_workbench.app.services.workflow_runtime_service import WorkflowRuntimeService
from tools.local_translation_workbench.app.services.workflow_step_executor_service import WorkflowStepExecutorService
from tools.local_translation_workbench.app.config import ToolConfig


def _create_profile_pair(db_session, suffix: str = "") -> tuple[str, str]:
    primary_provider = f"route_primary_provider{suffix}"
    secondary_provider = f"route_secondary_provider{suffix}"
    primary_profile = f"route_primary_profile{suffix}"
    secondary_profile = f"route_secondary_profile{suffix}"
    service = ProviderProfileService(db_session)
    service.create_provider(
        provider_key=primary_provider,
        provider_type="openai_compatible",
        display_name="Route Primary",
        base_url="https://primary.example.com/v1",
        api_key_value="sk-primary-secret",
        status="active",
        note=None,
    )
    service.create_provider(
        provider_key=secondary_provider,
        provider_type="openai_compatible",
        display_name="Route Secondary",
        base_url="https://secondary.example.com/v1",
        api_key_value="sk-secondary-secret",
        status="active",
        note=None,
    )
    service.create_profile(
        profile_key=primary_profile,
        provider_key=primary_provider,
        model_name="gpt-5.5",
        timeout_seconds=60,
        temperature=0,
        is_default=True,
        status="active",
        note=None,
    )
    service.create_profile(
        profile_key=secondary_profile,
        provider_key=secondary_provider,
        model_name="deepseek-v4-pro",
        timeout_seconds=60,
        temperature=0,
        is_default=False,
        status="active",
        note=None,
    )
    return primary_profile, secondary_profile


def test_create_provider_can_store_masked_database_key_without_env(db_session) -> None:
    service = ProviderProfileService(db_session)

    payload = service.create_provider(
        provider_key="db_key_provider",
        provider_type="openai_compatible",
        display_name="DB Key Provider",
        base_url="https://db-key.example.com/v1/",
        api_key_value="sk-db-secret-123456",
        status="active",
        note=None,
    )

    stored = db_session.execute(
        select(ProviderConfig).where(ProviderConfig.provider_key == "db_key_provider")
    ).scalar_one()
    inspected = service.inspect_provider(provider_key="db_key_provider")

    assert payload["api_key_source"] == "database"
    assert stored.api_key_value == "sk-db-secret-123456"
    assert inspected["api_key_is_set"] is True
    assert inspected["api_key_source"] == "database"
    assert inspected["api_key_masked"] == "sk-db...3456"
    assert "sk-db-secret-123456" not in str(inspected)


def test_provider_resolution_uses_database_key(db_session) -> None:
    service = ProviderProfileService(db_session)
    service.create_provider(
        provider_key="db_only_provider",
        provider_type="openai_compatible",
        display_name="DB Only Provider",
        base_url="https://db-only.example.com/v1",
        api_key_value="sk-db-only-secret",
        status="active",
        note=None,
    )
    service.create_profile(
        profile_key="db_only_profile",
        provider_key="db_only_provider",
        model_name="gpt-5.5",
        timeout_seconds=60,
        temperature=0,
        is_default=True,
        status="active",
        note=None,
    )

    chain = ProviderResolutionService(
        db_session,
        ToolConfig(
            database_url="mysql+pymysql://example/test",
            data_dir="data/projects",
        ),
    ).resolve_profile_chain(model_profile_id="db_only_profile")

    assert chain is not None
    assert chain.candidates[0].build_error is None
    assert getattr(chain.candidates[0].provider, "api_key") == "sk-db-only-secret"


def test_route_preset_persists_bindings_and_resolves_workflow_steps(db_session) -> None:
    primary_profile, secondary_profile = _create_profile_pair(db_session)
    service = ProviderProfileService(db_session)

    payload = service.set_route_preset(
        preset_key="novel_gpt55_deepseek",
        display_name="Novel GPT 5.5 + DeepSeek",
        bindings=[
            {
                "stage": "glossary",
                "step_key": "extract_primary",
                "model_profile_id": primary_profile,
            },
            {
                "stage": "glossary",
                "step_key": "extract_secondary",
                "model_profile_id": secondary_profile,
            },
            {
                "stage": "translation",
                "step_key": "generate_secondary",
                "model_profile_id": secondary_profile,
            },
        ],
        is_default=True,
        status="active",
        note="main/sub LLM routing",
    )

    preset = db_session.execute(
        select(ModelRoutePreset).where(ModelRoutePreset.preset_key == "novel_gpt55_deepseek")
    ).scalar_one()
    bindings = db_session.execute(
        select(ModelRouteBinding)
        .where(ModelRouteBinding.preset_id == preset.id)
        .order_by(ModelRouteBinding.id.asc())
    ).scalars().all()
    executor = WorkflowStepExecutorService(db_session)

    resolved_primary = executor.resolve_step_model_profile_id(
        {
            "step_key": "extract_primary",
            "action": "glossary.extract",
            "llm_role": "extractor",
            "model_profile_id": "$request.default",
        },
        {
            "model_profile_id": "default",
            "route_preset_key": "novel_gpt55_deepseek",
            "stage": "glossary",
        },
    )
    resolved_secondary = executor.resolve_step_model_profile_id(
        {
            "step_key": "extract_secondary",
            "action": "glossary.extract",
            "llm_role": "extractor",
            "model_profile_id": "$request.default",
        },
        {
            "model_profile_id": "default",
            "route_preset_key": "novel_gpt55_deepseek",
            "stage": "glossary",
        },
    )

    assert payload["preset_key"] == "novel_gpt55_deepseek"
    assert payload["is_default"] is True
    assert [item.model_profile_id for item in bindings] == [
        primary_profile,
        secondary_profile,
        secondary_profile,
    ]
    assert resolved_primary == primary_profile
    assert resolved_secondary == secondary_profile


class _NamedProvider:
    def __init__(self, name: str) -> None:
        self.name = name


class _RouteAwareGlossaryPipeline:
    def __init__(self, *, provider=None, calls: list[dict[str, object]] | None = None) -> None:
        self.provider = provider
        self.calls = calls if calls is not None else []

    def with_provider(self, provider):
        return _RouteAwareGlossaryPipeline(provider=provider, calls=self.calls)

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
        self.calls.append(
            {
                "provider": None if self.provider is None else self.provider.name,
                "model_profile_id": model_profile_id,
                "provider_model_name": provider_model_name,
            }
        )
        return {"candidate_count": 0, "model_profile_id": model_profile_id}

    def finalize(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
    ) -> dict[str, object]:
        return {"candidate_count": 0, "model_profile_id": model_profile_id}


def test_route_preset_switches_provider_per_workflow_step(
    db_session,
    monkeypatch,
) -> None:
    primary_profile, secondary_profile = _create_profile_pair(db_session, suffix="_runtime")
    ProviderProfileService(db_session).set_route_preset(
        preset_key="runtime_gpt55_deepseek",
        display_name="Runtime GPT 5.5 + DeepSeek",
        bindings=[
            {
                "stage": "glossary",
                "step_key": "extract_primary",
                "model_profile_id": primary_profile,
            },
            {
                "stage": "glossary",
                "step_key": "extract_secondary",
                "model_profile_id": secondary_profile,
            },
        ],
        is_default=False,
        status="active",
        note=None,
    )
    project = TranslationProject(
        request_id="route-runtime-project",
        project_key="route-runtime-project",
        source_path="source.txt",
        source_language="zh",
        target_language="en",
        status="created",
    )
    db_session.add(project)
    WorkflowRepository(db_session).create_profile(
        workflow_key="route_runtime_glossary",
        stage="glossary",
        status="active",
        is_default=False,
        definition_json={
            "steps": [
                {
                    "step_key": "extract_primary",
                    "action": "glossary.extract",
                    "llm_role": "extractor",
                    "model_profile_id": "$request.default",
                },
                {
                    "step_key": "extract_secondary",
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
    db_session.commit()

    def fake_build_provider_from_profile(session, config, model_profile_id):
        profile = session.execute(
            select(ModelProfile).where(ModelProfile.profile_key == model_profile_id)
        ).scalar_one()
        return ResolvedProviderProfile(
            provider=_NamedProvider(name=str(model_profile_id)),
            profile_key=str(model_profile_id),
            model_name=profile.model_name,
        )

    from tools.local_translation_workbench.app.services import workflow_runtime_service as runtime_module

    monkeypatch.setattr(runtime_module, "build_provider_from_profile", fake_build_provider_from_profile)
    pipeline = _RouteAwareGlossaryPipeline()
    runtime = WorkflowRuntimeService(db_session)

    runtime.run_glossary_workflow(
        workflow_definition={
            "workflow_key": "route_runtime_glossary",
            "stage": "glossary",
            "definition_json": {
                "steps": [
                    {
                        "step_key": "extract_primary",
                        "action": "glossary.extract",
                        "llm_role": "extractor",
                        "model_profile_id": "$request.default",
                    },
                    {
                        "step_key": "extract_secondary",
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
        },
        workflow_key="route_runtime_glossary",
        request_id="route-runtime-run",
        project_id=project.id,
        scope={"type": "all"},
        request_model_profile_id="default",
        provider_model_name=None,
        pipeline=pipeline,
        route_preset_key="runtime_gpt55_deepseek",
    )

    assert pipeline.calls == [
        {
            "provider": primary_profile,
            "model_profile_id": primary_profile,
            "provider_model_name": "gpt-5.5",
        },
        {
            "provider": secondary_profile,
            "model_profile_id": secondary_profile,
            "provider_model_name": "deepseek-v4-pro",
        },
    ]


def test_explicit_workflow_step_profile_switches_provider_without_route_preset(
    db_session,
    monkeypatch,
) -> None:
    primary_profile, secondary_profile = _create_profile_pair(db_session, suffix="_explicit_runtime")
    project = TranslationProject(
        request_id="explicit-runtime-project",
        project_key="explicit-runtime-project",
        source_path="source.txt",
        source_language="zh",
        target_language="en",
        status="created",
    )
    db_session.add(project)
    WorkflowRepository(db_session).create_profile(
        workflow_key="explicit_runtime_glossary",
        stage="glossary",
        status="active",
        is_default=False,
        definition_json={
            "steps": [
                {
                    "step_key": "extract_primary",
                    "action": "glossary.extract",
                    "llm_role": "extractor",
                    "model_profile_id": "$request.default",
                },
                {
                    "step_key": "extract_secondary",
                    "action": "glossary.extract",
                    "llm_role": "extractor",
                    "model_profile_id": secondary_profile,
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
    db_session.commit()

    def fake_build_provider_from_profile(session, config, model_profile_id):
        profile = session.execute(
            select(ModelProfile).where(ModelProfile.profile_key == model_profile_id)
        ).scalar_one()
        return ResolvedProviderProfile(
            provider=_NamedProvider(name=str(model_profile_id)),
            profile_key=str(model_profile_id),
            model_name=profile.model_name,
        )

    from tools.local_translation_workbench.app.services import workflow_runtime_service as runtime_module

    monkeypatch.setattr(runtime_module, "build_provider_from_profile", fake_build_provider_from_profile)
    pipeline = _RouteAwareGlossaryPipeline(provider=_NamedProvider(name=primary_profile))
    runtime = WorkflowRuntimeService(db_session)

    runtime.run_glossary_workflow(
        workflow_definition={
            "workflow_key": "explicit_runtime_glossary",
            "stage": "glossary",
            "definition_json": {
                "steps": [
                    {
                        "step_key": "extract_primary",
                        "action": "glossary.extract",
                        "llm_role": "extractor",
                        "model_profile_id": "$request.default",
                    },
                    {
                        "step_key": "extract_secondary",
                        "action": "glossary.extract",
                        "llm_role": "extractor",
                        "model_profile_id": secondary_profile,
                    },
                    {
                        "step_key": "finalize_terms",
                        "action": "glossary.finalize",
                        "llm_role": "final_judge",
                        "model_profile_id": "$request.default",
                    },
                ],
            },
        },
        workflow_key="explicit_runtime_glossary",
        request_id="explicit-runtime-run",
        project_id=project.id,
        scope={"type": "all"},
        request_model_profile_id=primary_profile,
        provider_model_name="gpt-5.5",
        pipeline=pipeline,
        route_preset_key=None,
    )

    assert pipeline.calls == [
        {
            "provider": primary_profile,
            "model_profile_id": primary_profile,
            "provider_model_name": "gpt-5.5",
        },
        {
            "provider": secondary_profile,
            "model_profile_id": secondary_profile,
            "provider_model_name": "deepseek-v4-pro",
        },
    ]


def test_route_preset_actions_create_and_inspect_bindings(db_session) -> None:
    primary_profile, secondary_profile = _create_profile_pair(db_session, suffix="_action")

    created = route_action(
        {
            "action": "profile.route_set",
            "preset_key": "action_gpt55_deepseek",
            "display_name": "Action GPT 5.5 + DeepSeek",
            "bindings_json": json.dumps(
                [
                    {
                        "stage": "glossary",
                        "step_key": "extract_primary",
                        "model_profile_id": primary_profile,
                    },
                    {
                        "stage": "glossary",
                        "step_key": "extract_secondary",
                        "model_profile_id": secondary_profile,
                    },
                ]
            ),
            "is_default": "true",
        }
    )
    inspected = route_action(
        {
            "action": "profile.route_inspect",
            "preset_key": "action_gpt55_deepseek",
        }
    )

    assert created["ok"] is True
    assert created["data"]["is_default"] is True
    assert [item["model_profile_id"] for item in inspected["data"]["bindings"]] == [
        primary_profile,
        secondary_profile,
    ]


def test_route_preset_action_reads_utf8_file_arguments(db_session, tmp_path: Path) -> None:
    primary_profile, secondary_profile = _create_profile_pair(db_session, suffix="_action_file")
    bindings_path = tmp_path / "bindings.json"
    note_path = tmp_path / "note.txt"
    bindings_path.write_text(
        json.dumps(
            [
                {
                    "stage": "glossary",
                    "step_key": "extract_primary",
                    "model_profile_id": primary_profile,
                    "note": "术语阶段主模型",
                },
                {
                    "stage": "translation",
                    "step_key": "generate_secondary",
                    "model_profile_id": secondary_profile,
                    "note": "翻译阶段副模型",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    note_path.write_text("中文备注：GPT 主模型 + DeepSeek 副模型", encoding="utf-8")

    created = route_action(
        {
            "action": "profile.route_set",
            "preset_key": "action_file_gpt55_deepseek",
            "display_name": "文件参数中文路由",
            "bindings_json_file": str(bindings_path),
            "note": f"@{note_path}",
        }
    )

    assert created["ok"] is True
    assert created["data"]["display_name"] == "文件参数中文路由"
    assert created["data"]["note"] == "中文备注：GPT 主模型 + DeepSeek 副模型"
    assert [item["note"] for item in created["data"]["bindings"]] == [
        "术语阶段主模型",
        "翻译阶段副模型",
    ]


def test_run_ps1_route_set_reads_utf8_file_arguments(
    db_session,
    database_url: str,
    tmp_path: Path,
) -> None:
    if shutil.which("powershell") is None:
        pytest.skip("PowerShell executable is not available")

    primary_profile, secondary_profile = _create_profile_pair(db_session, suffix="_ps_file")
    bindings_path = tmp_path / "bindings.json"
    note_path = tmp_path / "note.txt"
    bindings_path.write_text(
        json.dumps(
            [
                {
                    "stage": "glossary",
                    "step_key": "extract_primary",
                    "model_profile_id": primary_profile,
                    "note": "PowerShell 术语主模型",
                },
                {
                    "stage": "translation",
                    "step_key": "generate_secondary",
                    "model_profile_id": secondary_profile,
                    "note": "PowerShell 翻译副模型",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    note_path.write_text("PowerShell 中文备注：路由文件传参", encoding="utf-8")
    tool_root = Path(__file__).resolve().parents[1]

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(tool_root / "scripts" / "run.ps1"),
            "-Action",
            "profile.route_set",
            "-PresetKey",
            "ps_file_gpt55_deepseek",
            "-DisplayName",
            "PowerShell 中文路由",
            "-BindingsJsonFile",
            str(bindings_path),
            "-NoteFile",
            str(note_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "LTW_DATABASE_URL": database_url, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
    )

    payload = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert completed.stderr == ""
    assert payload["ok"] is True
    assert payload["data"]["display_name"] == "PowerShell 中文路由"
    assert payload["data"]["note"] == "PowerShell 中文备注：路由文件传参"
    assert [item["note"] for item in payload["data"]["bindings"]] == [
        "PowerShell 术语主模型",
        "PowerShell 翻译副模型",
    ]


def test_route_set_default_can_apply_multi_workflow_defaults(db_session) -> None:
    primary_profile, secondary_profile = _create_profile_pair(db_session, suffix="_default_stack")
    route_action(
        {
            "action": "profile.route_set",
            "preset_key": "default_stack_gpt55_deepseek",
            "display_name": "Default Stack GPT 5.5 + DeepSeek",
            "bindings_json": json.dumps(
                [
                    {
                        "stage": "glossary",
                        "step_key": "extract_primary",
                        "model_profile_id": primary_profile,
                    },
                    {
                        "stage": "glossary",
                        "step_key": "extract_secondary",
                        "model_profile_id": secondary_profile,
                    },
                    {
                        "stage": "translation",
                        "step_key": "generate_primary",
                        "model_profile_id": primary_profile,
                    },
                    {
                        "stage": "translation",
                        "step_key": "generate_secondary",
                        "model_profile_id": secondary_profile,
                    },
                ]
            ),
        }
    )

    try:
        payload = route_action(
            {
                "action": "profile.route_set_default",
                "preset_key": "default_stack_gpt55_deepseek",
                "workflow_mode": "multi",
            }
        )
        default_workflows = {
            item.stage: item.workflow_key
            for item in db_session.execute(
                select(WorkflowProfile).where(WorkflowProfile.is_default == 1)
            ).scalars().all()
        }

        assert payload["ok"] is True
        assert payload["data"]["is_default"] is True
        assert {item["workflow_key"] for item in payload["data"]["workflow_defaults"]} == {
            "glossary_multi_llm_v1",
            "translation_multi_llm_v1",
        }
        assert default_workflows["glossary"] == "glossary_multi_llm_v1"
        assert default_workflows["translation"] == "translation_multi_llm_v1"
    finally:
        route_action(
            {
                "action": "workflow.set_default",
                "workflow_key": "glossary_single_llm_v1",
                "stage": "glossary",
            }
        )
        route_action(
            {
                "action": "workflow.set_default",
                "workflow_key": "translation_single_llm_v1",
                "stage": "translation",
            }
        )
        db_session.execute(update(ModelRoutePreset).values(is_default=0))
        db_session.commit()
