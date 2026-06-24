from __future__ import annotations

import os
from pathlib import Path


def default_editorial_home() -> Path:
    value = os.getenv("LTW_EDITORIAL_HOME")
    if value:
        return Path(value).expanduser()
    return Path(__file__).resolve().parents[2] / "data" / "editorial_projects"
