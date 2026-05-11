from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ToolError(Exception):
    code: str
    message: str
    status: int = 400
    details: Any = None

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def to_payload(self, action: str | None) -> dict[str, Any]:
        return {
            "ok": False,
            "action": action,
            "status": self.status,
            "data": None,
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            },
        }
