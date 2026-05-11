from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import ProviderCallLog, TranslationProject
from ..errors import ToolError
from ..token_usage import normalize_token_usage_payload
from .provider_error_classifier import classify_provider_error


MODEL_CALL_ACTIONS = {
    "glossary.extract",
    "glossary.review_relations",
    "glossary.review_scope",
    "glossary.review_consistency",
    "translation.generate_draft",
    "translation.review_draft",
    "translation.rewrite_draft",
    "annotation.extract",
}


class ProviderCallLogService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record_call(
        self,
        *,
        project_id: int | None = None,
        workflow_run_id: int | None = None,
        workflow_step_run_id: int | None = None,
        stage: str | None = None,
        action: str | None = None,
        step_key: str | None = None,
        llm_role: str | None = None,
        requested_model_profile_id: str | None = None,
        actual_model_profile_id: str | None = None,
        provider_name: str | None = None,
        model_name: str | None = None,
        fallback_depth: int = 0,
        status: str = "ok",
        error_code: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        token_usage: object | None = None,
        latency_ms: int | None = None,
        cost_usd: float | None = None,
    ) -> dict[str, object]:
        usage = normalize_token_usage_payload(token_usage) or {}
        row = ProviderCallLog(
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            workflow_step_run_id=workflow_step_run_id,
            stage=self._normalize_optional_text(stage),
            action=self._normalize_optional_text(action),
            step_key=self._normalize_optional_text(step_key),
            llm_role=self._normalize_optional_text(llm_role),
            requested_model_profile_id=self._normalize_optional_text(requested_model_profile_id),
            actual_model_profile_id=self._normalize_optional_text(actual_model_profile_id),
            provider_name=self._normalize_optional_text(provider_name),
            model_name=self._normalize_optional_text(model_name),
            fallback_depth=int(fallback_depth or 0),
            status=self._normalize_optional_text(status) or "ok",
            error_code=self._normalize_optional_text(error_code),
            error_type=self._normalize_optional_text(error_type),
            error_message=self._normalize_optional_text(error_message),
            latency_ms=latency_ms,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
            cache_creation_input_tokens=usage.get("cache_creation_input_tokens"),
            cache_read_input_tokens=usage.get("cache_read_input_tokens"),
            cost_usd=cost_usd,
        )
        self.session.add(row)
        self.session.flush()
        return self._payload(row)

    def record_from_step_output(
        self,
        *,
        project_id: int,
        stage: str,
        workflow_run_id: int,
        workflow_step_run_id: int,
        step_key: str,
        action: str,
        llm_role: str,
        requested_model_profile_id: str,
        status: str,
        output_payload: Mapping[str, object] | None,
    ) -> dict[str, object] | None:
        payload = dict(output_payload or {})
        usage = normalize_token_usage_payload(payload.get("token_usage"))
        error_message = self._normalize_optional_text(payload.get("error"))
        error_code = self._normalize_optional_text(payload.get("error_code"))
        error_type = self._normalize_optional_text(payload.get("error_type"))
        if error_message and not error_type:
            error_type = classify_provider_error(
                code=error_code,
                message=error_message,
                details=payload,
            )
        action_name = str(action)
        has_call_signal = (
            action_name in MODEL_CALL_ACTIONS
            or usage is not None
            or error_message is not None
            or self._normalize_optional_text(payload.get("provider_name")) is not None
        )
        if not has_call_signal:
            return None
        actual_model_profile_id = (
            self._normalize_optional_text(payload.get("actual_model_profile_id"))
            or self._normalize_optional_text(payload.get("model_profile_id"))
            or requested_model_profile_id
        )
        return self.record_call(
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            workflow_step_run_id=workflow_step_run_id,
            stage=stage,
            action=action,
            step_key=step_key,
            llm_role=llm_role,
            requested_model_profile_id=(
                self._normalize_optional_text(payload.get("requested_model_profile_id"))
                or requested_model_profile_id
            ),
            actual_model_profile_id=actual_model_profile_id,
            provider_name=self._normalize_optional_text(payload.get("provider_name")),
            model_name=(
                self._normalize_optional_text(payload.get("actual_model_name"))
                or self._normalize_optional_text(payload.get("model_name"))
            ),
            fallback_depth=self._parse_int(payload.get("fallback_depth")),
            status="failed" if status == "failed" else "ok",
            error_code=error_code,
            error_type=error_type,
            error_message=error_message,
            token_usage=usage,
        )

    def list_calls(
        self,
        *,
        project_id: int,
        stage: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        self._ensure_project(project_id)
        statement = select(ProviderCallLog).where(ProviderCallLog.project_id == project_id)
        if stage:
            statement = statement.where(ProviderCallLog.stage == stage)
        if status:
            statement = statement.where(ProviderCallLog.status == status)
        statement = statement.order_by(ProviderCallLog.stage.asc(), ProviderCallLog.id.asc()).limit(max(1, min(limit, 500)))
        return [self._payload(row) for row in self.session.execute(statement).scalars().all()]

    def summarize_costs(self, *, project_id: int, stage: str | None = None) -> dict[str, object]:
        calls = self.list_calls(project_id=project_id, stage=stage, limit=500)
        totals = self._empty_summary_bucket()
        by_stage: dict[str, dict[str, object]] = {}
        by_model_profile: dict[str, dict[str, object]] = {}
        for item in calls:
            self._accumulate(totals, item)
            stage_key = str(item.get("stage") or "unknown")
            self._accumulate(by_stage.setdefault(stage_key, self._empty_summary_bucket()), item)
            model_profile_key = str(item.get("actual_model_profile_id") or item.get("requested_model_profile_id") or "unknown")
            self._accumulate(by_model_profile.setdefault(model_profile_key, self._empty_summary_bucket()), item)
        return {
            "project_id": project_id,
            "stage": stage,
            "totals": totals,
            "by_stage": by_stage,
            "by_model_profile": by_model_profile,
        }

    def _ensure_project(self, project_id: int) -> TranslationProject:
        project = self.session.get(TranslationProject, project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)
        return project

    def _payload(self, row: ProviderCallLog) -> dict[str, object]:
        return {
            "id": int(row.id),
            "project_id": row.project_id,
            "workflow_run_id": row.workflow_run_id,
            "workflow_step_run_id": row.workflow_step_run_id,
            "stage": row.stage,
            "action": row.action,
            "step_key": row.step_key,
            "llm_role": row.llm_role,
            "requested_model_profile_id": row.requested_model_profile_id,
            "actual_model_profile_id": row.actual_model_profile_id,
            "provider_name": row.provider_name,
            "model_name": row.model_name,
            "fallback_depth": int(row.fallback_depth or 0),
            "status": row.status,
            "error_code": row.error_code,
            "error_type": row.error_type,
            "error_message": row.error_message,
            "latency_ms": row.latency_ms,
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
            "total_tokens": row.total_tokens,
            "cache_creation_input_tokens": row.cache_creation_input_tokens,
            "cache_read_input_tokens": row.cache_read_input_tokens,
            "cost_usd": row.cost_usd,
            "created_at": row.created_at.isoformat() if row.created_at is not None else None,
        }

    def _empty_summary_bucket(self) -> dict[str, object]:
        return {
            "call_count": 0,
            "failed_call_count": 0,
            "fallback_call_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "cost_usd": 0.0,
        }

    def _accumulate(self, bucket: dict[str, object], item: Mapping[str, object]) -> None:
        bucket["call_count"] = int(bucket["call_count"]) + 1
        if item.get("status") == "failed":
            bucket["failed_call_count"] = int(bucket["failed_call_count"]) + 1
        if int(item.get("fallback_depth") or 0) > 0:
            bucket["fallback_call_count"] = int(bucket["fallback_call_count"]) + 1
        for key in (
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        ):
            bucket[key] = int(bucket[key]) + int(item.get(key) or 0)
        bucket["cost_usd"] = float(bucket["cost_usd"]) + float(item.get("cost_usd") or 0)

    def _normalize_optional_text(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _parse_int(self, value: object) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
