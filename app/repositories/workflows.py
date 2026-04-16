from __future__ import annotations

import json

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..db.models import WorkflowProfile, WorkflowRun, WorkflowStepRun


class WorkflowRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _decode_summary_payload(self, raw_summary: str | None) -> dict[str, object] | None:
        if raw_summary is None:
            return None
        try:
            payload = json.loads(raw_summary)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def create_profile(
        self,
        workflow_key: str,
        stage: str,
        status: str,
        is_default: bool,
        definition_json: dict[str, object],
    ) -> WorkflowProfile:
        profile = WorkflowProfile(
            workflow_key=workflow_key.strip(),
            stage=stage.strip(),
            status=status,
            is_default=1 if is_default else 0,
            definition_json=definition_json,
        )
        self.session.add(profile)
        self.session.flush()

        if is_default:
            self.set_default_for_stage(profile.workflow_key, profile.stage)

        return profile

    def list_profiles(self, stage: str | None = None) -> list[WorkflowProfile]:
        statement = select(WorkflowProfile)
        if stage is not None:
            statement = statement.where(WorkflowProfile.stage == stage.strip())
        statement = statement.order_by(WorkflowProfile.id.asc())
        return list(self.session.execute(statement).scalars().all())

    def get_profile(self, workflow_key: str) -> WorkflowProfile | None:
        statement = select(WorkflowProfile).where(WorkflowProfile.workflow_key == workflow_key.strip())
        return self.session.execute(statement).scalar_one_or_none()

    def set_default_for_stage(self, workflow_key: str, stage: str) -> WorkflowProfile | None:
        normalized_workflow_key = workflow_key.strip()
        normalized_stage = stage.strip()
        profile = self.get_profile(normalized_workflow_key)
        if profile is None:
            raise ValueError(f"找不到 workflow_key={normalized_workflow_key}。")
        if profile.stage != normalized_stage:
            raise ValueError(
                f"workflow_key={normalized_workflow_key} 的 stage={profile.stage}，与传入的 stage={normalized_stage} 不一致。"
            )

        self.session.execute(
            update(WorkflowProfile)
            .where(WorkflowProfile.stage == normalized_stage)
            .values(is_default=0)
        )

        profile.is_default = 1
        self.session.flush()
        return profile

    def create_run(
        self,
        workflow_key: str,
        project_id: int,
        stage: str,
        scope_type: str,
        scope_value: str,
        request_id: str,
        status: str,
        summary: str | None = None,
    ) -> WorkflowRun:
        profile = self.get_profile(workflow_key)
        if profile is None:
            raise ValueError(f"找不到 workflow_key={workflow_key.strip()}。")
        if profile.stage != stage.strip():
            raise ValueError(
                f"workflow_key={workflow_key.strip()} 的 stage={profile.stage}，与传入的 stage={stage.strip()} 不一致。"
            )

        run = WorkflowRun(
            workflow_key=workflow_key.strip(),
            project_id=project_id,
            stage=stage.strip(),
            scope_type=scope_type,
            scope_value=scope_value,
            request_id=request_id.strip(),
            status=status,
            summary=summary,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def create_step_run(
        self,
        workflow_run_id: int,
        step_key: str,
        action: str,
        llm_role: str,
        model_profile_id: str,
        status: str,
        input_ref: str,
        output_payload: dict[str, object] | None,
        summary: str | None = None,
    ) -> WorkflowStepRun:
        step_run = WorkflowStepRun(
            workflow_run_id=workflow_run_id,
            step_key=step_key.strip(),
            action=action,
            llm_role=llm_role,
            model_profile_id=model_profile_id.strip(),
            status=status,
            input_ref=input_ref,
            output_payload=output_payload,
            summary=summary,
        )
        self.session.add(step_run)
        self.session.flush()
        return step_run

    def update_run(
        self,
        workflow_run_id: int,
        status: str | None = None,
        summary: str | None = None,
    ) -> WorkflowRun:
        run = self.session.get(WorkflowRun, workflow_run_id)
        if run is None:
            raise ValueError(f"找不到 workflow_run_id={workflow_run_id}。")
        if status is not None:
            run.status = status
        if summary is not None:
            run.summary = summary
        self.session.flush()
        return run

    def update_step_run(
        self,
        step_run_id: int,
        status: str | None = None,
        output_payload: dict[str, object] | None = None,
    ) -> WorkflowStepRun:
        step_run = self.session.get(WorkflowStepRun, step_run_id)
        if step_run is None:
            raise ValueError(f"找不到 step_run_id={step_run_id}。")
        if status is not None:
            step_run.status = status
        if output_payload is not None:
            step_run.output_payload = output_payload
        self.session.flush()
        return step_run

    def find_latest_run_for_stage_context(
        self,
        *,
        project_id: int,
        stage: str,
        request_id: str | None,
        stage_run_id: int | None,
    ) -> WorkflowRun | None:
        normalized_stage = stage.strip().lower()
        statement = (
            select(WorkflowRun)
            .where(WorkflowRun.project_id == project_id, WorkflowRun.stage == normalized_stage)
            .order_by(WorkflowRun.id.desc())
        )
        if request_id is not None:
            statement = statement.where(WorkflowRun.request_id == request_id.strip())

        candidates = list(self.session.execute(statement).scalars().all())
        if stage_run_id is not None:
            for item in candidates:
                summary_payload = self._decode_summary_payload(item.summary)
                if summary_payload is None:
                    continue
                if int(summary_payload.get("stage_run_id") or -1) == int(stage_run_id):
                    return item
        return candidates[0] if candidates else None

    def list_failed_steps_for_run(self, workflow_run_id: int) -> list[WorkflowStepRun]:
        statement = (
            select(WorkflowStepRun)
            .where(
                WorkflowStepRun.workflow_run_id == workflow_run_id,
                WorkflowStepRun.status == "failed",
            )
            .order_by(WorkflowStepRun.id.asc())
        )
        return list(self.session.execute(statement).scalars().all())
