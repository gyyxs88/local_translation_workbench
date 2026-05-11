from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from ..errors import ToolError


class SchemaVersionService:
    def __init__(self, session) -> None:
        self.session = session

    def assert_current(self) -> None:
        expected_heads = self._load_expected_heads()
        current_revisions = self._load_current_revisions()
        if set(current_revisions) == set(expected_heads):
            return

        raise ToolError(
            code="schema_migration_required",
            message=(
                "数据库 schema 不是当前 Alembic head，请先执行迁移后再运行 stage。"
                f" 当前版本: {self._format_revisions(current_revisions)}；"
                f" 期望版本: {self._format_revisions(expected_heads)}。"
            ),
            status=409,
            details={
                "current_revisions": current_revisions,
                "expected_heads": expected_heads,
                "migration_command": "python -m alembic -c alembic.ini upgrade head",
            },
        )

    def _load_current_revisions(self) -> list[str]:
        bind = self.session.get_bind()
        if not inspect(bind).has_table("alembic_version"):
            return []
        rows = self.session.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        return sorted(str(item) for item in rows if item is not None and str(item).strip())

    def _load_expected_heads(self) -> list[str]:
        tool_root = Path(__file__).resolve().parents[2]
        config = Config(str(tool_root / "alembic.ini"))
        config.set_main_option("script_location", str(tool_root / "migrations"))
        return sorted(str(item) for item in ScriptDirectory.from_config(config).get_heads())

    def _format_revisions(self, revisions: list[str]) -> str:
        return ", ".join(revisions) if revisions else "未初始化"


def assert_database_schema_current(session) -> None:
    SchemaVersionService(session).assert_current()
