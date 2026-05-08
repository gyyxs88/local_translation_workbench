from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ..db.models import WorkflowRun, WorkflowStepRun
from ..errors import ToolError
from ..config import load_config
from ..providers.router import build_provider_from_profile
from ..repositories.workflows import WorkflowRepository
from .workflow_group_executor_service import WorkflowGroupExecutorService
from .workflow_pipeline_dispatch_service import WorkflowPipelineDispatchService
from .workflow_step_executor_service import WorkflowStepExecutorService
from .workflow_token_usage_service import WorkflowTokenUsageService

SUPPORTED_GLOSSARY_WORKFLOW_ACTIONS = frozenset(
    {
        "glossary.extract",
        "glossary.normalize",
        "glossary.review_relations",
        "glossary.review_scope",
        "glossary.review_consistency",
        "glossary.finalize",
        "glossary.inspect_pipeline",
    }
)

SUPPORTED_TRANSLATION_WORKFLOW_ACTIONS = frozenset(
    {
        "translation.generate_draft",
        "translation.review_draft",
        "translation.rewrite_draft",
        "translation.finalize",
        "translation.inspect_pipeline",
    }
)


class WorkflowRuntimeService:
    def __init__(self, session) -> None:
        self.session = session
        self.repository = WorkflowRepository(session)
        self.log_session_factory = sessionmaker(bind=session.get_bind(), future=True)
        self.step_executor = WorkflowStepExecutorService(session)
        self.group_executor = WorkflowGroupExecutorService()
        self.pipeline_dispatch = WorkflowPipelineDispatchService()
        self.token_usage = WorkflowTokenUsageService(session)

    def resolve_step_model_profile_id(
        self,
        step_definition: Mapping[str, Any],
        request_payload: Mapping[str, Any],
    ) -> str:
        return self.step_executor.resolve_step_model_profile_id(step_definition, request_payload)

    def resolve_workflow_profile(self, workflow_key: str) -> dict[str, Any]:
        profile = self.repository.get_profile(workflow_key)
        if profile is None:
            raise ToolError(code="not_found", message=f"找不到 workflow {workflow_key}。", status=404)
        return self._serialize_profile(profile)

    def resolve_workflow_definition(self, *, stage: str, workflow_key: str | None = None) -> dict[str, Any]:
        normalized_stage = stage.strip().lower()
        if workflow_key is not None and workflow_key.strip() != "":
            profile = self.resolve_workflow_profile(workflow_key.strip())
            if str(profile["stage"]).strip().lower() != normalized_stage:
                raise ToolError(
                    code="invalid_arguments",
                    message=f"workflow {workflow_key.strip()} 不属于 stage={normalized_stage}。",
                    status=400,
                )
            return profile

        profiles = [self._serialize_profile(item) for item in self.repository.list_profiles(stage=normalized_stage)]
        for profile in profiles:
            if bool(profile["is_default"]):
                return profile
        if profiles:
            return profiles[0]
        raise ToolError(code="not_found", message=f"stage={normalized_stage} 没有可用 workflow。", status=404)

    def create_workflow_run(
        self,
        *,
        workflow_key: str,
        project_id: int,
        scope: Mapping[str, Any],
        request_id: str,
        status: str = "running",
        summary: str | None = None,
    ) -> Any:
        profile = self.resolve_workflow_profile(workflow_key)
        try:
            return self.repository.create_run(
                workflow_key=profile["workflow_key"],
                project_id=project_id,
                stage=str(profile["stage"]),
                scope_type=str(scope.get("type", "all")),
                scope_value=json.dumps(dict(scope), ensure_ascii=False),
                request_id=request_id,
                status=status,
                summary=summary,
            )
        except ValueError as exc:
            raise self._tool_error_from_value_error(exc) from exc

    def create_step_run(
        self,
        *,
        workflow_run_id: int,
        step_key: str,
        action: str,
        llm_role: str,
        model_profile_id: str,
        status: str = "running",
        input_ref: str,
        output_payload: dict[str, Any] | None = None,
        summary: str | None = None,
    ):
        return self.repository.create_step_run(
            workflow_run_id=workflow_run_id,
            step_key=step_key,
            action=action,
            llm_role=llm_role,
            model_profile_id=model_profile_id,
            status=status,
            input_ref=input_ref,
            output_payload=output_payload,
            summary=summary,
        )

    def mark_run_status(
        self,
        workflow_run_id: int,
        *,
        status: str,
        summary: Mapping[str, Any] | str | None = None,
    ):
        try:
            return self.repository.update_run(
                workflow_run_id,
                status=status,
                summary=self._serialize_json_text(summary),
            )
        except ValueError as exc:
            raise self._tool_error_from_value_error(exc) from exc

    def mark_step_status(
        self,
        step_run_id: int,
        *,
        status: str,
        output_payload: dict[str, Any] | None = None,
    ):
        try:
            return self.repository.update_step_run(
                step_run_id,
                status=status,
                output_payload=self._serialize_json_payload(output_payload),
            )
        except ValueError as exc:
            raise self._tool_error_from_value_error(exc) from exc

    def run_glossary_workflow(
        self,
        *,
        workflow_definition: Mapping[str, Any],
        workflow_key: str,
        request_id: str,
        project_id: int,
        scope: Mapping[str, Any],
        request_model_profile_id: str,
        provider_model_name: str | None,
        pipeline,
        stage_run_id: int | None = None,
        route_preset_key: str | None = None,
        heartbeat=None,
    ):
        run_summary = json.dumps(
            {
                "request_id": request_id,
                "workflow_key": workflow_key,
                "stage_run_id": stage_run_id,
            },
            ensure_ascii=False,
        )
        workflow_stage = str(workflow_definition.get("stage") or "glossary")
        workflow_run = self.create_workflow_run(
            workflow_key=workflow_key,
            project_id=project_id,
            scope=scope,
            request_id=request_id,
            summary=run_summary,
        )
        steps = workflow_definition.get("definition_json", {}).get("steps", [])
        if not isinstance(steps, list) or not steps:
            raise ToolError(code="invalid_arguments", message=f"workflow {workflow_key} 没有可执行 steps。", status=400)
        self._commit_visibility_checkpoint()
        terminal_status = self._read_terminal_status_map(workflow_definition)

        finalize_payload: dict[str, object] | None = None
        executed_steps: list[dict[str, Any]] = []
        workflow_degraded = False
        degradation_events: list[dict[str, Any]] = []
        try:
            step_index = 0
            while step_index < len(steps):
                step = steps[step_index]
                if not isinstance(step, Mapping):
                    raise ToolError(code="invalid_arguments", message=f"workflow {workflow_key} 存在无效 step。", status=400)
                policy = self.group_executor.read_step_execution_policy(step)
                group_steps, next_step_index = self.group_executor.collect_step_group(
                    steps=steps,
                    start_index=step_index,
                    policy=policy,
                )
                if policy["failure_mode"] == "required":
                    step_execution = self._execute_glossary_workflow_step(
                        step_definition=step,
                        step_index=step_index + 1,
                        workflow_run_id=workflow_run.id,
                        request_id=request_id,
                        request_model_profile_id=request_model_profile_id,
                        request_provider_model_name=provider_model_name,
                        route_preset_key=route_preset_key,
                        project_id=project_id,
                        scope=scope,
                        pipeline=pipeline,
                        heartbeat=heartbeat,
                        allow_failure=False,
                    )
                    executed_steps.append(dict(step_execution["step_log"]))
                    if isinstance(step_execution.get("finalize_payload"), dict):
                        finalize_payload = dict(step_execution["finalize_payload"])
                else:
                    group_result = self._execute_glossary_step_group(
                        step_definitions=group_steps,
                        first_step_index=step_index + 1,
                        workflow_run_id=workflow_run.id,
                        request_id=request_id,
                        request_model_profile_id=request_model_profile_id,
                        request_provider_model_name=provider_model_name,
                        route_preset_key=route_preset_key,
                        project_id=project_id,
                        scope=scope,
                        pipeline=pipeline,
                        heartbeat=heartbeat,
                        policy=policy,
                    )
                    executed_steps.extend(dict(item) for item in group_result["step_logs"])
                    if group_result["degraded"]:
                        workflow_degraded = True
                        degradation_events.append(
                            {
                                "failure_mode": policy["failure_mode"],
                                "minimum_success": policy["minimum_success"],
                                "success_count": group_result["success_count"],
                                "failed_step_keys": list(group_result["failed_step_keys"]),
                            }
                        )
                    if isinstance(group_result.get("finalize_payload"), dict):
                        finalize_payload = dict(group_result["finalize_payload"])
                step_index = next_step_index
            result, summary_payload = self._resolve_glossary_workflow_result(
                pipeline=pipeline,
                project_id=project_id,
                workflow_run_id=workflow_run.id,
                finalize_payload=finalize_payload,
            )
            final_run_status = "completed"
            degradation_reason: str | None = None
            if workflow_degraded:
                degradation_reason = "low_confidence"
                final_run_status = self._resolve_terminal_run_status(
                    terminal_status=terminal_status,
                    degradation_reason=degradation_reason,
                )
            self.mark_run_status(
                workflow_run.id,
                status=final_run_status,
                summary=(
                    summary_payload
                    | {
                        "request_id": request_id,
                        "workflow_key": workflow_key,
                    }
                    | (
                        {
                            "degraded": workflow_degraded,
                            "degradation_events": degradation_events,
                            "degradation_reason": degradation_reason,
                        }
                        if workflow_degraded
                        else {"degraded": False}
                    )
                    | ({"terminal_status": terminal_status} if terminal_status is not None else {})
                ),
            )
            return result
        except Exception as exc:
            failed_status = "cancelled" if self._is_cancelled_error(exc) else "failed"
            pending_step_logs = getattr(exc, "_workflow_step_logs", None)
            if isinstance(pending_step_logs, list):
                executed_steps.extend(
                    dict(item) for item in pending_step_logs if isinstance(item, Mapping)
                )
            failed_summary = (
                {
                    "request_id": request_id,
                    "workflow_key": workflow_key,
                    "error": str(exc),
                }
                | (
                    {"token_usage": self.token_usage.summarize_step_logs(executed_steps)}
                    if self.token_usage.summarize_step_logs(executed_steps) is not None
                    else {}
                )
                | ({"terminal_status": terminal_status} if terminal_status is not None else {})
            )
            self.mark_run_status(
                workflow_run.id,
                status=failed_status,
                summary=failed_summary,
            )
            setattr(
                exc,
                "_workflow_failure_context",
                {
                    "workflow_run": {
                        "id": workflow_run.id,
                        "workflow_key": workflow_key,
                        "project_id": project_id,
                        "stage": workflow_stage,
                        "scope": dict(scope),
                        "request_id": request_id,
                        "status": failed_status,
                        "summary": self._serialize_json_text(failed_summary),
                    },
                    "step_runs": [dict(item) for item in executed_steps],
                },
            )
            raise

    def run_translation_workflow(
        self,
        *,
        workflow_definition: Mapping[str, Any],
        workflow_key: str,
        request_id: str,
        project_id: int,
        scope: Mapping[str, Any],
        request_model_profile_id: str,
        provider_model_name: str | None,
        pipeline,
        stage_run_id: int | None = None,
        route_preset_key: str | None = None,
        heartbeat=None,
    ):
        run_summary = json.dumps(
            {
                "request_id": request_id,
                "workflow_key": workflow_key,
                "stage_run_id": stage_run_id,
            },
            ensure_ascii=False,
        )
        workflow_stage = str(workflow_definition.get("stage") or "translation")
        workflow_run = self.create_workflow_run(
            workflow_key=workflow_key,
            project_id=project_id,
            scope=scope,
            request_id=request_id,
            summary=run_summary,
        )
        steps = workflow_definition.get("definition_json", {}).get("steps", [])
        if not isinstance(steps, list) or not steps:
            raise ToolError(code="invalid_arguments", message=f"workflow {workflow_key} 没有可执行 steps。", status=400)
        self._commit_visibility_checkpoint()
        terminal_status = self._read_terminal_status_map(workflow_definition)

        finalize_payload: dict[str, object] | None = None
        executed_steps: list[dict[str, Any]] = []
        workflow_degraded = False
        degradation_events: list[dict[str, Any]] = []
        try:
            step_index = 0
            while step_index < len(steps):
                step = steps[step_index]
                if not isinstance(step, Mapping):
                    raise ToolError(code="invalid_arguments", message=f"workflow {workflow_key} 存在无效 step。", status=400)
                policy = self.group_executor.read_step_execution_policy(step)
                group_steps, next_step_index = self.group_executor.collect_step_group(
                    steps=steps,
                    start_index=step_index,
                    policy=policy,
                )
                if policy["failure_mode"] == "required":
                    step_execution = self._execute_translation_workflow_step(
                        step_definition=step,
                        step_index=step_index + 1,
                        workflow_run_id=workflow_run.id,
                        request_id=request_id,
                        request_model_profile_id=request_model_profile_id,
                        request_provider_model_name=provider_model_name,
                        route_preset_key=route_preset_key,
                        project_id=project_id,
                        scope=scope,
                        pipeline=pipeline,
                        heartbeat=heartbeat,
                        allow_failure=False,
                    )
                    executed_steps.append(dict(step_execution["step_log"]))
                    if isinstance(step_execution.get("finalize_payload"), dict):
                        finalize_payload = dict(step_execution["finalize_payload"])
                else:
                    group_result = self._execute_translation_step_group(
                        step_definitions=group_steps,
                        first_step_index=step_index + 1,
                        workflow_run_id=workflow_run.id,
                        request_id=request_id,
                        request_model_profile_id=request_model_profile_id,
                        request_provider_model_name=provider_model_name,
                        route_preset_key=route_preset_key,
                        project_id=project_id,
                        scope=scope,
                        pipeline=pipeline,
                        heartbeat=heartbeat,
                        policy=policy,
                    )
                    executed_steps.extend(dict(item) for item in group_result["step_logs"])
                    if group_result["degraded"]:
                        workflow_degraded = True
                        degradation_events.append(
                            {
                                "failure_mode": policy["failure_mode"],
                                "minimum_success": policy["minimum_success"],
                                "success_count": group_result["success_count"],
                                "failed_step_keys": list(group_result["failed_step_keys"]),
                            }
                        )
                    if isinstance(group_result.get("finalize_payload"), dict):
                        finalize_payload = dict(group_result["finalize_payload"])
                step_index = next_step_index

            result, summary_payload = self._resolve_translation_workflow_result(
                pipeline=pipeline,
                project_id=project_id,
                workflow_run_id=workflow_run.id,
                finalize_payload=finalize_payload,
            )
            final_run_status = "completed"
            degradation_reason: str | None = None
            if workflow_degraded:
                degradation_reason = "low_confidence"
                final_run_status = self._resolve_terminal_run_status(
                    terminal_status=terminal_status,
                    degradation_reason=degradation_reason,
                )
            self.mark_run_status(
                workflow_run.id,
                status=final_run_status,
                summary=(
                    summary_payload
                    | {"request_id": request_id, "workflow_key": workflow_key}
                    | (
                        {
                            "degraded": workflow_degraded,
                            "degradation_events": degradation_events,
                            "degradation_reason": degradation_reason,
                        }
                        if workflow_degraded
                        else {"degraded": False}
                    )
                    | ({"terminal_status": terminal_status} if terminal_status is not None else {})
                ),
            )
            return result
        except Exception as exc:
            failed_status = "cancelled" if self._is_cancelled_error(exc) else "failed"
            pending_step_logs = getattr(exc, "_workflow_step_logs", None)
            if isinstance(pending_step_logs, list):
                executed_steps.extend(
                    dict(item) for item in pending_step_logs if isinstance(item, Mapping)
                )
            failed_summary = {
                "request_id": request_id,
                "workflow_key": workflow_key,
                "error": str(exc),
            } | (
                {"token_usage": self.token_usage.summarize_step_logs(executed_steps)}
                if self.token_usage.summarize_step_logs(executed_steps) is not None
                else {}
            ) | ({"terminal_status": terminal_status} if terminal_status is not None else {})
            self.mark_run_status(
                workflow_run.id,
                status=failed_status,
                summary=failed_summary,
            )
            setattr(
                exc,
                "_workflow_failure_context",
                {
                    "workflow_run": {
                        "id": workflow_run.id,
                        "workflow_key": workflow_key,
                        "project_id": project_id,
                        "stage": workflow_stage,
                        "scope": dict(scope),
                        "request_id": request_id,
                        "status": failed_status,
                        "summary": self._serialize_json_text(failed_summary),
                    },
                    "step_runs": [dict(item) for item in executed_steps],
                },
            )
            raise

    def _execute_glossary_step_group(
        self,
        *,
        step_definitions: list[Mapping[str, Any]],
        first_step_index: int,
        workflow_run_id: int,
        request_id: str,
        request_model_profile_id: str,
        request_provider_model_name: str | None,
        route_preset_key: str | None,
        project_id: int,
        scope: Mapping[str, Any],
        pipeline,
        heartbeat,
        policy: Mapping[str, Any],
    ) -> dict[str, Any]:
        group_action = str(step_definitions[0].get("action") or "<unknown>")
        if (
            len(step_definitions) > 1
            and group_action == "glossary.extract"
        ):
            prepared_steps: list[dict[str, Any]] = []
            for offset, step_definition in enumerate(step_definitions):
                prepared_step = self.step_executor.prepare_step_execution(
                    step_definition=step_definition,
                    step_index=first_step_index + offset,
                    workflow_run_id=workflow_run_id,
                    request_id=request_id,
                    request_model_profile_id=request_model_profile_id,
                    request_provider_model_name=request_provider_model_name,
                    route_preset_key=route_preset_key,
                    project_id=project_id,
                    scope=scope,
                    stage="glossary",
                )
                step_run = self.create_step_run(
                    workflow_run_id=workflow_run_id,
                    step_key=str(prepared_step["step_key"]),
                    action=str(prepared_step["action"]),
                    llm_role=str(prepared_step["llm_role"]),
                    model_profile_id=str(prepared_step["resolved_model_profile_id"]),
                    input_ref=str(prepared_step["input_ref"]),
                    status="running",
                    output_payload=None,
                    summary=str(prepared_step["step_summary"]),
                )
                prepared_step["step_run_id"] = step_run.id
                prepared_steps.append(prepared_step)

            self.session.commit()

            with ThreadPoolExecutor(max_workers=len(prepared_steps)) as executor:
                futures = [
                    executor.submit(
                        self._execute_glossary_parallel_worker,
                        prepared_step=prepared_step,
                        pipeline=pipeline,
                        heartbeat=heartbeat,
                    )
                    for prepared_step in prepared_steps
                ]
                executions = [future.result() for future in futures]

            self.session.expire_all()
            return self.group_executor.summarize_tolerant_group_result(
                executions=executions,
                action=group_action,
                minimum_success=int(policy["minimum_success"]),
            )

        executions: list[dict[str, Any]] = []

        for offset, step_definition in enumerate(step_definitions):
            execution = self._execute_glossary_workflow_step(
                step_definition=step_definition,
                step_index=first_step_index + offset,
                workflow_run_id=workflow_run_id,
                request_id=request_id,
                request_model_profile_id=request_model_profile_id,
                request_provider_model_name=request_provider_model_name,
                route_preset_key=route_preset_key,
                project_id=project_id,
                scope=scope,
                pipeline=pipeline,
                heartbeat=heartbeat,
                allow_failure=True,
            )
            executions.append(execution)

        return self.group_executor.summarize_tolerant_group_result(
            executions=executions,
            action=group_action,
            minimum_success=int(policy["minimum_success"]),
        )

    def _execute_glossary_parallel_worker(
        self,
        *,
        prepared_step: Mapping[str, Any],
        pipeline,
        heartbeat,
    ) -> dict[str, Any]:
        worker_session = self.log_session_factory()
        try:
            worker_runtime = WorkflowRuntimeService(worker_session)
            worker_pipeline = pipeline.fork_for_session(worker_session)
            execution = worker_runtime._execute_glossary_precreated_step(
                prepared_step=prepared_step,
                pipeline=worker_pipeline,
                heartbeat=heartbeat,
                allow_failure=True,
            )
            worker_session.commit()
            return execution
        except Exception:
            worker_session.rollback()
            raise
        finally:
            worker_session.close()

    def _execute_translation_step_group(
        self,
        *,
        step_definitions: list[Mapping[str, Any]],
        first_step_index: int,
        workflow_run_id: int,
        request_id: str,
        request_model_profile_id: str,
        request_provider_model_name: str | None,
        route_preset_key: str | None,
        project_id: int,
        scope: Mapping[str, Any],
        pipeline,
        heartbeat,
        policy: Mapping[str, Any],
    ) -> dict[str, Any]:
        executions: list[dict[str, Any]] = []
        group_action = str(step_definitions[0].get("action") or "<unknown>")

        for offset, step_definition in enumerate(step_definitions):
            execution = self._execute_translation_workflow_step(
                step_definition=step_definition,
                step_index=first_step_index + offset,
                workflow_run_id=workflow_run_id,
                request_id=request_id,
                request_model_profile_id=request_model_profile_id,
                request_provider_model_name=request_provider_model_name,
                route_preset_key=route_preset_key,
                project_id=project_id,
                scope=scope,
                pipeline=pipeline,
                heartbeat=heartbeat,
                allow_failure=True,
            )
            executions.append(execution)

        return self.group_executor.summarize_tolerant_group_result(
            executions=executions,
            action=group_action,
            minimum_success=int(policy["minimum_success"]),
        )

    def _execute_glossary_workflow_step(
        self,
        *,
        step_definition: Mapping[str, Any],
        step_index: int,
        workflow_run_id: int,
        request_id: str,
        request_model_profile_id: str,
        request_provider_model_name: str | None,
        route_preset_key: str | None,
        project_id: int,
        scope: Mapping[str, Any],
        pipeline,
        heartbeat,
        allow_failure: bool,
    ) -> dict[str, Any]:
        prepared_step = self.step_executor.prepare_step_execution(
            step_definition=step_definition,
            step_index=step_index,
            workflow_run_id=workflow_run_id,
            request_id=request_id,
            request_model_profile_id=request_model_profile_id,
            request_provider_model_name=request_provider_model_name,
            route_preset_key=route_preset_key,
            project_id=project_id,
            scope=scope,
            stage="glossary",
        )
        step_run = self.create_step_run(
            workflow_run_id=workflow_run_id,
            step_key=str(prepared_step["step_key"]),
            action=str(prepared_step["action"]),
            llm_role=str(prepared_step["llm_role"]),
            model_profile_id=str(prepared_step["resolved_model_profile_id"]),
            input_ref=str(prepared_step["input_ref"]),
            status="running",
            output_payload=None,
            summary=str(prepared_step["step_summary"]),
        )
        prepared_step["step_run_id"] = step_run.id
        self._commit_visibility_checkpoint()
        return self._execute_glossary_precreated_step(
            prepared_step=prepared_step,
            pipeline=pipeline,
            heartbeat=heartbeat,
            allow_failure=allow_failure,
        )

    def _execute_glossary_precreated_step(
        self,
        *,
        prepared_step: Mapping[str, Any],
        pipeline,
        heartbeat,
        allow_failure: bool,
    ) -> dict[str, Any]:
        if heartbeat is not None:
            heartbeat()
        step_run = self.session.get(WorkflowStepRun, int(prepared_step["step_run_id"]))
        if step_run is None:
            raise ToolError(code="not_found", message=f"找不到 step_run {prepared_step['step_run_id']}。", status=404)
        step_definition = prepared_step["step_definition"]
        step_log = {
            "step_key": str(prepared_step["step_key"]),
            "action": str(prepared_step["action"]),
            "llm_role": str(step_definition.get("llm_role") or "worker"),
            "model_profile_id": str(prepared_step["resolved_model_profile_id"]),
            "input_ref": str(prepared_step["input_ref"]),
            "status": "running",
            "output_payload": None,
            "summary": str(prepared_step["step_summary"]),
        }
        try:
            step_pipeline = self._pipeline_for_prepared_step(
                pipeline=pipeline,
                prepared_step=prepared_step,
            )
            output_payload = self._run_glossary_pipeline_step(
                action=str(prepared_step["action"]),
                pipeline=step_pipeline,
                workflow_run_id=int(prepared_step["workflow_run_id"]),
                workflow_step_run_id=step_run.id,
                project_id=int(prepared_step["project_id"]),
                scope=prepared_step["scope"],
                model_profile_id=str(prepared_step["resolved_model_profile_id"]),
                provider_model_name=prepared_step["resolved_step_model_name"],
            )
            output_payload = self.step_executor.decorate_step_output_payload(
                output_payload=output_payload,
                resolved_model_profile_id=str(prepared_step["resolved_model_profile_id"]),
                resolved_model_name=prepared_step["resolved_step_model_name"],
            )
            self._raise_if_glossary_extract_all_skipped(
                action=str(prepared_step["action"]),
                output_payload=output_payload,
            )
        except Exception as step_exc:
            step_status = "cancelled" if self._is_cancelled_error(step_exc) else "failed"
            error_payload = {"error": str(step_exc)}
            extra_payload = getattr(step_exc, "_step_output_payload", None)
            if isinstance(extra_payload, Mapping):
                error_payload.update(dict(extra_payload))
            step_log["status"] = step_status
            step_log["output_payload"] = error_payload
            self.mark_step_status(
                step_run.id,
                status=step_status,
                output_payload=error_payload,
            )
            if self._is_cancelled_error(step_exc):
                setattr(step_exc, "_workflow_step_logs", [dict(step_log)])
                raise
            if allow_failure:
                return {
                    "succeeded": False,
                    "step_log": step_log,
                    "exception": step_exc,
                    "finalize_payload": None,
            }
            setattr(step_exc, "_workflow_step_logs", [dict(step_log)])
            raise
        step_log["status"] = "completed"
        step_log["output_payload"] = output_payload
        self.mark_step_status(step_run.id, status="completed", output_payload=output_payload)
        return {
            "succeeded": True,
            "step_log": step_log,
            "exception": None,
            "finalize_payload": dict(output_payload) if prepared_step["action"] == "glossary.finalize" else None,
        }

    def _run_glossary_pipeline_step(
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
        return self.pipeline_dispatch.run_glossary_action(
            action=action,
            pipeline=pipeline,
            workflow_run_id=workflow_run_id,
            workflow_step_run_id=workflow_step_run_id,
            project_id=project_id,
            scope=scope,
            model_profile_id=model_profile_id,
            provider_model_name=provider_model_name,
        )

    def _pipeline_for_prepared_step(self, *, pipeline, prepared_step: Mapping[str, Any]):
        if not hasattr(pipeline, "with_provider"):
            return pipeline
        model_profile_id = str(prepared_step["resolved_model_profile_id"])
        requested_profile_id = str(prepared_step.get("request_model_profile_id") or "")
        if model_profile_id in {"", "default"}:
            return pipeline
        if model_profile_id == requested_profile_id and getattr(pipeline, "provider", None) is not None:
            return pipeline
        resolved_provider = build_provider_from_profile(
            self.session,
            load_config(),
            model_profile_id,
        )
        return pipeline.with_provider(resolved_provider.provider)

    def _execute_translation_workflow_step(
        self,
        *,
        step_definition: Mapping[str, Any],
        step_index: int,
        workflow_run_id: int,
        request_id: str,
        request_model_profile_id: str,
        request_provider_model_name: str | None,
        route_preset_key: str | None,
        project_id: int,
        scope: Mapping[str, Any],
        pipeline,
        heartbeat,
        allow_failure: bool,
    ) -> dict[str, Any]:
        if heartbeat is not None:
            heartbeat()
        prepared_step = self.step_executor.prepare_step_execution(
            step_definition=step_definition,
            step_index=step_index,
            workflow_run_id=workflow_run_id,
            request_id=request_id,
            request_model_profile_id=request_model_profile_id,
            request_provider_model_name=request_provider_model_name,
            route_preset_key=route_preset_key,
            project_id=project_id,
            scope=scope,
            stage="translation",
        )
        step_run = self.create_step_run(
            workflow_run_id=workflow_run_id,
            step_key=str(prepared_step["step_key"]),
            action=str(prepared_step["action"]),
            llm_role=str(prepared_step["llm_role"]),
            model_profile_id=str(prepared_step["resolved_model_profile_id"]),
            input_ref=str(prepared_step["input_ref"]),
            status="running",
            output_payload=None,
            summary=str(prepared_step["step_summary"]),
        )
        self._commit_visibility_checkpoint()
        step_log = {
            "step_key": str(prepared_step["step_key"]),
            "action": str(prepared_step["action"]),
            "llm_role": str(prepared_step["llm_role"]),
            "model_profile_id": str(prepared_step["resolved_model_profile_id"]),
            "input_ref": str(prepared_step["input_ref"]),
            "status": "running",
            "output_payload": None,
            "summary": str(prepared_step["step_summary"]),
        }
        try:
            step_pipeline = self._pipeline_for_prepared_step(
                pipeline=pipeline,
                prepared_step=prepared_step,
            )
            output_payload = self._run_translation_pipeline_step(
                action=str(prepared_step["action"]),
                step_definition=step_definition,
                pipeline=step_pipeline,
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=step_run.id,
                project_id=project_id,
                scope=scope,
                model_profile_id=str(prepared_step["resolved_model_profile_id"]),
                provider_model_name=prepared_step["resolved_step_model_name"],
                heartbeat=heartbeat,
            )
        except Exception as step_exc:
            step_status = "cancelled" if self._is_cancelled_error(step_exc) else "failed"
            error_payload = {"error": str(step_exc)}
            extra_payload = getattr(step_exc, "_step_output_payload", None)
            if isinstance(extra_payload, Mapping):
                error_payload.update(dict(extra_payload))
            step_log["status"] = step_status
            step_log["output_payload"] = error_payload
            self.mark_step_status(
                step_run.id,
                status=step_status,
                output_payload=error_payload,
            )
            if self._is_cancelled_error(step_exc):
                setattr(step_exc, "_workflow_step_logs", [dict(step_log)])
                raise
            if allow_failure:
                return {
                    "succeeded": False,
                    "step_log": step_log,
                    "exception": step_exc,
                    "finalize_payload": None,
                }
            setattr(step_exc, "_workflow_step_logs", [dict(step_log)])
            raise
        output_payload = self.step_executor.decorate_step_output_payload(
            output_payload=output_payload,
            resolved_model_profile_id=str(prepared_step["resolved_model_profile_id"]),
            resolved_model_name=prepared_step["resolved_step_model_name"],
        )
        step_log["status"] = "completed"
        step_log["output_payload"] = output_payload
        self.mark_step_status(step_run.id, status="completed", output_payload=output_payload)
        return {
            "succeeded": True,
            "step_log": step_log,
            "exception": None,
            "finalize_payload": (
                dict(output_payload)
                if str(prepared_step["action"]) == "translation.finalize"
                else None
            ),
        }

    def _run_translation_pipeline_step(
        self,
        *,
        action: str,
        step_definition: Mapping[str, Any],
        pipeline,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        scope: Mapping[str, Any],
        model_profile_id: str,
        provider_model_name: str | None,
        heartbeat,
    ) -> dict[str, object]:
        return self.pipeline_dispatch.run_translation_action(
            action=action,
            pipeline=pipeline,
            workflow_run_id=workflow_run_id,
            workflow_step_run_id=workflow_step_run_id,
            project_id=project_id,
            scope=scope,
            model_profile_id=model_profile_id,
            provider_model_name=provider_model_name,
            step_definition=step_definition,
            heartbeat=heartbeat,
        )

    def _resolve_glossary_workflow_result(
        self,
        *,
        pipeline,
        project_id: int,
        workflow_run_id: int,
        finalize_payload: dict[str, object] | None,
    ):
        from .glossary_service import GlossaryResult

        token_usage = self.token_usage.summarize_step_runs(workflow_run_id=workflow_run_id)
        if finalize_payload is not None:
            final_candidate_count = self._read_finalize_candidate_count(finalize_payload)
            return (
                GlossaryResult(candidate_count=final_candidate_count, token_usage=token_usage),
                {
                    "candidate_count": final_candidate_count,
                    "result_source": "glossary.finalize",
                    **({"token_usage": token_usage} if token_usage is not None else {}),
                },
            )
        fallback_result = pipeline.glossary_service.inspect_result(
            project_id=project_id,
            workflow_run_id=workflow_run_id,
        )
        return (
            GlossaryResult(candidate_count=fallback_result.candidate_count, token_usage=token_usage),
            {
                "candidate_count": fallback_result.candidate_count,
                "result_source": "final_candidates_fallback",
                "fallback_reason": "workflow_missing_finalize_step",
                **({"token_usage": token_usage} if token_usage is not None else {}),
            },
        )

    def _resolve_translation_workflow_result(
        self,
        *,
        pipeline,
        project_id: int,
        workflow_run_id: int,
        finalize_payload: dict[str, object] | None,
    ):
        from .translation_service import TranslationResult

        synopsis_summary = pipeline.inspect_synopsis_summary(project_id=project_id)
        token_usage = self.token_usage.summarize_step_runs(workflow_run_id=workflow_run_id)
        if finalize_payload is None:
            raise ToolError(
                code="invalid_arguments",
                message="translation workflow 缺少 finalize 步骤，无法生成正式译文。",
                status=400,
            )
        translated_segments = int(finalize_payload.get("translated_segments", 0))
        active_version_ids = [int(item) for item in finalize_payload.get("active_version_ids", [])]
        return (
            TranslationResult(
                translated_segments=translated_segments,
                active_version_ids=active_version_ids,
                synopsis_summary=synopsis_summary,
                token_usage=token_usage,
                workflow_run_id=workflow_run_id,
            ),
            {
                "translated_segments": translated_segments,
                "active_version_ids": active_version_ids,
                "synopsis_summary": synopsis_summary,
                "result_source": "translation.finalize",
                "workflow_run_id": workflow_run_id,
                **({"token_usage": token_usage} if token_usage is not None else {}),
            },
        )

    def _read_finalize_candidate_count(self, finalize_payload: Mapping[str, object]) -> int:
        raw_candidate_count = finalize_payload.get("candidate_count")
        if raw_candidate_count is None:
            raise ToolError(
                code="invalid_arguments",
                message="glossary.finalize 必须返回 candidate_count。",
                status=400,
            )
        return int(raw_candidate_count)

    def _raise_if_glossary_extract_all_skipped(
        self,
        *,
        action: str,
        output_payload: Mapping[str, object],
    ) -> None:
        if action != "glossary.extract":
            return
        if not self._glossary_extract_all_chapters_skipped(output_payload):
            return
        error = ToolError(
            code="provider_error",
            message="glossary.extract 没有成功处理任何章节：全部章节被跳过。",
            status=502,
        )
        setattr(error, "_step_output_payload", dict(output_payload))
        raise error

    def _glossary_extract_all_chapters_skipped(self, output_payload: Mapping[str, object]) -> bool:
        try:
            skipped_chapter_count = int(output_payload.get("skipped_chapter_count") or 0)
            draft_candidate_count = int(output_payload.get("draft_candidate_count") or 0)
        except (TypeError, ValueError):
            return False
        if skipped_chapter_count <= 0 or draft_candidate_count > 0:
            return False

        chapter_results = output_payload.get("chapter_results")
        if isinstance(chapter_results, list) and len(chapter_results) > 0:
            return False

        progress = output_payload.get("progress")
        if isinstance(progress, Mapping):
            try:
                total_chapters = int(progress.get("total_chapters") or 0)
                completed_chapters = int(progress.get("completed_chapters") or 0)
                progress_skipped = int(progress.get("skipped_chapters") or 0)
            except (TypeError, ValueError):
                return False
            if total_chapters > 0:
                return completed_chapters == 0 and progress_skipped >= total_chapters

        return True

    def persist_failure_context(self, failure_context: Mapping[str, Any]) -> None:
        workflow_run_payload = failure_context.get("workflow_run")
        if not isinstance(workflow_run_payload, Mapping):
            return
        step_runs_payload = failure_context.get("step_runs")
        if not isinstance(step_runs_payload, list):
            step_runs_payload = []

        def persist(log_session, _repository: WorkflowRepository) -> None:
            run = self._find_existing_failure_workflow_run(
                log_session=log_session,
                workflow_run_payload=workflow_run_payload,
            )
            if run is None:
                run = WorkflowRun(
                    workflow_key=str(workflow_run_payload["workflow_key"]),
                    project_id=int(workflow_run_payload["project_id"]),
                    stage=str(workflow_run_payload["stage"]),
                    scope_type=str(dict(workflow_run_payload.get("scope", {})).get("type", "all")),
                    scope_value=json.dumps(dict(workflow_run_payload.get("scope", {})), ensure_ascii=False),
                    request_id=str(workflow_run_payload["request_id"]),
                    status=str(workflow_run_payload.get("status") or "failed"),
                    summary=(
                        str(workflow_run_payload["summary"])
                        if workflow_run_payload.get("summary") is not None
                        else None
                    ),
                )
                log_session.add(run)
                log_session.flush()
            else:
                run.status = str(workflow_run_payload.get("status") or "failed")
                run.summary = (
                    str(workflow_run_payload["summary"])
                    if workflow_run_payload.get("summary") is not None
                    else None
                )
            for item in step_runs_payload:
                if not isinstance(item, Mapping):
                    continue
                step_key = str(item.get("step_key") or "")
                step_run = log_session.execute(
                    select(WorkflowStepRun).where(
                        WorkflowStepRun.workflow_run_id == run.id,
                        WorkflowStepRun.step_key == step_key,
                    )
                ).scalar_one_or_none()
                output_payload = (
                    dict(item.get("output_payload"))
                    if isinstance(item.get("output_payload"), dict)
                    else None
                )
                if step_run is None:
                    log_session.add(
                        WorkflowStepRun(
                            workflow_run_id=run.id,
                            step_key=step_key,
                            action=str(item.get("action") or ""),
                            llm_role=str(item.get("llm_role") or "worker"),
                            model_profile_id=str(item.get("model_profile_id") or "default"),
                            status=str(item.get("status") or "failed"),
                            input_ref=str(item.get("input_ref") or ""),
                            output_payload=output_payload,
                            summary=None,
                        )
                    )
                    continue
                step_run.action = str(item.get("action") or step_run.action)
                step_run.llm_role = str(item.get("llm_role") or step_run.llm_role)
                step_run.model_profile_id = str(item.get("model_profile_id") or step_run.model_profile_id)
                step_run.status = str(item.get("status") or step_run.status)
                step_run.input_ref = str(item.get("input_ref") or step_run.input_ref)
                if output_payload is not None:
                    step_run.output_payload = output_payload
            log_session.flush()

        self._execute_log_write(persist)

    def _find_existing_failure_workflow_run(
        self,
        *,
        log_session,
        workflow_run_payload: Mapping[str, Any],
    ) -> WorkflowRun | None:
        raw_run_id = workflow_run_payload.get("id")
        if raw_run_id is not None:
            try:
                existing = log_session.get(WorkflowRun, int(raw_run_id))
            except (TypeError, ValueError):
                existing = None
            if existing is not None:
                return existing
        return log_session.execute(
            select(WorkflowRun)
            .where(
                WorkflowRun.project_id == int(workflow_run_payload["project_id"]),
                WorkflowRun.stage == str(workflow_run_payload["stage"]),
                WorkflowRun.request_id == str(workflow_run_payload["request_id"]),
            )
            .order_by(WorkflowRun.id.desc())
        ).scalars().first()

    def _execute_log_write(self, operation):
        log_session = self.log_session_factory()
        try:
            result = operation(log_session, WorkflowRepository(log_session))
            log_session.commit()
            return result
        except Exception:
            log_session.rollback()
            raise
        finally:
            log_session.close()

    def _commit_visibility_checkpoint(self) -> None:
        self.session.commit()

    def _serialize_profile(self, profile) -> dict[str, Any]:
        return {
            "workflow_key": profile.workflow_key,
            "stage": profile.stage,
            "status": profile.status,
            "is_default": bool(profile.is_default),
            "definition_json": profile.definition_json,
        }

    def _serialize_json_text(self, value: Mapping[str, Any] | str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(dict(value), ensure_ascii=False)

    def _serialize_json_payload(self, value: Mapping[str, Any] | dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        return dict(value)

    def _read_terminal_status_map(self, workflow_definition: Mapping[str, Any]) -> dict[str, str] | None:
        definition_json = workflow_definition.get("definition_json", {})
        if not isinstance(definition_json, Mapping):
            return None
        raw_terminal_status = definition_json.get("terminal_status")
        if not isinstance(raw_terminal_status, Mapping):
            return None
        return {str(key): str(value) for key, value in raw_terminal_status.items()}

    def _resolve_terminal_run_status(
        self,
        *,
        terminal_status: Mapping[str, str] | None,
        degradation_reason: str,
    ) -> str:
        if terminal_status is None:
            return "completed"
        resolved_status = terminal_status.get(degradation_reason)
        if resolved_status is None or str(resolved_status).strip() == "":
            return "completed"
        return str(resolved_status).strip()

    def _is_cancelled_error(self, error: Exception) -> bool:
        return isinstance(error, ToolError) and error.code == "cancelled"

    def _tool_error_from_value_error(self, exc: ValueError) -> ToolError:
        message = str(exc)
        if message.startswith("找不到 "):
            return ToolError(code="not_found", message=message, status=404)
        return ToolError(code="invalid_arguments", message=message, status=400)
