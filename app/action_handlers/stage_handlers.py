from __future__ import annotations

from typing import Any

from .. import action_router as router
from ..config import load_config
from ..errors import ToolError
from ..repositories.projects import ProjectRepository
from ..repositories.synopsis import ProjectSynopsisRepository
from ..services.glossary_pipeline_service import GlossaryPipelineService
from ..services.project_query_service import ProjectQueryService
from ..services.scope_service import ScopeService, ensure_scope_supported, get_stage_scope_types
from ..services.stage_service import STAGE_SEQUENCE, StageCommand, StageService
from ..services.translation_pipeline_service import TranslationPipelineService


def _resolve_stage_provider_context(
    *,
    session,
    stage: str,
    arguments: dict[str, str],
) -> dict[str, Any]:
    config = load_config()
    requested_model_profile_id = arguments.get("model_profile_id", "default")
    resolved_provider = router._resolve_model_stage_provider(
        session=session,
        config=config,
        stage=stage,
        model_profile_id=requested_model_profile_id,
    )
    return {
        "config": config,
        "provider": None if resolved_provider is None else resolved_provider.provider,
        "resolved_profile_id": (
            resolved_provider.profile_key if resolved_provider is not None else requested_model_profile_id
        ),
        "resolved_model_name": (
            resolved_provider.model_name
            if resolved_provider is not None
            else arguments.get("provider_model_name")
        ),
    }


def handle_stage_run(arguments: dict[str, str]) -> dict[str, Any]:
    stage = router._require_argument(arguments, "stage").lower()
    if stage not in STAGE_SEQUENCE:
        raise ToolError(
            code="invalid_arguments",
            message="目前只支持 stage=chaptering、glossary、translation、review 或 export。",
            status=400,
        )

    request_id = router._require_argument(arguments, "request_id")
    project_id = int(router._require_argument(arguments, "project_id"))
    model_profile_id = arguments.get("model_profile_id", "default")
    workflow_key = router._read_optional_argument(arguments, "workflow_key")
    resume = router._parse_bool(arguments.get("resume"))
    rerun = router._parse_bool(arguments.get("rerun"))
    scope = ScopeService().build_scope(
        arguments.get("scope_type", "all"),
        scope_start=arguments.get("scope_start"),
        scope_end=arguments.get("scope_end"),
        scope_chapters=arguments.get("scope_chapters"),
    )
    ensure_scope_supported(scope, stage=stage, allowed_types=get_stage_scope_types(stage))

    config = load_config()
    session = router._open_session()
    try:
        router._bootstrap_workflow_profiles(session)
        project = ProjectRepository(session).get_by_id(project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        resolved_provider = router._resolve_model_stage_provider(
            session=session,
            config=config,
            stage=stage,
            model_profile_id=model_profile_id,
        )
        result = StageService(
            session,
            base_data_dir=config.data_dir,
            provider=None if resolved_provider is None else resolved_provider.provider,
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
                    else router._build_synopsis_summary(ProjectSynopsisRepository(session).get_by_project_id(project_id)),
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
                    else router._build_synopsis_summary(ProjectSynopsisRepository(session).get_by_project_id(project_id)),
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
                "synopsis": router._build_synopsis_summary(ProjectSynopsisRepository(session).get_by_project_id(project_id)),
            },
        }
    finally:
        session.close()


def handle_glossary_extract(arguments: dict[str, str]) -> dict[str, Any]:
    session = router._open_session()
    try:
        resolved = _resolve_stage_provider_context(session=session, stage="glossary", arguments=arguments)
        pipeline = GlossaryPipelineService(session, provider=resolved["provider"])
        data = pipeline.extract(
            workflow_run_id=int(router._require_argument(arguments, "workflow_run_id")),
            workflow_step_run_id=int(router._require_argument(arguments, "workflow_step_run_id")),
            project_id=int(router._require_argument(arguments, "project_id")),
            scope=ScopeService().build_scope(
                router._require_argument(arguments, "scope_type"),
                scope_start=arguments.get("scope_start"),
                scope_end=arguments.get("scope_end"),
                scope_chapters=arguments.get("scope_chapters"),
            ),
            model_profile_id=str(resolved["resolved_profile_id"]),
            provider_model_name=resolved["resolved_model_name"],
        )
        session.commit()
        return {"ok": True, "action": "glossary.extract", "data": data}
    finally:
        session.close()


