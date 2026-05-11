from __future__ import annotations

from dataclasses import dataclass

from ..errors import ToolError
from ..config import ToolConfig
from .base import Provider
from ..services.provider_resolution_service import FailoverProvider, ProviderResolutionService


@dataclass(frozen=True)
class ResolvedProviderProfile:
    provider: Provider
    profile_key: str
    model_name: str


def build_provider(config: ToolConfig) -> Provider:
    raise ToolError(
        code="invalid_arguments",
        message="模型调用阶段必须使用数据库 provider/profile 配置。",
        status=400,
    )


def build_provider_from_profile(session, config: ToolConfig, model_profile_id: str | None) -> ResolvedProviderProfile:
    normalized_model_profile_id = None if model_profile_id is None else model_profile_id.strip()
    use_default_profile = normalized_model_profile_id in {None, "", "default"}
    resolution_service = ProviderResolutionService(session, config)
    profile_chain = resolution_service.resolve_profile_chain(model_profile_id=normalized_model_profile_id)

    if profile_chain is not None:
        primary_candidate = profile_chain.candidates[0]
        resolved_provider: Provider
        if len(profile_chain.candidates) == 1:
            if primary_candidate.build_error is not None:
                raise primary_candidate.build_error
            if primary_candidate.provider is None:
                raise ToolError(
                    code="provider_error",
                    message=f"profile={primary_candidate.profile_key} 缺少可用 provider 实例。",
                    status=502,
                )
            resolved_provider = primary_candidate.provider
        else:
            resolved_provider = FailoverProvider(
                requested_profile_key=profile_chain.requested_profile_key,
                candidates=profile_chain.candidates,
            )
        return ResolvedProviderProfile(
            provider=resolved_provider,
            profile_key=profile_chain.requested_profile_key,
            model_name=primary_candidate.model_name,
        )

    raise ToolError(
        code="invalid_arguments",
        message="模型调用阶段缺少数据库默认 profile。请先创建数据库 provider/profile。",
        status=400,
    )
