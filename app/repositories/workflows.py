from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..db.models import WorkflowProfile, WorkflowRun, WorkflowStepRun


class WorkflowRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

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
