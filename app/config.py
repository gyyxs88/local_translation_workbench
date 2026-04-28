from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


TOOL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = TOOL_ROOT / "data" / "projects"


@dataclass(frozen=True)
class ToolConfig:
    database_url: str | None
    data_dir: Path


def load_config() -> ToolConfig:
    return ToolConfig(
        database_url=os.getenv("LTW_DATABASE_URL"),
        data_dir=Path(os.getenv("LTW_DATA_DIR", str(DEFAULT_DATA_DIR))),
    )
