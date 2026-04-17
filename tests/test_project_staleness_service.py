from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from tools.local_translation_workbench.app.db.models import (
    Chapter,
    ChapterSegment,
    ExportRun,
    ProjectSynopsis,
    ReviewRun,
    SegmentTranslation,
    SegmentTranslationVersion,
    StageRun,
)
from tools.local_translation_workbench.app.providers.base import TextGenerationResult
from tools.local_translation_workbench.app.repositories.projects import ProjectService
from tools.local_translation_workbench.app.services.chaptering_service import ChapteringService
from tools.local_translation_workbench.app.services.glossary_service import GlossaryService
from tools.local_translation_workbench.app.services.project_staleness_service import (
    ProjectStalenessService,
)
from tools.local_translation_workbench.app.services.stage_service import StageCommand, StageService
from tools.local_translation_workbench.app.services.translation_service import TranslationService


class MixedProvider:
    def __init__(self) -> None:
        self.call_count = 0

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        self.call_count += 1
        source_text = prompt.split("\n\n", maxsplit=1)[-1]
        if self.call_count == 1:
            content = "源简介内容"
        elif self.call_count == 2:
            content = "目标简介内容"
        elif self.call_count == 3:
            content = source_text
        else:
            content = f"[{model_name}] {source_text}"
        return TextGenerationResult(
            content=content,
            provider_name="mixed_provider",
            model_name=model_name,
        )


class FakeGlossaryProvider:
    TERM_MAP = {
        "程风": {
            "translated_term": "Cheng Feng",
            "category": "character",
            "note": "Character name",
        },
        "青石镇": {
            "translated_term": "Qingshi Town",
            "category": "location",
            "note": "Town name",
        },
    }

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        terms = []
        for source_term, metadata in self.TERM_MAP.items():
            if source_term in str(prompt):
                terms.append(
                    {
                        "source_term": source_term,
                        "translated_term": metadata["translated_term"],
                        "category": metadata["category"],
                        "note": metadata["note"],
                    }
                )
        return TextGenerationResult(
            content=json.dumps({"terms": terms}, ensure_ascii=False),
            provider_name="fake_glossary_provider",
            model_name=model_name,
        )


def _prepare_project_with_review_and_export(
    *,
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> int:
    source_file = project_workspace / "project-staleness-source.txt"
    source_file.write_text(
        "第1章 相遇\n程风走进青石镇。\n\n第2章 旧事\n程风想起青石镇的传闻。",
        encoding="utf-8",
    )

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("project-staleness-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("project-staleness-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    GlossaryService(db_session, provider=FakeGlossaryProvider()).run(
        request_id=request_id_factory("project-staleness-glossary"),
        project_id=project.id,
        scope={"type": "all"},
        model_profile_id="profile-project-staleness-glossary",
    )

    TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=MixedProvider(),
    ).run(
        request_id=request_id_factory("project-staleness-translation"),
        project_id=project.id,
        scope={"type": "all"},
        model_profile_id="profile-project-staleness-translation",
    )

    stage_service = StageService(db_session, base_data_dir=project_workspace)
    stage_service.run(
        StageCommand(
            request_id=request_id_factory("project-staleness-review"),
            project_id=project.id,
            stage="review",
            scope={"type": "all"},
        )
    )
    stage_service.run(
        StageCommand(
            request_id=request_id_factory("project-staleness-export"),
            project_id=project.id,
            stage="export",
            scope={"type": "all"},
        )
    )
    return project.id


def test_project_staleness_service_marks_translation_downstream_runs_stale(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_review_and_export(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    service = ProjectStalenessService(db_session)
    service.mark_translation_downstream_stale(
        project_id=project_id,
        affected_chapter_indexes=[1],
    )
    db_session.commit()

    review_run = db_session.execute(
        select(ReviewRun).where(ReviewRun.project_id == project_id)
    ).scalar_one()
    export_run = db_session.execute(
        select(ExportRun).where(ExportRun.project_id == project_id)
    ).scalar_one()
    downstream_stage_runs = db_session.execute(
        select(StageRun)
        .where(StageRun.project_id == project_id, StageRun.stage.in_(["review", "export"]))
        .order_by(StageRun.stage.asc())
    ).scalars().all()

    assert review_run.status == "stale"
    assert export_run.status == "stale"
    assert [(run.stage, run.status) for run in downstream_stage_runs] == [
        ("export", "stale"),
        ("review", "stale"),
    ]


def test_project_staleness_service_marks_glossary_changes_as_segment_stale(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_review_and_export(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    chapters = db_session.execute(
        select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.chapter_index.asc())
    ).scalars().all()

    service = ProjectStalenessService(db_session)
    service.mark_glossary_downstream_stale(
        project_id=project_id,
        chapters=chapters,
    )
    db_session.commit()

    segment_rows = db_session.execute(
        select(ChapterSegment.segment_index, ChapterSegment.translation_status, ChapterSegment.review_status)
        .where(ChapterSegment.project_id == project_id)
        .order_by(ChapterSegment.id.asc())
    ).all()
    active_versions = db_session.execute(
        select(SegmentTranslationVersion)
        .join(SegmentTranslation, SegmentTranslation.active_version_id == SegmentTranslationVersion.id)
        .where(SegmentTranslation.project_id == project_id)
        .order_by(SegmentTranslationVersion.id.asc())
    ).scalars().all()
    stage_runs = db_session.execute(
        select(StageRun)
        .where(StageRun.project_id == project_id, StageRun.stage.in_(["translation", "review", "export"]))
        .order_by(StageRun.stage.asc())
    ).scalars().all()
    review_run = db_session.execute(
        select(ReviewRun).where(ReviewRun.project_id == project_id)
    ).scalar_one()
    export_run = db_session.execute(
        select(ExportRun).where(ExportRun.project_id == project_id)
    ).scalar_one()

    assert segment_rows == [
        (1, "stale", "pending"),
        (1, "stale", "pending"),
    ]
    assert all(version.status == "stale" for version in active_versions)
    assert [(run.stage, run.status) for run in stage_runs] == [
        ("export", "stale"),
        ("review", "stale"),
        ("translation", "stale"),
    ]
    assert review_run.status == "stale"
    assert export_run.status == "stale"
