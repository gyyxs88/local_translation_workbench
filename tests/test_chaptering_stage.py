from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy import select

from tools.local_translation_workbench.app.cli import main
from tools.local_translation_workbench.app.db.models import (
    Chapter,
    ChapterSegment,
    ProjectSynopsis,
    StageRun,
    TranslationProject,
)
from tools.local_translation_workbench.app.repositories.projects import ProjectService
from tools.local_translation_workbench.app.services.chaptering_service import ChapteringService


def _build_sharded_chapter_source() -> str:
    first_paragraph = "甲" * 1300
    second_paragraph = "乙" * 1300
    return f"第1章 很长的一章\n{first_paragraph}\n\n{second_paragraph}\n\n尾声。"


def test_chaptering_service_creates_chapters_segments_and_stage_run(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    source_file = project_workspace / "novel.txt"
    source_file.write_text("第0章 简介\n简介正文\n\n补充说明\n\n第1章 开始\n第一章正文", encoding="utf-8")

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("chaptering"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    service = ChapteringService(db_session, base_data_dir=project_workspace)
    result = service.run(
        request_id=request_id_factory("chaptering-run"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    assert result.chapter_count == 2
    assert result.segment_count == 2

    project_row = db_session.execute(
        select(TranslationProject).where(TranslationProject.id == project.id)
    ).scalar_one()
    project_root = project_workspace / project_row.project_key
    assert (project_root / "chapters" / "0001_source.txt").is_file()
    assert (project_root / "chapters" / "0001_normalized.txt").is_file()
    assert (project_root / "segments" / "0001_0001_source.txt").is_file()
    assert (project_root / "chapters" / "0001_source.txt").read_text(encoding="utf-8") == "第0章 简介\n简介正文\n\n补充说明"

    chapter_count = db_session.execute(
        select(Chapter).where(Chapter.project_id == project.id)
    ).scalars().all()
    segment_count = db_session.execute(
        select(ChapterSegment).where(ChapterSegment.project_id == project.id)
    ).scalars().all()
    stage_runs = db_session.execute(
        select(StageRun).where(StageRun.project_id == project.id, StageRun.stage == "chaptering")
    ).scalars().all()

    assert len(chapter_count) == 2
    assert len(segment_count) == 2
    assert len(stage_runs) == 1
    assert stage_runs[0].status == "completed"

    rerun_result = service.run(
        request_id=request_id_factory("chaptering-rerun"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    assert rerun_result.chapter_count == 2
    assert rerun_result.segment_count == 2

    rerun_chapters = db_session.execute(
        select(Chapter).where(Chapter.project_id == project.id)
    ).scalars().all()
    rerun_segments = db_session.execute(
        select(ChapterSegment).where(ChapterSegment.project_id == project.id)
    ).scalars().all()
    rerun_stage_runs = db_session.execute(
        select(StageRun).where(StageRun.project_id == project.id, StageRun.stage == "chaptering")
    ).scalars().all()

    assert len(rerun_chapters) == 2
    assert len(rerun_segments) == 2
    assert len(rerun_stage_runs) == 2


def test_chaptering_service_splits_long_chapter_into_multiple_segment_files(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    source_file = project_workspace / "chapter-sharding.txt"
    source_file.write_text(_build_sharded_chapter_source(), encoding="utf-8")

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("chaptering-sharded-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    result = ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("chaptering-sharded-run"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    project_row = db_session.execute(
        select(TranslationProject).where(TranslationProject.id == project.id)
    ).scalar_one()
    project_root = project_workspace / project_row.project_key
    segments = db_session.execute(
        select(ChapterSegment)
        .where(ChapterSegment.project_id == project.id)
        .order_by(ChapterSegment.segment_index.asc())
    ).scalars().all()

    assert result.chapter_count == 1
    assert result.segment_count == 2
    assert [segment.segment_index for segment in segments] == [1, 2]
    assert (project_root / "segments" / "0001_0001_source.txt").is_file()
    assert (project_root / "segments" / "0001_0002_source.txt").is_file()
    assert "第1章 很长的一章" not in (
        project_root / "segments" / "0001_0001_source.txt"
    ).read_text(encoding="utf-8")


def test_cli_project_create_and_stage_run_chaptering(
    project_workspace: Path,
    request_id_factory,
    capsys,
) -> None:
    source_file = project_workspace / "cli-novel.txt"
    source_file.write_text(
        "## 简介\n\n"
        "这是简介。\n\n"
        "## 正文\n\n"
        "### 1\n\n"
        "第一章正文\n\n"
        "### 2\n\n"
        "第二章正文",
        encoding="utf-8",
    )

    create_request_id = request_id_factory("cli-create")
    create_exit_code = main(
        [
            "-Action",
            "project.create",
            "-RequestId",
            create_request_id,
            "-SourcePath",
            str(source_file),
            "-SourceLanguage",
            "zh",
            "-TargetLanguage",
            "en",
        ]
    )
    create_payload = json.loads(capsys.readouterr().out)

    assert create_exit_code == 0
    assert create_payload["ok"] is True
    assert create_payload["action"] == "project.create"

    project_id = create_payload["data"]["id"]

    stage_exit_code = main(
        [
            "-Action",
            "stage.run",
            "-ProjectId",
            str(project_id),
            "-Stage",
            "chaptering",
            "-ScopeType",
            "all",
            "-RequestId",
            request_id_factory("cli-stage"),
        ]
    )
    stage_payload = json.loads(capsys.readouterr().out)

    assert stage_exit_code == 0
    assert stage_payload["ok"] is True
    assert stage_payload["action"] == "stage.run"
    assert stage_payload["data"]["stage"] == "chaptering"
    assert stage_payload["data"]["scope"]["type"] == "all"
    assert stage_payload["data"]["chapter_count"] == 2
    assert stage_payload["data"]["segment_count"] == 2
    assert stage_payload["data"]["synopsis"]["source"]["status"] == "ready"
    assert stage_payload["data"]["synopsis"]["source"]["origin"] == "extracted"
    assert stage_payload["data"]["synopsis"]["source"]["length"] == len("这是简介。")
    assert stage_payload["data"]["synopsis"]["target"]["status"] == "missing"
    assert stage_payload["data"]["synopsis"]["target"]["origin"] is None
    assert stage_payload["data"]["synopsis"]["target"]["length"] == 0


def test_cli_stage_run_chaptering_reports_multi_segment_count(
    project_workspace: Path,
    request_id_factory,
    capsys,
) -> None:
    source_file = project_workspace / "cli-sharded-chapter.txt"
    source_file.write_text(_build_sharded_chapter_source(), encoding="utf-8")

    create_exit_code = main(
        [
            "-Action",
            "project.create",
            "-RequestId",
            request_id_factory("chaptering-sharded-cli-create"),
            "-SourcePath",
            str(source_file),
            "-SourceLanguage",
            "zh",
            "-TargetLanguage",
            "en",
        ]
    )
    create_payload = json.loads(capsys.readouterr().out)

    assert create_exit_code == 0
    assert create_payload["ok"] is True

    stage_exit_code = main(
        [
            "-Action",
            "stage.run",
            "-ProjectId",
            str(create_payload["data"]["id"]),
            "-Stage",
            "chaptering",
            "-ScopeType",
            "all",
            "-RequestId",
            request_id_factory("chaptering-sharded-cli-stage"),
        ]
    )
    stage_payload = json.loads(capsys.readouterr().out)

    assert stage_exit_code == 0
    assert stage_payload["ok"] is True
    assert stage_payload["data"]["chapter_count"] == 1
    assert stage_payload["data"]["segment_count"] == 2


def test_cli_stage_run_chaptering_replay_keeps_synopsis_summary_stable(
    project_workspace: Path,
    request_id_factory,
    db_session,
    capsys,
) -> None:
    source_file = project_workspace / "replay-novel.md"
    source_file.write_text(
        "## 简介\n\n"
        "这是简介。\n\n"
        "## 正文\n\n"
        "### 1\n\n"
        "第一章正文。\n",
        encoding="utf-8",
    )

    create_request_id = request_id_factory("replay-create")
    create_exit_code = main(
        [
            "-Action",
            "project.create",
            "-RequestId",
            create_request_id,
            "-SourcePath",
            str(source_file),
            "-SourceLanguage",
            "zh",
            "-TargetLanguage",
            "en",
        ]
    )
    create_payload = json.loads(capsys.readouterr().out)

    assert create_exit_code == 0
    assert create_payload["ok"] is True

    project_id = create_payload["data"]["id"]
    stage_request_id = request_id_factory("replay-stage")
    first_exit_code = main(
        [
            "-Action",
            "stage.run",
            "-ProjectId",
            str(project_id),
            "-Stage",
            "chaptering",
            "-ScopeType",
            "all",
            "-RequestId",
            stage_request_id,
        ]
    )
    first_payload = json.loads(capsys.readouterr().out)

    assert first_exit_code == 0
    assert first_payload["ok"] is True

    synopsis_row = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project_id)
    ).scalar_one()
    synopsis_row.target_synopsis_text = "后续变更的目标简介"
    synopsis_row.target_synopsis_status = "completed"
    synopsis_row.target_synopsis_origin = "generated"
    db_session.commit()

    second_exit_code = main(
        [
            "-Action",
            "stage.run",
            "-ProjectId",
            str(project_id),
            "-Stage",
            "chaptering",
            "-ScopeType",
            "all",
            "-RequestId",
            stage_request_id,
        ]
    )
    second_payload = json.loads(capsys.readouterr().out)

    assert second_exit_code == 0
    assert second_payload["ok"] is True
    assert second_payload["data"]["synopsis"] == first_payload["data"]["synopsis"]


def test_chaptering_service_splits_markdown_numeric_headings(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    source_file = project_workspace / "markdown-novel.md"
    source_file.write_text(
        "# 地下室最后一张照片\n\n"
        "## 简介\n\n"
        "这是简介。\n\n"
        "## 正文\n\n"
        "### 1\n\n"
        "第一章正文。\n\n"
        "### 2\n\n"
        "第二章正文。\n",
        encoding="utf-8",
    )

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("markdown-chaptering"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    synopsis_row = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project.id)
    ).scalar_one()
    synopsis_row.target_synopsis_text = "旧摘要"
    synopsis_row.target_synopsis_status = "completed"
    synopsis_row.target_synopsis_origin = "generated"
    synopsis_row.target_synopsis_hash = "hash-target"
    synopsis_row.target_synopsis_model_profile_id = "profile-target"
    synopsis_row.target_synopsis_provider_name = "provider-target"
    synopsis_row.target_synopsis_model_name = "model-target"
    db_session.commit()

    service = ChapteringService(db_session, base_data_dir=project_workspace)
    result = service.run(
        request_id=request_id_factory("markdown-chaptering-run"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    assert result.chapter_count == 2
    assert result.segment_count == 2

    synopsis_row = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project.id)
    ).scalar_one()
    assert synopsis_row.source_synopsis_status == "ready"
    assert synopsis_row.source_synopsis_origin == "extracted"
    assert synopsis_row.source_synopsis_text == "这是简介。"
    assert synopsis_row.source_synopsis_hash == hashlib.sha256("这是简介。".encode("utf-8")).hexdigest()
    assert synopsis_row.target_synopsis_status == "stale"
    assert synopsis_row.target_synopsis_text == "旧摘要"

    chapters = db_session.execute(
        select(Chapter).where(Chapter.project_id == project.id).order_by(Chapter.chapter_index.asc())
    ).scalars().all()
    assert [chapter.chapter_title for chapter in chapters] == ["第1章", "第2章"]

    first_source = Path(chapters[0].source_path).read_text(encoding="utf-8")
    first_normalized = Path(chapters[0].normalized_path).read_text(encoding="utf-8")
    second_source = Path(chapters[1].source_path).read_text(encoding="utf-8")

    assert "# 地下室最后一张照片" in first_source
    assert "## 简介" not in first_source
    assert "这是简介。" not in first_source
    assert "## 简介" not in first_normalized
    assert "这是简介。" not in first_normalized
    assert "### 1" in first_source
    assert "第一章正文。" in first_source
    assert second_source.startswith("### 2")
    assert "第二章正文。" in second_source


def test_chaptering_extracts_inline_plain_text_synopsis_without_preface_chapter(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    source_file = project_workspace / "plain-inline-synopsis.txt"
    source_file.write_text(
        "魔女小姐的遗愿，怎么都是贴贴\n"
        "作者：余音廖廖\n"
        "分类：都市高武、都市、穿越\n"
        "主角：林溪、时羽\n"
        "简介：赵馨宁同学的腿又长又白，想和她贴贴；\n"
        "时羽同学的眼睛又大又水灵，还香香的，想和她贴贴；\n"
        "否则，24小时后，他就会死去。\n"
        "贴贴还是死亡？这是一个值得考虑的问题……\n"
        "\n"
        "第一卷\n"
        "\n"
        "第1章 贴贴魔女\n"
        "第一章正文。\n"
        "\n"
        "第2章 她想干嘛？！\n"
        "第二章正文。\n",
        encoding="utf-8",
    )

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("plain-inline-synopsis"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    result = ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("plain-inline-synopsis-run"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    assert result.chapter_count == 2
    assert result.segment_count == 2

    synopsis_row = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project.id)
    ).scalar_one()
    assert synopsis_row.source_synopsis_status == "ready"
    assert synopsis_row.source_synopsis_origin == "extracted"
    assert synopsis_row.source_synopsis_text == (
        "赵馨宁同学的腿又长又白，想和她贴贴；\n"
        "时羽同学的眼睛又大又水灵，还香香的，想和她贴贴；\n"
        "否则，24小时后，他就会死去。\n"
        "贴贴还是死亡？这是一个值得考虑的问题……"
    )

    chapters = db_session.execute(
        select(Chapter).where(Chapter.project_id == project.id).order_by(Chapter.chapter_index.asc())
    ).scalars().all()
    assert [chapter.chapter_title for chapter in chapters] == ["第1章 贴贴魔女", "第2章 她想干嘛？！"]

    first_source = Path(chapters[0].source_path).read_text(encoding="utf-8")
    assert first_source.startswith("第1章 贴贴魔女")
    assert "魔女小姐的遗愿" not in first_source
    assert "作者：" not in first_source
    assert "简介：" not in first_source
    assert "第一卷" not in first_source


def test_chaptering_clears_extracted_synopsis_when_source_no_longer_has_explicit_block(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    source_file = project_workspace / "markdown-novel-no-synopsis.md"
    source_file.write_text(
        "# 地下室最后一张照片\n\n"
        "## 正文\n\n"
        "### 1\n\n"
        "第一章正文。\n",
        encoding="utf-8",
    )

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("markdown-chaptering-no-synopsis"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    synopsis_row = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project.id)
    ).scalar_one()
    synopsis_row.source_synopsis_text = "旧简介"
    synopsis_row.source_synopsis_status = "ready"
    synopsis_row.source_synopsis_origin = "extracted"
    synopsis_row.source_synopsis_hash = "old-source-hash"
    synopsis_row.target_synopsis_text = "Old synopsis"
    synopsis_row.target_synopsis_status = "ready"
    synopsis_row.target_synopsis_origin = "manual"
    db_session.commit()

    service = ChapteringService(db_session, base_data_dir=project_workspace)
    result = service.run(
        request_id=request_id_factory("markdown-chaptering-no-synopsis-run"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    assert result.chapter_count == 1
    assert result.segment_count == 1

    refreshed_synopsis = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project.id)
    ).scalar_one()
    assert refreshed_synopsis.source_synopsis_text is None
    assert refreshed_synopsis.source_synopsis_status == "missing"
    assert refreshed_synopsis.source_synopsis_origin is None
    assert refreshed_synopsis.source_synopsis_hash is None
    assert refreshed_synopsis.target_synopsis_text == "Old synopsis"
    assert refreshed_synopsis.target_synopsis_status == "ready"
    assert refreshed_synopsis.target_synopsis_origin == "manual"


def test_chaptering_service_extracts_synopsis_at_file_end(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    source_file = project_workspace / "synopsis-eof.md"
    source_file.write_text(
        "## Summary\n\n"
        "This is a summary.\n",
        encoding="utf-8",
    )

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("synopsis-eof"),
        source_path=str(source_file),
        source_language="en",
        target_language="zh-CN",
    )

    service = ChapteringService(db_session, base_data_dir=project_workspace)
    result = service.run(
        request_id=request_id_factory("synopsis-eof-run"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    assert result.chapter_count == 0
    assert result.segment_count == 0

    synopsis_row = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project.id)
    ).scalar_one()
    assert synopsis_row.source_synopsis_status == "ready"
    assert synopsis_row.source_synopsis_origin == "extracted"
    assert synopsis_row.source_synopsis_text == "This is a summary."

    chapters = db_session.execute(select(Chapter).where(Chapter.project_id == project.id)).scalars().all()
    assert chapters == []


def test_chaptering_rerun_keeps_target_synopsis_ready_when_explicit_source_is_unchanged(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    source_file = project_workspace / "synopsis-unchanged.md"
    source_file.write_text(
        "## 简介\n\n"
        "这是简介。\n\n"
        "## 正文\n\n"
        "### 1\n\n"
        "第一章正文。\n",
        encoding="utf-8",
    )

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("synopsis-unchanged"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    service = ChapteringService(db_session, base_data_dir=project_workspace)
    first_result = service.run(
        request_id=request_id_factory("synopsis-unchanged-run-1"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    assert first_result.chapter_count == 1
    assert first_result.segment_count == 1

    synopsis_row = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project.id)
    ).scalar_one()
    synopsis_row.target_synopsis_text = "已存在的目标简介"
    synopsis_row.target_synopsis_status = "ready"
    synopsis_row.target_synopsis_origin = "generated"
    synopsis_row.target_synopsis_hash = "target-hash"
    synopsis_row.target_synopsis_model_profile_id = "target-profile"
    synopsis_row.target_synopsis_provider_name = "target-provider"
    synopsis_row.target_synopsis_model_name = "target-model"
    db_session.commit()

    rerun_result = service.run(
        request_id=request_id_factory("synopsis-unchanged-run-2"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    assert rerun_result.chapter_count == 1
    assert rerun_result.segment_count == 1

    refreshed_synopsis = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project.id)
    ).scalar_one()
    assert refreshed_synopsis.source_synopsis_status == "ready"
    assert refreshed_synopsis.source_synopsis_origin == "extracted"
    assert refreshed_synopsis.source_synopsis_text == "这是简介。"
    assert refreshed_synopsis.target_synopsis_text == "已存在的目标简介"
    assert refreshed_synopsis.target_synopsis_status == "ready"
    assert refreshed_synopsis.target_synopsis_origin == "generated"
    assert refreshed_synopsis.target_synopsis_hash == "target-hash"
    assert refreshed_synopsis.target_synopsis_model_profile_id == "target-profile"
    assert refreshed_synopsis.target_synopsis_provider_name == "target-provider"
    assert refreshed_synopsis.target_synopsis_model_name == "target-model"


def test_chaptering_without_explicit_synopsis_preserves_generated_or_manual_target_synopsis(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    source_file = project_workspace / "no-explicit-synopsis.md"
    source_file.write_text(
        "# 地下室最后一张照片\n\n"
        "## 正文\n\n"
        "### 1\n\n"
        "第一章正文。\n",
        encoding="utf-8",
    )

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("no-explicit-synopsis"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    synopsis_row = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project.id)
    ).scalar_one()
    synopsis_row.source_synopsis_text = "旧简介"
    synopsis_row.source_synopsis_status = "ready"
    synopsis_row.source_synopsis_origin = "extracted"
    synopsis_row.source_synopsis_hash = "old-source-hash"
    synopsis_row.target_synopsis_text = "保留的目标简介"
    synopsis_row.target_synopsis_status = "ready"
    synopsis_row.target_synopsis_origin = "manual"
    synopsis_row.target_synopsis_hash = "target-hash"
    synopsis_row.target_synopsis_model_profile_id = "target-profile"
    synopsis_row.target_synopsis_provider_name = "target-provider"
    synopsis_row.target_synopsis_model_name = "target-model"
    db_session.commit()

    service = ChapteringService(db_session, base_data_dir=project_workspace)
    result = service.run(
        request_id=request_id_factory("no-explicit-synopsis-run"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    assert result.chapter_count == 1
    assert result.segment_count == 1

    refreshed_synopsis = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project.id)
    ).scalar_one()
    assert refreshed_synopsis.source_synopsis_text is None
    assert refreshed_synopsis.source_synopsis_status == "missing"
    assert refreshed_synopsis.source_synopsis_origin is None
    assert refreshed_synopsis.source_synopsis_hash is None
    assert refreshed_synopsis.target_synopsis_text == "保留的目标简介"
    assert refreshed_synopsis.target_synopsis_status == "ready"
    assert refreshed_synopsis.target_synopsis_origin == "manual"
    assert refreshed_synopsis.target_synopsis_hash == "target-hash"
    assert refreshed_synopsis.target_synopsis_model_profile_id == "target-profile"
    assert refreshed_synopsis.target_synopsis_provider_name == "target-provider"
    assert refreshed_synopsis.target_synopsis_model_name == "target-model"


def test_chaptering_without_explicit_synopsis_marks_generated_source_synopsis_stale(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    source_file = project_workspace / "generated-source-synopsis.md"
    source_file.write_text(
        "# 地下室最后一张照片\n\n"
        "## 正文\n\n"
        "### 1\n\n"
        "第一章正文。\n",
        encoding="utf-8",
    )

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("generated-source-synopsis"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    synopsis_row = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project.id)
    ).scalar_one()
    synopsis_row.source_synopsis_text = "旧的 source synopsis"
    synopsis_row.source_synopsis_status = "ready"
    synopsis_row.source_synopsis_origin = "generated"
    synopsis_row.source_synopsis_hash = "old-source-hash"
    synopsis_row.source_synopsis_model_profile_id = "source-profile"
    synopsis_row.source_synopsis_provider_name = "source-provider"
    synopsis_row.source_synopsis_model_name = "source-model"
    db_session.commit()

    service = ChapteringService(db_session, base_data_dir=project_workspace)
    result = service.run(
        request_id=request_id_factory("generated-source-synopsis-run"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    assert result.chapter_count == 1
    assert result.segment_count == 1

    refreshed_synopsis = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project.id)
    ).scalar_one()
    assert refreshed_synopsis.source_synopsis_text == "旧的 source synopsis"
    assert refreshed_synopsis.source_synopsis_status == "stale"
    assert refreshed_synopsis.source_synopsis_origin == "generated"
    assert refreshed_synopsis.source_synopsis_hash == "old-source-hash"
    assert refreshed_synopsis.source_synopsis_model_profile_id == "source-profile"
    assert refreshed_synopsis.source_synopsis_provider_name == "source-provider"
    assert refreshed_synopsis.source_synopsis_model_name == "source-model"


def test_chaptering_without_explicit_synopsis_marks_generated_source_and_target_synopsis_stale(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    source_file = project_workspace / "generated-source-target-synopsis.md"
    source_file.write_text(
        "# 地下室最后一张照片\n\n"
        "## 正文\n\n"
        "### 1\n\n"
        "第一章正文。\n",
        encoding="utf-8",
    )

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("generated-source-target-synopsis"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    synopsis_row = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project.id)
    ).scalar_one()
    synopsis_row.source_synopsis_text = "旧的 source synopsis"
    synopsis_row.source_synopsis_status = "ready"
    synopsis_row.source_synopsis_origin = "generated"
    synopsis_row.source_synopsis_hash = "old-source-hash"
    synopsis_row.source_synopsis_model_profile_id = "source-profile"
    synopsis_row.source_synopsis_provider_name = "source-provider"
    synopsis_row.source_synopsis_model_name = "source-model"
    synopsis_row.target_synopsis_text = "旧的 target synopsis"
    synopsis_row.target_synopsis_status = "ready"
    synopsis_row.target_synopsis_origin = "translated"
    synopsis_row.target_synopsis_hash = "old-target-hash"
    synopsis_row.target_synopsis_model_profile_id = "target-profile"
    synopsis_row.target_synopsis_provider_name = "target-provider"
    synopsis_row.target_synopsis_model_name = "target-model"
    db_session.commit()

    service = ChapteringService(db_session, base_data_dir=project_workspace)
    result = service.run(
        request_id=request_id_factory("generated-source-target-synopsis-run"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    assert result.chapter_count == 1
    assert result.segment_count == 1

    refreshed_synopsis = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project.id)
    ).scalar_one()
    assert refreshed_synopsis.source_synopsis_text == "旧的 source synopsis"
    assert refreshed_synopsis.source_synopsis_status == "stale"
    assert refreshed_synopsis.source_synopsis_origin == "generated"
    assert refreshed_synopsis.source_synopsis_hash == "old-source-hash"
    assert refreshed_synopsis.source_synopsis_model_profile_id == "source-profile"
    assert refreshed_synopsis.source_synopsis_provider_name == "source-provider"
    assert refreshed_synopsis.source_synopsis_model_name == "source-model"
    assert refreshed_synopsis.target_synopsis_text == "旧的 target synopsis"
    assert refreshed_synopsis.target_synopsis_status == "stale"
    assert refreshed_synopsis.target_synopsis_origin == "translated"
    assert refreshed_synopsis.target_synopsis_hash == "old-target-hash"
    assert refreshed_synopsis.target_synopsis_model_profile_id == "target-profile"
    assert refreshed_synopsis.target_synopsis_provider_name == "target-provider"
    assert refreshed_synopsis.target_synopsis_model_name == "target-model"


def test_chaptering_rerun_keeps_manual_target_ready_when_explicit_synopsis_changes(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    source_file = project_workspace / "explicit-synopsis-manual-target.md"
    source_file.write_text(
        "## 简介\n\n"
        "第一版简介。\n\n"
        "## 正文\n\n"
        "### 1\n\n"
        "第一章正文。\n",
        encoding="utf-8",
    )

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("explicit-manual-target"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    service = ChapteringService(db_session, base_data_dir=project_workspace)
    first_result = service.run(
        request_id=request_id_factory("explicit-manual-target-run-1"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    assert first_result.chapter_count == 1
    assert first_result.segment_count == 1

    synopsis_row = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project.id)
    ).scalar_one()
    synopsis_row.target_synopsis_text = "手动目标简介"
    synopsis_row.target_synopsis_status = "ready"
    synopsis_row.target_synopsis_origin = "manual"
    synopsis_row.target_synopsis_hash = "manual-target-hash"
    synopsis_row.target_synopsis_model_profile_id = "manual-profile"
    synopsis_row.target_synopsis_provider_name = "manual-provider"
    synopsis_row.target_synopsis_model_name = "manual-model"
    db_session.commit()

    source_file.write_text(
        "## 简介\n\n"
        "第二版简介。\n\n"
        "## 正文\n\n"
        "### 1\n\n"
        "第一章正文。\n",
        encoding="utf-8",
    )

    second_result = service.run(
        request_id=request_id_factory("explicit-manual-target-run-2"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    assert second_result.chapter_count == 1
    assert second_result.segment_count == 1

    refreshed_synopsis = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project.id)
    ).scalar_one()
    assert refreshed_synopsis.source_synopsis_text == "第二版简介。"
    assert refreshed_synopsis.source_synopsis_status == "ready"
    assert refreshed_synopsis.source_synopsis_origin == "extracted"
    assert refreshed_synopsis.target_synopsis_text == "手动目标简介"
    assert refreshed_synopsis.target_synopsis_status == "ready"
    assert refreshed_synopsis.target_synopsis_origin == "manual"
    assert refreshed_synopsis.target_synopsis_hash == "manual-target-hash"
    assert refreshed_synopsis.target_synopsis_model_profile_id == "manual-profile"
    assert refreshed_synopsis.target_synopsis_provider_name == "manual-provider"
    assert refreshed_synopsis.target_synopsis_model_name == "manual-model"
