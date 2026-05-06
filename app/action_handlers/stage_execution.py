from __future__ import annotations

from typing import Any

from .. import action_router as router
from ..services.provider_profile_service import ProviderProfileService
from ..services.schema_version_service import assert_database_schema_current
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
    route_preset_key: str | None = None,
    review_mode: str = "hybrid",
    max_rewrite_rounds: int = 2,
    resume: bool = False,
    rerun: bool = False,
) -> Any:
    assert_database_schema_current(session)
    normalized_stage = stage.strip().lower()
    normalized_review_mode = review_mode.strip().lower()
    needs_model_provider = normalized_stage != "review" or normalized_review_mode != "hard_only"
    provider_model_profile_id = model_profile_id
    route_service = ProviderProfileService(session)
    effective_route_preset_key = route_preset_key
    auto_route_allowed = model_profile_id is None or model_profile_id.strip() in {"", "default"}
    if (
        needs_model_provider
        and auto_route_allowed
        and (effective_route_preset_key is None or not effective_route_preset_key.strip())
    ):
        effective_route_preset_key = route_service.get_default_route_preset_key()
    if effective_route_preset_key is not None and effective_route_preset_key.strip() and needs_model_provider:
        routed_profile_id = route_service.resolve_route_stage_default_profile_id(
            preset_key=effective_route_preset_key,
            stage=normalized_stage,
        )
        if routed_profile_id:
            provider_model_profile_id = routed_profile_id
    resolved_provider = (
        router._resolve_model_stage_provider(
            session=session,
            config=config,
            stage=stage,
            model_profile_id=provider_model_profile_id,
        )
        if needs_model_provider
        else None
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
            route_preset_key=effective_route_preset_key,
            provider_model_name=resolved_provider.model_name if resolved_provider is not None else None,
            review_mode=review_mode,
            max_rewrite_rounds=max_rewrite_rounds,
            resume=resume,
            rerun=rerun,
        )
    )
