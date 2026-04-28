from __future__ import annotations

from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session

from ..providers.base import Provider
from .translation_inspection_service import TranslationInspectionService
from .translation_run_service import TranslationResult, TranslationRunService


class TranslationService:
    def __init__(self, session: Session, *, base_data_dir: Path, provider: Provider | None = None) -> None:
        self.session = session
        self.base_data_dir = Path(base_data_dir)
        self.provider = provider
        self.runner = TranslationRunService(session, base_data_dir=base_data_dir, provider=provider)
        self.inspection = TranslationInspectionService(session)

    def run(
        self,
        *,
        request_id: str,
        project_id: int,
        scope: dict[str, object],
        model_profile_id: str,
        workflow_key: str | None = None,
        route_preset_key: str | None = None,
        provider_model_name: str | None = None,
        stage_run_id: int | None = None,
        heartbeat: Callable[[], None] | None = None,
    ) -> TranslationResult:
        return self.runner.run(
            request_id=request_id,
            project_id=project_id,
            scope=scope,
            model_profile_id=model_profile_id,
            workflow_key=workflow_key,
            route_preset_key=route_preset_key,
            provider_model_name=provider_model_name,
            stage_run_id=stage_run_id,
            heartbeat=heartbeat,
        )

    def inspect(
        self,
        *,
        project_id: int,
        scope: dict[str, object] | None = None,
        segment_id: int | None = None,
        chapter_index: int | None = None,
        segment_index: int | None = None,
        version_id: int | None = None,
        compare_version_id: int | None = None,
    ) -> dict[str, list[dict[str, object]]]:
        kwargs = {
            "project_id": project_id,
            "segment_id": segment_id,
            "chapter_index": chapter_index,
            "segment_index": segment_index,
            "version_id": version_id,
            "compare_version_id": compare_version_id,
        }
        if scope is not None:
            kwargs["scope"] = scope
        return self.inspection.inspect(**kwargs)
