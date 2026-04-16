from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from typing import Any, Mapping

from sqlalchemy.orm import sessionmaker

from ..db.models import WorkflowRun, WorkflowStepRun
from ..errors import ToolError
from ..repositories.provider_profiles import ProviderProfileRepository
from ..repositories.workflows import WorkflowRepository

SUPPORTED_GLOSSARY_WORKFLOW_ACTIONS = frozenset(
    {
        "glossary.extract",
        "glossary.normalize",
        "glossary.review_relations",
        "glossary.review_scope",
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
        self.provider_profiles = ProviderProfileRepository(session)
        self.log_session_factory = sessionmaker(bind=session.get_bind(), future=True)

    def resolve_step_model_profile_id(
        self,
        step_definition: Mapping[str, Any],
        request_payload: Mapping[str, Any],
    ) -> str:
        requested_profile_id = request_payload.get("model_profile_id")
        model_profile_id = step_definition.get("model_profile_id")
        if model_profile_id == "$request.default":
            if requested_profile_id is None or requested_profile_id == "":
                return "default"
            return str(requested_profile_id)
        if model_profile_id is None or model_profile_id == "":
            if requested_profile_id is None or requested_profile_id == "":
                return "default"
            return str(requested_profile_id)
        return str(model_profile_id)

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
                policy = self._read_step_execution_policy(step)
                group_steps, next_step_index = self._collect_glossary_step_group(
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
                | ({"terminal_status": terminal_status} if terminal_status is not None else {})
            )
            self.mark_run_status(
                workflow_run.id,
                status="failed",
                summary=failed_summary,
            )
            setattr(
                exc,
                "_workflow_failure_context",
                {
                    "workflow_run": {
                        "workflow_key": workflow_key,
                        "project_id": project_id,
                        "stage": workflow_stage,
                        "scope": dict(scope),
                        "request_id": request_id,
                        "status": "failed",
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
                policy = self._read_step_execution_policy(step)
                group_steps, next_step_index = self._collect_glossary_step_group(
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
            pending_step_logs = getattr(exc, "_workflow_step_logs", None)
            if isinstance(pending_step_logs, list):
                executed_steps.extend(
                    dict(item) for item in pending_step_logs if isinstance(item, Mapping)
                )
            failed_summary = {
                "request_id": request_id,
                "workflow_key": workflow_key,
                "error": str(exc),
            } | ({"terminal_status": terminal_status} if terminal_status is not None else {})
            self.mark_run_status(
                workflow_run.id,
                status="failed",
                summary=failed_summary,
            )
            setattr(
                exc,
                "_workflow_failure_context",
                {
                    "workflow_run": {
                        "workflow_key": workflow_key,
                        "project_id": project_id,
                        "stage": workflow_stage,
                        "scope": dict(scope),
                        "request_id": request_id,
                        "status": "failed",
                        "summary": self._serialize_json_text(failed_summary),
                    },
                    "step_runs": [dict(item) for item in executed_steps],
                },
            )
            raise

    def _collect_glossary_step_group(
        self,
        *,
        steps: list[Any],
        start_index: int,
        policy: Mapping[str, Any],
    ) -> tuple[list[Mapping[str, Any]], int]:
        current_step = steps[start_index]
        if not isinstance(current_step, Mapping):
            raise ToolError(code="invalid_arguments", message="workflow step 不是对象。", status=400)
        if policy["failure_mode"] == "required":
            return [current_step], start_index + 1

        grouped_steps: list[Mapping[str, Any]] = [current_step]
        current_action = str(current_step.get("action") or "").strip()
        next_index = start_index + 1
        while next_index < len(steps):
            candidate_step = steps[next_index]
            if not isinstance(candidate_step, Mapping):
                break
            candidate_policy = self._read_step_execution_policy(candidate_step)
            candidate_action = str(candidate_step.get("action") or "").strip()
            if (
                candidate_policy["failure_mode"] != policy["failure_mode"]
                or candidate_policy["minimum_success"] != policy["minimum_success"]
                or candidate_action != current_action
            ):
                break
            grouped_steps.append(candidate_step)
            next_index += 1
        return grouped_steps, next_index

    def _execute_glossary_step_group(
        self,
        *,
        step_definitions: list[Mapping[str, Any]],
        first_step_index: int,
        workflow_run_id: int,
        request_id: str,
        request_model_profile_id: str,
        request_provider_model_name: str | None,
        project_id: int,
        scope: Mapping[str, Any],
        pipeline,
        heartbeat,
        policy: Mapping[str, Any],
    ) -> dict[str, Any]:
        if (
            len(step_definitions) > 1
            and str(step_definitions[0].get("action") or "").strip() == "glossary.extract"
        ):
            prepared_steps: list[dict[str, Any]] = []
            for offset, step_definition in enumerate(step_definitions):
                prepared_step = self._prepare_glossary_step_execution(
                    step_definition=step_definition,
                    step_index=first_step_index + offset,
                    workflow_run_id=workflow_run_id,
                    request_id=request_id,
                    request_model_profile_id=request_model_profile_id,
                    request_provider_model_name=request_provider_model_name,
                    project_id=project_id,
                    scope=scope,
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
            return self._summarize_tolerant_group_result(
                executions=executions,
                step_definitions=step_definitions,
                minimum_success=int(policy["minimum_success"]),
            )

        success_count = 0
        failed_step_keys: list[str] = []
        finalize_payload: dict[str, object] | None = None
        step_logs: list[dict[str, Any]] = []

        for offset, step_definition in enumerate(step_definitions):
            execution = self._execute_glossary_workflow_step(
                step_definition=step_definition,
                step_index=first_step_index + offset,
                workflow_run_id=workflow_run_id,
                request_id=request_id,
                request_model_profile_id=request_model_profile_id,
                request_provider_model_name=request_provider_model_name,
                project_id=project_id,
                scope=scope,
                pipeline=pipeline,
                heartbeat=heartbeat,
                allow_failure=True,
            )
            step_logs.append(dict(execution["step_log"]))
            if execution["succeeded"]:
                success_count += 1
                if isinstance(execution.get("finalize_payload"), dict):
                    finalize_payload = dict(execution["finalize_payload"])
            else:
                failed_step_keys.append(str(execution["step_log"]["step_key"]))

        minimum_success = int(policy["minimum_success"])
        if success_count < minimum_success:
            action = str(step_definitions[0].get("action") or "<unknown>")
            error = ToolError(
                code="workflow_quorum_failed",
                message=(
                    f"workflow tolerant step group {action} 至少需要 {minimum_success} 个成功步骤，"
                    f"实际仅 {success_count} 个成功。"
                ),
                status=502,
            )
            setattr(error, "_workflow_step_logs", [dict(item) for item in step_logs])
            raise error
        return {
            "success_count": success_count,
            "failed_step_keys": failed_step_keys,
            "degraded": bool(failed_step_keys),
            "finalize_payload": finalize_payload,
            "step_logs": step_logs,
        }

    def _prepare_glossary_step_execution(
        self,
        *,
        step_definition: Mapping[str, Any],
        step_index: int,
        workflow_run_id: int,
        request_id: str,
        request_model_profile_id: str,
        request_provider_model_name: str | None,
        project_id: int,
        scope: Mapping[str, Any],
    ) -> dict[str, Any]:
        resolved_model_profile_id = self.resolve_step_model_profile_id(
            step_definition,
            {
                "request_id": request_id,
                "model_profile_id": request_model_profile_id,
            },
        )
        resolved_step_model_name = self.resolve_step_model_name(
            model_profile_id=resolved_model_profile_id,
            request_model_profile_id=request_model_profile_id,
            request_provider_model_name=request_provider_model_name,
        )
        step_key = str(step_definition.get("step_key") or f"step_{step_index}")
        action = str(step_definition.get("action") or "").strip()
        input_ref = json.dumps({"project_id": project_id, "scope": dict(scope)}, ensure_ascii=False)
        step_summary = self._build_step_summary(
            step_definition=step_definition,
            resolved_model_profile_id=resolved_model_profile_id,
            resolved_model_name=resolved_step_model_name,
        )
        return {
            "step_definition": step_definition,
            "step_index": step_index,
            "step_key": step_key,
            "action": action,
            "llm_role": str(step_definition.get("llm_role") or "worker"),
            "resolved_model_profile_id": resolved_model_profile_id,
            "resolved_step_model_name": resolved_step_model_name,
            "input_ref": input_ref,
            "step_summary": step_summary,
            "workflow_run_id": workflow_run_id,
            "project_id": project_id,
            "scope": dict(scope),
        }

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

    def _summarize_tolerant_group_result(
        self,
        *,
        executions: list[Mapping[str, Any]],
        step_definitions: list[Mapping[str, Any]],
        minimum_success: int,
    ) -> dict[str, Any]:
        success_count = sum(1 for item in executions if item["succeeded"])
        failed_step_keys = [str(item["step_log"]["step_key"]) for item in executions if not item["succeeded"]]
        finalize_payload = None
        for item in executions:
            if item["succeeded"] and isinstance(item.get("finalize_payload"), dict):
                finalize_payload = dict(item["finalize_payload"])
        if success_count < minimum_success:
            action = str(step_definitions[0].get("action") or "<unknown>")
            error = ToolError(
                code="workflow_quorum_failed",
                message=(
                    f"workflow tolerant step group {action} 至少需要 {minimum_success} 个成功步骤，"
                    f"实际仅 {success_count} 个成功。"
                ),
                status=502,
            )
            setattr(error, "_workflow_step_logs", [dict(item["step_log"]) for item in executions])
            raise error
        return {
            "success_count": success_count,
            "failed_step_keys": failed_step_keys,
            "degraded": bool(failed_step_keys),
            "finalize_payload": finalize_payload,
            "step_logs": [dict(item["step_log"]) for item in executions],
        }

    def _execute_translation_step_group(
        self,
        *,
        step_definitions: list[Mapping[str, Any]],
        first_step_index: int,
        workflow_run_id: int,
        request_id: str,
        request_model_profile_id: str,
        request_provider_model_name: str | None,
        project_id: int,
        scope: Mapping[str, Any],
        pipeline,
        heartbeat,
        policy: Mapping[str, Any],
    ) -> dict[str, Any]:
        success_count = 0
        failed_step_keys: list[str] = []
        finalize_payload: dict[str, object] | None = None
        step_logs: list[dict[str, Any]] = []

        for offset, step_definition in enumerate(step_definitions):
            execution = self._execute_translation_workflow_step(
                step_definition=step_definition,
                step_index=first_step_index + offset,
                workflow_run_id=workflow_run_id,
                request_id=request_id,
                request_model_profile_id=request_model_profile_id,
                request_provider_model_name=request_provider_model_name,
                project_id=project_id,
                scope=scope,
                pipeline=pipeline,
                heartbeat=heartbeat,
                allow_failure=True,
            )
            step_logs.append(dict(execution["step_log"]))
            if execution["succeeded"]:
                success_count += 1
                if isinstance(execution.get("finalize_payload"), dict):
                    finalize_payload = dict(execution["finalize_payload"])
            else:
                failed_step_keys.append(str(execution["step_log"]["step_key"]))

        minimum_success = int(policy["minimum_success"])
        if success_count < minimum_success:
            action = str(step_definitions[0].get("action") or "<unknown>")
            error = ToolError(
                code="workflow_quorum_failed",
                message=(
                    f"workflow tolerant step group {action} 至少需要 {minimum_success} 个成功步骤，"
                    f"实际仅 {success_count} 个成功。"
                ),
                status=502,
            )
            setattr(error, "_workflow_step_logs", [dict(item) for item in step_logs])
            raise error
        return {
            "success_count": success_count,
            "failed_step_keys": failed_step_keys,
            "degraded": bool(failed_step_keys),
            "finalize_payload": finalize_payload,
            "step_logs": step_logs,
        }

    def _execute_glossary_workflow_step(
        self,
        *,
        step_definition: Mapping[str, Any],
        step_index: int,
        workflow_run_id: int,
        request_id: str,
        request_model_profile_id: str,
        request_provider_model_name: str | None,
        project_id: int,
        scope: Mapping[str, Any],
        pipeline,
        heartbeat,
        allow_failure: bool,
    ) -> dict[str, Any]:
        prepared_step = self._prepare_glossary_step_execution(
            step_definition=step_definition,
            step_index=step_index,
            workflow_run_id=workflow_run_id,
            request_id=request_id,
            request_model_profile_id=request_model_profile_id,
            request_provider_model_name=request_provider_model_name,
            project_id=project_id,
            scope=scope,
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
            output_payload = self._run_glossary_pipeline_step(
                action=str(prepared_step["action"]),
                pipeline=pipeline,
                workflow_run_id=int(prepared_step["workflow_run_id"]),
                workflow_step_run_id=step_run.id,
                project_id=int(prepared_step["project_id"]),
                scope=prepared_step["scope"],
                model_profile_id=str(prepared_step["resolved_model_profile_id"]),
                provider_model_name=prepared_step["resolved_step_model_name"],
            )
        except Exception as step_exc:
            error_payload = {"error": str(step_exc)}
            extra_payload = getattr(step_exc, "_step_output_payload", None)
            if isinstance(extra_payload, Mapping):
                error_payload.update(dict(extra_payload))
            step_log["status"] = "failed"
            step_log["output_payload"] = error_payload
            self.mark_step_status(
                step_run.id,
                status="failed",
                output_payload=error_payload,
            )
            if allow_failure:
                return {
                    "succeeded": False,
                    "step_log": step_log,
                    "exception": step_exc,
                    "finalize_payload": None,
                }
            setattr(step_exc, "_workflow_step_logs", [dict(step_log)])
            raise
        output_payload = self._decorate_step_output_payload(
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
        raise ToolError(code="invalid_arguments", message=f"不支持的 glossary workflow action: {action}", status=400)

    def _execute_translation_workflow_step(
        self,
        *,
        step_definition: Mapping[str, Any],
        step_index: int,
        workflow_run_id: int,
        request_id: str,
        request_model_profile_id: str,
        request_provider_model_name: str | None,
        project_id: int,
        scope: Mapping[str, Any],
        pipeline,
        heartbeat,
        allow_failure: bool,
    ) -> dict[str, Any]:
        if heartbeat is not None:
            heartbeat()
        resolved_model_profile_id = self.resolve_step_model_profile_id(
            step_definition,
            {
                "request_id": request_id,
                "model_profile_id": request_model_profile_id,
            },
        )
        resolved_step_model_name = self.resolve_step_model_name(
            model_profile_id=resolved_model_profile_id,
            request_model_profile_id=request_model_profile_id,
            request_provider_model_name=request_provider_model_name,
        )
        step_key = str(step_definition.get("step_key") or f"step_{step_index}")
        action = str(step_definition.get("action") or "").strip()
        input_ref = json.dumps({"project_id": project_id, "scope": dict(scope)}, ensure_ascii=False)
        step_summary = self._build_step_summary(
            step_definition=step_definition,
            resolved_model_profile_id=resolved_model_profile_id,
            resolved_model_name=resolved_step_model_name,
        )
        step_run = self.create_step_run(
            workflow_run_id=workflow_run_id,
            step_key=step_key,
            action=action,
            llm_role=str(step_definition.get("llm_role") or "worker"),
            model_profile_id=resolved_model_profile_id,
            input_ref=input_ref,
            status="running",
            output_payload=None,
            summary=step_summary,
        )
        step_log = {
            "step_key": step_key,
            "action": action,
            "llm_role": str(step_definition.get("llm_role") or "worker"),
            "model_profile_id": resolved_model_profile_id,
            "input_ref": input_ref,
            "status": "running",
            "output_payload": None,
            "summary": step_summary,
        }
        try:
            output_payload = self._run_translation_pipeline_step(
                action=action,
                step_definition=step_definition,
                pipeline=pipeline,
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=step_run.id,
                project_id=project_id,
                scope=scope,
                model_profile_id=resolved_model_profile_id,
                provider_model_name=resolved_step_model_name,
                heartbeat=heartbeat,
            )
        except Exception as step_exc:
            step_log["status"] = "failed"
            step_log["output_payload"] = {"error": str(step_exc)}
            self.mark_step_status(
                step_run.id,
                status="failed",
                output_payload={"error": str(step_exc)},
            )
            if allow_failure:
                return {
                    "succeeded": False,
                    "step_log": step_log,
                    "exception": step_exc,
                    "finalize_payload": None,
                }
            setattr(step_exc, "_workflow_step_logs", [dict(step_log)])
            raise
        output_payload = self._decorate_step_output_payload(
            output_payload=output_payload,
            resolved_model_profile_id=resolved_model_profile_id,
            resolved_model_name=resolved_step_model_name,
        )
        step_log["status"] = "completed"
        step_log["output_payload"] = output_payload
        self.mark_step_status(step_run.id, status="completed", output_payload=output_payload)
        return {
            "succeeded": True,
            "step_log": step_log,
            "exception": None,
            "finalize_payload": dict(output_payload) if action == "translation.finalize" else None,
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
        raise ToolError(code="invalid_arguments", message=f"不支持的 translation workflow action: {action}", status=400)

    def _resolve_glossary_workflow_result(
        self,
        *,
        pipeline,
        project_id: int,
        workflow_run_id: int,
        finalize_payload: dict[str, object] | None,
    ):
        from .glossary_service import GlossaryResult

        if finalize_payload is not None:
            final_candidate_count = self._read_finalize_candidate_count(finalize_payload)
            return (
                GlossaryResult(candidate_count=final_candidate_count),
                {
                    "candidate_count": final_candidate_count,
                    "result_source": "glossary.finalize",
                },
            )
        fallback_result = pipeline.glossary_service.inspect_result(
            project_id=project_id,
            workflow_run_id=workflow_run_id,
        )
        return (
            fallback_result,
            {
                "candidate_count": fallback_result.candidate_count,
                "result_source": "final_candidates_fallback",
                "fallback_reason": "workflow_missing_finalize_step",
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
            ),
            {
                "translated_segments": translated_segments,
                "active_version_ids": active_version_ids,
                "synopsis_summary": synopsis_summary,
                "result_source": "translation.finalize",
                "workflow_run_id": workflow_run_id,
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

    def persist_failure_context(self, failure_context: Mapping[str, Any]) -> None:
        workflow_run_payload = failure_context.get("workflow_run")
        if not isinstance(workflow_run_payload, Mapping):
            return
        step_runs_payload = failure_context.get("step_runs")
        if not isinstance(step_runs_payload, list):
            step_runs_payload = []

        def persist(log_session, _repository: WorkflowRepository) -> None:
            run = WorkflowRun(
                workflow_key=str(workflow_run_payload["workflow_key"]),
                project_id=int(workflow_run_payload["project_id"]),
                stage=str(workflow_run_payload["stage"]),
                scope_type=str(dict(workflow_run_payload.get("scope", {})).get("type", "all")),
                scope_value=json.dumps(dict(workflow_run_payload.get("scope", {})), ensure_ascii=False),
                request_id=str(workflow_run_payload["request_id"]),
                status=str(workflow_run_payload.get("status") or "failed"),
                summary=str(workflow_run_payload["summary"]) if workflow_run_payload.get("summary") is not None else None,
            )
            log_session.add(run)
            log_session.flush()
            for item in step_runs_payload:
                if not isinstance(item, Mapping):
                    continue
                log_session.add(
                    WorkflowStepRun(
                        workflow_run_id=run.id,
                        step_key=str(item.get("step_key") or ""),
                        action=str(item.get("action") or ""),
                        llm_role=str(item.get("llm_role") or "worker"),
                        model_profile_id=str(item.get("model_profile_id") or "default"),
                        status=str(item.get("status") or "failed"),
                        input_ref=str(item.get("input_ref") or ""),
                        output_payload=(
                            dict(item.get("output_payload"))
                            if isinstance(item.get("output_payload"), dict)
                            else None
                        ),
                        summary=None,
                    )
                )
            log_session.flush()

        self._execute_log_write(persist)

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

    def resolve_step_model_name(
        self,
        *,
        model_profile_id: str,
        request_model_profile_id: str,
        request_provider_model_name: str | None,
    ) -> str:
        if request_provider_model_name and model_profile_id == request_model_profile_id:
            return request_provider_model_name
        profile = self.provider_profiles.get_profile_by_key(model_profile_id)
        if profile is not None:
            return profile.model_name
        if request_provider_model_name and model_profile_id in {"default", ""}:
            return request_provider_model_name
        return model_profile_id

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

    def _decorate_step_output_payload(
        self,
        *,
        output_payload: Mapping[str, Any],
        resolved_model_profile_id: str,
        resolved_model_name: str | None,
    ) -> dict[str, Any]:
        payload = dict(output_payload)
        raw_actual_profile_id = payload.get("model_profile_id")
        actual_profile_id = (
            resolved_model_profile_id
            if raw_actual_profile_id is None or str(raw_actual_profile_id).strip() == ""
            else str(raw_actual_profile_id)
        )
        raw_fallback_depth = payload.get("fallback_depth")
        try:
            fallback_depth = 0 if raw_fallback_depth is None else int(raw_fallback_depth)
        except (TypeError, ValueError):
            fallback_depth = 0
        payload["requested_model_profile_id"] = resolved_model_profile_id
        payload["actual_model_profile_id"] = actual_profile_id
        payload["fallback_depth"] = fallback_depth
        actual_model_name = payload.get("model_name")
        if actual_model_name is None and resolved_model_name:
            payload["actual_model_name"] = resolved_model_name
        elif actual_model_name is not None:
            payload["actual_model_name"] = str(actual_model_name)
        return payload

    def _build_step_summary(
        self,
        *,
        step_definition: Mapping[str, Any],
        resolved_model_profile_id: str,
        resolved_model_name: str | None,
    ) -> str:
        payload: dict[str, Any] = {
            "failure_mode": str(step_definition.get("failure_mode") or "required"),
            "model_profile_id": resolved_model_profile_id,
        }
        minimum_success = step_definition.get("minimum_success")
        if minimum_success is not None:
            payload["minimum_success"] = int(minimum_success)
        if resolved_model_name:
            payload["provider_model_name"] = resolved_model_name
        return json.dumps(payload, ensure_ascii=False)

    def _read_step_execution_policy(self, step_definition: Mapping[str, Any]) -> dict[str, Any]:
        failure_mode = str(step_definition.get("failure_mode") or "required").strip().lower()
        if failure_mode not in {"required", "quorum", "best_effort"}:
            raise ToolError(
                code="invalid_arguments",
                message=f"不支持的 failure_mode: {failure_mode or '<empty>'}。",
                status=400,
            )
        minimum_success = step_definition.get("minimum_success")
        if minimum_success is None:
            resolved_minimum_success = 0 if failure_mode == "best_effort" else 1
        else:
            resolved_minimum_success = int(minimum_success)
        if resolved_minimum_success < 0:
            raise ToolError(code="invalid_arguments", message="minimum_success 不能为负数。", status=400)
        return {
            "failure_mode": failure_mode,
            "minimum_success": resolved_minimum_success,
        }

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

    def _tool_error_from_value_error(self, exc: ValueError) -> ToolError:
        message = str(exc)
        if message.startswith("找不到 "):
            return ToolError(code="not_found", message=message, status=404)
        return ToolError(code="invalid_arguments", message=message, status=400)
