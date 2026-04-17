from __future__ import annotations

import pytest

from tools.local_translation_workbench.app.services.translation_service import TranslationService


def test_translation_service_inspect_delegates_to_inspection_service(
    db_session,
    project_workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.local_translation_workbench.app.services.translation_inspection_service import (
        TranslationInspectionService,
    )

    captured: dict[str, object] = {}

    def fake_inspect(self, **kwargs):
        captured.update(kwargs)
        return {"translations": [], "versions": []}

    monkeypatch.setattr(TranslationInspectionService, "inspect", fake_inspect)

    service = TranslationService(db_session, base_data_dir=project_workspace, provider=None)

    payload = service.inspect(
        project_id=11,
        segment_id=22,
        chapter_index=None,
        segment_index=None,
        compare_version_id=33,
    )

    assert payload == {"translations": [], "versions": []}
    assert captured == {
        "project_id": 11,
        "segment_id": 22,
        "chapter_index": None,
        "segment_index": None,
        "compare_version_id": 33,
    }


def test_translation_inspection_service_rejects_compare_without_locator(db_session) -> None:
    from tools.local_translation_workbench.app.errors import ToolError
    from tools.local_translation_workbench.app.services.translation_inspection_service import (
        TranslationInspectionService,
    )

    service = TranslationInspectionService(db_session)

    with pytest.raises(ToolError, match="compare_version_id"):
        service.inspect(project_id=7, compare_version_id=9)
