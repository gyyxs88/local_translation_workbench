from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from tools.local_translation_workbench.app.db.engine import get_session_factory
from tools.local_translation_workbench.app.db import models  # noqa: F401

@pytest.fixture
def project_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    workspace = tmp_path / "projects"
    workspace.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LTW_DATA_DIR", str(workspace))
    return workspace


@pytest.fixture(scope="session")
def database_url() -> str:
    database_url = os.environ.get("LTW_TEST_DATABASE_URL")
    if not database_url:
        pytest.fail("缺少 LTW_TEST_DATABASE_URL。测试必须显式指定独立测试库，禁止回退到共享库。")
    os.environ["LTW_DATABASE_URL"] = database_url
    return database_url


@pytest.fixture(scope="session", autouse=True)
def apply_migrations(database_url: str) -> None:
    tool_root = Path(__file__).resolve().parents[1]
    alembic_ini = tool_root / "alembic.ini"
    config = Config(str(alembic_ini))
    config.set_main_option("script_location", str(tool_root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    _reset_database_schema(database_url)
    command.upgrade(config, "head")


def _reset_database_schema(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            table_names = list(
                connection.execute(
                    text(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = DATABASE()
                        """
                    )
                ).scalars()
            )
            if not table_names:
                return

            connection.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for table_name in table_names:
                connection.execute(text(f"DROP TABLE IF EXISTS `{table_name}`"))
            connection.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    finally:
        engine.dispose()


@pytest.fixture
def db_session(database_url: str) -> Session:
    session = get_session_factory(database_url)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def request_id_factory() -> callable:
    def build(prefix: str) -> str:
        return f"pytest-{prefix}-{uuid4().hex[:12]}"

    return build
