#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TOOL_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

if [ -x "$TOOL_ROOT/.venv/bin/python" ]; then
  PYTHON_EXE="$TOOL_ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_EXE="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_EXE="$(command -v python)"
else
  echo "No available Python interpreter was found." >&2
  exit 1
fi

export PYTHONUTF8=1
cd "$TOOL_ROOT"
exec "$PYTHON_EXE" -m local_translation_workbench "$@"
