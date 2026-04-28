from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..db.models import ModelProfile, ModelRouteBinding, ModelRoutePreset, ProviderConfig


class ProviderProfileRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_provider_by_id(self, provider_id: int) -> ProviderConfig | None:
        return self.session.get(ProviderConfig, provider_id)

    def get_provider_by_key(self, provider_key: str) -> ProviderConfig | None:
        return self.session.execute(
            select(ProviderConfig).where(ProviderConfig.provider_key == provider_key)
        ).scalar_one_or_none()

    def list_providers(self) -> list[ProviderConfig]:
        return list(
            self.session.execute(select(ProviderConfig).order_by(ProviderConfig.id.asc())).scalars().all()
        )

    def create_provider(self, **kwargs) -> ProviderConfig:
        record = ProviderConfig(**kwargs)
        self.session.add(record)
        self.session.flush()
        return record

    def update_provider_secret(
        self,
        *,
        provider_key: str,
        api_key_value: str,
    ) -> ProviderConfig:
        provider = self.get_provider_by_key(provider_key)
        if provider is None:
            raise ValueError(f"provider {provider_key} not found")
        provider.api_key_value = api_key_value
        self.session.flush()
        return provider

    def get_profile_by_key(self, profile_key: str) -> ModelProfile | None:
        return self.session.execute(
            select(ModelProfile).where(ModelProfile.profile_key == profile_key)
        ).scalar_one_or_none()

    def get_default_profile(self) -> ModelProfile | None:
        return self.session.execute(
            select(ModelProfile).where(ModelProfile.is_default == 1).order_by(ModelProfile.id.desc())
        ).scalar_one_or_none()

    def list_profiles(self) -> list[ModelProfile]:
        return list(
            self.session.execute(select(ModelProfile).order_by(ModelProfile.id.asc())).scalars().all()
        )

    def clear_default_profiles(self) -> None:
        self.session.execute(update(ModelProfile).values(is_default=0))

    def create_profile(self, **kwargs) -> ModelProfile:
        record = ModelProfile(**kwargs)
        self.session.add(record)
        self.session.flush()
        return record

    def update_profile_fallbacks(self, *, profile_key: str, fallback_profile_keys: list[str]) -> ModelProfile:
        profile = self.get_profile_by_key(profile_key)
        if profile is None:
            raise ValueError(f"profile {profile_key} not found")
        profile.fallback_profile_keys_json = list(fallback_profile_keys)
        self.session.flush()
        return profile

    def get_route_preset_by_key(self, preset_key: str) -> ModelRoutePreset | None:
        return self.session.execute(
            select(ModelRoutePreset).where(ModelRoutePreset.preset_key == preset_key)
        ).scalar_one_or_none()

    def get_default_route_preset(self) -> ModelRoutePreset | None:
        return self.session.execute(
            select(ModelRoutePreset)
            .where(ModelRoutePreset.is_default == 1)
            .order_by(ModelRoutePreset.id.desc())
        ).scalar_one_or_none()

    def list_route_presets(self) -> list[ModelRoutePreset]:
        return list(
            self.session.execute(select(ModelRoutePreset).order_by(ModelRoutePreset.id.asc())).scalars().all()
        )

    def clear_default_route_presets(self) -> None:
        self.session.execute(update(ModelRoutePreset).values(is_default=0))

    def create_route_preset(self, **kwargs) -> ModelRoutePreset:
        record = ModelRoutePreset(**kwargs)
        self.session.add(record)
        self.session.flush()
        return record

    def replace_route_bindings(
        self,
        *,
        preset_id: int,
        bindings: list[dict[str, object]],
    ) -> list[ModelRouteBinding]:
        self.session.execute(delete(ModelRouteBinding).where(ModelRouteBinding.preset_id == preset_id))
        records: list[ModelRouteBinding] = []
        for binding in bindings:
            record = ModelRouteBinding(preset_id=preset_id, **binding)
            self.session.add(record)
            records.append(record)
        self.session.flush()
        return records

    def list_route_bindings(self, *, preset_id: int) -> list[ModelRouteBinding]:
        return list(
            self.session.execute(
                select(ModelRouteBinding)
                .where(ModelRouteBinding.preset_id == preset_id)
                .order_by(ModelRouteBinding.id.asc())
            )
            .scalars()
            .all()
        )
