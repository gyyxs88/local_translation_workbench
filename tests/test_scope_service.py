from __future__ import annotations

import pytest

from tools.local_translation_workbench.app.errors import ToolError
from tools.local_translation_workbench.app.services.scope_service import ScopeService


def test_scope_service_accepts_failed_only_and_missing_only() -> None:
    service = ScopeService()

    assert service.build_scope("failed_only") == {"type": "failed_only"}
    assert service.build_scope("missing_only") == {"type": "missing_only"}


def test_scope_service_rejects_unknown_scope_type() -> None:
    with pytest.raises(ToolError) as exc:
        ScopeService().build_scope("unknown_scope")

    assert exc.value.code == "invalid_arguments"
    assert "unknown_scope" in exc.value.message
