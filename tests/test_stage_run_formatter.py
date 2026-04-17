from __future__ import annotations

from tools.local_translation_workbench.app.services.translation_run_service import TranslationResult


def test_build_stage_run_response_formats_translation_payload(
    db_session,
) -> None:
    from tools.local_translation_workbench.app.services.stage_run_response_service import (
        build_stage_run_response,
    )

    payload = build_stage_run_response(
        session=db_session,
        project_id=18,
        stage="translation",
        scope={"type": "all"},
        result=TranslationResult(
            translated_segments=4,
            active_version_ids=[3, 4, 5, 6],
            synopsis_summary={"source": {"status": "ready"}},
        ),
    )

    assert payload == {
        "ok": True,
        "action": "stage.run",
        "data": {
            "project_id": 18,
            "stage": "translation",
            "scope": {"type": "all"},
            "translated_segments": 4,
            "active_version_ids": [3, 4, 5, 6],
            "synopsis": {"source": {"status": "ready"}},
        },
    }
