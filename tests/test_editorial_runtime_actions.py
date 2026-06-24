from __future__ import annotations

import json
from pathlib import Path

from tools.local_translation_workbench.app.action_router import route_action


def test_editorial_actions_run_single_chapter_dry_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LTW_EDITORIAL_HOME", str(tmp_path))

    init_payload = route_action(
        {
            "action": "project.init_editorial",
            "project_key": "lantern_demo",
            "title": "青灯小先生",
            "source_language": "zh",
            "target_language": "en",
        }
    )
    assert init_payload["ok"] is True

    route_action(
        {
            "action": "source.prepare",
            "project_key": "lantern_demo",
            "synopsis": "简介",
            "chapters_json": json.dumps(
                [{"chapter_key": "ch001", "title": "第一章", "source_text": "林溪点亮青灯。"}],
                ensure_ascii=False,
            ),
        }
    )
    route_action(
        {
            "action": "chapter.assign",
            "project_key": "lantern_demo",
            "chapter_key": "ch001",
            "brief": "Translate chapter 1.",
        }
    )
    route_action(
        {
            "action": "terms.prepare_pack",
            "project_key": "lantern_demo",
            "chapter_key": "ch001",
            "terms_json": json.dumps(
                [{"source_term": "林溪", "target_term": "Lin Xi", "status": "approved"}],
                ensure_ascii=False,
            ),
        }
    )
    route_action(
        {
            "action": "chapter.translate_raw",
            "project_key": "lantern_demo",
            "chapter_key": "ch001",
            "content": "raw draft",
            "note": "main translator",
        }
    )
    route_action(
        {
            "action": "chapter.review_bilingual",
            "project_key": "lantern_demo",
            "chapter_key": "ch001",
            "content": "review",
            "needs_annotation": "true",
        }
    )
    route_action(
        {
            "action": "review.adjudicate",
            "project_key": "lantern_demo",
            "chapter_key": "ch001",
            "decision": "accept_with_annotation",
            "content": "accepted review scope",
        }
    )
    route_action(
        {
            "action": "chapter.revise",
            "project_key": "lantern_demo",
            "chapter_key": "ch001",
            "content": "accepted revision",
            "annotations_json": json.dumps([{"status": "approved", "text": "note"}], ensure_ascii=False),
        }
    )
    route_action(
        {
            "action": "chapter.accept",
            "project_key": "lantern_demo",
            "chapter_key": "ch001",
            "note": "accepted",
        }
    )
    route_action({"action": "memory.derive_from_accepted", "project_key": "lantern_demo"})
    route_action({"action": "cache.rebuild", "project_key": "lantern_demo"})
    export_payload = route_action({"action": "export.build", "project_key": "lantern_demo"})
    status_payload = route_action({"action": "inspect.status", "project_key": "lantern_demo"})

    assert export_payload["data"]["chapter_count"] == 1
    assert status_payload["data"]["chapters"][0]["status"] == "accepted"
    assert "accepted revision" in (tmp_path / "lantern_demo" / "memory" / "tm.accepted.jsonl").read_text(
        encoding="utf-8"
    )
