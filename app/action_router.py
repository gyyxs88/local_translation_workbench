from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from sqlalchemy import func, select

from .config import load_config
from .db.models import (
    Chapter,
    ExportRun,
    GlossaryEntry,
    ReviewRun,
    SegmentTranslation,
    StageRun,
)
from .db.engine import get_session_factory
from .errors import ToolError
from .providers.router import build_provider, build_provider_from_profile
from .repositories.projects import ProjectRepository, ProjectService
from .repositories.synopsis import ProjectSynopsisRepository
from .services.provider_profile_service import ProviderProfileService
from .services.provider_resolution_service import ProviderResolutionService
from .services.chapter_query_service import ChapterQueryService
from .services.export_service import ExportService
from .services.glossary_pipeline_service import GlossaryPipelineService
from .services.glossary_service import GlossaryService
from .services.project_query_service import ProjectQueryService
from .services.review_service import ReviewService
from .services.scope_service import ScopeService, ensure_scope_supported, get_stage_scope_types
from .services.workflow_profile_service import WorkflowProfileService
from .services.stage_service import STAGE_SEQUENCE, StageCommand, StageService
from .services.synopsis_service import SynopsisService
from .services.translation_pipeline_service import TranslationPipelineService
from .services.translation_service import TranslationService


def route_action(arguments: dict[str, str]) -> dict[str, Any]:
    action = _require_argument(arguments, "action").lower()
    if action == "project.create":
        return _handle_project_create(arguments)
    if action == "project.list":
        return _handle_project_list(arguments)
    if action == "project.cancel":
        return _handle_project_cancel(arguments)
    if action == "project.run_full":
        return _handle_project_run_full(arguments)
    if action == "provider.create":
        return _handle_provider_create(arguments)
    if action == "provider.list":
        return _handle_provider_list(arguments)
    if action == "provider.inspect":
        return _handle_provider_inspect(arguments)
    if action == "provider.health_check":
        return _handle_provider_health_check(arguments)
    if action == "profile.create":
        return _handle_profile_create(arguments)
    if action == "profile.list":
        return _handle_profile_list(arguments)
    if action == "profile.inspect":
        return _handle_profile_inspect(arguments)
    if action == "profile.set_fallbacks":
        return _handle_profile_set_fallbacks(arguments)
    if action == "workflow.create":
        return _handle_workflow_create(arguments)
    if action == "workflow.list":
        return _handle_workflow_list(arguments)
    if action == "workflow.inspect":
        return _handle_workflow_inspect(arguments)
    if action == "workflow.set_default":
        return _handle_workflow_set_default(arguments)
    if action == "glossary.extract":
        return _handle_glossary_extract(arguments)
    if action == "glossary.normalize":
        return _handle_glossary_normalize(arguments)
    if action == "glossary.review_relations":
        return _handle_glossary_review_relations(arguments)
    if action == "glossary.review_scope":
        return _handle_glossary_review_scope(arguments)
    if action == "glossary.finalize":
        return _handle_glossary_finalize(arguments)
    if action == "glossary.inspect_pipeline":
        return _handle_glossary_inspect_pipeline(arguments)
    if action == "translation.generate_draft":
        return _handle_translation_generate_draft(arguments)
    if action == "translation.review_draft":
        return _handle_translation_review_draft(arguments)
    if action == "translation.rewrite_draft":
        return _handle_translation_rewrite_draft(arguments)
    if action == "translation.finalize":
        return _handle_translation_finalize(arguments)
    if action == "translation.inspect_pipeline":
        return _handle_translation_inspect_pipeline(arguments)
    if action == "stage.run":
        return _handle_stage_run(arguments)
    if action == "stage.inspect_runs":
        return _handle_stage_inspect_runs(arguments)
    if action == "inspect.project":
        return _handle_inspect_project(arguments)
    if action == "inspect.glossary":
        return _handle_inspect_glossary(arguments)
    if action == "inspect.synopsis":
        return _handle_inspect_synopsis(arguments)
    if action == "inspect.chapter":
        return _handle_inspect_chapter(arguments)
    if action == "inspect.chapters":
        return _handle_inspect_chapters(arguments)
    if action == "inspect.segment":
        return _handle_inspect_segment(arguments)
    if action == "inspect.translation":
        return _handle_inspect_translation(arguments)
    if action == "inspect.review":
        return _handle_inspect_review(arguments)
    if action == "inspect.export":
        return _handle_inspect_export(arguments)
    raise ToolError(code="invalid_arguments", message=f"不支持的 action: {action}", status=400)


