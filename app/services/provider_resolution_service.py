from __future__ import annotations

from dataclasses import dataclass
import os
from time import perf_counter

from ..config import ToolConfig
from ..errors import ToolError
from ..providers.anthropic_messages import AnthropicMessagesProvider
from ..providers.base import Provider, TextGenerationResult
from ..providers.openai_compatible import OpenAICompatibleProvider
from ..repositories.provider_profiles import ProviderProfileRepository


@dataclass(frozen=True)
class ResolvedProviderCandidate:
    profile_key: str
    provider_key: str
    provider_type: str
    model_name: str
    timeout_seconds: int | None
    temperature: int | None
    provider: Provider | None
    build_error: ToolError | None = None


@dataclass(frozen=True)
class ResolvedProviderChain:
    requested_profile_key: str
    candidates: list[ResolvedProviderCandidate]


class FailoverProvider(Provider):
    FALLBACK_ELIGIBLE_ERROR_CODES = {"provider_error", "invalid_arguments", "not_found"}

    def __init__(self, *, requested_profile_key: str, candidates: list[ResolvedProviderCandidate]) -> None:
        self.requested_profile_key = requested_profile_key
        self.candidates = list(candidates)

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        attempts: list[dict[str, object]] = []
        for fallback_depth, candidate in enumerate(self.candidates):
            if candidate.build_error is not None:
                attempts.append(
                    {
                        "profile_key": candidate.profile_key,
                        "provider_key": candidate.provider_key,
                        "provider_type": candidate.provider_type,
                        "model_name": candidate.model_name,
                        "ok": False,
                        "fallback_depth": fallback_depth,
                        "error_code": candidate.build_error.code,
                        "error_message": candidate.build_error.message,
                    }
                )
                if candidate.build_error.code not in self.FALLBACK_ELIGIBLE_ERROR_CODES:
                    raise candidate.build_error
                continue
            if candidate.provider is None:
                raise ToolError(
                    code="provider_error",
                    message=f"profile={candidate.profile_key} 缺少可用 provider 实例。",
                    status=502,
                )
            try:
                result = candidate.provider.generate_text(
                    prompt=prompt,
                    model_name=candidate.model_name,
                    timeout_seconds=timeout_seconds or candidate.timeout_seconds or 60,
                )
                return TextGenerationResult(
                    content=result.content,
                    provider_name=result.provider_name,
                    model_name=result.model_name,
                    model_profile_id=candidate.profile_key,
                    fallback_depth=fallback_depth,
                )
            except ToolError as exc:
                attempts.append(
                    {
                        "profile_key": candidate.profile_key,
                        "provider_key": candidate.provider_key,
                        "provider_type": candidate.provider_type,
                        "model_name": candidate.model_name,
                        "ok": False,
                        "fallback_depth": fallback_depth,
                        "error_code": exc.code,
                        "error_message": exc.message,
                    }
                )
                if exc.code not in self.FALLBACK_ELIGIBLE_ERROR_CODES:
                    raise

        raise ToolError(
            code="provider_error",
            message="所有候选 profile 都调用失败。",
            status=502,
            details={
                "requested_profile_id": self.requested_profile_key,
                "attempts": attempts,
            },
        )


