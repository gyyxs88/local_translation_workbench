from __future__ import annotations

import sys
from collections.abc import Sequence

from app.cli import build_help_text
from app.cli import main as action_main


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return _print_help()

    command = args[0].lower()
    if command in {"help", "-h", "--help", "/?"}:
        return _print_help()

    if command == "doctor":
        from .doctor import run

        return run()

    if command in {"update-check", "check-update"}:
        from .update_check import run

        return run()

    if command == "migrate":
        from .migrate import run

        return run()

    return action_main(args)


def _print_help() -> int:
    print(
        build_help_text()
        + "\n"
        + "本地入口命令:\n"
        + "  doctor\n"
        + "  migrate\n"
        + "  update-check / check-update\n"
    )
    return 0
