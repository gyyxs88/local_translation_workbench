from __future__ import annotations

from typing import Any

from .. import action_support as support
from ..config import load_config
from ..errors import ToolError
from ..services.glossary_pipeline_service import GlossaryPipelineService
from ..services.project_query_service import ProjectQueryService
from ..services.schema_version_service import assert_database_schema_current
from ..services.stage_run_response_service import build_stage_run_response
from ..services.scope_service import ScopeService, ensure_scope_supported, get_stage_scope_types
from ..services.stage_service import STAGE_SEQUENCE
from ..services.translation_pipeline_service import TranslationPipelineService
from ..stage_action_support import run_glossary_pipeline_action, run_translation_pipeline_action
from .stage_execution import execute_stage_command


def handle_stage_run(arguments: dict[str, str]) -> dict[str, Any]:
    stage = support._require_argument(arguments, "stage").lower()
    if stage not in STAGE_SEQUENCE:
        raise ToolError(
            code="invalid_arguments",
            message="目前只支持 stage=chaptering、glossary、translation、review 或 export。",
            status=400,
        )

    request_id = support._require_argument(arguments, "request_id")
    project_id = support._parse_required_int_argument(arguments, "project_id")
    model_profile_id = arguments.get("model_profile_id", "default")
    workflow_key = support._read_optional_argument(arguments, "workflow_key")
    route_preset_key = support._read_optional_argument(arguments, "route_preset_key")
    review_mode = (
        arguments.get("review_mode")
        or arguments.get("reviewmode")
        or "hybrid"
    ).strip().lower()
    max_rewrite_rounds = support._parse_int_value(
        arguments.get("max_rewrite_rounds")
        or arguments.get("maxrewriterounds")
        or "2",
        argument_name="max_rewrite_rounds",
    )
    resume = support._parse_bool(arguments.get("resume"))
    rerun = support._parse_bool(arguments.get("rerun"))
    scope = ScopeService().build_scope(
        arguments.get("scope_type", "all"),
        scope_start=arguments.get("scope_start"),
        scope_end=arguments.get("scope_end"),
        scope_chapters=arguments.get("scope_chapters"),
    )
    ensure_scope_supported(scope, stage=stage, allowed_types=get_stage_scope_types(stage))

    config = load_config()
    session = support._open_session()
    try:
        assert_database_schema_current(session)
        support._bootstrap_workflow_profiles(session)
        result = execute_stage_command(
            session=session,
            config=config,
            request_id=request_id,
            project_id=project_id,
            stage=stage,
            scope=scope,
            model_profile_id=model_profile_id,
            workflow_key=workflow_key,
            route_preset_key=route_preset_key,
            review_mode=review_mode,
            max_rewrite_rounds=max_rewrite_rounds,
            resume=resume,
            rerun=rerun,
        )
        return build_stage_run_response(
            session=session,
            project_id=project_id,
            stage=stage,
            scope=scope,
            result=result,
            request_id=request_id,
        )
    finally:
        session.close()