def _handle_project_create(arguments: dict[str, str]) -> dict[str, Any]:
    request_id = _require_argument(arguments, "request_id")
    source_path = _require_argument(arguments, "source_path")
    source_language = _require_argument(arguments, "source_language")
    target_language = _require_argument(arguments, "target_language")

    service = ProjectService(load_config().database_url)
    record = service.create_project(
        request_id=request_id,
        source_path=source_path,
        source_language=source_language,
        target_language=target_language,
    )
    return {"ok": True, "action": "project.create", "data": asdict(record)}


def _handle_project_list(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        data = ProjectQueryService(session).list_projects()
        return {"ok": True, "action": "project.list", "data": data}
    finally:
        session.close()


def _handle_project_cancel(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        data = ProjectQueryService(session).cancel_project(
            project_id=int(_require_argument(arguments, "project_id")),
            request_id=_require_argument(arguments, "request_id"),
        )
        return {"ok": True, "action": "project.cancel", "data": data}
    finally:
        session.close()


def _handle_project_run_full(arguments: dict[str, str]) -> dict[str, Any]:
    request_id = _require_argument(arguments, "request_id")
    project_id = int(_require_argument(arguments, "project_id"))
    model_profile_id = arguments.get("model_profile_id", "default")
    resume = _parse_bool(arguments.get("resume"))
    rerun = _parse_bool(arguments.get("rerun"))
    stage_names = _resolve_stage_window(
        from_stage=arguments.get("from_stage"),
        until_stage=arguments.get("until_stage"),
    )
    config = load_config()
    session = _open_session()
    try:
        project = ProjectRepository(session).get_by_id(project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        results: dict[str, Any] = {}
        scope = {"type": "all"}
        for stage_name in stage_names:
            resolved_provider = _resolve_model_stage_provider(
                session=session,
                config=config,
                stage=stage_name,
                model_profile_id=model_profile_id,
            )
            stage_result = StageService(
                session,
                base_data_dir=config.data_dir,
                provider=None if resolved_provider is None else resolved_provider.provider,
            ).run(
                StageCommand(
                    request_id=f"{request_id}:{stage_name}",
                    project_id=project_id,
                    stage=stage_name,
                    scope=scope,
                    model_profile_id=(
                        resolved_provider.profile_key if resolved_provider is not None else model_profile_id
                    ),
                    provider_model_name=(
                        resolved_provider.model_name if resolved_provider is not None else None
                    ),
                    resume=resume,
                    rerun=rerun,
                )
            )
            results[stage_name] = _summarize_stage_result(stage_name, stage_result)

        return {
            "ok": True,
            "action": "project.run_full",
            "data": {
                "project_id": project_id,
                "stages": list(stage_names),
                "results": results,
            },
        }
    finally:
        session.close()


def _handle_provider_create(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        data = ProviderProfileService(session).create_provider(
            provider_key=_require_argument(arguments, "provider_key"),
            provider_type=_require_argument(arguments, "provider_type"),
            display_name=_require_argument(arguments, "display_name"),
            base_url=_require_argument(arguments, "base_url"),
            api_key_env_name=_require_argument(arguments, "api_key_env_name"),
            status=arguments.get("status", "active"),
            note=arguments.get("note"),
        )
        return {"ok": True, "action": "provider.create", "data": data}
    finally:
        session.close()


def _handle_provider_list(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        data = ProviderProfileService(session).list_providers()
        return {"ok": True, "action": "provider.list", "data": data}
    finally:
        session.close()


def _handle_provider_inspect(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        data = ProviderProfileService(session).inspect_provider(
            provider_key=_require_argument(arguments, "provider_key")
        )
        return {"ok": True, "action": "provider.inspect", "data": data}
    finally:
        session.close()


def _handle_provider_health_check(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        include_fallbacks_value = _read_optional_argument(arguments, "include_fallbacks")
        data = ProviderResolutionService(session, load_config()).health_check(
            model_profile_id=_read_optional_argument(arguments, "model_profile_id") or "default",
            include_fallbacks=True if include_fallbacks_value is None else _parse_bool(include_fallbacks_value),
        )
        return {"ok": True, "action": "provider.health_check", "data": data}
    finally:
        session.close()


def _handle_profile_create(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        data = ProviderProfileService(session).create_profile(
            profile_key=_require_argument(arguments, "profile_key"),
            provider_key=_require_argument(arguments, "provider_key"),
            model_name=_require_argument(arguments, "model_name"),
            timeout_seconds=_parse_optional_int(arguments.get("timeout_seconds")),
            temperature=_parse_optional_int(arguments.get("temperature")),
            fallback_profile_keys=_parse_json_string_list_argument(
                _read_optional_argument(arguments, "fallback_profile_keys_json")
            ),
            is_default=_parse_bool(arguments.get("is_default")),
            status=arguments.get("status", "active"),
            note=arguments.get("note"),
        )
        return {"ok": True, "action": "profile.create", "data": data}
    finally:
        session.close()


def _handle_profile_list(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        data = ProviderProfileService(session).list_profiles()
        return {"ok": True, "action": "profile.list", "data": data}
    finally:
        session.close()


def _handle_profile_inspect(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        data = ProviderProfileService(session).inspect_profile(
            profile_key=_require_argument(arguments, "profile_key")
        )
        return {"ok": True, "action": "profile.inspect", "data": data}
    finally:
        session.close()


def _handle_profile_set_fallbacks(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        data = ProviderProfileService(session).set_profile_fallbacks(
            profile_key=_require_argument(arguments, "profile_key"),
            fallback_profile_keys=_parse_json_string_list_argument(
                _read_argument(arguments, "fallback_profile_keys_json")
            ),
        )
        return {"ok": True, "action": "profile.set_fallbacks", "data": data}
    finally:
        session.close()


def _handle_workflow_create(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        _bootstrap_workflow_profiles(session)
        service = WorkflowProfileService(session)
        data = service.create_workflow(
            workflow_key=_read_argument(arguments, "workflow_key"),
            stage=_read_argument(arguments, "stage"),
            status=arguments.get("status", "active"),
            is_default=_parse_bool(arguments.get("is_default")),
            definition_json=_parse_json_argument(arguments.get("definition_json") or arguments.get("definitionjson")),
        )
        return {"ok": True, "action": "workflow.create", "data": data}
    finally:
        session.close()


def _handle_workflow_list(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        _bootstrap_workflow_profiles(session)
        service = WorkflowProfileService(session)
        stage = _read_optional_argument(arguments, "stage")
        data = service.list_workflows(stage=stage)
        return {"ok": True, "action": "workflow.list", "data": data}
    finally:
        session.close()


def _handle_workflow_inspect(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        _bootstrap_workflow_profiles(session)
        service = WorkflowProfileService(session)
        data = service.inspect_workflow(workflow_key=_read_argument(arguments, "workflow_key"))
        return {"ok": True, "action": "workflow.inspect", "data": data}
    finally:
        session.close()


def _handle_workflow_set_default(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        _bootstrap_workflow_profiles(session)
        service = WorkflowProfileService(session)
        data = service.set_default(
            workflow_key=_read_argument(arguments, "workflow_key"),
            stage=_read_optional_argument(arguments, "stage"),
        )
        return {"ok": True, "action": "workflow.set_default", "data": data}
    finally:
        session.close()


def _bootstrap_workflow_profiles(session) -> None:
    service = WorkflowProfileService(session)
    if service.ensure_builtin_profiles():
        session.commit()


def _handle_stage_run(arguments: dict[str, str]) -> dict[str, Any]:
    stage = _require_argument(arguments, "stage").lower()
    if stage not in STAGE_SEQUENCE:
        raise ToolError(
            code="invalid_arguments",
            message="目前只支持 stage=chaptering、glossary、translation、review 或 export。",
            status=400,
        )

    request_id = _require_argument(arguments, "request_id")
    project_id = int(_require_argument(arguments, "project_id"))
    scope_type = arguments.get("scope_type", "all")
    model_profile_id = arguments.get("model_profile_id", "default")
    workflow_key = _read_optional_argument(arguments, "workflow_key")
    resume = _parse_bool(arguments.get("resume"))
    rerun = _parse_bool(arguments.get("rerun"))
    scope_service = ScopeService()
    scope = scope_service.build_scope(
        scope_type,
        scope_start=arguments.get("scope_start"),
        scope_end=arguments.get("scope_end"),
        scope_chapters=arguments.get("scope_chapters"),
    )
    ensure_scope_supported(scope, stage=stage, allowed_types=get_stage_scope_types(stage))

    config = load_config()
    session_factory = get_session_factory(_require_database_url(config.database_url))
    session = session_factory()
    try:
        _bootstrap_workflow_profiles(session)
        project = ProjectRepository(session).get_by_id(project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        resolved_provider = _resolve_model_stage_provider(
            session=session,
            config=config,
            stage=stage,
            model_profile_id=model_profile_id,
        )
        provider = resolved_provider.provider if resolved_provider is not None else None
        result = StageService(
            session,
            base_data_dir=config.data_dir,
            provider=provider,
        ).run(
                StageCommand(
                    request_id=request_id,
                    project_id=project_id,
                    stage=stage,
                    scope=scope,
                    model_profile_id=resolved_provider.profile_key if resolved_provider is not None else model_profile_id,
                    workflow_key=workflow_key,
                    provider_model_name=resolved_provider.model_name if resolved_provider is not None else None,
                    resume=resume,
                    rerun=rerun,
                )
            )
        if stage == "chaptering":
            return {
                "ok": True,
                "action": "stage.run",
                "data": {
                    "project_id": project_id,
                    "stage": stage,
                    "scope": scope,
                    "chapter_count": result.chapter_count,
                    "segment_count": result.segment_count,
                    "synopsis": result.synopsis_summary
                    if result.synopsis_summary is not None
                    else _build_synopsis_summary(ProjectSynopsisRepository(session).get_by_project_id(project_id)),
                },
            }

        if stage == "glossary":
            return {
                "ok": True,
                "action": "stage.run",
                "data": {
                    "project_id": project_id,
                    "stage": stage,
                    "scope": scope,
                    "candidate_count": result.candidate_count,
                },
            }

        if stage == "translation":
            return {
                "ok": True,
                "action": "stage.run",
                "data": {
                    "project_id": project_id,
                    "stage": stage,
                    "scope": scope,
                    "translated_segments": result.translated_segments,
                    "active_version_ids": result.active_version_ids,
                    "synopsis": result.synopsis_summary
                    if result.synopsis_summary is not None
                    else _build_synopsis_summary(ProjectSynopsisRepository(session).get_by_project_id(project_id)),
                },
            }

        if stage == "review":
            return {
                "ok": True,
                "action": "stage.run",
                "data": {
                    "project_id": project_id,
                    "stage": stage,
                    "scope": scope,
                    "issue_count": result.issue_count,
                    "run_id": result.run_id,
                },
            }

        return {
            "ok": True,
            "action": "stage.run",
            "data": {
                "project_id": project_id,
                "stage": stage,
                "scope": scope,
                "artifact_count": result.artifact_count,
                "manifest_path": result.manifest_path,
                "run_id": result.run_id,
                "synopsis": _build_synopsis_summary(ProjectSynopsisRepository(session).get_by_project_id(project_id)),
            },
        }
    finally:
        session.close()


def _handle_glossary_extract(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        config = load_config()
        resolved_provider = _resolve_model_stage_provider(
            session=session,
            config=config,
            stage="glossary",
            model_profile_id=arguments.get("model_profile_id", "default"),
        )
        resolved_profile_id = (
            resolved_provider.profile_key if resolved_provider is not None else arguments.get("model_profile_id", "default")
        )
        resolved_model_name = resolved_provider.model_name if resolved_provider is not None else arguments.get("provider_model_name")
        pipeline = GlossaryPipelineService(
            session,
            provider=None if resolved_provider is None else resolved_provider.provider,
        )
        data = pipeline.extract(
            workflow_run_id=int(_require_argument(arguments, "workflow_run_id")),
            workflow_step_run_id=int(_require_argument(arguments, "workflow_step_run_id")),
            project_id=int(_require_argument(arguments, "project_id")),
            scope=ScopeService().build_scope(
                _require_argument(arguments, "scope_type"),
                scope_start=arguments.get("scope_start"),
                scope_end=arguments.get("scope_end"),
                scope_chapters=arguments.get("scope_chapters"),
            ),
            model_profile_id=resolved_profile_id,
            provider_model_name=resolved_model_name,
        )
        session.commit()
        return {"ok": True, "action": "glossary.extract", "data": data}
    finally:
        session.close()


def _handle_glossary_normalize(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        pipeline = GlossaryPipelineService(session)
        data = pipeline.normalize(
            workflow_run_id=int(_require_argument(arguments, "workflow_run_id")),
            workflow_step_run_id=int(_require_argument(arguments, "workflow_step_run_id")),
        )
        return {"ok": True, "action": "glossary.normalize", "data": data}
    finally:
        session.close()


def _handle_glossary_review_relations(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        config = load_config()
        resolved_provider = _resolve_model_stage_provider(
            session=session,
            config=config,
            stage="glossary",
            model_profile_id=arguments.get("model_profile_id", "default"),
        )
        resolved_profile_id = (
            resolved_provider.profile_key if resolved_provider is not None else arguments.get("model_profile_id", "default")
        )
        resolved_model_name = resolved_provider.model_name if resolved_provider is not None else arguments.get("provider_model_name")
        pipeline = GlossaryPipelineService(
            session,
            provider=None if resolved_provider is None else resolved_provider.provider,
        )
        data = pipeline.review_relations(
            workflow_run_id=int(_require_argument(arguments, "workflow_run_id")),
            workflow_step_run_id=int(_require_argument(arguments, "workflow_step_run_id")),
            model_profile_id=resolved_profile_id,
            provider_model_name=resolved_model_name,
        )
        session.commit()
        return {"ok": True, "action": "glossary.review_relations", "data": data}
    finally:
        session.close()


def _handle_glossary_review_scope(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        config = load_config()
        resolved_provider = _resolve_model_stage_provider(
            session=session,
            config=config,
            stage="glossary",
            model_profile_id=arguments.get("model_profile_id", "default"),
        )
        resolved_profile_id = (
            resolved_provider.profile_key if resolved_provider is not None else arguments.get("model_profile_id", "default")
        )
        resolved_model_name = resolved_provider.model_name if resolved_provider is not None else arguments.get("provider_model_name")
        pipeline = GlossaryPipelineService(
            session,
            provider=None if resolved_provider is None else resolved_provider.provider,
        )
        data = pipeline.review_scope(
            workflow_run_id=int(_require_argument(arguments, "workflow_run_id")),
            workflow_step_run_id=int(_require_argument(arguments, "workflow_step_run_id")),
            model_profile_id=resolved_profile_id,
            provider_model_name=resolved_model_name,
        )
        session.commit()
        return {"ok": True, "action": "glossary.review_scope", "data": data}
    finally:
        session.close()


def _handle_glossary_finalize(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        config = load_config()
        resolved_provider = _resolve_model_stage_provider(
            session=session,
            config=config,
            stage="glossary",
            model_profile_id=arguments.get("model_profile_id", "default"),
        )
        resolved_profile_id = (
            resolved_provider.profile_key if resolved_provider is not None else arguments.get("model_profile_id", "default")
        )
        resolved_model_name = resolved_provider.model_name if resolved_provider is not None else arguments.get("provider_model_name")
        pipeline = GlossaryPipelineService(
            session,
            provider=None if resolved_provider is None else resolved_provider.provider,
        )
        data = pipeline.finalize(
            workflow_run_id=int(_require_argument(arguments, "workflow_run_id")),
            workflow_step_run_id=int(_require_argument(arguments, "workflow_step_run_id")),
            project_id=int(_require_argument(arguments, "project_id")),
            model_profile_id=resolved_profile_id,
            provider_model_name=resolved_model_name,
        )
        session.commit()
        return {"ok": True, "action": "glossary.finalize", "data": data}
    finally:
        session.close()


def _handle_glossary_inspect_pipeline(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        pipeline = GlossaryPipelineService(session)
        data = pipeline.inspect_pipeline(
            workflow_run_id=int(_require_argument(arguments, "workflow_run_id")),
        )
        return {"ok": True, "action": "glossary.inspect_pipeline", "data": data}
    finally:
        session.close()


def _handle_translation_generate_draft(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        config = load_config()
        resolved_provider = _resolve_model_stage_provider(
            session=session,
            config=config,
            stage="translation",
            model_profile_id=arguments.get("model_profile_id", "default"),
        )
        resolved_profile_id = (
            resolved_provider.profile_key if resolved_provider is not None else arguments.get("model_profile_id", "default")
        )
        resolved_model_name = resolved_provider.model_name if resolved_provider is not None else arguments.get("provider_model_name")
        pipeline = TranslationPipelineService(
            session,
            base_data_dir=config.data_dir,
            provider=None if resolved_provider is None else resolved_provider.provider,
        )
        data = pipeline.generate_draft(
            workflow_run_id=int(_require_argument(arguments, "workflow_run_id")),
            workflow_step_run_id=int(_require_argument(arguments, "workflow_step_run_id")),
            project_id=int(_require_argument(arguments, "project_id")),
            scope=ScopeService().build_scope(
                _require_argument(arguments, "scope_type"),
                scope_start=arguments.get("scope_start"),
                scope_end=arguments.get("scope_end"),
                scope_chapters=arguments.get("scope_chapters"),
            ),
            model_profile_id=resolved_profile_id,
            provider_model_name=resolved_model_name,
            draft_role=arguments.get("draft_role", "primary"),
        )
        session.commit()
        return {"ok": True, "action": "translation.generate_draft", "data": data}
    finally:
        session.close()


def _handle_translation_finalize(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        config = load_config()
        pipeline = TranslationPipelineService(session, base_data_dir=config.data_dir)
        data = pipeline.finalize(
            workflow_run_id=int(_require_argument(arguments, "workflow_run_id")),
            workflow_step_run_id=int(_require_argument(arguments, "workflow_step_run_id")),
            project_id=int(_require_argument(arguments, "project_id")),
            model_profile_id=arguments.get("model_profile_id", "default"),
            provider_model_name=arguments.get("provider_model_name"),
        )
        session.commit()
        return {"ok": True, "action": "translation.finalize", "data": data}
    finally:
        session.close()


def _handle_translation_review_draft(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        config = load_config()
        resolved_provider = _resolve_model_stage_provider(
            session=session,
            config=config,
            stage="translation",
            model_profile_id=arguments.get("model_profile_id", "default"),
        )
        resolved_profile_id = (
            resolved_provider.profile_key if resolved_provider is not None else arguments.get("model_profile_id", "default")
        )
        resolved_model_name = resolved_provider.model_name if resolved_provider is not None else arguments.get("provider_model_name")
        pipeline = TranslationPipelineService(
            session,
            base_data_dir=config.data_dir,
            provider=None if resolved_provider is None else resolved_provider.provider,
        )
        data = pipeline.review_draft(
            workflow_run_id=int(_require_argument(arguments, "workflow_run_id")),
            workflow_step_run_id=int(_require_argument(arguments, "workflow_step_run_id")),
            model_profile_id=resolved_profile_id,
            provider_model_name=resolved_model_name,
        )
        session.commit()
        return {"ok": True, "action": "translation.review_draft", "data": data}
    finally:
        session.close()


def _handle_translation_rewrite_draft(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        config = load_config()
        resolved_provider = _resolve_model_stage_provider(
            session=session,
            config=config,
            stage="translation",
            model_profile_id=arguments.get("model_profile_id", "default"),
        )
        resolved_profile_id = (
            resolved_provider.profile_key if resolved_provider is not None else arguments.get("model_profile_id", "default")
        )
        resolved_model_name = resolved_provider.model_name if resolved_provider is not None else arguments.get("provider_model_name")
        pipeline = TranslationPipelineService(
            session,
            base_data_dir=config.data_dir,
            provider=None if resolved_provider is None else resolved_provider.provider,
        )
        data = pipeline.rewrite_draft(
            workflow_run_id=int(_require_argument(arguments, "workflow_run_id")),
            workflow_step_run_id=int(_require_argument(arguments, "workflow_step_run_id")),
            model_profile_id=resolved_profile_id,
            provider_model_name=resolved_model_name,
        )
        session.commit()
        return {"ok": True, "action": "translation.rewrite_draft", "data": data}
    finally:
        session.close()


def _handle_translation_inspect_pipeline(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        config = load_config()
        pipeline = TranslationPipelineService(session, base_data_dir=config.data_dir)
        data = pipeline.inspect_pipeline(
            workflow_run_id=int(_require_argument(arguments, "workflow_run_id")),
        )
        return {"ok": True, "action": "translation.inspect_pipeline", "data": data}
    finally:
        session.close()


def _handle_stage_inspect_runs(arguments: dict[str, str]) -> dict[str, Any]:
    session = _open_session()
    try:
        data = ProjectQueryService(session).inspect_stage_runs(
            project_id=int(_require_argument(arguments, "project_id")),
            stage=arguments.get("stage"),
            limit=_parse_optional_int(arguments.get("limit")) or 20,
        )
        return {"ok": True, "action": "stage.inspect_runs", "data": data}
    finally:
        session.close()


def _handle_inspect_project(arguments: dict[str, str]) -> dict[str, Any]:
    project_id = int(_require_argument(arguments, "project_id"))
    config = load_config()
    session_factory = get_session_factory(_require_database_url(config.database_url))
    session = session_factory()
    try:
        project = ProjectRepository(session).get_by_id(project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        synopsis = ProjectSynopsisRepository(session).get_by_project_id(project_id)
        data = {
            "project": {
                "id": project.id,
                "request_id": project.request_id,
                "project_key": project.project_key,
                "source_path": project.source_path,
                "source_language": project.source_language,
                "target_language": project.target_language,
                "status": project.status,
            },
            "synopsis": _build_synopsis_summary(synopsis),
            "counts": {
                "chapters": _count_rows(session, select(func.count()).select_from(Chapter).where(Chapter.project_id == project_id)),
                "glossary_entries": _count_rows(
                    session,
                    select(func.count()).select_from(GlossaryEntry).where(GlossaryEntry.project_id == project_id),
                ),
                "translations": _count_rows(
                    session,
                    select(func.count()).select_from(SegmentTranslation).where(SegmentTranslation.project_id == project_id),
                ),
                "review_runs": _count_rows(
                    session,
                    select(func.count()).select_from(ReviewRun).where(ReviewRun.project_id == project_id),
                ),
                "export_runs": _count_rows(
                    session,
                    select(func.count()).select_from(ExportRun).where(ExportRun.project_id == project_id),
                ),
                "stage_runs": _count_rows(
                    session,
                    select(func.count()).select_from(StageRun).where(StageRun.project_id == project_id),
                ),
            },
        }
        return {"ok": True, "action": "inspect.project", "data": data}
    finally:
        session.close()


def _handle_inspect_glossary(arguments: dict[str, str]) -> dict[str, Any]:
    project_id = int(_require_argument(arguments, "project_id"))
    config = load_config()
    session_factory = get_session_factory(_require_database_url(config.database_url))
    session = session_factory()
    try:
        project = ProjectRepository(session).get_by_id(project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        data = GlossaryService(session).inspect(project_id=project_id)
        return {"ok": True, "action": "inspect.glossary", "data": data}
    finally:
        session.close()


def _handle_inspect_synopsis(arguments: dict[str, str]) -> dict[str, Any]:
    project_id = int(_require_argument(arguments, "project_id"))
    config = load_config()
    session_factory = get_session_factory(_require_database_url(config.database_url))
    session = session_factory()
    try:
        project = ProjectRepository(session).get_by_id(project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        data = SynopsisService(session).inspect(project_id=project_id)
        return {"ok": True, "action": "inspect.synopsis", "data": data}
    finally:
        session.close()


def _handle_inspect_chapter(arguments: dict[str, str]) -> dict[str, Any]:
    project_id = int(_require_argument(arguments, "project_id"))
    config = load_config()
    session_factory = get_session_factory(_require_database_url(config.database_url))
    session = session_factory()
    try:
        project = ProjectRepository(session).get_by_id(project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        data = ChapterQueryService(session).inspect_chapter(
            project_id=project_id,
            chapter_id=_parse_optional_int(arguments.get("chapter_id")),
            chapter_index=_parse_optional_int(arguments.get("chapter_index")),
        )
        return {"ok": True, "action": "inspect.chapter", "data": data}
    finally:
        session.close()


def _handle_inspect_chapters(arguments: dict[str, str]) -> dict[str, Any]:
    project_id = int(_require_argument(arguments, "project_id"))
    scope = ScopeService().build_scope(
        arguments.get("scope_type", "all"),
        scope_start=arguments.get("scope_start"),
        scope_end=arguments.get("scope_end"),
        scope_chapters=arguments.get("scope_chapters"),
    )
    ensure_scope_supported(scope, stage="chaptering", allowed_types=get_stage_scope_types("chaptering"))

    config = load_config()
    session_factory = get_session_factory(_require_database_url(config.database_url))
    session = session_factory()
    try:
        project = ProjectRepository(session).get_by_id(project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        data = ChapterQueryService(session).inspect_chapters(
            project_id=project_id,
            scope=scope,
            include_segments=_parse_bool(arguments.get("include_segments")),
        )
        return {"ok": True, "action": "inspect.chapters", "data": data}
    finally:
        session.close()


def _handle_inspect_segment(arguments: dict[str, str]) -> dict[str, Any]:
    project_id = int(_require_argument(arguments, "project_id"))
    config = load_config()
    session_factory = get_session_factory(_require_database_url(config.database_url))
    session = session_factory()
    try:
        project = ProjectRepository(session).get_by_id(project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        data = ChapterQueryService(session).inspect_segment(
            project_id=project_id,
            segment_id=_parse_optional_int(arguments.get("segment_id")),
            chapter_index=_parse_optional_int(arguments.get("chapter_index")),
            segment_index=_parse_optional_int(arguments.get("segment_index")),
        )
        return {"ok": True, "action": "inspect.segment", "data": data}
    finally:
        session.close()


def _handle_inspect_translation(arguments: dict[str, str]) -> dict[str, Any]:
    project_id = int(_require_argument(arguments, "project_id"))
    config = load_config()
    session_factory = get_session_factory(_require_database_url(config.database_url))
    session = session_factory()
    try:
        project = ProjectRepository(session).get_by_id(project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        data = TranslationService(session, base_data_dir=config.data_dir).inspect(project_id=project_id)
        return {"ok": True, "action": "inspect.translation", "data": data}
    finally:
        session.close()


def _handle_inspect_review(arguments: dict[str, str]) -> dict[str, Any]:
    project_id = int(_require_argument(arguments, "project_id"))
    config = load_config()
    session_factory = get_session_factory(_require_database_url(config.database_url))
    session = session_factory()
    try:
        project = ProjectRepository(session).get_by_id(project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        data = ReviewService(session).inspect(project_id=project_id)
        return {"ok": True, "action": "inspect.review", "data": data}
    finally:
        session.close()


def _handle_inspect_export(arguments: dict[str, str]) -> dict[str, Any]:
    project_id = int(_require_argument(arguments, "project_id"))
    config = load_config()
    session_factory = get_session_factory(_require_database_url(config.database_url))
    session = session_factory()
    try:
        project = ProjectRepository(session).get_by_id(project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        data = ExportService(session, base_data_dir=config.data_dir).inspect(project_id=project_id)
        return {"ok": True, "action": "inspect.export", "data": data}
    finally:
        session.close()


def _open_session():
    config = load_config()
    session_factory = get_session_factory(_require_database_url(config.database_url))
    return session_factory()


def _resolve_model_stage_provider(*, session, config, stage: str, model_profile_id: str):
    if stage not in {"glossary", "translation"}:
        return None
    return build_provider_from_profile(session, config, model_profile_id)


def _require_argument(arguments: dict[str, str], key: str) -> str:
    value = arguments.get(key)
    if value is None or value == "":
        raise ToolError(code="invalid_arguments", message=f"缺少必填参数 {key}。", status=400)
    return value


def _read_argument(arguments: dict[str, str], key: str) -> str:
    value = _read_optional_argument(arguments, key)
    if value is None or value == "":
        raise ToolError(code="invalid_arguments", message=f"缺少必填参数 {key}。", status=400)
    return value


def _read_optional_argument(arguments: dict[str, str], key: str) -> str | None:
    candidates = {
        key,
        key.replace("_", ""),
    }
    for candidate in candidates:
        value = arguments.get(candidate)
        if value is not None:
            return value
    return None


def _parse_json_argument(value: str | dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise ToolError(code="invalid_arguments", message="definition_json 不是有效的 JSON。", status=400) from exc
    if not isinstance(parsed, dict):
        raise ToolError(code="invalid_arguments", message="definition_json 必须是对象。", status=400)
    return parsed


def _parse_json_string_list_argument(value: str | None) -> list[str]:
    if value is None:
        return []
    normalized = value.strip()
    if not normalized:
        return []
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise ToolError(code="invalid_arguments", message="fallback_profile_keys_json 不是有效的 JSON。", status=400) from exc
    if not isinstance(parsed, list):
        raise ToolError(code="invalid_arguments", message="fallback_profile_keys_json 必须是字符串数组。", status=400)
    result: list[str] = []
    for item in parsed:
        if not isinstance(item, str):
            raise ToolError(code="invalid_arguments", message="fallback_profile_keys_json 必须是字符串数组。", status=400)
        result.append(item)
    return result


def _require_database_url(database_url: str | None) -> str:
    if database_url:
        return database_url
    raise ToolError(code="invalid_arguments", message="缺少 LTW_DATABASE_URL。", status=400)


def _count_rows(session, statement) -> int:
    return int(session.execute(statement).scalar_one())


def _build_synopsis_summary(synopsis: Any | None) -> dict[str, dict[str, Any]]:
    if synopsis is None:
        return {
            "source": {"status": "missing", "origin": None, "length": 0},
            "target": {"status": "missing", "origin": None, "length": 0},
        }

    return {
        "source": {
            "status": synopsis.source_synopsis_status,
            "origin": synopsis.source_synopsis_origin if synopsis.source_synopsis_origin is not None else None,
            "length": len(synopsis.source_synopsis_text or ""),
        },
        "target": {
            "status": synopsis.target_synopsis_status,
            "origin": synopsis.target_synopsis_origin if synopsis.target_synopsis_origin is not None else None,
            "length": len(synopsis.target_synopsis_text or ""),
        },
    }


def _parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() not in {"", "false", "0", "no"}


def _parse_optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _resolve_stage_window(*, from_stage: str | None, until_stage: str | None) -> tuple[str, ...]:
    start_index = 0
    end_index = len(STAGE_SEQUENCE) - 1

    if from_stage is not None:
        normalized_from_stage = from_stage.strip().lower()
        if normalized_from_stage not in STAGE_SEQUENCE:
            raise ToolError(code="invalid_arguments", message=f"不支持的 from_stage: {from_stage}", status=400)
        start_index = STAGE_SEQUENCE.index(normalized_from_stage)

    if until_stage is not None:
        normalized_until_stage = until_stage.strip().lower()
        if normalized_until_stage not in STAGE_SEQUENCE:
            raise ToolError(code="invalid_arguments", message=f"不支持的 until_stage: {until_stage}", status=400)
        end_index = STAGE_SEQUENCE.index(normalized_until_stage)

    if start_index > end_index:
        raise ToolError(
            code="invalid_arguments",
            message="from_stage 不能晚于 until_stage。",
            status=400,
        )

    return STAGE_SEQUENCE[start_index : end_index + 1]


def _summarize_stage_result(stage_name: str, result: Any) -> dict[str, Any]:
    if stage_name == "chaptering":
        return {
            "chapter_count": result.chapter_count,
            "segment_count": result.segment_count,
        }
    if stage_name == "glossary":
        return {"candidate_count": result.candidate_count}
    if stage_name == "translation":
        return {
            "translated_segments": result.translated_segments,
            "active_version_ids": result.active_version_ids,
        }
    if stage_name == "review":
        return {
            "issue_count": result.issue_count,
            "run_id": result.run_id,
        }
    return {
        "artifact_count": result.artifact_count,
        "manifest_path": result.manifest_path,
        "run_id": result.run_id,
    }
