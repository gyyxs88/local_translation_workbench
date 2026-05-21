from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from local_translation_workbench.paths import default_data_dir

DEFAULT_DATA_DIR = default_data_dir()


@dataclass(frozen=True)
class ToolConfig:
    database_url: str | None
    data_dir: Path


def load_config() -> ToolConfig:
    return ToolConfig(
        database_url=os.getenv("LTW_DATABASE_URL"),
        data_dir=Path(os.getenv("LTW_DATA_DIR", str(DEFAULT_DATA_DIR))),
    )