def handle_glossary_extract(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        return run_glossary_pipeline_action(
            session=session,
            arguments=arguments,
            action_name="glossary.extract",
            runner=lambda pipeline, context: pipeline.extract(
                workflow_run_id=support._parse_required_int_argument(arguments, "workflow_run_id"),
                workflow_step_run_id=support._parse_required_int_argument(arguments, "workflow_step_run_id"),
                project_id=support._parse_required_int_argument(arguments, "project_id"),
                scope=ScopeService().build_scope(
                    support._require_argument(arguments, "scope_type"),
                    scope_start=arguments.get("scope_start"),
                    scope_end=arguments.get("scope_end"),
                    scope_chapters=arguments.get("scope_chapters"),
                ),
                model_profile_id=context.resolved_profile_id,
                provider_model_name=context.resolved_model_name,
            ),
        )
    finally:
        session.close()


def handle_glossary_normalize(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        pipeline = GlossaryPipelineService(session)
        data = pipeline.normalize(
            workflow_run_id=support._parse_required_int_argument(arguments, "workflow_run_id"),
            workflow_step_run_id=support._parse_required_int_argument(arguments, "workflow_step_run_id"),
        )
        return {"ok": True, "action": "glossary.normalize", "data": data}
    finally:
        session.close()


def handle_glossary_review_relations(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        return run_glossary_pipeline_action(
            session=session,
            arguments=arguments,
            action_name="glossary.review_relations",
            runner=lambda pipeline, context: pipeline.review_relations(
                workflow_run_id=support._parse_required_int_argument(arguments, "workflow_run_id"),
                workflow_step_run_id=support._parse_required_int_argument(arguments, "workflow_step_run_id"),
                model_profile_id=context.resolved_profile_id,
                provider_model_name=context.resolved_model_name,
            ),
        )
    finally:
        session.close()


def handle_glossary_review_scope(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        return run_glossary_pipeline_action(
            session=session,
            arguments=arguments,
            action_name="glossary.review_scope",
            runner=lambda pipeline, context: pipeline.review_scope(
                workflow_run_id=support._parse_required_int_argument(arguments, "workflow_run_id"),
                workflow_step_run_id=support._parse_required_int_argument(arguments, "workflow_step_run_id"),
                model_profile_id=context.resolved_profile_id,
                provider_model_name=context.resolved_model_name,
            ),
        )
    finally:
        session.close()


def handle_glossary_review_consistency(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        return run_glossary_pipeline_action(
            session=session,
            arguments=arguments,
            action_name="glossary.review_consistency",
            runner=lambda pipeline, context: pipeline.review_consistency(
                workflow_run_id=support._parse_required_int_argument(arguments, "workflow_run_id"),
                workflow_step_run_id=support._parse_required_int_argument(arguments, "workflow_step_run_id"),
                project_id=support._parse_required_int_argument(arguments, "project_id"),
                model_profile_id=context.resolved_profile_id,
                provider_model_name=context.resolved_model_name,
            ),
        )
    finally:
        session.close()


def handle_glossary_finalize(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        return run_glossary_pipeline_action(
            session=session,
            arguments=arguments,
            action_name="glossary.finalize",
            runner=lambda pipeline, context: pipeline.finalize(
                workflow_run_id=support._parse_required_int_argument(arguments, "workflow_run_id"),
                workflow_step_run_id=support._parse_required_int_argument(arguments, "workflow_step_run_id"),
                project_id=support._parse_required_int_argument(arguments, "project_id"),
                model_profile_id=context.resolved_profile_id,
                provider_model_name=context.resolved_model_name,
            ),
        )
    finally:
        session.close()


def handle_glossary_inspect_pipeline(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        pipeline = GlossaryPipelineService(session)
        data = pipeline.inspect_pipeline(
            workflow_run_id=support._parse_required_int_argument(arguments, "workflow_run_id"),
        )
        return {"ok": True, "action": "glossary.inspect_pipeline", "data": data}
    finally:
        session.close()


def handle_translation_generate_draft(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        return run_translation_pipeline_action(
            session=session,
            arguments=arguments,
            action_name="translation.generate_draft",
            runner=lambda pipeline, context: pipeline.generate_draft(
                workflow_run_id=support._parse_required_int_argument(arguments, "workflow_run_id"),
                workflow_step_run_id=support._parse_required_int_argument(arguments, "workflow_step_run_id"),
                project_id=support._parse_required_int_argument(arguments, "project_id"),
                scope=ScopeService().build_scope(
                    support._require_argument(arguments, "scope_type"),
                    scope_start=arguments.get("scope_start"),
                    scope_end=arguments.get("scope_end"),
                    scope_chapters=arguments.get("scope_chapters"),
                ),
                model_profile_id=context.resolved_profile_id,
                provider_model_name=context.resolved_model_name,
                draft_role=arguments.get("draft_role", "primary"),
            ),
        )
    finally:
        session.close()


def handle_translation_finalize(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        config = load_config()
        pipeline = TranslationPipelineService(session, base_data_dir=config.data_dir)
        data = pipeline.finalize(
            workflow_run_id=support._parse_required_int_argument(arguments, "workflow_run_id"),
            workflow_step_run_id=support._parse_required_int_argument(arguments, "workflow_step_run_id"),
            project_id=support._parse_required_int_argument(arguments, "project_id"),
            model_profile_id=arguments.get("model_profile_id", "default"),
            provider_model_name=arguments.get("provider_model_name"),
        )
        session.commit()
        return {"ok": True, "action": "translation.finalize", "data": data}
    finally:
        session.close()


def handle_translation_review_draft(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        return run_translation_pipeline_action(
            session=session,
            arguments=arguments,
            action_name="translation.review_draft",
            runner=lambda pipeline, context: pipeline.review_draft(
                workflow_run_id=support._parse_required_int_argument(arguments, "workflow_run_id"),
                workflow_step_run_id=support._parse_required_int_argument(arguments, "workflow_step_run_id"),
                model_profile_id=context.resolved_profile_id,
                provider_model_name=context.resolved_model_name,
            ),
        )
    finally:
        session.close()


def handle_translation_rewrite_draft(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        return run_translation_pipeline_action(
            session=session,
            arguments=arguments,
            action_name="translation.rewrite_draft",
            runner=lambda pipeline, context: pipeline.rewrite_draft(
                workflow_run_id=support._parse_required_int_argument(arguments, "workflow_run_id"),
                workflow_step_run_id=support._parse_required_int_argument(arguments, "workflow_step_run_id"),
                model_profile_id=context.resolved_profile_id,
                provider_model_name=context.resolved_model_name,
            ),
        )
    finally:
        session.close()


def handle_translation_inspect_pipeline(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        config = load_config()
        pipeline = TranslationPipelineService(session, base_data_dir=config.data_dir)
        data = pipeline.inspect_pipeline(
            workflow_run_id=support._parse_required_int_argument(arguments, "workflow_run_id"),
        )
        return {"ok": True, "action": "translation.inspect_pipeline", "data": data}
    finally:
        session.close()


def handle_stage_inspect_runs(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        data = ProjectQueryService(session).inspect_stage_runs(
            project_id=support._parse_required_int_argument(arguments, "project_id"),
            stage=arguments.get("stage"),
            limit=support._parse_optional_int(arguments.get("limit")) or 20,
        )
        return {"ok": True, "action": "stage.inspect_runs", "data": data}
    finally:
        session.close()


def handle_stage_cancel(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        data = ProjectQueryService(session).cancel_stage_run(
            project_id=support._parse_required_int_argument(arguments, "project_id"),
            request_id=support._require_argument(arguments, "request_id"),
            stage_run_id=support._parse_optional_int(arguments.get("stage_run_id")),
            stage=arguments.get("stage"),
        )
        return {"ok": True, "action": "stage.cancel", "data": data}
    finally:
        session.close()


STAGE_ACTION_HANDLERS = {
    "stage.run": handle_stage_run,
    "stage.cancel": handle_stage_cancel,
    "stage.inspect_runs": handle_stage_inspect_runs,
    "glossary.extract": handle_glossary_extract,
    "glossary.normalize": handle_glossary_normalize,
    "glossary.review_relations": handle_glossary_review_relations,
    "glossary.review_scope": handle_glossary_review_scope,
    "glossary.review_consistency": handle_glossary_review_consistency,
    "glossary.finalize": handle_glossary_finalize,
    "glossary.inspect_pipeline": handle_glossary_inspect_pipeline,
    "translation.generate_draft": handle_translation_generate_draft,
    "translation.review_draft": handle_translation_review_draft,
    "translation.rewrite_draft": handle_translation_rewrite_draft,
    "translation.finalize": handle_translation_finalize,
    "translation.inspect_pipeline": handle_translation_inspect_pipeline,
}
