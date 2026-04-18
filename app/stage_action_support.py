from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .config import load_config
from .services.glossary_pipeline_service import GlossaryPipelineService
from .services.translation_pipeline_service import TranslationPipelineService


@dataclass(frozen=True)
class StageProviderContext:
    config: Any
    provider: Any | None
    resolved_profile_id: str
    resolved_model_name: str | None


def resolve_stage_provider_context(
    *,
    session,
    stage: str,
    arguments: dict[str, str],
) -> StageProviderContext:
    from . import action_router

    config = load_config()
    requested_model_profile_id = arguments.get("model_profile_id", "default")
    resolved_provider = action_router._resolve_model_stage_provider(
        session=session,
        config=config,
        stage=stage,
        model_profile_id=requested_model_profile_id,
    )
    return StageProviderContext(
        config=config,
        provider=None if resolved_provider is None else resolved_provider.provider,
        resolved_profile_id=(
            resolved_provider.profile_key if resolved_provider is not None else requested_model_profile_id
        ),
        resolved_model_name=(
            resolved_provider.model_name if resolved_provider is not None else arguments.get("provider_model_name")
        ),
    )


def run_glossary_pipeline_action(
    *,
    session,
    arguments: dict[str, str],
    action_name: str,
    runner: Callable[[GlossaryPipelineService, StageProviderContext], Any],
) -> dict[str, Any]:
    context = resolve_stage_provider_context(session=session, stage="glossary", arguments=arguments)
    pipeline = GlossaryPipelineService(session, provider=context.provider)
    data = runner(pipeline, context)
    session.commit()
    return {"ok": True, "action": action_name, "data": data}


def run_translation_pipeline_action(
    *,
    session,
    arguments: dict[str, str],
    action_name: str,
    runner: Callable[[TranslationPipelineService, StageProviderContext], Any],
) -> dict[str, Any]:
    context = resolve_stage_provider_context(session=session, stage="translation", arguments=arguments)
    pipeline = TranslationPipelineService(
        session,
        base_data_dir=Path(context.config.data_dir),
        provider=context.provider,
    )
    data = runner(pipeline, context)
    session.commit()
    return {"ok": True, "action": action_name, "data": data}
