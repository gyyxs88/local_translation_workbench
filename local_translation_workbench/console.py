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

    if command == "doctor":
        from .doctor import run

        return run()

    if command == "migrate":
        from .migrate import run

        return run()

    return action_main(args)
