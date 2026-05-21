from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import update_check
from .paths import alembic_ini_path, default_data_dir, migrations_dir


def _mask_configured_secret(value: str | None) -> dict[str, object]:
    return {
        "configured": bool(value),
        "masked": "<set>" if value else None,
    }


def build_report() -> dict[str, object]:
    data_dir = Path(os.getenv("LTW_DATA_DIR", str(default_data_dir())))
    python_ok = sys.version_info >= (3, 9)
    database_url = _mask_configured_secret(os.getenv("LTW_DATABASE_URL"))
    data_dir_check = {
        "path": str(data_dir),
        "exists": data_dir.exists(),
        "parent_exists": data_dir.parent.exists(),
    }
    alembic_check = {
        "ini_exists": alembic_ini_path().exists(),
        "migrations_exists": migrations_dir().exists(),
    }
    checks: dict[str, object] = {
        "python": {
            "version": sys.version.split()[0],
            "ok": python_ok,
        },
        "database_url": database_url,
        "data_dir": data_dir_check,
        "alembic": alembic_check,
        "update": update_check.maybe_check_for_update(),
    }
    ok = bool(
        python_ok
        and database_url["configured"]
        and data_dir_check["parent_exists"]
        and alembic_check["ini_exists"]
        and alembic_check["migrations_exists"]
    )
    return {"ok": ok, "checks": checks}


def run() -> int:
    print(json.dumps(build_report(), ensure_ascii=False))
    return 0
