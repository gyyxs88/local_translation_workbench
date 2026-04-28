from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from ..providers.base import Provider
from ..text_counting import build_text_count_payload
from .synopsis_service import SynopsisService
from .translation_workflow_draft_service import TranslationWorkflowDraftService
from .translation_workflow_execution_service import TranslationWorkflowExecutionService


class TranslationPipelineService:
    def __init__(
        self,
        session: Session,
        *,
        base_data_dir: Path,
        provider: Provider | None = None,
        parallel_session_factory=None,
        max_parallel_workers: int = 4,
    ) -> None:
        self.session = session
        self.base_data_dir = Path(base_data_dir)
        self.provider = provider
        self.parallel_session_factory = parallel_session_factory
        self.max_parallel_workers = max_parallel_workers
        self.synopses = SynopsisService(session)
        self.workflow_drafts = TranslationWorkflowDraftService(session)
        self.workflow_execution = TranslationWorkflowExecutionService(
            session,
            base_data_dir=self.base_data_dir,
            provider=provider,
            parallel_session_factory=parallel_session_factory,
            max_parallel_workers=max_parallel_workers,
        )

    def fork_for_session(self, session: Session) -> "TranslationPipelineService":
        return TranslationPipelineService(
            session,
            base_data_dir=self.base_data_dir,
            provider=self.provider,
            parallel_session_factory=self.parallel_session_factory,
            max_parallel_workers=self.max_parallel_workers,
        )

    def with_provider(self, provider: Provider) -> "TranslationPipelineService":
        return TranslationPipelineService(
            self.session,
            base_data_dir=self.base_data_dir,
            provider=provider,
            parallel_session_factory=self.parallel_session_factory,
            max_parallel_workers=self.max_parallel_workers,
        )

    def generate_draft(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        scope: dict[str, object],
        model_profile_id: str,
        provider_model_name: str | None,
        draft_role: str,
        heartbeat=None,
    ) -> dict[str, object]:
        return self.workflow_execution.generate_draft(
            workflow_run_id=workflow_run_id,
            workflow_step_run_id=workflow_step_run_id,
            project_id=project_id,
            scope=scope,
            model_profile_id=model_profile_id,
            provider_model_name=provider_model_name,
            draft_role=draft_role,
            heartbeat=heartbeat,
        )

    def review_draft(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
        heartbeat=None,
    ) -> dict[str, object]:
        return self.workflow_execution.review_draft(
            workflow_run_id=workflow_run_id,
            workflow_step_run_id=workflow_step_run_id,
            model_profile_id=model_profile_id,
            provider_model_name=provider_model_name,
            heartbeat=heartbeat,
        )

    def rewrite_draft(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
        heartbeat=None,
    ) -> dict[str, object]:
        return self.workflow_execution.rewrite_draft(
            workflow_run_id=workflow_run_id,
            workflow_step_run_id=workflow_step_run_id,
            model_profile_id=model_profile_id,
            provider_model_name=provider_model_name,
            heartbeat=heartbeat,
        )

    def inspect_pipeline(self, *, workflow_run_id: int) -> dict[str, object]:
        return self.workflow_drafts.inspect_pipeline(workflow_run_id=workflow_run_id)

    def finalize(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
        heartbeat=None,
    ) -> dict[str, object]:
        return self.workflow_execution.finalize(
            workflow_run_id=workflow_run_id,
            workflow_step_run_id=workflow_step_run_id,
            project_id=project_id,
            model_profile_id=model_profile_id,
            provider_model_name=provider_model_name,
            heartbeat=heartbeat,
        )

    def inspect_synopsis_summary(self, *, project_id: int) -> dict[str, dict[str, object]]:
        payload = self.synopses.inspect(project_id=project_id)
        return {
            "source": {
                "status": payload["source_synopsis_status"],
                "origin": payload["source_synopsis_origin"],
                **build_text_count_payload(payload["source_synopsis_text"]),
            },
            "target": {
                "status": payload["target_synopsis_status"],
                "origin": payload["target_synopsis_origin"],
                **build_text_count_payload(payload["target_synopsis_text"]),
            },
        }

