from __future__ import annotations

from typing import Any, Mapping

from ..errors import ToolError


class WorkflowGroupExecutorService:
    def read_step_execution_policy(self, step_definition: Mapping[str, Any]) -> dict[str, Any]:
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

    def collect_step_group(
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
            candidate_policy = self.read_step_execution_policy(candidate_step)
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

    def summarize_tolerant_group_result(
        self,
        *,
        executions: list[Mapping[str, Any]],
        action: str,
        minimum_success: int,
    ) -> dict[str, Any]:
        success_count = sum(1 for item in executions if item["succeeded"])
        failed_step_keys = [str(item["step_log"]["step_key"]) for item in executions if not item["succeeded"]]
        finalize_payload = None
        for item in executions:
            if item["succeeded"] and isinstance(item.get("finalize_payload"), dict):
                finalize_payload = dict(item["finalize_payload"])
        if success_count < minimum_success:
            error = ToolError(
                code="workflow_quorum_failed",
                message=(
                    f"workflow tolerant step group {action or '<unknown>'} 至少需要 {minimum_success} 个成功步骤，"
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
