from __future__ import annotations

import sys
from collections.abc import Sequence

from app.cli import main as action_main


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return action_main(["help"])

    command = args[0].lower()
    if command in {"help", "-h", "--help", "/?"}:
        return action_main(["help"])

    return action_main(args)