class ProviderResolutionService:
    MAX_CHAIN_LENGTH = 8

    def __init__(self, session, config: ToolConfig) -> None:
        self.session = session
        self.config = config
        self.repository = ProviderProfileRepository(session)

    def resolve_profile_chain(self, *, model_profile_id: str | None) -> ResolvedProviderChain | None:
        normalized_model_profile_id = None if model_profile_id is None else model_profile_id.strip()
        use_default_profile = normalized_model_profile_id in {None, "", "default"}

        if use_default_profile:
            requested_profile = self.repository.get_default_profile()
            if requested_profile is None:
                return None
        else:
            requested_profile = self.repository.get_profile_by_key(normalized_model_profile_id)
            if requested_profile is None:
                raise ToolError(
                    code="not_found",
                    message=f"找不到 profile {normalized_model_profile_id}。",
                    status=404,
                )

        ordered_profile_keys = self._expand_profile_keys(requested_profile.profile_key)
        candidates = [self._build_candidate(profile_key) for profile_key in ordered_profile_keys]
        return ResolvedProviderChain(
            requested_profile_key=requested_profile.profile_key,
            candidates=candidates,
        )

    def health_check(
        self,
        *,
        model_profile_id: str | None,
        include_fallbacks: bool = True,
    ) -> dict[str, object]:
        profile_chain = self.resolve_profile_chain(model_profile_id=model_profile_id)
        if profile_chain is None:
            raise ToolError(
                code="invalid_arguments",
                message="当前没有可用的默认 profile，也没有可探测的 provider 配置。",
                status=400,
            )

        attempts: list[dict[str, object]] = []
        probe_candidates = profile_chain.candidates if include_fallbacks else profile_chain.candidates[:1]
        for candidate in probe_candidates:
            started_at = perf_counter()
            if candidate.build_error is not None:
                latency_ms = int((perf_counter() - started_at) * 1000)
                attempts.append(
                    {
                        "profile_key": candidate.profile_key,
                        "provider_key": candidate.provider_key,
                        "model_name": candidate.model_name,
                        "ok": False,
                        "latency_ms": latency_ms,
                        "content_length": 0,
                        "error_code": candidate.build_error.code,
                        "error_message": candidate.build_error.message,
                    }
                )
                if candidate.build_error.code not in FailoverProvider.FALLBACK_ELIGIBLE_ERROR_CODES:
                    raise candidate.build_error
                continue
            if candidate.provider is None:
                raise ToolError(
                    code="provider_error",
                    message=f"profile={candidate.profile_key} 缺少可用 provider 实例。",
                    status=502,
                )
            try:
                result = candidate.provider.generate_text(
                    prompt="Return exactly: OK",
                    model_name=candidate.model_name,
                    timeout_seconds=candidate.timeout_seconds or 30,
                )
                latency_ms = int((perf_counter() - started_at) * 1000)
                attempts.append(
                    {
                        "profile_key": candidate.profile_key,
                        "provider_key": candidate.provider_key,
                        "model_name": candidate.model_name,
                        "ok": True,
                        "latency_ms": latency_ms,
                        "content_length": len(result.content or ""),
                    }
                )
                return {
                    "requested_profile_id": profile_chain.requested_profile_key,
                    "selected_profile_id": candidate.profile_key,
                    "ok": True,
                    "attempts": attempts,
                }
            except ToolError as exc:
                latency_ms = int((perf_counter() - started_at) * 1000)
                attempts.append(
                    {
                        "profile_key": candidate.profile_key,
                        "provider_key": candidate.provider_key,
                        "model_name": candidate.model_name,
                        "ok": False,
                        "latency_ms": latency_ms,
                        "content_length": 0,
                        "error_code": exc.code,
                        "error_message": exc.message,
                    }
                )
                if exc.code not in FailoverProvider.FALLBACK_ELIGIBLE_ERROR_CODES:
                    raise

        raise ToolError(
            code="provider_error",
            message="所有候选 profile 都调用失败。",
            status=502,
            details={
                "requested_profile_id": profile_chain.requested_profile_key,
                "attempts": attempts,
            },
        )

    def _expand_profile_keys(self, requested_profile_key: str) -> list[str]:
        ordered_profile_keys: list[str] = []
        seen: set[str] = set()

        def visit(profile_key: str) -> None:
            if profile_key in seen or len(ordered_profile_keys) >= self.MAX_CHAIN_LENGTH:
                return
            seen.add(profile_key)
            ordered_profile_keys.append(profile_key)

            profile = self.repository.get_profile_by_key(profile_key)
            if profile is None:
                return
            for fallback_profile_key in profile.fallback_profile_keys_json or []:
                visit(str(fallback_profile_key).strip())

        visit(requested_profile_key)
        return ordered_profile_keys

    def _build_candidate(self, profile_key: str) -> ResolvedProviderCandidate:
        profile = self.repository.get_profile_by_key(profile_key)
        if profile is None:
            raise ToolError(code="not_found", message=f"找不到 profile {profile_key}。", status=404)
        provider_config = self.repository.get_provider_by_id(profile.provider_id)
        if provider_config is None:
            raise ToolError(
                code="not_found",
                message=f"profile={profile.profile_key} 关联的 provider 不存在。",
                status=404,
            )
        if profile.status != "active":
            raise ToolError(
                code="invalid_arguments",
                message=f"profile={profile.profile_key} 未启用。",
                status=400,
            )
        if provider_config.status != "active":
            raise ToolError(
                code="invalid_arguments",
                message=f"provider={provider_config.provider_key} 未启用。",
                status=400,
            )

        build_error: ToolError | None = None
        provider: Provider | None
        try:
            provider = self._build_provider_for_candidate(
                provider_type=provider_config.provider_type,
                base_url=provider_config.base_url,
                api_key_env_name=provider_config.api_key_env_name,
            )
        except ToolError as exc:
            provider = None
            build_error = exc
        return ResolvedProviderCandidate(
            profile_key=profile.profile_key,
            provider_key=provider_config.provider_key,
            provider_type=provider_config.provider_type,
            model_name=profile.model_name,
            timeout_seconds=profile.timeout_seconds,
            temperature=profile.temperature,
            provider=provider,
            build_error=build_error,
        )

    def _build_provider_for_candidate(self, *, provider_type: str, base_url: str, api_key_env_name: str) -> Provider:
        api_key = os.getenv(api_key_env_name)
        if not api_key:
            raise ToolError(
                code="invalid_arguments",
                message=f"provider 缺少环境变量 {api_key_env_name}。请先在环境变量中配置真实 API Key。",
                status=400,
            )
        if provider_type == "openai_compatible":
            return OpenAICompatibleProvider(base_url=base_url, api_key=api_key)
        if provider_type == "anthropic_messages":
            return AnthropicMessagesProvider(base_url=base_url, api_key=api_key)
        raise ToolError(
            code="invalid_arguments",
            message=f"不支持的 provider_type: {provider_type}",
            status=400,
        )
