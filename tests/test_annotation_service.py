from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from tools.local_translation_workbench.app.db.models import (
    Annotation,
    AnnotationOccurrence,
    Chapter,
    ChapterSegment,
    ProjectSynopsis,
    SegmentTranslation,
    SegmentTranslationVersion,
    TranslationProject,
)
from tools.local_translation_workbench.app.providers.base import TextGenerationResult
from tools.local_translation_workbench.app.services.annotation_prompt_service import AnnotationPromptService
from tools.local_translation_workbench.app.services.annotation_service import AnnotationService


class StaticAnnotationProvider:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.prompts: list[str] = []

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        self.prompts.append(prompt)
        return TextGenerationResult(
            content=json.dumps(self.payload, ensure_ascii=False),
            provider_name="static_annotation_provider",
            model_name=model_name,
        )


def _create_project_with_active_translation(db_session, project_workspace: Path) -> tuple[TranslationProject, Chapter, ChapterSegment, SegmentTranslationVersion]:
    project_key = f"annotation-{uuid4().hex[:10]}"
    project_root = project_workspace / project_key
    chapter_dir = project_root / "chapters"
    translation_dir = project_root / "translation"
    chapter_dir.mkdir(parents=True, exist_ok=True)
    translation_dir.mkdir(parents=True, exist_ok=True)

    source_file = project_workspace / f"{project_key}.txt"
    source_file.write_text("第1章 小目标\n他说，先定一个小目标。", encoding="utf-8")
    segment_source_path = chapter_dir / "0001_0001_source.txt"
    segment_source_path.write_text("他说，先定一个小目标。", encoding="utf-8")
    translated_text_path = translation_dir / "0001_0001_v0001.txt"
    translated_text_path.write_text("He said, first set one small target.", encoding="utf-8")

    project = TranslationProject(
        request_id=f"pytest-annotation-{uuid4().hex[:10]}",
        project_key=project_key,
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
        status="translated",
    )
    db_session.add(project)
    db_session.flush()

    synopsis = ProjectSynopsis(
        project_id=project.id,
        source_synopsis_text="原文简介。",
        source_synopsis_status="ready",
        source_synopsis_origin="manual",
        target_synopsis_text="Target synopsis.",
        target_synopsis_status="ready",
        target_synopsis_origin="manual",
    )
    chapter = Chapter(
        project_id=project.id,
        chapter_index=1,
        chapter_title="第1章 小目标",
        source_path=str(segment_source_path),
        normalized_path=str(segment_source_path),
        stage_status="ready",
    )
    db_session.add_all([synopsis, chapter])
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
        translated_text="He said, first set one small target.",
        translated_text_path=str(translated_text_path),
        status="completed",
    )
    db_session.add(version)
    db_session.flush()
    translation.active_version_id = version.id
    db_session.flush()
    return project, chapter, segment, version


def test_annotation_prompt_service_parses_json_candidates() -> None:
    service = AnnotationPromptService()

    candidates = service.parse_extraction_response(
        json.dumps(
            {
                "annotations": [
                    {
                        "source_anchor": "一个小目标",
                        "target_anchor": "one hundred million",
                        "annotation_type": "idiom",
                        "explanation": "A Chinese internet meme referring to one hundred million yuan.",
                    }
                ]
            },
            ensure_ascii=False,
        )
    )

    assert candidates == [
        {
            "source_anchor": "一个小目标",
            "target_anchor": "one hundred million",
            "annotation_type": "idiom",
            "canonical_key": "idiom:一个小目标",
            "explanation": "A Chinese internet meme referring to one hundred million yuan.",
            "status": "candidate",
            "source": "llm_annotation",
            "evidence_payload": {},
        }
    ]


