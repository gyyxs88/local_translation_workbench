from __future__ import annotations

import json
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import WorkflowRun, WorkflowStepRun
from ..token_usage import merge_token_usage_payloads, normalize_token_usage_payload


class WorkflowTokenUsageService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def summarize_step_runs(self, *, workflow_run_id: int) -> dict[str, int] | None:
        step_runs = self.session.execute(
            select(WorkflowStepRun).where(WorkflowStepRun.workflow_run_id == workflow_run_id)
        ).scalars().all()
        return merge_token_usage_payloads(
            None if not isinstance(step.output_payload, dict) else step.output_payload.get("token_usage")
            for step in step_runs
        )

    def summarize_step_logs(self, step_logs: list[Mapping[str, object]]) -> dict[str, int] | None:
        return merge_token_usage_payloads(
            None
            if not isinstance(step_log.get("output_payload"), Mapping)
            else step_log["output_payload"].get("token_usage")
            for step_log in step_logs
        )

    def read_workflow_run_usage(self, *, workflow_run: WorkflowRun) -> dict[str, int] | None:
        summary_payload = self._decode_summary_payload(workflow_run.summary)
        if isinstance(summary_payload, dict):
            usage = normalize_token_usage_payload(summary_payload.get("token_usage"))
            if usage is not None:
                return usage
        return self.summarize_step_runs(workflow_run_id=int(workflow_run.id))

    def _decode_summary_payload(self, raw_summary: str | None) -> dict[str, object] | None:
        if raw_summary is None or raw_summary == "":
            return None
        try:
            payload = json.loads(raw_summary)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None
