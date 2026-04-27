from __future__ import annotations

import json

from sqlalchemy import inspect, select

from tools.local_translation_workbench.app.db.models import (
    Chapter,
    ChapterSegment,
    ReviewIssue,
    SegmentTranslation,
    SegmentTranslationVersion,
    TranslationProject,
)
from tools.local_translation_workbench.app.repositories.review import ReviewRepository


def _create_review_issue_context(db_session):
    project = TranslationProject(
        request_id="review-loop-schema-project",
        project_key="review_loop_schema_project",
        source_path="source.txt",
        source_language="zh",
        target_language="en",
        status="created",
    )
    db_session.add(project)
    db_session.flush()

    chapter = Chapter(
        project_id=project.id,
        chapter_index=1,
        chapter_title="开始",
        source_path="chapter.txt",
        normalized_path="chapter.normalized.txt",
        stage_status="ready",
    )
    db_session.add(chapter)
    db_session.flush()

    segment = ChapterSegment(
        project_id=project.id,
        chapter_id=chapter.id,
        segment_index=1,
        source_text_path="segment.txt",
        translation_status="translated",
        review_status="pending",
    )
    db_session.add(segment)
    db_session.flush()

    translation = SegmentTranslation(
        project_id=project.id,
        segment_id=segment.id,
        active_version_id=None,
    )
    db_session.add(translation)
    db_session.flush()

    version = SegmentTranslationVersion(
        project_id=project.id,
        segment_translation_id=translation.id,
        version_index=1,
        source_hash="a" * 64,
        glossary_snapshot_id="b" * 64,
        provider_name="fake_provider",
        model_profile_id="profile-review-loop",
        model_name="review-model",
        source_text="她推开门。",
        translated_text="She closed the door.",
        translated_text_path="v0001.txt",
        status="completed",
    )
    db_session.add(version)
    db_session.flush()
    translation.active_version_id = version.id
    db_session.flush()
    return project, chapter, segment, version


def test_review_issue_schema_and_repository_store_segment_loop_payload(db_session) -> None:
    columns = {column["name"] for column in inspect(db_session.bind).get_columns("ltw_review_issues")}

    assert {
        "segment_id",
        "version_id",
        "issue_source",
        "round_index",
        "requires_rewrite",
        "structured_payload",
    } <= columns

    project, chapter, segment, version = _create_review_issue_context(db_session)
    repository = ReviewRepository(db_session)
    review_run = repository.create_run(
        project_id=project.id,
        scope_type="all",
        scope_value=json.dumps({"type": "all"}),
        status="completed",
        summary=json.dumps({"request_id": "schema-test"}),
    )
    issue = repository.create_issue(
        project_id=project.id,
        review_run_id=review_run.id,
        chapter_id=chapter.id,
        segment_id=segment.id,
        version_id=version.id,
        issue_type="mistranslation",
        severity="high",
        message="译文误解了动作。",
        status="open",
        issue_source="llm",
        round_index=1,
        requires_rewrite=True,
        structured_payload={"rewrite_instruction": "修正动作含义。"},
    )
    db_session.commit()

    stored = db_session.execute(select(ReviewIssue).where(ReviewIssue.id == issue.id)).scalar_one()
    assert stored.segment_id == segment.id
    assert stored.version_id == version.id
    assert stored.issue_source == "llm"
    assert stored.round_index == 1
    assert stored.requires_rewrite is True
    assert stored.structured_payload == {"rewrite_instruction": "修正动作含义。"}
