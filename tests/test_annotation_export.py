from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from tools.local_translation_workbench.app.db.models import (
    Chapter,
    ChapterSegment,
    ProjectSynopsis,
    SegmentTranslation,
    SegmentTranslationVersion,
    TranslationProject,
)
from tools.local_translation_workbench.app.services.annotation_service import AnnotationService
from tools.local_translation_workbench.app.services.export_service import ExportService


def _create_project_with_active_translation(db_session, project_workspace: Path) -> tuple[TranslationProject, Chapter, ChapterSegment, SegmentTranslationVersion]:
    project_key = f"annotation-export-{uuid4().hex[:10]}"
    project_root = project_workspace / project_key
    chapter_dir = project_root / "chapters"
    translation_dir = project_root / "translation"
    chapter_dir.mkdir(parents=True, exist_ok=True)
    translation_dir.mkdir(parents=True, exist_ok=True)

    source_file = project_workspace / f"{project_key}.txt"
    source_file.write_text("第1章 小目标\n他说，先定一个小目标。", encoding="utf-8")
    segment_source_path = chapter_dir / "0001_0001_source.txt"
    segment_source_path.write_text("他说，先定一个小目标。", encoding="utf-8")
    translated_text = "He said, first set one small target."
    translated_text_path = translation_dir / "0001_0001_v0001.txt"
    translated_text_path.write_text(translated_text, encoding="utf-8")

    project = TranslationProject(
        request_id=f"pytest-annotation-export-{uuid4().hex[:10]}",
        project_key=project_key,
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
        status="translated",
    )
    db_session.add(project)
    db_session.flush()

    db_session.add(
        ProjectSynopsis(
            project_id=project.id,
            source_synopsis_text="原文简介。",
            source_synopsis_status="ready",
            source_synopsis_origin="manual",
            target_synopsis_text="Target synopsis.",
            target_synopsis_status="ready",
            target_synopsis_origin="manual",
        )
    )
    chapter = Chapter(
        project_id=project.id,
        chapter_index=1,
        chapter_title="第1章 小目标",
        source_path=str(segment_source_path),
        normalized_path=str(segment_source_path),
        stage_status="ready",
    )
    db_session.add(chapter)
    db_session.flush()

    segment = ChapterSegment(
        project_id=project.id,
        chapter_id=chapter.id,
        segment_index=1,
        source_text_path=str(segment_source_path),
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
        glossary_snapshot_id="glossary-hash",
        provider_name="pytest",
        model_profile_id="pytest-profile",
        model_name="pytest-model",
        source_text="他说，先定一个小目标。",
        translated_text=translated_text,
        translated_text_path=str(translated_text_path),
        status="completed",
    )
    db_session.add(version)
    db_session.flush()
    translation.active_version_id = version.id
    db_session.flush()
    return project, chapter, segment, version


def test_export_includes_approved_annotations_without_changing_translation_text(db_session, project_workspace: Path, request_id_factory) -> None:
    project, chapter, segment, version = _create_project_with_active_translation(db_session, project_workspace)
    service = AnnotationService(db_session)
    annotation = service.repository.create_annotation(
        project_id=project.id,
        source_anchor="一个小目标",
        target_anchor="one small target",
        annotation_type="idiom",
        canonical_key="idiom:一个小目标",
        explanation="A Chinese expression often used as a wry reference to one hundred million yuan.",
        status="approved",
        locked=1,
        source="manual",
        evidence_payload=None,
    )
    service.repository.create_or_update_occurrence(
        annotation_id=annotation.id,
        project_id=project.id,
        chapter_id=chapter.id,
        segment_id=segment.id,
        version_id=version.id,
        source_anchor="一个小目标",
        target_anchor="one small target",
        source_start=5,
        source_end=10,
        target_start=19,
        target_end=35,
        display_order=1,
    )

    result = ExportService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("annotation-export"),
        project_id=project.id,
        scope={"type": "all"},
    )
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    export_text = Path(result.manifest_path).with_name("export.md").read_text(encoding="utf-8")

    assert manifest["annotations"][0]["canonical_key"] == "idiom:一个小目标"
    assert manifest["annotations"][0]["occurrences"][0]["chapter_index"] == 1
    assert "#### 注释" in export_text
    assert "[1] 一个小目标 / one small target：A Chinese expression often used as a wry reference to one hundred million yuan." in export_text
    assert "one small target[1]" not in export_text
    assert manifest["translations"][0]["translated_text"] == "He said, first set one small target."
