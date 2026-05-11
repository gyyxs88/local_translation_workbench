from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from tools.local_translation_workbench.app.action_router import route_action
from tools.local_translation_workbench.app.cli import main
from tools.local_translation_workbench.app.db.models import ModelProfile, ProviderConfig
from tools.local_translation_workbench.app.errors import ToolError
from tools.local_translation_workbench.app.providers.base import TextGenerationResult
from tools.local_translation_workbench.app.services.provider_profile_service import ProviderProfileService


def test_create_provider_and_profile(db_session) -> None:
    service = ProviderProfileService(db_session)

    provider = service.create_provider(
        provider_key="codex_hk",
        provider_type="openai_compatible",
        display_name="Codex HK",
        base_url="https://provider.example.com",
        api_key_value="sk-codex-hk",
        status="active",
        note="HK gateway",
    )
    profile = service.create_profile(
        profile_key="claude_hk_sonnet_4_6",
        provider_key="codex_hk",
        model_name="claude-sonnet-4-6",
        timeout_seconds=60,
        temperature=0,
        is_default=True,
        status="active",
        note="Claude Sonnet 4.6",
    )

    stored_provider = db_session.execute(
        select(ProviderConfig).where(ProviderConfig.provider_key == "codex_hk")
    ).scalar_one()
    stored_profile = db_session.execute(
        select(ModelProfile).where(ModelProfile.profile_key == "claude_hk_sonnet_4_6")
    ).scalar_one()

    assert provider["provider_key"] == "codex_hk"
    assert stored_provider.base_url == "https://provider.example.com"
    assert stored_provider.display_name == "Codex HK"
    assert stored_provider.api_key_value == "sk-codex-hk"
    assert profile["profile_key"] == "claude_hk_sonnet_4_6"
    assert stored_profile.model_name == "claude-sonnet-4-6"
    assert stored_profile.is_default == 1


def test_create_provider_accepts_anthropic_messages_type(db_session) -> None:
    service = ProviderProfileService(db_session)

    provider = service.create_provider(
        provider_key="anthropic_proxy",
        provider_type="anthropic_messages",
        display_name="Anthropic Proxy",
        base_url="https://anthropic-proxy.example.com/v1/",
        api_key_value="sk-anthropic-proxy",
        status="active",
        note="Anthropic messages gateway",
    )

    stored_provider = db_session.execute(
        select(ProviderConfig).where(ProviderConfig.provider_key == "anthropic_proxy")
    ).scalar_one()

    assert provider["provider_key"] == "anthropic_proxy"
    assert provider["provider_type"] == "anthropic_messages"
    assert stored_provider.provider_type == "anthropic_messages"
    assert stored_provider.base_url == "https://anthropic-proxy.example.com/v1"
    assert stored_provider.api_key_value == "sk-anthropic-proxy"


def test_create_profile_rejects_missing_provider(db_session) -> None:
    service = ProviderProfileService(db_session)

    try:
        service.create_profile(
            profile_key="missing-provider-profile",
            provider_key="missing_provider",
            model_name="claude-sonnet-4-6",
            timeout_seconds=60,
            temperature=0,
            is_default=False,
            status="active",
            note=None,
        )
    except ToolError as exc:
        assert exc.code == "not_found"
        assert "missing_provider" in exc.message
    else:
        raise AssertionError("expected ToolError")


def test_create_profile_rejects_reserved_default_profile_key(db_session) -> None:
    service = ProviderProfileService(db_session)
    service.create_provider(
        provider_key="reserved_default_provider",
        provider_type="openai_compatible",
        display_name="Reserved Default Provider",
        base_url="https://reserved-default.example.com",
        api_key_value="sk-reserved-default",
        status="active",
        note=None,
    )

    with pytest.raises(ToolError) as exc:
        service.create_profile(
            profile_key="default",
            provider_key="reserved_default_provider",
            model_name="claude-sonnet-4-6",
            timeout_seconds=60,
            temperature=0,
            is_default=True,
            status="active",
            note=None,
        )

    assert exc.value.code == "invalid_arguments"
    assert exc.value.status == 400
    assert "default" in exc.value.message