def handle_glossary_normalize(arguments: dict[str, str]) -> dict[str, Any]:
    session = router._open_session()
    try:
        pipeline = GlossaryPipelineService(session)
        data = pipeline.normalize(
            workflow_run_id=int(router._require_argument(arguments, "workflow_run_id")),
            workflow_step_run_id=int(router._require_argument(arguments, "workflow_step_run_id")),
        )
        return {"ok": True, "action": "glossary.normalize", "data": data}
    finally:
        session.close()


def handle_glossary_review_relations(arguments: dict[str, str]) -> dict[str, Any]:
    session = router._open_session()
    try:
        resolved = _resolve_stage_provider_context(session=session, stage="glossary", arguments=arguments)
        pipeline = GlossaryPipelineService(session, provider=resolved["provider"])
        data = pipeline.review_relations(
            workflow_run_id=int(router._require_argument(arguments, "workflow_run_id")),
            workflow_step_run_id=int(router._require_argument(arguments, "workflow_step_run_id")),
            model_profile_id=str(resolved["resolved_profile_id"]),
            provider_model_name=resolved["resolved_model_name"],
        )
        session.commit()
        return {"ok": True, "action": "glossary.review_relations", "data": data}
    finally:
        session.close()


def handle_glossary_review_scope(arguments: dict[str, str]) -> dict[str, Any]:
    session = router._open_session()
    try:
        resolved = _resolve_stage_provider_context(session=session, stage="glossary", arguments=arguments)
        pipeline = GlossaryPipelineService(session, provider=resolved["provider"])
        data = pipeline.review_scope(
            workflow_run_id=int(router._require_argument(arguments, "workflow_run_id")),
            workflow_step_run_id=int(router._require_argument(arguments, "workflow_step_run_id")),
            model_profile_id=str(resolved["resolved_profile_id"]),
            provider_model_name=resolved["resolved_model_name"],
        )
        session.commit()
        return {"ok": True, "action": "glossary.review_scope", "data": data}
    finally:
        session.close()


def handle_glossary_finalize(arguments: dict[str, str]) -> dict[str, Any]:
    session = router._open_session()
    try:
        resolved = _resolve_stage_provider_context(session=session, stage="glossary", arguments=arguments)
        pipeline = GlossaryPipelineService(session, provider=resolved["provider"])
        data = pipeline.finalize(
            workflow_run_id=int(router._require_argument(arguments, "workflow_run_id")),
            workflow_step_run_id=int(router._require_argument(arguments, "workflow_step_run_id")),
            project_id=int(router._require_argument(arguments, "project_id")),
            model_profile_id=str(resolved["resolved_profile_id"]),
            provider_model_name=resolved["resolved_model_name"],
        )
        session.commit()
        return {"ok": True, "action": "glossary.finalize", "data": data}
    finally:
        session.close()


def handle_glossary_inspect_pipeline(arguments: dict[str, str]) -> dict[str, Any]:
    session = router._open_session()
    try:
        pipeline = GlossaryPipelineService(session)
        data = pipeline.inspect_pipeline(
            workflow_run_id=int(router._require_argument(arguments, "workflow_run_id")),
        )
        return {"ok": True, "action": "glossary.inspect_pipeline", "data": data}
    finally:
        session.close()


def handle_translation_generate_draft(arguments: dict[str, str]) -> dict[str, Any]:
    session = router._open_session()
    try:
        resolved = _resolve_stage_provider_context(session=session, stage="translation", arguments=arguments)
        pipeline = TranslationPipelineService(
            session,
            base_data_dir=resolved["config"].data_dir,
            provider=resolved["provider"],
        )
        data = pipeline.generate_draft(
            workflow_run_id=int(router._require_argument(arguments, "workflow_run_id")),
            workflow_step_run_id=int(router._require_argument(arguments, "workflow_step_run_id")),
            project_id=int(router._require_argument(arguments, "project_id")),
            scope=ScopeService().build_scope(
                router._require_argument(arguments, "scope_type"),
                scope_start=arguments.get("scope_start"),
                scope_end=arguments.get("scope_end"),
                scope_chapters=arguments.get("scope_chapters"),
            ),
            model_profile_id=str(resolved["resolved_profile_id"]),
            provider_model_name=resolved["resolved_model_name"],
            draft_role=arguments.get("draft_role", "primary"),
        )
        session.commit()
        return {"ok": True, "action": "translation.generate_draft", "data": data}
    finally:
        session.close()


