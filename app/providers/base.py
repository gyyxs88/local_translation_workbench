from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class TextGenerationUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, object] | None) -> "TextGenerationUsage | None":
        if payload is None:
            return None

        values: dict[str, int] = {}
        for key in (
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        ):
            raw_value = payload.get(key)
            if raw_value is None or raw_value == "":
                continue
            try:
                values[key] = int(raw_value)
            except (TypeError, ValueError):
                continue

        if "total_tokens" not in values and (
            "input_tokens" in values or "output_tokens" in values
        ):
            values["total_tokens"] = values.get("input_tokens", 0) + values.get("output_tokens", 0)

        if not values:
            return None
        return cls(**values)

    def to_payload(self) -> dict[str, int]:
        payload: dict[str, int] = {}
        for key in (
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        ):
            value = getattr(self, key)
            if value is not None:
                payload[key] = int(value)
        return payload


@dataclass(frozen=True)
class TextGenerationResult:
    content: str
    provider_name: str
    model_name: str
    model_profile_id: str | None = None
    fallback_depth: int = 0
    usage: TextGenerationUsage | Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.usage, Mapping):
            object.__setattr__(self, "usage", TextGenerationUsage.from_payload(self.usage))


class Provider(ABC):
    @abstractmethod
    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        raise NotImplementedError
