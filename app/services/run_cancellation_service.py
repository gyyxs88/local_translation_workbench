from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import ProjectLease, StageRun, TranslationProject, WorkflowRun, WorkflowStepRun
from ..errors import ToolError


class RunCancellationService:
    ACTIVE_STATUSES = {"running"}

    def __init__(self, session: Session) -> None:
        self.session = session

    def cancel_project_runs(self, *, project_id: int, request_id: str, reason: str) -> dict[str, int]:
        stage_runs = list(
            self.session.execute(
                select(StageRun).where(
                    StageRun.project_id == project_id,
                    StageRun.status.in_(self.ACTIVE_STATUSES),
                )
            ).scalars().all()
        )
        workflow_runs = list(
            self.session.execute(
                select(WorkflowRun).where(
                    WorkflowRun.project_id == project_id,
                    WorkflowRun.status.in_(self.ACTIVE_STATUSES),
                )
            ).scalars().all()
        )
        workflow_step_count = self._cancel_workflow_steps(
            workflow_run_ids=[int(item.id) for item in workflow_runs],
            request_id=request_id,
            reason=reason,
        )
        stage_run_count = sum(
            1
            for stage_run in stage_runs
            if self._mark_stage_run_cancelled(stage_run, request_id=request_id, reason=reason)
        )
        workflow_run_count = sum(
            1
            for workflow_run in workflow_runs
            if self._mark_workflow_run_cancelled(workflow_run, request_id=request_id, reason=reason)
        )
        released_lease_count = self.release_project_leases(project_id=project_id)
        self.session.flush()
        return {
            "cancelled_stage_run_count": stage_run_count,
            "cancelled_workflow_run_count": workflow_run_count,
            "cancelled_workflow_step_count": workflow_step_count,
            "released_lease_count": released_lease_count,
        }

    def cancel_stage_run(
        self,
        *,
        project_id: int,
        request_id: str,
        stage_run_id: int | None = None,
        stage: str | None = None,
        reason: str,
    ) -> dict[str, int | None]:
        stage_run = self._resolve_stage_run(project_id=project_id, stage_run_id=stage_run_id, stage=stage)
        workflow_runs = self._find_workflow_runs_for_stage_run(stage_run)
        workflow_step_count = self._cancel_workflow_steps(
            workflow_run_ids=[int(item.id) for item in workflow_runs],
            request_id=request_id,
            reason=reason,
        )
        stage_run_count = 1 if self._mark_stage_run_cancelled(stage_run, request_id=request_id, reason=reason) else 0
        workflow_run_count = sum(
            1
            for workflow_run in workflow_runs
            if self._mark_workflow_run_cancelled(workflow_run, request_id=request_id, reason=reason)
        )
        released_lease_count = self.release_project_leases(project_id=project_id)
        self.session.flush()
        return {
            "stage_run_id": int(stage_run.id),
            "cancelled_stage_run_count": stage_run_count,
            "cancelled_workflow_run_count": workflow_run_count,
            "cancelled_workflow_step_count": workflow_step_count,
            "released_lease_count": released_lease_count,
        }

    def release_project_leases(self, *, project_id: int) -> int:
        leases = list(
            self.session.execute(
                select(ProjectLease).where(ProjectLease.project_id == project_id)
            ).scalars().all()
        )
        for lease in leases:
            self.session.delete(lease)
        return len(leases)

    def raise_if_cancelled(self, *, project_id: int, stage_run_id: int | None = None) -> None:
        project = self.session.get(TranslationProject, project_id)
        if project is not None and project.status == "cancelled":
            raise ToolError(
                code="cancelled",
                message=f"项目 {project_id} 已取消，停止当前 stage.run。",
                status=409,
            )
        if stage_run_id is None:
            return
        stage_run = self.session.get(StageRun, stage_run_id)
        if stage_run is not None and stage_run.status == "cancelled":
            raise ToolError(
                code="cancelled",
                message=f"stage_run {stage_run_id} 已取消，停止当前 stage.run。",
                status=409,
            )

    def _resolve_stage_run(self, *, project_id: int, stage_run_id: int | None, stage: str | None) -> StageRun:
        if stage_run_id is not None:
            stage_run = self.session.get(StageRun, stage_run_id)
            if stage_run is None or int(stage_run.project_id) != project_id:
                raise ToolError(code="not_found", message=f"找不到 stage_run {stage_run_id}。", status=404)
        else:
            statement = select(StageRun).where(
                StageRun.project_id == project_id,
                StageRun.status.in_(self.ACTIVE_STATUSES),
            )
            if stage is not None and stage.strip():
                statement = statement.where(StageRun.stage == stage.strip().lower())
            stage_run = self.session.execute(statement.order_by(StageRun.id.desc())).scalars().first()
            if stage_run is None:
                raise ToolError(code="not_found", message=f"项目 {project_id} 当前没有运行中的 stage_run。", status=404)

        if stage_run.status not in self.ACTIVE_STATUSES and stage_run.status != "cancelled":
            raise ToolError(
                code="conflict_error",
                message=f"stage_run {stage_run.id} 当前状态为 {stage_run.status}，不能取消。",
                status=409,
            )
        return stage_run

    def _find_workflow_runs_for_stage_run(self, stage_run: StageRun) -> list[WorkflowRun]:
        request_id = self._read_summary_text(stage_run.summary, "request_id")
        candidates = list(
            self.session.execute(
                select(WorkflowRun).where(
                    WorkflowRun.project_id == stage_run.project_id,
                    WorkflowRun.stage == stage_run.stage,
                    WorkflowRun.status.in_(self.ACTIVE_STATUSES),
                )
            ).scalars().all()
        )
        matched: list[WorkflowRun] = []
        for workflow_run in candidates:
            summary = self._decode_json_text(workflow_run.summary)
            if isinstance(summary, dict) and self._parse_optional_int(summary.get("stage_run_id")) == int(stage_run.id):
                matched.append(workflow_run)
                continue
            if request_id is not None and workflow_run.request_id == request_id:
                matched.append(workflow_run)
        return matched

    def _cancel_workflow_steps(self, *, workflow_run_ids: list[int], request_id: str, reason: str) -> int:
        if not workflow_run_ids:
            return 0
        steps = list(
            self.session.execute(
                select(WorkflowStepRun).where(
                    WorkflowStepRun.workflow_run_id.in_(workflow_run_ids),
                    WorkflowStepRun.status.in_(self.ACTIVE_STATUSES),
                )
            ).scalars().all()
        )
        for step in steps:
            step.status = "cancelled"
            output_payload: dict[str, object] = {}
            if isinstance(step.output_payload, dict):
                output_payload.update(step.output_payload)
            output_payload.update(self._cancel_payload(request_id=request_id, reason=reason))
            step.output_payload = output_payload
        return len(steps)

    def _mark_stage_run_cancelled(self, stage_run: StageRun, *, request_id: str, reason: str) -> bool:
        if stage_run.status == "cancelled":
            return False
        stage_run.status = "cancelled"
        stage_run.summary = self._merge_summary(stage_run.summary, request_id=request_id, reason=reason)
        return True

    def _mark_workflow_run_cancelled(self, workflow_run: WorkflowRun, *, request_id: str, reason: str) -> bool:
        if workflow_run.status == "cancelled":
            return False
        workflow_run.status = "cancelled"
        workflow_run.summary = self._merge_summary(workflow_run.summary, request_id=request_id, reason=reason)
        return True

    def _merge_summary(self, summary: str | None, *, request_id: str, reason: str) -> str:
        payload = self._decode_json_text(summary)
        if not isinstance(payload, dict):
            payload = {"previous_summary": summary} if summary else {}
        payload.update(self._cancel_payload(request_id=request_id, reason=reason))
        return json.dumps(payload, ensure_ascii=False)

    def _cancel_payload(self, *, request_id: str, reason: str) -> dict[str, object]:
        return {
            "cancelled": True,
            "cancel_request_id": request_id,
            "cancel_reason": reason,
            "cancelled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def _decode_json_text(self, value: str | None) -> object:
        if value is None or value == "":
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    def _read_summary_text(self, summary: str | None, key: str) -> str | None:
        payload = self._decode_json_text(summary)
        if not isinstance(payload, dict):
            return None
        value = payload.get(key)
        if value is None or value == "":
            return None
        return str(value)

    def _parse_optional_int(self, value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