def handle_translation_finalize(arguments: dict[str, str]) -> dict[str, Any]:
    session = router._open_session()
    try:
        config = load_config()
        pipeline = TranslationPipelineService(session, base_data_dir=config.data_dir)
        data = pipeline.finalize(
            workflow_run_id=int(router._require_argument(arguments, "workflow_run_id")),
            workflow_step_run_id=int(router._require_argument(arguments, "workflow_step_run_id")),
            project_id=int(router._require_argument(arguments, "project_id")),
            model_profile_id=arguments.get("model_profile_id", "default"),
            provider_model_name=arguments.get("provider_model_name"),
        )
        session.commit()
        return {"ok": True, "action": "translation.finalize", "data": data}
    finally:
        session.close()


def handle_translation_review_draft(arguments: dict[str, str]) -> dict[str, Any]:
    session = router._open_session()
    try:
        resolved = _resolve_stage_provider_context(session=session, stage="translation", arguments=arguments)
        pipeline = TranslationPipelineService(
            session,
            base_data_dir=resolved["config"].data_dir,
            provider=resolved["provider"],
        )
        data = pipeline.review_draft(
            workflow_run_id=int(router._require_argument(arguments, "workflow_run_id")),
            workflow_step_run_id=int(router._require_argument(arguments, "workflow_step_run_id")),
            model_profile_id=str(resolved["resolved_profile_id"]),
            provider_model_name=resolved["resolved_model_name"],
        )
        session.commit()
        return {"ok": True, "action": "translation.review_draft", "data": data}
    finally:
        session.close()


def handle_translation_rewrite_draft(arguments: dict[str, str]) -> dict[str, Any]:
    session = router._open_session()
    try:
        resolved = _resolve_stage_provider_context(session=session, stage="translation", arguments=arguments)
        pipeline = TranslationPipelineService(
            session,
            base_data_dir=resolved["config"].data_dir,
            provider=resolved["provider"],
        )
        data = pipeline.rewrite_draft(
            workflow_run_id=int(router._require_argument(arguments, "workflow_run_id")),
            workflow_step_run_id=int(router._require_argument(arguments, "workflow_step_run_id")),
            model_profile_id=str(resolved["resolved_profile_id"]),
            provider_model_name=resolved["resolved_model_name"],
        )
        session.commit()
        return {"ok": True, "action": "translation.rewrite_draft", "data": data}
    finally:
        session.close()


def handle_translation_inspect_pipeline(arguments: dict[str, str]) -> dict[str, Any]:
    session = router._open_session()
    try:
        config = load_config()
        pipeline = TranslationPipelineService(session, base_data_dir=config.data_dir)
        data = pipeline.inspect_pipeline(
            workflow_run_id=int(router._require_argument(arguments, "workflow_run_id")),
        )
        return {"ok": True, "action": "translation.inspect_pipeline", "data": data}
    finally:
        session.close()


def handle_stage_inspect_runs(arguments: dict[str, str]) -> dict[str, Any]:
    session = router._open_session()
    try:
        data = ProjectQueryService(session).inspect_stage_runs(
            project_id=int(router._require_argument(arguments, "project_id")),
            stage=arguments.get("stage"),
            limit=router._parse_optional_int(arguments.get("limit")) or 20,
        )
        return {"ok": True, "action": "stage.inspect_runs", "data": data}
    finally:
        session.close()


STAGE_ACTION_HANDLERS = {
    "stage.run": handle_stage_run,
    "stage.inspect_runs": handle_stage_inspect_runs,
    "glossary.extract": handle_glossary_extract,
    "glossary.normalize": handle_glossary_normalize,
    "glossary.review_relations": handle_glossary_review_relations,
    "glossary.review_scope": handle_glossary_review_scope,
    "glossary.finalize": handle_glossary_finalize,
    "glossary.inspect_pipeline": handle_glossary_inspect_pipeline,
    "translation.generate_draft": handle_translation_generate_draft,
    "translation.review_draft": handle_translation_review_draft,
    "translation.rewrite_draft": handle_translation_rewrite_draft,
    "translation.finalize": handle_translation_finalize,
    "translation.inspect_pipeline": handle_translation_inspect_pipeline,
}
