from __future__ import annotations

from typing import Any, Mapping

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
        api_key_value: str | None = None,
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
        normalized_api_key_value = None if api_key_value is None else api_key_value.strip()
        if not normalized_api_key_value:
            raise ToolError(
                code="invalid_arguments",
                message="api_key_value 不能为空。",
                status=400,
            )

        record = self.repository.create_provider(
            provider_key=provider_key,
            provider_type=normalized_type,
            display_name=display_name,
            base_url=base_url.rstrip("/"),
            api_key_value=normalized_api_key_value,
            status=status,
            note=note,
        )
        self.session.commit()
        return {
            "provider_key": record.provider_key,
            "provider_type": record.provider_type,
            "display_name": record.display_name,
            "api_key_source": self._resolve_api_key_state(record)["source"],
            "status": record.status,
        }

    def set_provider_key(
        self,
        *,
        provider_key: str,
        api_key_value: str | None = None,
    ) -> dict[str, object]:
        provider = self.repository.get_provider_by_key(provider_key)
        if provider is None:
            raise ToolError(code="not_found", message=f"找不到 provider {provider_key}。", status=404)
        normalized_api_key_value = None if api_key_value is None else api_key_value.strip()
        if not normalized_api_key_value:
            raise ToolError(
                code="invalid_arguments",
                message="api_key_value 不能为空。",
                status=400,
            )
        record = self.repository.update_provider_secret(
            provider_key=provider.provider_key,
            api_key_value=normalized_api_key_value,
        )
        self.session.commit()
        return self._serialize_provider(record)

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

    def set_route_preset(
        self,
        *,
        preset_key: str,
        display_name: str,
        bindings: list[Mapping[str, Any]],
        is_default: bool = False,
        status: str = "active",
        note: str | None = None,
    ) -> dict[str, object]:
        normalized_preset_key = preset_key.strip()
        if not normalized_preset_key:
            raise ToolError(code="invalid_arguments", message="preset_key 不能为空。", status=400)
        normalized_bindings = self._normalize_route_bindings(bindings)
        if is_default:
            self.repository.clear_default_route_presets()
        preset = self.repository.get_route_preset_by_key(normalized_preset_key)
        if preset is None:
            preset = self.repository.create_route_preset(
                preset_key=normalized_preset_key,
                display_name=display_name,
                is_default=1 if is_default else 0,
                status=status,
                note=note,
            )
        else:
            preset.display_name = display_name
            preset.is_default = 1 if is_default else 0
            preset.status = status
            preset.note = note
        records = self.repository.replace_route_bindings(
            preset_id=preset.id,
            bindings=normalized_bindings,
        )
        self.session.commit()
        return self._serialize_route_preset(preset, records)

    def list_route_presets(self) -> dict[str, object]:
        return {
            "presets": [
                self._serialize_route_preset(
                    preset,
                    self.repository.list_route_bindings(preset_id=preset.id),
                )
                for preset in self.repository.list_route_presets()
            ]
        }

    def inspect_route_preset(self, *, preset_key: str) -> dict[str, object]:
        preset = self._resolve_route_preset(preset_key)
        return self._serialize_route_preset(
            preset,
            self.repository.list_route_bindings(preset_id=preset.id),
        )

    def set_default_route_preset(self, *, preset_key: str) -> dict[str, object]:
        preset = self.repository.get_route_preset_by_key(preset_key)
        if preset is None:
            raise ToolError(code="not_found", message=f"找不到 route preset {preset_key}。", status=404)
        self.repository.clear_default_route_presets()
        preset.is_default = 1
        self.session.commit()
        return self._serialize_route_preset(
            preset,
            self.repository.list_route_bindings(preset_id=preset.id),
        )

    def resolve_route_model_profile_id(
        self,
        *,
        preset_key: str | None,
        stage: str,
        step_definition: Mapping[str, Any],
    ) -> str | None:
        if preset_key is None or not str(preset_key).strip():
            return None
        preset = self._resolve_route_preset(str(preset_key))
        if preset.status != "active":
            raise ToolError(
                code="invalid_arguments",
                message=f"route preset={preset.preset_key} 未启用。",
                status=400,
            )
        bindings = self.repository.list_route_bindings(preset_id=preset.id)
        match = self._select_route_binding(
            bindings=bindings,
            stage=stage,
            step_definition=step_definition,
        )
        return None if match is None else match.model_profile_id

    def resolve_route_stage_default_profile_id(self, *, preset_key: str | None, stage: str) -> str | None:
        if preset_key is None or not str(preset_key).strip():
            return None
        preset = self._resolve_route_preset(str(preset_key))
        if preset.status != "active":
            raise ToolError(
                code="invalid_arguments",
                message=f"route preset={preset.preset_key} 未启用。",
                status=400,
            )
        bindings = [
            item
            for item in self.repository.list_route_bindings(preset_id=preset.id)
            if item.stage == stage.strip().lower()
        ]
        if not bindings:
            return None
        preferred_step_keys = {
            "glossary": ("extract_primary", "extract_secondary"),
            "translation": ("generate_primary", "generate_secondary"),
            "review": ("review_drafts", "rewrite_consensus"),
        }.get(stage.strip().lower(), ())
        for step_key in preferred_step_keys:
            for binding in bindings:
                if binding.step_key == step_key:
                    return binding.model_profile_id
        return bindings[0].model_profile_id

    def _serialize_provider(self, provider) -> dict[str, object]:
        key_state = self._resolve_api_key_state(provider)
        return {
            "provider_key": provider.provider_key,
            "provider_type": provider.provider_type,
            "display_name": provider.display_name,
            "base_url": provider.base_url,
            "api_key_is_set": key_state["is_set"],
            "api_key_source": key_state["source"],
            "api_key_masked": key_state["masked"],
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

    def _resolve_route_preset(self, preset_key: str) -> object:
        normalized_preset_key = preset_key.strip()
        if normalized_preset_key in {"", "default"}:
            preset = self.repository.get_default_route_preset()
            if preset is None:
                raise ToolError(code="not_found", message="找不到默认 route preset。", status=404)
            return preset
        preset = self.repository.get_route_preset_by_key(normalized_preset_key)
        if preset is None:
            raise ToolError(code="not_found", message=f"找不到 route preset {normalized_preset_key}。", status=404)
        return preset

    def _normalize_route_bindings(self, bindings: list[Mapping[str, Any]]) -> list[dict[str, object]]:
        if not isinstance(bindings, list) or not bindings:
            raise ToolError(code="invalid_arguments", message="bindings 必须是非空数组。", status=400)
        normalized: list[dict[str, object]] = []
        seen: set[tuple[object, ...]] = set()
        for raw_binding in bindings:
            if not isinstance(raw_binding, Mapping):
                raise ToolError(code="invalid_arguments", message="bindings 必须是对象数组。", status=400)
            stage = str(raw_binding.get("stage") or "").strip().lower()
            model_profile_id = str(raw_binding.get("model_profile_id") or "").strip()
            if not stage:
                raise ToolError(code="invalid_arguments", message="route binding 的 stage 不能为空。", status=400)
            if not model_profile_id:
                raise ToolError(
                    code="invalid_arguments",
                    message="route binding 的 model_profile_id 不能为空。",
                    status=400,
                )
            if self.repository.get_profile_by_key(model_profile_id) is None:
                raise ToolError(code="not_found", message=f"找不到 route profile {model_profile_id}。", status=404)
            binding = {
                "stage": stage,
                "step_key": self._normalize_optional_route_text(raw_binding.get("step_key")),
                "action": self._normalize_optional_route_text(raw_binding.get("action")),
                "llm_role": self._normalize_optional_route_text(raw_binding.get("llm_role")),
                "draft_role": self._normalize_optional_route_text(raw_binding.get("draft_role")),
                "model_profile_id": model_profile_id,
                "note": self._normalize_optional_route_text(raw_binding.get("note")),
            }
            if not any(binding[key] for key in ("step_key", "action", "llm_role", "draft_role")):
                raise ToolError(
                    code="invalid_arguments",
                    message="route binding 至少需要 step_key、action、llm_role 或 draft_role 之一。",
                    status=400,
                )
            dedupe_key = (
                binding["stage"],
                binding["step_key"],
                binding["action"],
                binding["llm_role"],
                binding["draft_role"],
            )
            if dedupe_key in seen:
                raise ToolError(code="conflict_error", message="route binding 存在重复匹配键。", status=409)
            seen.add(dedupe_key)
            normalized.append(binding)
        return normalized

    def _select_route_binding(self, *, bindings, stage: str, step_definition: Mapping[str, Any]):
        normalized_stage = stage.strip().lower()
        step_key = str(step_definition.get("step_key") or "").strip()
        action = str(step_definition.get("action") or "").strip()
        llm_role = str(step_definition.get("llm_role") or "").strip()
        draft_role = str(step_definition.get("draft_role") or "").strip()
        candidates = [item for item in bindings if item.stage == normalized_stage]
        exact_step_matches = [item for item in candidates if item.step_key and item.step_key == step_key]
        if exact_step_matches:
            return exact_step_matches[0]

        def score(binding) -> int:
            value = 0
            if binding.action and binding.action == action:
                value += 4
            elif binding.action:
                return -1
            if binding.llm_role and binding.llm_role == llm_role:
                value += 2
            elif binding.llm_role:
                return -1
            if binding.draft_role and binding.draft_role == draft_role:
                value += 1
            elif binding.draft_role:
                return -1
            return value

        scored = [(score(item), item) for item in candidates]
        matched = [(score_value, item) for score_value, item in scored if score_value > 0]
        if not matched:
            return None
        matched.sort(key=lambda pair: pair[0], reverse=True)
        return matched[0][1]

    def _serialize_route_preset(self, preset, bindings) -> dict[str, object]:
        return {
            "preset_key": preset.preset_key,
            "display_name": preset.display_name,
            "is_default": bool(preset.is_default),
            "status": preset.status,
            "note": preset.note,
            "bindings": [self._serialize_route_binding(item) for item in bindings],
        }

    def _serialize_route_binding(self, binding) -> dict[str, object]:
        return {
            "stage": binding.stage,
            "step_key": binding.step_key,
            "action": binding.action,
            "llm_role": binding.llm_role,
            "draft_role": binding.draft_role,
            "model_profile_id": binding.model_profile_id,
            "note": binding.note,
        }

    def _resolve_api_key_state(self, provider) -> dict[str, object]:
        db_key = provider.api_key_value or ""
        if db_key:
            return {
                "is_set": True,
                "source": "database",
                "masked": self._mask_secret(db_key),
            }
        return {
            "is_set": False,
            "source": "missing",
            "masked": None,
        }

    def _mask_secret(self, value: str) -> str:
        if len(value) <= 8:
            return "****"
        return f"{value[:5]}...{value[-4:]}"

    def _normalize_optional_route_text(self, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None
