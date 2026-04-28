from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import StageRun, WorkflowRun, WorkflowStepRun
from ..repositories.workflows import WorkflowRepository
from ..token_usage import normalize_token_usage_payload
from .workflow_token_usage_service import WorkflowTokenUsageService


class StageRunInspectionService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.workflows = WorkflowRepository(session)
        self.token_usage = WorkflowTokenUsageService(session)

    def build_stage_run_payload(self, *, stage_run: StageRun) -> dict[str, object]:
        summary_payload = self._decode_summary_payload(stage_run.summary)
        workflow_run = self._resolve_workflow_run(stage_run=stage_run, summary_payload=summary_payload)
        return {
            "id": stage_run.id,
            "stage": stage_run.stage,
            "scope_type": stage_run.scope_type,
            "scope_value": self._decode_scope_value(stage_run.scope_value),
            "status": stage_run.status,
            "summary": summary_payload,
            "context": self._build_context_payload(summary_payload=summary_payload, workflow_run=workflow_run),
            "result": self._build_result_payload(stage=stage_run.stage, summary_payload=summary_payload),
            "workflow": self._build_workflow_payload(stage=stage_run.stage, workflow_run=workflow_run),
            "observability": self._build_run_observability(
                stage_run=stage_run,
                summary_payload=summary_payload,
                workflow_run=workflow_run,
            ),
            "diagnostics": self._build_failed_run_diagnostics(
                stage_run=stage_run,
                summary_payload=summary_payload,
                workflow_run=workflow_run,
            ),
        }

    def _decode_summary_payload(self, raw_summary: str | None) -> dict[str, object] | None:
        if raw_summary is None:
            return None
        try:
            payload = json.loads(raw_summary)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _decode_scope_value(self, raw_scope_value: str | None) -> dict[str, object] | None:
        if raw_scope_value is None:
            return None
        try:
            payload = json.loads(raw_scope_value)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _build_context_payload(
        self,
        *,
        summary_payload: dict[str, object] | None,
        workflow_run: WorkflowRun | None,
    ) -> dict[str, object]:
        return {
            "request_id": (
                None
                if not isinstance(summary_payload, dict) or summary_payload.get("request_id") is None
                else str(summary_payload["request_id"])
            ),
            "model_profile_id": (
                None
                if not isinstance(summary_payload, dict) or summary_payload.get("model_profile_id") is None
                else str(summary_payload["model_profile_id"])
            ),
            "workflow_key": (
                str(workflow_run.workflow_key)
                if workflow_run is not None
                else (
                    None
                    if not isinstance(summary_payload, dict) or summary_payload.get("workflow_key") is None
                    else str(summary_payload["workflow_key"])
                )
            ),
            "workflow_run_id": None if workflow_run is None else int(workflow_run.id),
        }

    def _build_result_payload(self, *, stage: str, summary_payload: dict[str, object] | None) -> dict[str, object] | None:
        if not isinstance(summary_payload, dict):
            return None
        if stage == "chaptering":
            return {
                "chapter_count": self._read_optional_int(summary_payload.get("chapter_count")) or 0,
                "segment_count": self._read_optional_int(summary_payload.get("segment_count")) or 0,
            }
        if stage == "glossary":
            return {
                "candidate_count": self._read_optional_int(summary_payload.get("candidate_count")) or 0,
            }
        if stage == "translation":
            active_version_ids = summary_payload.get("active_version_ids")
            active_version_count = len(active_version_ids) if isinstance(active_version_ids, list) else 0
            return {
                "translated_segments": self._read_optional_int(summary_payload.get("translated_segments")) or 0,
                "active_version_count": active_version_count,
            }
        if stage == "review":
            return {
                "issue_count": self._read_optional_int(summary_payload.get("issue_count")) or 0,
                "review_run_id": self._read_optional_int(summary_payload.get("run_id")),
            }
        if stage == "export":
            manifest_path = summary_payload.get("manifest_path")
            return {
                "artifact_count": self._read_optional_int(summary_payload.get("artifact_count")) or 0,
                "export_run_id": self._read_optional_int(summary_payload.get("run_id")),
                "manifest_path": None if manifest_path is None else str(manifest_path),
            }
        return None

    def _build_workflow_payload(self, *, stage: str, workflow_run: WorkflowRun | None) -> dict[str, object] | None:
        if workflow_run is None or stage not in {"glossary", "translation"}:
            return None

        step_rows = list(
            self.session.execute(
                select(WorkflowStepRun)
                .where(WorkflowStepRun.workflow_run_id == workflow_run.id)
                .order_by(WorkflowStepRun.id.asc())
            ).scalars().all()
        )
        workflow_token_usage = self.token_usage.read_workflow_run_usage(workflow_run=workflow_run)
        return {
            "id": int(workflow_run.id),
            "workflow_key": str(workflow_run.workflow_key),
            "status": str(workflow_run.status),
            "step_counts": {
                "total": len(step_rows),
                "completed": sum(1 for step in step_rows if step.status == "completed"),
                "failed": sum(1 for step in step_rows if step.status == "failed"),
                "running": sum(1 for step in step_rows if step.status == "running"),
            },
            "steps": [self._build_workflow_step_payload(step) for step in step_rows],
            "token_usage": workflow_token_usage,
        }

    def _build_workflow_step_payload(self, step: WorkflowStepRun) -> dict[str, object]:
        payload: dict[str, object] = {
            "step_run_id": int(step.id),
            "step_key": str(step.step_key),
            "action": str(step.action),
            "llm_role": str(step.llm_role),
            "model_profile_id": str(step.model_profile_id),
            "status": str(step.status),
            "fallback_depth": max(
                self._read_fallback_depth(step.output_payload),
                self._read_fallback_depth(self._decode_summary_payload(step.summary)),
            ),
            "actual_model_name": self._resolve_step_actual_model_name(step),
            "token_usage": normalize_token_usage_payload(
                None if not isinstance(step.output_payload, dict) else step.output_payload.get("token_usage")
            ),
        }
        progress = self._read_step_progress(step.output_payload)
        if progress is not None:
            payload["progress"] = progress
        return payload

    def _build_failed_run_diagnostics(
        self,
        *,
        stage_run: StageRun,
        summary_payload: dict[str, object] | None,
        workflow_run: WorkflowRun | None,
    ) -> dict[str, object] | None:
        if stage_run.status != "failed":
            return None

        error_payload = None
        if isinstance(summary_payload, dict) and isinstance(summary_payload.get("error"), dict):
            error_payload = dict(summary_payload["error"])

        diagnostics: dict[str, object] = {
            "error": error_payload,
            "failure_step": None,
            "model_profile_id": (
                str(summary_payload.get("model_profile_id"))
                if isinstance(summary_payload, dict) and summary_payload.get("model_profile_id") is not None
                else None
            ),
            "model_name": None,
        }

        if stage_run.stage not in {"glossary", "translation"}:
            return diagnostics

        step_context = self._resolve_workflow_failure_step(
            stage_run=stage_run,
            summary_payload=summary_payload,
            workflow_run=workflow_run,
        )
        if step_context is None:
            return diagnostics

        diagnostics["failure_step"] = step_context["failure_step"]
        diagnostics["model_profile_id"] = step_context.get("model_profile_id") or diagnostics["model_profile_id"]
        diagnostics["model_name"] = step_context.get("model_name")
        return diagnostics

    def _resolve_workflow_failure_step(
        self,
        *,
        stage_run: StageRun,
        summary_payload: dict[str, object] | None,
        workflow_run: WorkflowRun | None,
    ) -> dict[str, object] | None:
        workflow_run = workflow_run or self._resolve_workflow_run(stage_run=stage_run, summary_payload=summary_payload)
        if workflow_run is None:
            return None

        failed_steps = self.workflows.list_failed_steps_for_run(workflow_run.id)
        if not failed_steps:
            return None

        step_run = failed_steps[0]
        return {
            "failure_step": {
                "step_key": str(step_run.step_key),
                "action": str(step_run.action),
            },
            "model_profile_id": str(step_run.model_profile_id),
            "model_name": self._resolve_step_actual_model_name(step_run),
        }

    def _resolve_workflow_run(self, *, stage_run: StageRun, summary_payload: dict[str, object] | None) -> WorkflowRun | None:
        request_id = None if summary_payload is None else summary_payload.get("request_id")
        return self.workflows.find_latest_run_for_stage_context(
            project_id=stage_run.project_id,
            stage=stage_run.stage,
            request_id=None if request_id is None else str(request_id),
            stage_run_id=stage_run.id,
        )

    def _build_run_observability(
        self,
        *,
        stage_run: StageRun,
        summary_payload: dict[str, object] | None,
        workflow_run: WorkflowRun | None,
    ) -> dict[str, object]:
        return {
            "timing": self._build_timing_observability(summary_payload),
            "recovery": self._build_recovery_observability(summary_payload),
            "usage": self._build_usage_observability(
                stage=stage_run.stage,
                summary_payload=summary_payload,
                workflow_run=workflow_run,
            ),
            "fallback": self._build_fallback_observability(
                stage_run=stage_run,
                summary_payload=summary_payload,
                workflow_run=workflow_run,
            ),
        }

    def _build_timing_observability(self, summary_payload: dict[str, object] | None) -> dict[str, object]:
        duration_ms = None
        if isinstance(summary_payload, dict) and summary_payload.get("duration_ms") is not None:
            try:
                duration_ms = int(summary_payload["duration_ms"])
            except (TypeError, ValueError):
                duration_ms = None
        return {
            "started_at": (
                None
                if not isinstance(summary_payload, dict) or summary_payload.get("started_at") is None
                else str(summary_payload["started_at"])
            ),
            "finished_at": (
                None
                if not isinstance(summary_payload, dict) or summary_payload.get("finished_at") is None
                else str(summary_payload["finished_at"])
            ),
            "duration_ms": duration_ms,
        }

    def _build_recovery_observability(self, summary_payload: dict[str, object] | None) -> dict[str, object]:
        return {
            "resume": bool(summary_payload.get("resume")) if isinstance(summary_payload, dict) else False,
            "rerun": bool(summary_payload.get("rerun")) if isinstance(summary_payload, dict) else False,
            "resume_from_run_id": self._read_optional_int(
                None if not isinstance(summary_payload, dict) else summary_payload.get("resume_from_run_id")
            ),
            "rerun_from_run_id": self._read_optional_int(
                None if not isinstance(summary_payload, dict) else summary_payload.get("rerun_from_run_id")
            ),
        }

    def _build_usage_observability(
        self,
        *,
        stage: str,
        summary_payload: dict[str, object] | None,
        workflow_run: WorkflowRun | None,
    ) -> dict[str, int] | None:
        if isinstance(summary_payload, dict):
            stage_usage = normalize_token_usage_payload(summary_payload.get("token_usage"))
            if stage_usage is not None:
                return stage_usage

        if workflow_run is not None:
            workflow_usage = self.token_usage.read_workflow_run_usage(workflow_run=workflow_run)
            if workflow_usage is not None:
                return workflow_usage

        if stage in {"chaptering", "review", "export"}:
            return {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "call_count": 0,
                "measured_call_count": 0,
            }
        return None

    def _build_fallback_observability(
        self,
        *,
        stage_run: StageRun,
        summary_payload: dict[str, object] | None,
        workflow_run: WorkflowRun | None,
    ) -> dict[str, object]:
        max_depth = 0
        max_depth = max(
            max_depth,
            self._read_optional_int(None if not isinstance(summary_payload, dict) else summary_payload.get("fallback_depth")) or 0,
            self._read_optional_int(
                None if not isinstance(summary_payload, dict) else summary_payload.get("max_fallback_depth")
            )
            or 0,
        )
        if workflow_run is not None and stage_run.stage in {"glossary", "translation"}:
            statement = select(WorkflowStepRun).where(WorkflowStepRun.workflow_run_id == workflow_run.id)
            for step_run in self.session.execute(statement).scalars().all():
                max_depth = max(
                    max_depth,
                    self._read_fallback_depth(step_run.output_payload),
                    self._read_fallback_depth(self._decode_summary_payload(step_run.summary)),
                )
        return {
            "triggered": max_depth > 0,
            "max_depth": max_depth,
        }

    def _resolve_step_actual_model_name(self, step_run: WorkflowStepRun) -> str | None:
        output_payload = step_run.output_payload if isinstance(step_run.output_payload, dict) else {}
        step_summary = self._decode_summary_payload(step_run.summary)
        for candidate in (
            output_payload.get("actual_model_name"),
            output_payload.get("provider_model_name"),
            None if not isinstance(step_summary, dict) else step_summary.get("provider_model_name"),
        ):
            if candidate not in {None, ""}:
                return str(candidate)
        return None

    def _read_fallback_depth(self, payload: dict[str, object] | None) -> int:
        if not isinstance(payload, dict):
            return 0
        return max(
            self._read_optional_int(payload.get("fallback_depth")) or 0,
            self._read_optional_int(payload.get("max_fallback_depth")) or 0,
        )

    def _read_step_progress(self, payload: dict[str, object] | None) -> dict[str, object] | None:
        if not isinstance(payload, dict):
            return None
        progress = payload.get("progress")
        return dict(progress) if isinstance(progress, dict) else None

    def _read_optional_int(self, value: object) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