def test_create_profile_accepts_fallback_profile_keys(db_session) -> None:
    service = ProviderProfileService(db_session)
    service.create_provider(
        provider_key="main_provider",
        provider_type="openai_compatible",
        display_name="Main Provider",
        base_url="https://main.example.com/v1",
        api_key_value="sk-main-provider",
        status="active",
        note=None,
    )
    service.create_provider(
        provider_key="backup_provider",
        provider_type="openai_compatible",
        display_name="Backup Provider",
        base_url="https://backup.example.com/v1",
        api_key_value="sk-backup-provider",
        status="active",
        note=None,
    )
    service.create_profile(
        profile_key="backup_profile",
        provider_key="backup_provider",
        model_name="gpt-5.4",
        timeout_seconds=60,
        temperature=0,
        is_default=False,
        status="active",
        note=None,
    )

    payload = service.create_profile(
        profile_key="main_profile",
        provider_key="main_provider",
        model_name="gpt-5.4",
        timeout_seconds=60,
        temperature=0,
        fallback_profile_keys=["backup_profile"],
        is_default=False,
        status="active",
        note=None,
    )
    stored_profile = db_session.execute(
        select(ModelProfile).where(ModelProfile.profile_key == "main_profile")
    ).scalar_one()

    assert payload["profile_key"] == "main_profile"
    assert payload["fallback_profile_keys"] == ["backup_profile"]
    assert stored_profile.fallback_profile_keys_json == ["backup_profile"]


def test_set_profile_fallbacks_rejects_self_reference(db_session) -> None:
    service = ProviderProfileService(db_session)
    service.create_provider(
        provider_key="self_provider",
        provider_type="openai_compatible",
        display_name="Self Provider",
        base_url="https://self.example.com/v1",
        api_key_value="sk-self-provider",
        status="active",
        note=None,
    )
    service.create_profile(
        profile_key="self_profile",
        provider_key="self_provider",
        model_name="gpt-5.4",
        timeout_seconds=60,
        temperature=0,
        is_default=False,
        status="active",
        note=None,
    )

    with pytest.raises(ToolError) as exc:
        service.set_profile_fallbacks(
            profile_key="self_profile",
            fallback_profile_keys=["self_profile"],
        )

    assert exc.value.code == "invalid_arguments"
    assert "self_profile" in exc.value.message


def test_cli_provider_create_and_profile_list(capsys) -> None:
    provider_key = "codex_hk_cli"
    profile_key = "claude_hk_sonnet_4_6_cli"

    exit_code = main(
        [
            "-Action",
            "provider.create",
            "-ProviderKey",
            provider_key,
            "-ProviderType",
            "openai_compatible",
            "-DisplayName",
            "Codex HK",
            "-BaseUrl",
            "https://provider.example.com",
            "-ApiKey",
            "sk-codex-hk-cli",
        ]
    )
    provider_payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert provider_payload["ok"] is True
    assert provider_payload["action"] == "provider.create"
    assert provider_payload["data"]["provider_key"] == provider_key

    exit_code = main(
        [
            "-Action",
            "profile.create",
            "-ProfileKey",
            profile_key,
            "-ProviderKey",
            provider_key,
            "-ModelName",
            "claude-sonnet-4-6",
            "-IsDefault",
            "true",
        ]
    )
    profile_payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert profile_payload["ok"] is True
    assert profile_payload["action"] == "profile.create"
    assert profile_payload["data"]["profile_key"] == profile_key

    exit_code = main(["-Action", "profile.list"])
    list_payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert list_payload["ok"] is True
    assert list_payload["action"] == "profile.list"
    assert any(item["profile_key"] == profile_key for item in list_payload["data"]["profiles"])

    exit_code = main(
        [
            "-Action",
            "provider.inspect",
            "-ProviderKey",
            provider_key,
        ]
    )
    inspect_payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert inspect_payload["ok"] is True
    assert inspect_payload["action"] == "provider.inspect"
    assert inspect_payload["data"]["provider_key"] == provider_key
    assert inspect_payload["data"]["api_key_source"] == "database"
    assert inspect_payload["data"]["api_key_is_set"] is True
    assert inspect_payload["data"]["api_key_masked"] == "sk-co...-cli"


