from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from tools.local_translation_workbench.app.cli import main
from tools.local_translation_workbench.app.db.models import Chapter, ChapterSegment
from tools.local_translation_workbench.app.repositories.projects import ProjectService
from tools.local_translation_workbench.app.services.chaptering_service import ChapteringService
from tools.local_translation_workbench.app.services.chapter_query_service import ChapterQueryService
from tools.local_translation_workbench.app.services.review_service import ReviewService
from tools.local_translation_workbench.tests.test_review_export import _prepare_project_with_current_translations


def _build_single_long_chapter_source() -> str:
    first_shard = "第一片正文" + ("甲" * 1294)
    second_shard = "第二片正文" + ("乙" * 1294)
    return f"第1章 长夜\n{first_shard}\n\n{second_shard}\n\n尾声。"


def _prepare_project_for_chapter_queries(
    *,
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> int:
    project_id = _prepare_project_with_current_translations(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    ReviewService(db_session).run(
        request_id=request_id_factory("chapter-query-review-first"),
        project_id=project_id,
        scope={"type": "chapter_list", "chapters": [1]},
    )

    second_segment = db_session.execute(
        select(ChapterSegment)
        .where(ChapterSegment.project_id == project_id)
        .order_by(ChapterSegment.id.asc())
    ).scalars().all()[1]
    second_segment.translation_status = "failed"
    second_segment.review_status = "pending"
    db_session.commit()
    return project_id


def test_chapter_query_service_inspect_chapter_by_id_returns_summary_and_segments(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_for_chapter_queries(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    first_chapter = db_session.execute(
        select(Chapter).where(Chapter.project_id == project_id, Chapter.chapter_index == 1)
    ).scalar_one()

    payload = ChapterQueryService(db_session).inspect_chapter(
        project_id=project_id,
        chapter_id=first_chapter.id,
    )

    chapter = payload["chapter"]
    assert chapter["chapter_id"] == first_chapter.id
    assert chapter["chapter_index"] == 1
    assert chapter["summary"]["segment_count"] == 1
    assert chapter["summary"]["translated_segment_count"] == 1
    assert chapter["summary"]["failed_segment_count"] == 0
    assert chapter["summary"]["reviewed_segment_count"] == 1
    assert chapter["summary"]["pending_review_segment_count"] == 0
    assert chapter["summary"]["active_version_segment_count"] == 1
    assert chapter["summary"]["is_translation_dirty"] is False
    assert chapter["summary"]["is_review_dirty"] is False
    assert len(chapter["segments"]) == 1
    assert chapter["segments"][0]["segment_index"] == 1
    assert chapter["segments"][0]["active_version_id"] is not None
    assert chapter["segments"][0]["current_version"]["translated_text"]


def test_chapter_query_service_inspect_chapter_reports_multiple_segments_for_single_chapter(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    source_file = project_workspace / "inspect-sharded-chapter.txt"
    source_file.write_text(_build_single_long_chapter_source(), encoding="utf-8")

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("inspect-sharded-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )
    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("inspect-sharded-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    payload = ChapterQueryService(db_session).inspect_chapter(
        project_id=project.id,
        chapter_index=1,
    )

    chapter = payload["chapter"]
    assert chapter["chapter_index"] == 1
    assert chapter["summary"]["segment_count"] == 2
    assert len(chapter["segments"]) == 2
    assert [item["segment_index"] for item in chapter["segments"]] == [1, 2]


def test_chapter_query_service_inspect_chapter_by_index_returns_failed_chapter_summary(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_for_chapter_queries(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    payload = ChapterQueryService(db_session).inspect_chapter(
        project_id=project_id,
        chapter_index=2,
    )

    chapter = payload["chapter"]
    assert chapter["chapter_index"] == 2
    assert chapter["summary"]["segment_count"] == 1
    assert chapter["summary"]["failed_segment_count"] == 1
    assert chapter["summary"]["translated_segment_count"] == 0
    assert chapter["summary"]["reviewed_segment_count"] == 0
    assert chapter["summary"]["pending_review_segment_count"] == 1
    assert chapter["summary"]["active_version_segment_count"] == 1
    assert chapter["summary"]["is_translation_dirty"] is True
    assert chapter["summary"]["is_review_dirty"] is True


def test_chapter_query_service_inspect_chapters_returns_summary_only_by_default(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_for_chapter_queries(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    payload = ChapterQueryService(db_session).inspect_chapters(
        project_id=project_id,
        scope={"type": "all"},
        include_segments=False,
    )

    assert payload["project_id"] == project_id
    assert payload["scope"] == {"type": "all"}
    assert payload["include_segments"] is False
    assert [item["chapter_index"] for item in payload["chapters"]] == [1, 2]
    assert "segments" not in payload["chapters"][0]
    assert payload["chapters"][1]["summary"]["failed_segment_count"] == 1


def test_chapter_query_service_inspect_chapters_supports_range_with_segment_details(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_for_chapter_queries(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    payload = ChapterQueryService(db_session).inspect_chapters(
        project_id=project_id,
        scope={"type": "chapter_range", "start": 2, "end": 2},
        include_segments=True,
    )

    assert payload["scope"] == {"type": "chapter_range", "start": 2, "end": 2}
    assert payload["include_segments"] is True
    assert len(payload["chapters"]) == 1
    assert payload["chapters"][0]["chapter_index"] == 2
    assert len(payload["chapters"][0]["segments"]) == 1
    assert payload["chapters"][0]["segments"][0]["current_version"]["status"] == "completed"


def test_inspect_chapter_cli_returns_single_chapter_detail(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    capsys,
) -> None:
    project_id = _prepare_project_for_chapter_queries(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    exit_code = main(
        [
            "-Action",
            "inspect.chapter",
            "-ProjectId",
            str(project_id),
            "-ChapterIndex",
            "1",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["action"] == "inspect.chapter"
    assert payload["data"]["chapter"]["chapter_index"] == 1
    assert payload["data"]["chapter"]["summary"]["segment_count"] == 1


def test_inspect_chapters_cli_supports_include_segments(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    capsys,
) -> None:
    project_id = _prepare_project_for_chapter_queries(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    exit_code = main(
        [
            "-Action",
            "inspect.chapters",
            "-ProjectId",
            str(project_id),
            "-ScopeType",
            "chapter_list",
            "-ScopeChapters",
            "2",
            "-IncludeSegments",
            "true",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["action"] == "inspect.chapters"
    assert payload["data"]["scope"]["type"] == "chapter_list"
    assert payload["data"]["scope"]["chapters"] == [2]
    assert payload["data"]["include_segments"] is True
    assert len(payload["data"]["chapters"][0]["segments"]) == 1


def test_inspect_chapter_cli_requires_exactly_one_locator(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    capsys,
) -> None:
    project_id = _prepare_project_for_chapter_queries(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    exit_code = main(["-Action", "inspect.chapter", "-ProjectId", str(project_id)])
    payload = json.loads(capsys.readouterr().err)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_arguments"
    assert "chapter_id" in payload["error"]["message"]


def test_inspect_chapter_cli_rejects_conflicting_locators(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    capsys,
) -> None:
    project_id = _prepare_project_for_chapter_queries(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    first_chapter = db_session.execute(
        select(Chapter).where(Chapter.project_id == project_id, Chapter.chapter_index == 1)
    ).scalar_one()

    exit_code = main(
        [
            "-Action",
            "inspect.chapter",
            "-ProjectId",
            str(project_id),
            "-ChapterId",
            str(first_chapter.id),
            "-ChapterIndex",
            "1",
        ]
    )
    payload = json.loads(capsys.readouterr().err)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_arguments"
    assert "chapter_index" in payload["error"]["message"]


@pytest.mark.parametrize("scope_type", ["stale_only", "failed_only", "missing_only"])
def test_inspect_chapters_cli_rejects_dynamic_scope_types(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    capsys,
    scope_type: str,
) -> None:
    project_id = _prepare_project_for_chapter_queries(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    exit_code = main(
        [
            "-Action",
            "inspect.chapters",
            "-ProjectId",
            str(project_id),
            "-ScopeType",
            scope_type,
        ]
    )
    payload = json.loads(capsys.readouterr().err)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_arguments"
    assert scope_type in payload["error"]["message"]
