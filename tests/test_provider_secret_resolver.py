from __future__ import annotations

from pathlib import Path

import pytest

from tools.local_translation_workbench.app.errors import ToolError
from tools.local_translation_workbench.app.services.provider_secret_resolver import ProviderSecretResolver


def test_provider_secret_resolver_reads_database_legacy_value() -> None:
    resolver = ProviderSecretResolver()

    value = resolver.resolve(api_key_value="sk-database-secret-123456", api_key_secret_ref=None)
    state = resolver.inspect(api_key_value="sk-database-secret-123456", api_key_secret_ref=None)

    assert value == "sk-database-secret-123456"
    assert state == {
        "is_set": True,
        "source": "database",
        "ref": None,
        "masked": "sk-da...3456",
    }


def test_provider_secret_resolver_reads_env_ref_without_exposing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LTW_TEST_PROVIDER_SECRET", "sk-env-secret-abcdef")
    resolver = ProviderSecretResolver()

    value = resolver.resolve(api_key_value=None, api_key_secret_ref="env:LTW_TEST_PROVIDER_SECRET")
    state = resolver.inspect(api_key_value=None, api_key_secret_ref="env:LTW_TEST_PROVIDER_SECRET")

    assert value == "sk-env-secret-abcdef"
    assert state["is_set"] is True
    assert state["source"] == "env"
    assert state["ref"] == "env:LTW_TEST_PROVIDER_SECRET"
    assert state["masked"] == "****"
    assert "sk-env-secret-abcdef" not in repr(state)


def test_provider_secret_resolver_reads_file_ref_without_exposing_secret(tmp_path: Path) -> None:
    secret_file = tmp_path / "provider-key.txt"
    secret_file.write_text("sk-file-secret-abcdef\n", encoding="utf-8")
    resolver = ProviderSecretResolver()

    value = resolver.resolve(api_key_value=None, api_key_secret_ref=f"file:{secret_file}")
    state = resolver.inspect(api_key_value=None, api_key_secret_ref=f"file:{secret_file}")

    assert value == "sk-file-secret-abcdef"
    assert state["is_set"] is True
    assert state["source"] == "file"
    assert state["ref"] == f"file:{secret_file}"
    assert state["masked"] == "****"
    assert "sk-file-secret-abcdef" not in repr(state)


def test_provider_secret_resolver_reports_missing_env_ref_without_secret_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LTW_TEST_PROVIDER_SECRET_MISSING", raising=False)
    resolver = ProviderSecretResolver()

    with pytest.raises(ToolError) as exc:
        resolver.resolve(api_key_value=None, api_key_secret_ref="env:LTW_TEST_PROVIDER_SECRET_MISSING")

    assert exc.value.code == "invalid_arguments"
    assert "env:LTW_TEST_PROVIDER_SECRET_MISSING" in exc.value.message
    assert "secret" not in (exc.value.details or {})
