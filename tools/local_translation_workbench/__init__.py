from __future__ import annotations

from pathlib import Path


# Support standalone-repo imports like `tools.local_translation_workbench.app.cli`
# by pointing the package search path back to the tool root.
_TOOL_ROOT = Path(__file__).resolve().parents[2]
__path__ = [str(_TOOL_ROOT)]
