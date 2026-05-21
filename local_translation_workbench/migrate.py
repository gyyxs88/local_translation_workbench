from __future__ import annotations

import json
import os
import sys

from alembic import command
from alembic.config import Config

from .paths import alembic_ini_path, migrations_dir


def run() -> int:
    database_url = os.getenv("LTW_DATABASE_URL")
    if not database_url:
        sys.stderr.write(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "missing_config",
                        "message": "缺少 LTW_DATABASE_URL，无法执行数据库迁移。",
                    },
                },
                ensure_ascii=False,
            )
        )
        sys.stderr.write("\n")
        return 1

    config = Config(str(alembic_ini_path()))
    config.set_main_option("script_location", str(migrations_dir()))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    print(json.dumps({"ok": True, "migration": "head"}, ensure_ascii=False))
    return 0
