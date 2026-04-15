from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from tools.local_translation_workbench.app.cli import main
from tools.local_translation_workbench.app.db.models import ChapterSegment, SegmentTranslation
from tools.local_translation_workbench.app.errors import ToolError
from tools.local_translation_workbench.app.services.chapter_query_service import ChapterQueryService
from tools.local_translation_workbench.tests.test_chapter_queries import _prepare_project_for_chapter_queries


def _prepare_project_for_segment_queries(
    *,
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> int:
    project_id = _prepare_project_for_chapter_queries(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    first_segment = db_session.execute(
        select(ChapterSegment)
        .where(ChapterSegment.project_id == project_id)
        .order_by(ChapterSegment.id.asc())
    ).scalars().all()[0]
    translation = db_session.execute(
        select(SegmentTranslation).where(
            SegmentTranslation.project_id == project_id,
            SegmentTranslation.segment_id == first_segment.id,
        )
    ).scalar_one()
    translation.active_version_id = None
    first_segment.translation_status = "pending"
    db_session.commit()
    return project_id


def test_chapter_query_service_inspect_segment_by_segment_id_returns_null_translation_when_no_active_version(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_for_segment_queries(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    first_segment = db_session.execute(
        select(ChapterSegment)
        .where(ChapterSegment.project_id == project_id)
        .order_by(ChapterSegment.id.asc())
    ).scalars().all()[0]

    payload = ChapterQueryService(db_session).inspect_segment(
        project_id=project_id,
        segment_id=first_segment.id,
    )

    segment = payload["segment"]
    assert segment["segment_id"] == first_segment.id
    assert segment["chapter_index"] == 1
    assert segment["segment_index"] == 1
    assert segment["source_text"]
    assert segment["translated_text"] is None
    assert segment["current_version"] is None
    assert segment["active_version_id"] is None


def test_chapter_query_service_inspect_segment_by_chapter_and_segment_index_returns_active_translation(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_for_segment_queries(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    payload = ChapterQueryService(db_session).inspect_segment(
        project_id=project_id,
        chapter_index=2,
        segment_index=1,
    )

    segment = payload["segment"]
    assert segment["chapter_index"] == 2
    assert segment["segment_index"] == 1
    assert segment["translation_status"] == "failed"
    assert segment["review_status"] == "pending"
    assert segment["translated_text"]
    assert segment["current_version"]["model_profile_id"]
    assert segment["current_version"]["translated_text_path"]


def test_chapter_query_service_inspect_segment_rejects_partial_chapter_locator(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_for_segment_queries(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    with pytest.raises(ToolError) as exc:
        ChapterQueryService(db_session).inspect_segment(
            project_id=project_id,
            chapter_index=1,
        )

    assert exc.value.code == "invalid_arguments"
    assert "segment_index" in exc.value.message


def test_inspect_segment_cli_returns_single_segment_detail(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    capsys,
) -> None:
    project_id = _prepare_project_for_segment_queries(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    exit_code = main(
        [
            "-Action",
            "inspect.segment",
            "-ProjectId",
            str(project_id),
            "-ChapterIndex",
            "2",
            "-SegmentIndex",
            "1",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["action"] == "inspect.segment"
    assert payload["data"]["segment"]["chapter_index"] == 2
    assert payload["data"]["segment"]["segment_index"] == 1


def test_inspect_segment_cli_requires_locator(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    capsys,
) -> None:
    project_id = _prepare_project_for_segment_queries(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    exit_code = main(["-Action", "inspect.segment", "-ProjectId", str(project_id)])
    payload = json.loads(capsys.readouterr().err)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_arguments"
    assert "segment_id" in payload["error"]["message"]


def test_inspect_segment_cli_rejects_conflicting_locators(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    capsys,
) -> None:
    project_id = _prepare_project_for_segment_queries(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    second_segment = db_session.execute(
        select(ChapterSegment)
        .where(ChapterSegment.project_id == project_id)
        .order_by(ChapterSegment.id.asc())
    ).scalars().all()[1]

    exit_code = main(
        [
            "-Action",
            "inspect.segment",
            "-ProjectId",
            str(project_id),
            "-SegmentId",
            str(second_segment.id),
            "-ChapterIndex",
            "2",
            "-SegmentIndex",
            "1",
        ]
    )
    payload = json.loads(capsys.readouterr().err)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_arguments"
    assert "segment_id" in payload["error"]["message"]


def test_inspect_segment_cli_rejects_partial_chapter_locator(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    capsys,
) -> None:
    project_id = _prepare_project_for_segment_queries(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    exit_code = main(
        [
            "-Action",
            "inspect.segment",
            "-ProjectId",
            str(project_id),
            "-ChapterIndex",
            "1",
        ]
    )
    payload = json.loads(capsys.readouterr().err)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_arguments"
    assert "segment_index" in payload["error"]["message"]
