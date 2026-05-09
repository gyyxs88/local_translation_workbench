from __future__ import annotations

from pathlib import Path

from tools.local_translation_workbench.app.config import ToolConfig
from tools.local_translation_workbench.app.errors import ToolError
from tools.local_translation_workbench.app.providers.base import TextGenerationResult
from tools.local_translation_workbench.app.repositories.provider_profiles import ProviderProfileRepository


class _FailingProvider:
    def __init__(
        self,
        *,
        code: str = "provider_error",
        message: str = "upstream failed",
        details: object | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        raise ToolError(code=self.code, message=self.message, status=502, details=self.details)


class _SuccessfulProvider:
    def __init__(self, *, content: str, usage: dict[str, int] | None = None) -> None:
        self.content = content
        self.usage = usage

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        return TextGenerationResult(
            content=self.content,
            provider_name="successful_provider",
            model_name=model_name,
            usage=self.usage,
        )


def test_provider_resolution_service_expands_recursive_chain_without_duplicates(db_session) -> None:
    from tools.local_translation_workbench.app.services.provider_resolution_service import ProviderResolutionService

    repository = ProviderProfileRepository(db_session)
    provider_a = repository.create_provider(
        provider_key="provider_a",
        provider_type="openai_compatible",
        display_name="Provider A",
        base_url="https://a.example.com/v1",
        api_key_value="sk-provider-a",
        status="active",
        note=None,
    )
    provider_b = repository.create_provider(
        provider_key="provider_b",
        provider_type="openai_compatible",
        display_name="Provider B",
        base_url="https://b.example.com/v1",
        api_key_value="sk-provider-b",
        status="active",
        note=None,
    )
    provider_c = repository.create_provider(
        provider_key="provider_c",
        provider_type="openai_compatible",
        display_name="Provider C",
        base_url="https://c.example.com/v1",
        api_key_value="sk-provider-c",
        status="active",
        note=None,
    )
    repository.create_profile(
        profile_key="profile_c",
        provider_id=provider_c.id,
        model_name="gpt-5.4",
        timeout_seconds=60,
        temperature=0,
        fallback_profile_keys_json=None,
        is_default=0,
        status="active",
        note=None,
    )
    repository.create_profile(
        profile_key="profile_b",
        provider_id=provider_b.id,
        model_name="gpt-5.4",
        timeout_seconds=60,
        temperature=0,
        fallback_profile_keys_json=["profile_c"],
        is_default=0,
        status="active",
        note=None,
    )
    repository.create_profile(
        profile_key="profile_a",
        provider_id=provider_a.id,
        model_name="gpt-5.4",
        timeout_seconds=60,
        temperature=0,
        fallback_profile_keys_json=["profile_b", "profile_c"],
        is_default=0,
        status="active",
        note=None,
    )
    db_session.commit()

    service = ProviderResolutionService(
        db_session,
        ToolConfig(database_url=None, data_dir=Path(".")),
    )
    chain = service.resolve_profile_chain(model_profile_id="profile_a")

    assert chain is not None
    assert chain.requested_profile_key == "profile_a"
    assert [item.profile_key for item in chain.candidates] == ["profile_a", "profile_b", "profile_c"]


def test_failover_provider_returns_actual_profile_after_first_candidate_failure() -> None:
    from tools.local_translation_workbench.app.services.provider_resolution_service import (
        FailoverProvider,
        ResolvedProviderCandidate,
    )

    provider = FailoverProvider(
        requested_profile_key="main_profile",
        candidates=[
            ResolvedProviderCandidate(
                profile_key="main_profile",
                provider_key="main_provider",
                provider_type="openai_compatible",
                model_name="gpt-5.4",
                timeout_seconds=60,
                temperature=0,
                provider=_FailingProvider(),
            ),
            ResolvedProviderCandidate(
                profile_key="backup_profile",
                provider_key="backup_provider",
                provider_type="openai_compatible",
                model_name="gpt-5.4",
                timeout_seconds=60,
                temperature=0,
                provider=_SuccessfulProvider(content="backup text"),
            ),
        ],
    )

    result = provider.generate_text(
        prompt="hello",
        model_name="ignored",
        timeout_seconds=60,
    )

    assert result.content == "backup text"
    assert result.model_profile_id == "backup_profile"
    assert result.fallback_depth == 1


def test_failover_provider_preserves_usage_from_successful_candidate() -> None:
    from tools.local_translation_workbench.app.services.provider_resolution_service import (
        FailoverProvider,
        ResolvedProviderCandidate,
    )

    provider = FailoverProvider(
        requested_profile_key="main_profile",
        candidates=[
            ResolvedProviderCandidate(
                profile_key="main_profile",
                provider_key="main_provider",
                provider_type="openai_compatible",
                model_name="gpt-5.4",
                timeout_seconds=60,
                temperature=0,
                provider=_SuccessfulProvider(
                    content="ok",
                    usage={"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
                ),
            ),
        ],
    )

    result = provider.generate_text(prompt="hello", model_name="ignored", timeout_seconds=60)

    assert result.usage is not None
    assert result.usage.to_payload() == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
    }


def test_failover_provider_attempts_include_error_type_when_all_candidates_fail() -> None:
    from tools.local_translation_workbench.app.services.provider_resolution_service import (
        FailoverProvider,
        ResolvedProviderCandidate,
    )

    provider = FailoverProvider(
        requested_profile_key="main_profile",
        candidates=[
            ResolvedProviderCandidate(
                profile_key="main_profile",
                provider_key="main_provider",
                provider_type="openai_compatible",
                model_name="gpt-5.4",
                timeout_seconds=60,
                temperature=0,
                provider=_FailingProvider(message="429 rate limit exceeded"),
            ),
            ResolvedProviderCandidate(
                profile_key="backup_profile",
                provider_key="backup_provider",
                provider_type="openai_compatible",
                model_name="gpt-5.4",
                timeout_seconds=60,
                temperature=0,
                provider=_FailingProvider(message="content policy blocked"),
            ),
        ],
    )

    try:
        provider.generate_text(prompt="hello", model_name="ignored", timeout_seconds=60)
    except ToolError as exc:
        attempts = exc.details["attempts"]
    else:
        raise AssertionError("expected ToolError")

    assert [item["error_type"] for item in attempts] == ["rate_limit", "policy_block"]
