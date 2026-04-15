from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class TextGenerationResult:
    content: str
    provider_name: str
    model_name: str
    model_profile_id: str | None = None
    fallback_depth: int = 0


class Provider(ABC):
    @abstractmethod
    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        raise NotImplementedError