def test_cli_profile_set_fallbacks_and_inspect(capsys) -> None:
    exit_code = main(
        [
            "-Action",
            "provider.create",
            "-ProviderKey",
            "cli_main_provider",
            "-ProviderType",
            "openai_compatible",
            "-DisplayName",
            "CLI Main Provider",
            "-BaseUrl",
            "https://main.example.com/v1",
            "-ApiKey",
            "sk-cli-main",
        ]
    )
    assert exit_code == 0
    capsys.readouterr()

    exit_code = main(
        [
            "-Action",
            "provider.create",
            "-ProviderKey",
            "cli_backup_provider",
            "-ProviderType",
            "openai_compatible",
            "-DisplayName",
            "CLI Backup Provider",
            "-BaseUrl",
            "https://backup.example.com/v1",
            "-ApiKey",
            "sk-cli-backup",
        ]
    )
    assert exit_code == 0
    capsys.readouterr()

    exit_code = main(
        [
            "-Action",
            "profile.create",
            "-ProfileKey",
            "cli_main_profile",
            "-ProviderKey",
            "cli_main_provider",
            "-ModelName",
            "gpt-5.4",
        ]
    )
    assert exit_code == 0
    capsys.readouterr()

    exit_code = main(
        [
            "-Action",
            "profile.create",
            "-ProfileKey",
            "cli_backup_profile",
            "-ProviderKey",
            "cli_backup_provider",
            "-ModelName",
            "gpt-5.4",
        ]
    )
    assert exit_code == 0
    capsys.readouterr()

    exit_code = main(
        [
            "-Action",
            "profile.set_fallbacks",
            "-ProfileKey",
            "cli_main_profile",
            "-FallbackProfileKeysJson",
            "[\"cli_backup_profile\"]",
        ]
    )
    fallback_payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert fallback_payload["ok"] is True
    assert fallback_payload["action"] == "profile.set_fallbacks"
    assert fallback_payload["data"]["fallback_profile_keys"] == ["cli_backup_profile"]

    exit_code = main(
        [
            "-Action",
            "profile.inspect",
            "-ProfileKey",
            "cli_main_profile",
        ]
    )
    inspect_payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert inspect_payload["ok"] is True
    assert inspect_payload["action"] == "profile.inspect"
    assert inspect_payload["data"]["fallback_profile_keys"] == ["cli_backup_profile"]


def test_provider_health_check_reports_fallback_success(db_session, monkeypatch) -> None:
    service = ProviderProfileService(db_session)
    service.create_provider(
        provider_key="health_main_provider",
        provider_type="openai_compatible",
        display_name="Health Main Provider",
        base_url="https://main.example.com/v1",
        api_key_value="sk-health-main",
        status="active",
        note=None,
    )
    service.create_provider(
        provider_key="health_backup_provider",
        provider_type="openai_compatible",
        display_name="Health Backup Provider",
        base_url="https://backup.example.com/v1",
        api_key_value="sk-health-backup",
        status="active",
        note=None,
    )
    service.create_profile(
        profile_key="health_backup_profile",
        provider_key="health_backup_provider",
        model_name="gpt-5.4",
        timeout_seconds=60,
        temperature=0,
        is_default=False,
        status="active",
        note=None,
    )
    service.create_profile(
        profile_key="health_main_profile",
        provider_key="health_main_provider",
        model_name="gpt-5.4",
        timeout_seconds=60,
        temperature=0,
        fallback_profile_keys=["health_backup_profile"],
        is_default=False,
        status="active",
        note=None,
    )
    def fake_generate(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        if "main.example.com" in self.base_url:
            raise ToolError(code="provider_error", message="main failed", status=502)
        return TextGenerationResult(
            content="OK",
            provider_name="openai_compatible",
            model_name=model_name,
        )

    monkeypatch.setattr(
        "tools.local_translation_workbench.app.services.provider_resolution_service.OpenAICompatibleProvider.generate_text",
        fake_generate,
    )

    payload = route_action(
        {
            "action": "provider.health_check",
            "model_profile_id": "health_main_profile",
        }
    )

    assert payload["ok"] is True
    assert payload["action"] == "provider.health_check"
    assert payload["data"]["requested_profile_id"] == "health_main_profile"
    assert payload["data"]["selected_profile_id"] == "health_backup_profile"
    assert payload["data"]["attempts"][0]["ok"] is False
    assert payload["data"]["attempts"][1]["ok"] is True


def test_create_provider_rejects_missing_database_key(db_session) -> None:
    service = ProviderProfileService(db_session)

    with pytest.raises(ToolError) as exc:
        service.create_provider(
            provider_key="missing_database_key_provider",
            provider_type="openai_compatible",
            display_name="Missing Database Key Provider",
            base_url="https://missing-key.example.com/v1",
            status="active",
            note=None,
        )

    assert exc.value.code == "invalid_arguments"
    assert "api_key_value" in exc.value.message
