from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from tools.local_translation_workbench.app import action_router
from tools.local_translation_workbench.app.db.models import (
    Chapter,
    ChapterSegment,
    SegmentTranslation,
    SegmentTranslationVersion,
    TranslationProject,
)
from tools.local_translation_workbench.app.errors import ToolError
from tools.local_translation_workbench.app.services.glossary_management_service import (
    GlossaryManagementService,
)
from tools.local_translation_workbench.app.services.glossary_denylist_service import GlossaryDenylistService


def _create_project_with_translated_segment(db_session, project_workspace: Path):
    project_key = f"glossary-management-{uuid4().hex[:10]}"
    project_root = project_workspace / project_key
    source_dir = project_root / "chapters"
    translation_dir = project_root / "translation"
    source_dir.mkdir(parents=True, exist_ok=True)
    translation_dir.mkdir(parents=True, exist_ok=True)

    source_path = project_workspace / f"{project_key}.txt"
    chapter_path = source_dir / "0001_source.txt"
    segment_path = source_dir / "0001_0001_source.txt"
    translated_path = translation_dir / "0001_0001_v0001.txt"
    source_path.write_text("第1章\n亚修拿起术灵。", encoding="utf-8")
    chapter_path.write_text("亚修拿起术灵。", encoding="utf-8")
    segment_path.write_text("亚修拿起术灵。", encoding="utf-8")
    translated_path.write_text("Ash picked up the Spell Spirit.", encoding="utf-8")

    project = TranslationProject(
        request_id=f"pytest-glossary-management-{uuid4().hex[:10]}",
        project_key=project_key,
        source_path=str(source_path),
        source_language="zh",
        target_language="en",
        status="translated",
    )
    db_session.add(project)
    db_session.flush()

    chapter = Chapter(
        project_id=project.id,
        chapter_index=1,
        chapter_title="第1章",
        source_path=str(chapter_path),
        normalized_path=str(chapter_path),
        stage_status="ready",
    )
    db_session.add(chapter)
    db_session.flush()

    segment = ChapterSegment(
        project_id=project.id,
        chapter_id=chapter.id,
        segment_index=1,
        source_text_path=str(segment_path),
        translation_status="translated",
        review_status="reviewed",
    )
    db_session.add(segment)
    db_session.flush()

    translation = SegmentTranslation(project_id=project.id, segment_id=segment.id)
    db_session.add(translation)
    db_session.flush()

    version = SegmentTranslationVersion(
        project_id=project.id,
        segment_translation_id=translation.id,
        version_index=1,
        source_hash="source-hash",
        glossary_snapshot_id="old-glossary",
        provider_name="pytest",
        model_profile_id="pytest-profile",
        model_name="pytest-model",
        source_text="亚修拿起术灵。",
        translated_text="Ash picked up the Spell Spirit.",
        translated_text_path=str(translated_path),
        status="completed",
    )
    db_session.add(version)
    db_session.flush()
    translation.active_version_id = version.id
    db_session.flush()

    return project, chapter, segment, version


def test_glossary_management_actions_are_registered() -> None:
    for action in [
        "glossary.entry.create",
        "glossary.entry.update",
        "glossary.entry.delete",
        "glossary.entry.lock",
        "glossary.entry.unlock",
        "glossary.candidate.create",
        "glossary.candidate.update",
        "glossary.candidate.approve",
        "glossary.candidate.reject",
        "glossary.candidate.delete",
        "glossary.candidate.promote",
        "glossary.denylist.add",
        "glossary.denylist.list",
        "glossary.denylist.delete",
    ]:
        assert action in action_router.ACTION_HANDLERS


