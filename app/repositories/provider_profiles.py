from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..db.models import ModelProfile, ProviderConfig


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
