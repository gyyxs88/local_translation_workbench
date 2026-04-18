from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import Chapter, ExportRun, GlossaryEntry, ReviewRun, SegmentTranslation, StageRun, WorkflowStepRun
from ..errors import ToolError
from ..repositories.projects import ProjectRepository
from ..repositories.workflows import WorkflowRepository
from .idempotency_service import IdempotencyService


class ProjectQueryService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.projects = ProjectRepository(session)
        self.workflows = WorkflowRepository(session)
        self.idempotency = IdempotencyService(session)

    def list_projects(self) -> dict[str, object]:
        records = self.projects.list_all()
        return {
            "projects": [
                {
                    "id": item.id,
                    "request_id": item.request_id,
                    "project_key": item.project_key,
                    "source_language": item.source_language,
                    "target_language": item.target_language,
                    "status": item.status,
                    "counts": self._build_project_counts(item.id),
                }
                for item in records
            ]
        }

    def cancel_project(self, *, project_id: int, request_id: str) -> dict[str, object]:
        project = self.projects.get_by_id(project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        self.idempotency.record(
            request_id=request_id,
            operation_name="project.cancel",
            project_id=project_id,
        )
        self.projects.update_status(project, status="cancelled")
        self.session.commit()
        return {
            "project_id": project.id,
            "project_key": project.project_key,
            "status": project.status,
        }

    def inspect_stage_runs(
        self,
        *,
        project_id: int,
        stage: str | None = None,
        limit: int = 20,
    ) -> dict[str, object]:
        project = self.projects.get_by_id(project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        normalized_limit = max(1, min(limit, 200))
        statement = select(StageRun).where(StageRun.project_id == project_id)
        if stage:
            statement = statement.where(StageRun.stage == stage.strip().lower())
        statement = statement.order_by(StageRun.id.desc()).limit(normalized_limit)

        runs = list(self.session.execute(statement).scalars().all())
        runs_payload = []
        for item in runs:
            summary_payload = self._decode_summary_payload(item.summary)
            workflow_run = self._resolve_workflow_run(stage_run=item, summary_payload=summary_payload)
            runs_payload.append(
                {
                    "id": item.id,
                    "stage": item.stage,
                    "scope_type": item.scope_type,
                    "status": item.status,
                    "summary": summary_payload,
                    "observability": self._build_run_observability(
                        stage_run=item,
                        summary_payload=summary_payload,
                        workflow_run=workflow_run,
                    ),
                    "diagnostics": self._build_failed_run_diagnostics(
                        stage_run=item,
                        summary_payload=summary_payload,
                        workflow_run=workflow_run,
                    ),
                }
            )
        return {
            "project_id": project_id,
            "runs": runs_payload,
        }

    def _decode_summary_payload(self, raw_summary: str | None) -> dict[str, object] | None:
        if raw_summary is None:
            return None
        try:
            payload = json.loads(raw_summary)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _build_failed_run_diagnostics(
        self,
        *,
        stage_run: StageRun,
        summary_payload: dict[str, object] | None,
        workflow_run=None,
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
        workflow_run=None,
    ) -> dict[str, object] | None:
        workflow_run = workflow_run or self._resolve_workflow_run(stage_run=stage_run, summary_payload=summary_payload)
        if workflow_run is None:
            return None

        failed_steps = self.workflows.list_failed_steps_for_run(workflow_run.id)
        if not failed_steps:
            return None

        step_run = failed_steps[0]
        output_payload = step_run.output_payload if isinstance(step_run.output_payload, dict) else {}
        step_summary = self._decode_summary_payload(step_run.summary)
        model_name = (
            output_payload.get("actual_model_name")
            or output_payload.get("provider_model_name")
            or (step_summary.get("provider_model_name") if isinstance(step_summary, dict) else None)
        )
        return {
            "failure_step": {
                "step_key": str(step_run.step_key),
                "action": str(step_run.action),
            },
            "model_profile_id": str(step_run.model_profile_id),
            "model_name": None if model_name is None else str(model_name),
        }

    def _resolve_workflow_run(self, *, stage_run: StageRun, summary_payload: dict[str, object] | None):
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
        workflow_run,
    ) -> dict[str, object]:
        return {
            "timing": self._build_timing_observability(summary_payload),
            "recovery": self._build_recovery_observability(summary_payload),
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

    def _build_fallback_observability(
        self,
        *,
        stage_run: StageRun,
        summary_payload: dict[str, object] | None,
        workflow_run,
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

    def _read_fallback_depth(self, payload: dict[str, object] | None) -> int:
        if not isinstance(payload, dict):
            return 0
        return max(
            self._read_optional_int(payload.get("fallback_depth")) or 0,
            self._read_optional_int(payload.get("max_fallback_depth")) or 0,
        )

    def _build_project_counts(self, project_id: int) -> dict[str, int]:
        return {
            "chapters": self._count(select(func.count()).select_from(Chapter).where(Chapter.project_id == project_id)),
            "glossary_entries": self._count(
                select(func.count()).select_from(GlossaryEntry).where(GlossaryEntry.project_id == project_id)
            ),
            "translations": self._count(
                select(func.count()).select_from(SegmentTranslation).where(SegmentTranslation.project_id == project_id)
            ),
            "review_runs": self._count(
                select(func.count()).select_from(ReviewRun).where(ReviewRun.project_id == project_id)
            ),
            "export_runs": self._count(
                select(func.count()).select_from(ExportRun).where(ExportRun.project_id == project_id)
            ),
            "stage_runs": self._count(
                select(func.count()).select_from(StageRun).where(StageRun.project_id == project_id)
            ),
        }

    def _count(self, statement) -> int:
        return int(self.session.execute(statement).scalar_one())

    def _read_optional_int(self, value: object) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
