from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session

from ..db.models import TranslationProject
from ..errors import ToolError
from ..providers.base import Provider
from .chaptering_service import ChapteringResult, ChapteringService
from .export_service import ExportResult, ExportService
from .glossary_service import GlossaryResult, GlossaryService
from .review_service import ReviewResult, ReviewService
from .stage_run_orchestrator_service import StageRunOrchestratorService
from .translation_service import TranslationResult, TranslationService

STAGE_SEQUENCE = ("chaptering", "glossary", "translation", "review", "export")


@dataclass(frozen=True)
class StageCommand:
    request_id: str
    project_id: int
    stage: str
    scope: dict[str, object]
    model_profile_id: str = "default"
    workflow_key: str | None = None
    route_preset_key: str | None = None
    provider_model_name: str | None = None
    source_file_path: Path | None = None
    resume: bool = False
    rerun: bool = False
    review_mode: str = "hybrid"
    max_rewrite_rounds: int = 2


class StageService:
    def __init__(self, session: Session, *, base_data_dir: Path, provider: Provider | None = None) -> None:
        self.session = session
        self.base_data_dir = Path(base_data_dir)
        self.provider = provider
        self.runner = StageRunOrchestratorService(
            session,
            base_data_dir=base_data_dir,
            provider=provider,
        )

    @property
    def leases(self):
        return self.runner.leases

    @leases.setter
    def leases(self, value) -> None:
        self.runner.leases = value

    @property
    def idempotency(self):
        return self.runner.idempotency

    @idempotency.setter
    def idempotency(self, value) -> None:
        self.runner.idempotency = value

    def run(
        self,
        command: StageCommand,
    ) -> ChapteringResult | GlossaryResult | TranslationResult | ReviewResult | ExportResult:
        return self.runner.run(command=command, dispatch=self._dispatch)

    def _dispatch(
        self,
        *,
        project: TranslationProject,
        command: StageCommand,
        stage_run_id: int,
        heartbeat: Callable[[], None],
    ):
        stage = command.stage.lower()
        if stage == "chaptering":
            return ChapteringService(self.session, base_data_dir=self.base_data_dir).run(
                request_id=command.request_id,
                project_id=command.project_id,
                source_file_path=command.source_file_path or Path(project.source_path),
                scope=command.scope,
                stage_run_id=stage_run_id,
                heartbeat=heartbeat,
            )
        if stage == "glossary":
            return GlossaryService(self.session, provider=self.provider).run(
                request_id=command.request_id,
                project_id=command.project_id,
                scope=command.scope,
                model_profile_id=command.model_profile_id,
                workflow_key=command.workflow_key,
                route_preset_key=command.route_preset_key,
                provider_model_name=command.provider_model_name,
                stage_run_id=stage_run_id,
                heartbeat=heartbeat,
            )
        if stage == "translation":
            return TranslationService(
                self.session,
                base_data_dir=self.base_data_dir,
                provider=self.provider,
            ).run(
                request_id=command.request_id,
                project_id=command.project_id,
                scope=command.scope,
                model_profile_id=command.model_profile_id,
                workflow_key=command.workflow_key,
                route_preset_key=command.route_preset_key,
                provider_model_name=command.provider_model_name,
                stage_run_id=stage_run_id,
                heartbeat=heartbeat,
            )
        if stage == "review":
            return ReviewService(
                self.session,
                base_data_dir=self.base_data_dir,
                provider=self.provider,
            ).run(
                request_id=command.request_id,
                project_id=command.project_id,
                scope=command.scope,
                model_profile_id=command.model_profile_id,
                provider_model_name=command.provider_model_name,
                review_mode=command.review_mode,
                max_rewrite_rounds=command.max_rewrite_rounds,
                stage_run_id=stage_run_id,
                heartbeat=heartbeat,
            )
        if stage == "export":
            return ExportService(self.session, base_data_dir=self.base_data_dir).run(
                request_id=command.request_id,
                project_id=command.project_id,
                scope=command.scope,
                heartbeat=heartbeat,
            )
        raise ToolError(
            code="invalid_arguments",
            message="目前只支持 stage=chaptering、glossary、translation、review 或 export。",
            status=400,
        )