def test_annotation_schema_enforces_project_canonical_key_uniqueness(db_session, project_workspace: Path) -> None:
    project, _, _, _ = _create_project_with_active_translation(db_session, project_workspace)
    db_session.add(
        Annotation(
            project_id=project.id,
            source_anchor="一个小目标",
            target_anchor="one hundred million",
            annotation_type="idiom",
            canonical_key="idiom:一个小目标",
            explanation="A Chinese internet meme referring to one hundred million yuan.",
            status="candidate",
            locked=0,
            source="llm_annotation",
        )
    )
    db_session.flush()
    db_session.add(
        Annotation(
            project_id=project.id,
            source_anchor="一个小目标",
            target_anchor="one hundred million yuan",
            annotation_type="idiom",
            canonical_key="idiom:一个小目标",
            explanation="Conflicting explanation.",
            status="candidate",
            locked=0,
            source="llm_annotation",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_annotation_service_extract_reuses_existing_annotation_and_occurrence(db_session, project_workspace: Path) -> None:
    project, chapter, segment, version = _create_project_with_active_translation(db_session, project_workspace)
    provider = StaticAnnotationProvider(
        {
            "annotations": [
                {
                    "source_anchor": "一个小目标",
                    "target_anchor": "one small target",
                    "annotation_type": "idiom",
                    "explanation": "A Chinese expression often used as a wry reference to one hundred million yuan.",
                }
            ]
        }
    )
    service = AnnotationService(db_session, provider=provider)

    first = service.extract(
        request_id="pytest-annotation-extract",
        project_id=project.id,
        scope={"type": "all"},
        model_profile_id="annotation-profile",
        provider_model_name="annotation-model",
    )
    second = service.extract(
        request_id="pytest-annotation-extract-again",
        project_id=project.id,
        scope={"type": "all"},
        model_profile_id="annotation-profile",
        provider_model_name="annotation-model",
    )
    inspected = service.inspect(project_id=project.id)

    assert first["annotation_count"] == 1
    assert second["annotation_count"] == 1
    assert len(inspected["annotations"]) == 1
    assert inspected["annotations"][0]["canonical_key"] == "idiom:一个小目标"
    assert inspected["annotations"][0]["occurrences"] == [
        {
            "id": inspected["annotations"][0]["occurrences"][0]["id"],
            "chapter_id": chapter.id,
            "chapter_index": 1,
            "segment_id": segment.id,
            "segment_index": 1,
            "version_id": version.id,
            "source_anchor": "一个小目标",
            "target_anchor": "one small target",
            "source_start": 5,
            "source_end": 10,
            "target_start": 19,
            "target_end": 35,
            "display_order": 1,
        }
    ]


def test_annotation_service_keeps_locked_annotation_and_records_conflict_candidate(db_session, project_workspace: Path) -> None:
    project, _, _, _ = _create_project_with_active_translation(db_session, project_workspace)
    service = AnnotationService(db_session)
    locked = service.repository.create_annotation(
        project_id=project.id,
        source_anchor="一个小目标",
        target_anchor="one hundred million",
        annotation_type="idiom",
        canonical_key="idiom:一个小目标",
        explanation="A Chinese internet meme referring to one hundred million yuan.",
        status="approved",
        locked=1,
        source="manual",
        evidence_payload=None,
    )

    conflict = service.merge_candidate(
        project_id=project.id,
        candidate={
            "source_anchor": "一个小目标",
            "target_anchor": "one small target",
            "annotation_type": "idiom",
            "canonical_key": "idiom:一个小目标",
            "explanation": "A different explanation.",
            "status": "candidate",
            "source": "llm_annotation",
            "evidence_payload": {},
        },
    )

    assert locked.explanation == "A Chinese internet meme referring to one hundred million yuan."
    assert conflict.id != locked.id
    assert conflict.status == "candidate"
    assert conflict.conflict_with_annotation_id == locked.id
    assert conflict.canonical_key.startswith("idiom:一个小目标#conflict:")


def test_annotation_approve_changes_status_and_lock(db_session, project_workspace: Path) -> None:
    project, _, _, _ = _create_project_with_active_translation(db_session, project_workspace)
    service = AnnotationService(db_session)
    annotation = service.repository.create_annotation(
        project_id=project.id,
        source_anchor="一个小目标",
        target_anchor="one hundred million",
        annotation_type="idiom",
        canonical_key="idiom:一个小目标",
        explanation="A Chinese internet meme referring to one hundred million yuan.",
        status="candidate",
        locked=0,
        source="llm_annotation",
        evidence_payload=None,
    )

    result = service.approve(annotation_id=annotation.id, locked=True)

    assert result["status"] == "approved"
    assert result["locked"] == 1


def test_annotation_occurrence_schema_enforces_version_anchor_uniqueness(db_session, project_workspace: Path) -> None:
    project, chapter, segment, version = _create_project_with_active_translation(db_session, project_workspace)
    annotation = Annotation(
        project_id=project.id,
        source_anchor="一个小目标",
        target_anchor="one small target",
        annotation_type="idiom",
        canonical_key="idiom:一个小目标",
        explanation="A Chinese expression often used as a wry reference to one hundred million yuan.",
        status="approved",
        locked=0,
        source="manual",
    )
    db_session.add(annotation)
    db_session.flush()
    db_session.add(
        AnnotationOccurrence(
            annotation_id=annotation.id,
            project_id=project.id,
            chapter_id=chapter.id,
            segment_id=segment.id,
            version_id=version.id,
            source_anchor="一个小目标",
            target_anchor="one small target",
            display_order=1,
        )
    )
    db_session.flush()
    db_session.add(
        AnnotationOccurrence(
            annotation_id=annotation.id,
            project_id=project.id,
            chapter_id=chapter.id,
            segment_id=segment.id,
            version_id=version.id,
            source_anchor="一个小目标",
            target_anchor="one small target",
            display_order=2,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