def test_entry_management_creates_updates_locks_and_deletes_entries(
    db_session,
    project_workspace: Path,
) -> None:
    project, _, segment, version = _create_project_with_translated_segment(db_session, project_workspace)
    service = GlossaryManagementService(db_session)

    created = service.create_entry(
        project_id=project.id,
        source_term="术灵",
        target_term="Spell Spirit",
        category="power_system",
        note="世界观核心术语",
        locked=True,
    )

    assert created["source_term"] == "术灵"
    assert created["target_term"] == "Spell Spirit"
    assert created["locked"] == 1
    assert segment.translation_status == "stale"
    assert version.status == "stale"

    updated = service.update_entry(
        entry_id=int(created["id"]),
        source_term="术灵核心",
        target_term="Arcane Spirit",
        category="artifact",
        note="仲裁后译名",
        locked=False,
    )
    assert updated["source_term"] == "术灵核心"
    assert updated["target_term"] == "Arcane Spirit"
    assert updated["category"] == "artifact"
    assert updated["locked"] == 0

    locked = service.set_entry_lock(entry_id=int(created["id"]), locked=True)
    assert locked["locked"] == 1
    with pytest.raises(ToolError) as exc_info:
        service.delete_entry(entry_id=int(created["id"]))
    assert exc_info.value.code == "conflict_error"

    deleted = service.delete_entry(entry_id=int(created["id"]), force=True)
    assert deleted == {"id": created["id"], "project_id": project.id, "deleted": True}


def test_candidate_management_promotes_candidate_to_entry(
    db_session,
    project_workspace: Path,
) -> None:
    project, chapter, _, _ = _create_project_with_translated_segment(db_session, project_workspace)
    service = GlossaryManagementService(db_session)

    candidate = service.create_candidate(
        project_id=project.id,
        chapter_id=chapter.id,
        source_term="亚修",
        suggested_term="Yaxiu",
        category="character",
        gender="male",
        status="pending",
    )
    updated = service.update_candidate(
        candidate_id=int(candidate["id"]),
        suggested_term="Ash",
        note="主角名，采用英文名式转写",
    )
    approved = service.approve_candidate(candidate_id=int(candidate["id"]))
    promoted = service.promote_candidate(candidate_id=int(candidate["id"]), locked=True)

    assert updated["suggested_term"] == "Ash"
    assert approved["status"] == "approved"
    assert promoted["candidate"]["status"] == "promoted"
    assert promoted["entry"]["source_term"] == "亚修"
    assert promoted["entry"]["target_term"] == "Ash"
    assert promoted["entry"]["locked"] == 1

    rejected = service.reject_candidate(candidate_id=int(candidate["id"]))
    assert rejected["status"] == "rejected"
    deleted = service.delete_candidate(candidate_id=int(candidate["id"]))
    assert deleted == {"id": candidate["id"], "project_id": project.id, "deleted": True}


def test_glossary_denylist_service_adds_lists_filters_and_deletes_rules(
    db_session,
    project_workspace: Path,
) -> None:
    project, _, _, _ = _create_project_with_translated_segment(db_session, project_workspace)
    service = GlossaryDenylistService(db_session)

    rule = service.add_rule(
        project_id=project.id,
        source_term="第1章",
        match_type="exact",
        reason_code="chapter_title",
        note="章节标题不能进入术语表。",
    )

    assert rule["source_term"] == "第1章"
    assert rule["status"] == "active"
    assert service.list_rules(project_id=project.id)[0]["reason_code"] == "chapter_title"

    decision = service.filter_terms(
        project_id=project.id,
        terms=[
            {"source_term": "第1章", "suggested_term": "Chapter 1"},
            {"source_term": "术灵", "suggested_term": "Spell Spirit"},
        ],
    )
    assert [item["source_term"] for item in decision["accepted_terms"]] == ["术灵"]
    assert decision["rejected_terms"][0]["source_term"] == "第1章"
    assert decision["rejected_terms"][0]["rule"]["reason_code"] == "chapter_title"

    deleted = service.delete_rule(rule_id=int(rule["id"]))
    assert deleted == {"id": rule["id"], "project_id": project.id, "deleted": True}
