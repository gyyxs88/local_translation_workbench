from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_provider_secret_refs_migration():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "0026_provider_secret_refs.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0026_provider_secret_refs", migration_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _ScalarResult:
    def __init__(self, value: int) -> None:
        self.value = value

    def scalar_one(self) -> int:
        return self.value


class _FakeBind:
    def __init__(self, *, ref_only_provider_count: int) -> None:
        self.ref_only_provider_count = ref_only_provider_count
        self.statements: list[str] = []

    def execute(self, statement):
        self.statements.append(str(statement))
        return _ScalarResult(self.ref_only_provider_count)


class _FakeOp:
    def __init__(self, *, ref_only_provider_count: int) -> None:
        self.bind = _FakeBind(ref_only_provider_count=ref_only_provider_count)
        self.calls: list[tuple[str, object, object]] = []

    def get_bind(self):
        self.calls.append(("get_bind", None, None))
        return self.bind

    def drop_column(self, table_name: str, column_name: str) -> None:
        self.calls.append(("drop_column", table_name, column_name))

    def alter_column(self, table_name: str, column_name: str, **kwargs) -> None:
        self.calls.append(("alter_column", table_name, column_name))


def test_provider_secret_refs_downgrade_blocks_ref_only_providers_before_destructive_ddl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_provider_secret_refs_migration()
    fake_op = _FakeOp(ref_only_provider_count=1)
    monkeypatch.setattr(migration, "op", fake_op)

    with pytest.raises(RuntimeError) as exc:
        migration.downgrade()

    assert "api_key_secret_ref" in str(exc.value)
    assert "api_key_value" in str(exc.value)
    assert not any(call[0] == "drop_column" for call in fake_op.calls)
    assert not any(call[0] == "alter_column" for call in fake_op.calls)
