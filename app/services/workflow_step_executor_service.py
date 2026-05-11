from __future__ import annotations

import json
from typing import Any, Mapping

from ..repositories.provider_profiles import ProviderProfileRepository
from .provider_profile_service import ProviderProfileService


class WorkflowStepExecutorService:
    def __init__(self, session) -> None:
        self.session = session
        self.provider_profiles = ProviderProfileRepository(session)

    def resolve_step_model_profile_id(
        self,
        step_definition: Mapping[str, Any],
        request_payload: Mapping[str, Any],
    ) -> str:
        route_preset_key = request_payload.get("route_preset_key")
        if route_preset_key is not None and str(route_preset_key).strip():
            routed_profile_id = ProviderProfileService(self.session).resolve_route_model_profile_id(
                preset_key=str(route_preset_key),
                stage=str(request_payload.get("stage") or step_definition.get("stage") or ""),
                step_definition=step_definition,
            )
            if routed_profile_id:
                return routed_profile_id
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

    def build_step_summary(
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

    def decorate_step_output_payload(
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

    def prepare_step_execution(
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
        stage: str | None = None,
        route_preset_key: str | None = None,
    ) -> dict[str, Any]:
        resolved_model_profile_id = self.resolve_step_model_profile_id(
            step_definition,
            {
                "request_id": request_id,
                "model_profile_id": request_model_profile_id,
                "stage": stage or "",
                "route_preset_key": route_preset_key,
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
        step_summary = self.build_step_summary(
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
            "request_model_profile_id": request_model_profile_id,
            "route_preset_key": route_preset_key,
            "input_ref": input_ref,
            "step_summary": step_summary,
            "workflow_run_id": workflow_run_id,
            "project_id": project_id,
            "scope": dict(scope),
        }
