from __future__ import annotations

from typing import Any

from .. import action_router as router
from ..services.stage_service import StageCommand, StageService


def execute_stage_command(
    *,
    session,
    config,
    request_id: str,
    project_id: int,
    stage: str,
    scope: dict[str, object],
    model_profile_id: str = "default",
    workflow_key: str | None = None,
    resume: bool = False,
    rerun: bool = False,
) -> Any:
    resolved_provider = router._resolve_model_stage_provider(
        session=session,
        config=config,
        stage=stage,
        model_profile_id=model_profile_id,
    )
    return StageService(
        session,
        base_data_dir=config.data_dir,
        provider=None if resolved_provider is None else resolved_provider.provider,
    ).run(
        StageCommand(
            request_id=request_id,
            project_id=project_id,
            stage=stage,
            scope=scope,
            model_profile_id=resolved_provider.profile_key if resolved_provider is not None else model_profile_id,
            workflow_key=workflow_key,
            provider_model_name=resolved_provider.model_name if resolved_provider is not None else None,
            resume=resume,
            rerun=rerun,
        )
    )
