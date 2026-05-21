from __future__ import annotations

import os
import sys
from pathlib import Path


def find_source_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "alembic.ini").exists() and (parent / "migrations").is_dir():
            return parent
    app_root = Path(__file__).resolve().parents[1]
    if (app_root / "alembic.ini").exists() and (app_root / "migrations").is_dir():
        return app_root
    return app_root


def is_source_checkout() -> bool:
    root = find_source_root()
    return (root / "README.md").exists() and (root / "migrations").is_dir()


def user_data_base_dir() -> Path:
    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
        return Path(base) if base else Path.home() / "AppData" / "Local"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def default_data_dir() -> Path:
    root = find_source_root()
    if is_source_checkout():
        return root / "data" / "projects"
    return user_data_base_dir() / "local_translation_workbench" / "projects"


def migrations_dir() -> Path:
    return find_source_root() / "migrations"


def alembic_ini_path() -> Path:
    return find_source_root() / "alembic.ini"
