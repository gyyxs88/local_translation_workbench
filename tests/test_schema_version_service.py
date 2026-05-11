from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from tools.local_translation_workbench.app.errors import ToolError
from tools.local_translation_workbench.app.services.schema_version_service import SchemaVersionService


def _open_sqlite_session_with_revisions(revisions: list[str] | None = None):
    engine = create_engine("sqlite:///:memory:", future=True)
    if revisions is not None:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            for revision in revisions:
                connection.execute(
                    text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                    {"revision": revision},
                )
    return sessionmaker(bind=engine, future=True)(), engine


def test_schema_version_service_accepts_current_alembic_head() -> None:
    bootstrap_session, bootstrap_engine = _open_sqlite_session_with_revisions([])
    try:
        expected_heads = SchemaVersionService(bootstrap_session)._load_expected_heads()
    finally:
        bootstrap_session.close()
        bootstrap_engine.dispose()

    session, engine = _open_sqlite_session_with_revisions(expected_heads)
    try:
        SchemaVersionService(session).assert_current()
    finally:
        session.close()
        engine.dispose()


def test_schema_version_service_rejects_stale_revision() -> None:
    session, engine = _open_sqlite_session_with_revisions(["0001_initial_schema"])
    try:
        with pytest.raises(ToolError) as exc:
            SchemaVersionService(session).assert_current()
    finally:
        session.close()
        engine.dispose()

    assert exc.value.code == "schema_migration_required"
    assert exc.value.status == 409
    assert exc.value.details["current_revisions"] == ["0001_initial_schema"]
    assert "upgrade head" in exc.value.details["migration_command"]


def test_schema_version_service_rejects_missing_alembic_version_table() -> None:
    session, engine = _open_sqlite_session_with_revisions(None)
    try:
        with pytest.raises(ToolError) as exc:
            SchemaVersionService(session).assert_current()
    finally:
        session.close()
        engine.dispose()

    assert exc.value.code == "schema_migration_required"
    assert exc.value.details["current_revisions"] == []
    assert "未初始化" in exc.value.message


def test_execute_stage_command_checks_schema_before_project_lookup(monkeypatch) -> None:
    from tools.local_translation_workbench.app import action_router as _action_router
    from tools.local_translation_workbench.app.action_handlers import stage_execution
    from tools.local_translation_workbench.app.action_handlers.stage_execution import execute_stage_command

    _ = _action_router

    def fail_schema_check(session) -> None:
        _ = session
        raise ToolError(
            code="schema_migration_required",
            message="schema stale",
            status=409,
            details={"current_revisions": ["old"], "expected_heads": ["head"]},
        )

    monkeypatch.setattr(stage_execution, "assert_database_schema_current", fail_schema_check)

    with pytest.raises(ToolError) as exc:
        execute_stage_command(
            session=object(),
            config=SimpleNamespace(data_dir=Path(".")),
            request_id="schema-check-before-stage",
            project_id=1,
            stage="chaptering",
            scope={"type": "all"},
        )

    assert exc.value.code == "schema_migration_required"
