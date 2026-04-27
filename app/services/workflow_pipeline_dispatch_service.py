from __future__ import annotations

from typing import Any, Mapping

from ..errors import ToolError


class WorkflowPipelineDispatchService:
    def run_glossary_action(
        self,
        *,
        action: str,
        pipeline,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        scope: Mapping[str, Any],
        model_profile_id: str,
        provider_model_name: str | None,
    ) -> dict[str, object]:
        if action == "glossary.extract":
            return pipeline.extract(
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=workflow_step_run_id,
                project_id=project_id,
                scope=dict(scope),
                model_profile_id=model_profile_id,
                provider_model_name=provider_model_name,
            )
        if action == "glossary.normalize":
            return pipeline.normalize(
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=workflow_step_run_id,
            )
        if action == "glossary.review_relations":
            return pipeline.review_relations(
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=workflow_step_run_id,
                model_profile_id=model_profile_id,
                provider_model_name=provider_model_name,
            )
        if action == "glossary.review_scope":
            return pipeline.review_scope(
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=workflow_step_run_id,
                model_profile_id=model_profile_id,
                provider_model_name=provider_model_name,
            )
        if action == "glossary.finalize":
            return pipeline.finalize(
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=workflow_step_run_id,
                project_id=project_id,
                model_profile_id=model_profile_id,
                provider_model_name=provider_model_name,
            )
        if action == "glossary.inspect_pipeline":
            return pipeline.inspect_pipeline(workflow_run_id=workflow_run_id)
        raise ToolError(code="invalid_arguments", message=f"不支持的 glossary workflow action: {action}。", status=400)

    def run_translation_action(
        self,
        *,
        action: str,
        pipeline,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        scope: Mapping[str, Any],
        model_profile_id: str,
        provider_model_name: str | None,
        step_definition: Mapping[str, Any],
        heartbeat=None,
    ) -> dict[str, object]:
        if action == "translation.generate_draft":
            return pipeline.generate_draft(
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=workflow_step_run_id,
                project_id=project_id,
                scope=dict(scope),
                model_profile_id=model_profile_id,
                provider_model_name=provider_model_name,
                draft_role=str(step_definition.get("draft_role") or "primary"),
                heartbeat=heartbeat,
            )
        if action == "translation.review_draft":
            return pipeline.review_draft(
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=workflow_step_run_id,
                model_profile_id=model_profile_id,
                provider_model_name=provider_model_name,
                heartbeat=heartbeat,
            )
        if action == "translation.rewrite_draft":
            return pipeline.rewrite_draft(
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=workflow_step_run_id,
                model_profile_id=model_profile_id,
                provider_model_name=provider_model_name,
                heartbeat=heartbeat,
            )
        if action == "translation.finalize":
            return pipeline.finalize(
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=workflow_step_run_id,
                project_id=project_id,
                model_profile_id=model_profile_id,
                provider_model_name=provider_model_name,
                heartbeat=heartbeat,
            )
        if action == "translation.inspect_pipeline":
            return pipeline.inspect_pipeline(workflow_run_id=workflow_run_id)
        raise ToolError(code="invalid_arguments", message=f"不支持的 translation workflow action: {action}。", status=400)
