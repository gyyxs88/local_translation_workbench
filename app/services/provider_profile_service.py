from __future__ import annotations

import os

from ..errors import ToolError
from ..repositories.provider_profiles import ProviderProfileRepository


class ProviderProfileService:
    SUPPORTED_PROVIDER_TYPES = {"openai_compatible", "anthropic_messages"}

    def __init__(self, session) -> None:
        self.session = session
        self.repository = ProviderProfileRepository(session)

    def create_provider(
        self,
        *,
        provider_key: str,
        provider_type: str,
        display_name: str,
        base_url: str,
        api_key_env_name: str,
        status: str = "active",
        note: str | None = None,
    ) -> dict[str, object]:
        normalized_type = provider_type.strip().lower()
        if normalized_type not in self.SUPPORTED_PROVIDER_TYPES:
            raise ToolError(
                code="invalid_arguments",
                message=f"不支持的 provider_type: {provider_type}",
                status=400,
            )
        if self.repository.get_provider_by_key(provider_key) is not None:
            raise ToolError(
                code="conflict_error",
                message=f"provider_key={provider_key} 已存在。",
                status=409,
            )
        normalized_env_name = api_key_env_name.strip()
        if not normalized_env_name:
            raise ToolError(
                code="invalid_arguments",
                message="api_key_env_name 不能为空。",
                status=400,
            )

        record = self.repository.create_provider(
            provider_key=provider_key,
            provider_type=normalized_type,
            display_name=display_name,
            base_url=base_url.rstrip("/"),
            api_key_env_name=normalized_env_name,
            status=status,
            note=note,
        )
        self.session.commit()
        return {
            "provider_key": record.provider_key,
            "provider_type": record.provider_type,
            "display_name": record.display_name,
            "api_key_env_name": record.api_key_env_name,
            "status": record.status,
        }

    def create_profile(
        self,
        *,
        profile_key: str,
        provider_key: str,
        model_name: str,
        timeout_seconds: int | None = None,
        temperature: int | None = None,
        fallback_profile_keys: list[str] | None = None,
        is_default: bool = False,
        status: str = "active",
        note: str | None = None,
    ) -> dict[str, object]:
        normalized_profile_key = profile_key.strip()
        if normalized_profile_key.lower() == "default":
            raise ToolError(
                code="invalid_arguments",
                message="profile_key=default 是保留值，不能用于创建 profile。",
                status=400,
            )
        provider = self.repository.get_provider_by_key(provider_key)
        if provider is None:
            raise ToolError(
                code="not_found",
                message=f"找不到 provider {provider_key}。",
                status=404,
            )
        if self.repository.get_profile_by_key(normalized_profile_key) is not None:
            raise ToolError(
                code="conflict_error",
                message=f"profile_key={normalized_profile_key} 已存在。",
                status=409,
            )
        normalized_fallback_profile_keys = self._normalize_fallback_profile_keys(
            owner_profile_key=normalized_profile_key,
            fallback_profile_keys=fallback_profile_keys,
        )
        if is_default:
            self.repository.clear_default_profiles()

        record = self.repository.create_profile(
            profile_key=normalized_profile_key,
            provider_id=provider.id,
            model_name=model_name,
            timeout_seconds=timeout_seconds,
            temperature=temperature,
            fallback_profile_keys_json=normalized_fallback_profile_keys or None,
            is_default=1 if is_default else 0,
            status=status,
            note=note,
        )
        self.session.commit()
        return {
            "profile_key": record.profile_key,
            "provider_key": provider.provider_key,
            "model_name": record.model_name,
            "fallback_profile_keys": normalized_fallback_profile_keys,
            "status": record.status,
        }

    def set_profile_fallbacks(
        self,
        *,
        profile_key: str,
        fallback_profile_keys: list[str],
    ) -> dict[str, object]:
        profile = self.repository.get_profile_by_key(profile_key)
        if profile is None:
            raise ToolError(code="not_found", message=f"找不到 profile {profile_key}。", status=404)

        normalized_fallback_profile_keys = self._normalize_fallback_profile_keys(
            owner_profile_key=profile.profile_key,
            fallback_profile_keys=fallback_profile_keys,
        )
        record = self.repository.update_profile_fallbacks(
            profile_key=profile.profile_key,
            fallback_profile_keys=normalized_fallback_profile_keys,
        )
        self.session.commit()
        return {
            "profile_key": record.profile_key,
            "fallback_profile_keys": normalized_fallback_profile_keys,
        }

    def list_providers(self) -> dict[str, object]:
        return {
            "providers": [self._serialize_provider(item) for item in self.repository.list_providers()]
        }

    def inspect_provider(self, *, provider_key: str) -> dict[str, object]:
        provider = self.repository.get_provider_by_key(provider_key)
        if provider is None:
            raise ToolError(code="not_found", message=f"找不到 provider {provider_key}。", status=404)
        return self._serialize_provider(provider)

    def list_profiles(self) -> dict[str, object]:
        providers_by_id = {item.id: item for item in self.repository.list_providers()}
        return {
            "profiles": [
                self._serialize_profile(item, providers_by_id.get(item.provider_id))
                for item in self.repository.list_profiles()
            ]
        }

    def inspect_profile(self, *, profile_key: str) -> dict[str, object]:
        profile = self.repository.get_profile_by_key(profile_key)
        if profile is None:
            raise ToolError(code="not_found", message=f"找不到 profile {profile_key}。", status=404)
        provider = self.repository.get_provider_by_id(profile.provider_id)
        return self._serialize_profile(profile, provider)

    def _serialize_provider(self, provider) -> dict[str, object]:
        return {
            "provider_key": provider.provider_key,
            "provider_type": provider.provider_type,
            "display_name": provider.display_name,
            "base_url": provider.base_url,
            "api_key_env_name": provider.api_key_env_name,
            "api_key_is_set": bool(os.getenv(provider.api_key_env_name)),
            "status": provider.status,
            "note": provider.note,
        }

    def _serialize_profile(self, profile, provider) -> dict[str, object]:
        return {
            "profile_key": profile.profile_key,
            "provider_key": None if provider is None else provider.provider_key,
            "model_name": profile.model_name,
            "timeout_seconds": profile.timeout_seconds,
            "temperature": profile.temperature,
            "fallback_profile_keys": list(profile.fallback_profile_keys_json or []),
            "is_default": bool(profile.is_default),
            "status": profile.status,
            "note": profile.note,
        }

    def _normalize_fallback_profile_keys(
        self,
        *,
        owner_profile_key: str,
        fallback_profile_keys: list[str] | None,
    ) -> list[str]:
        if fallback_profile_keys is None:
            return []

        normalized_fallback_profile_keys: list[str] = []
        seen: set[str] = set()
        for raw_key in fallback_profile_keys:
            normalized_key = str(raw_key).strip()
            if not normalized_key:
                raise ToolError(code="invalid_arguments", message="fallback profile 不能为空。", status=400)
            if normalized_key == owner_profile_key:
                raise ToolError(
                    code="invalid_arguments",
                    message=f"profile={owner_profile_key} 不能把自己加入 fallback 列表。",
                    status=400,
                )
            if normalized_key in seen:
                continue
            if self.repository.get_profile_by_key(normalized_key) is None:
                raise ToolError(code="not_found", message=f"找不到 fallback profile {normalized_key}。", status=404)
            seen.add(normalized_key)
            normalized_fallback_profile_keys.append(normalized_key)
        return normalized_fallback_profile_keys
