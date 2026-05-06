from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from tools.local_translation_workbench.app.cli import main
from tools.local_translation_workbench.app.db.models import (
    Chapter,
    ChapterSegment,
    ExportArtifact,
    ExportRun,
    GlossaryEntry,
    ProjectSynopsis,
    ReviewIssue,
    ReviewRun,
    SegmentTranslation,
    SegmentTranslationVersion,
)
from tools.local_translation_workbench.app.errors import ToolError
from tools.local_translation_workbench.app.providers.base import TextGenerationResult
from tools.local_translation_workbench.app.repositories.projects import ProjectService
from tools.local_translation_workbench.app.repositories.synopsis import ProjectSynopsisRepository
from tools.local_translation_workbench.app.services.chaptering_service import ChapteringService
from tools.local_translation_workbench.app.services.export_service import ExportService
from tools.local_translation_workbench.app.services.glossary_service import GlossaryService
from tools.local_translation_workbench.app.services.review_service import ReviewService
from tools.local_translation_workbench.app.services.translation_service import TranslationService


class MixedProvider:
    def __init__(self) -> None:
        self.call_count = 0

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        self.call_count += 1
        source_text = prompt.rsplit("\n\n", maxsplit=1)[-1]
        if "生成 source synopsis" in prompt:
            content = "源简介内容"
        elif "翻译 target synopsis" in prompt:
            content = "目标简介内容"
        elif "章节: 1" in prompt and "分片: 1" in prompt:
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
        payload = {
            "extraction_status": "terms_found" if terms else "no_new_terms",
            "terms": terms,
            "reason": "fake glossary extraction",
        }
        return TextGenerationResult(
            content=json.dumps(payload, ensure_ascii=False),
            provider_name="fake_glossary_provider",
            model_name=model_name,
        )


class StaticTranslationProvider:
    def __init__(self, *, translated_text: str) -> None:
        self.translated_text = translated_text

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        return TextGenerationResult(
            content=self.translated_text,
            provider_name="static_translation_provider",
            model_name=model_name,
        )


def _build_single_long_chapter_source() -> str:
    first_shard = "第一片正文" + ("甲" * 1294)
    second_shard = "第二片正文" + ("乙" * 1294)
    return f"第1章 长夜\n{first_shard}\n\n{second_shard}\n\n尾声。"


def _prepare_project_with_current_translations(
    *,
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> int:
    source_file = project_workspace / "review-export-source.txt"
    source_file.write_text(
        "第1章 相遇\n程风走进青石镇。\n\n第2章 旧事\n程风想起青石镇的传闻。",
        encoding="utf-8",
    )

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("review-export-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("review-export-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    GlossaryService(db_session, provider=FakeGlossaryProvider()).run(
        request_id=request_id_factory("review-export-glossary"),
        project_id=project.id,
        scope={"type": "all"},
        model_profile_id="profile-review-export-glossary",
    )

    TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=MixedProvider(),
    ).run(
        request_id=request_id_factory("review-export-translation"),
        project_id=project.id,
        scope={"type": "all"},
        model_profile_id="profile-review-export",
    )
    return project.id


def _prepare_project_with_sharded_translations(
    *,
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> int:
    source_file = project_workspace / "review-export-sharded-source.txt"
    source_file.write_text(_build_single_long_chapter_source(), encoding="utf-8")

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("review-export-sharded-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("review-export-sharded-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=MixedProvider(),
    ).run(
        request_id=request_id_factory("review-export-sharded-translation"),
        project_id=project.id,
        scope={"type": "all"},
        model_profile_id="profile-review-export-sharded",
    )
    return project.id


def _prepare_project_for_glossary_review(
    *,
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    source_text: str,
    translated_text: str,
    glossary_terms: list[tuple[str, str]],
) -> int:
    source_file = project_workspace / "review-glossary-source.txt"
    source_file.write_text(source_text, encoding="utf-8")

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("review-glossary-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("review-glossary-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    glossary_service = GlossaryService(db_session)
    for source_term, target_term in glossary_terms:
        glossary_service.seed_locked_entry(
            project_id=project.id,
            source_term=source_term,
            target_term=target_term,
        )

    TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=StaticTranslationProvider(translated_text=translated_text),
    ).run(
        request_id=request_id_factory("review-glossary-translation"),
        project_id=project.id,
        scope={"type": "all"},
        model_profile_id="profile-review-glossary",
    )
    return project.id


def test_review_creates_structured_issues_for_current_translations(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_current_translations(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    result = ReviewService(db_session).run(
        request_id=request_id_factory("review-run"),
        project_id=project_id,
        scope={"type": "all"},
        review_mode="hard_only",
    )

    assert result.issue_count >= 1

    runs = db_session.execute(
        select(ReviewRun).where(ReviewRun.project_id == project_id)
    ).scalars().all()
    issues = db_session.execute(
        select(ReviewIssue).where(ReviewIssue.project_id == project_id)
    ).scalars().all()

    assert len(runs) == 1
    assert len(issues) >= 1
    assert {issue.issue_type for issue in issues} <= {
        "missing_translation",
        "unchanged_translation",
        "glossary_term_missing",
    }
    assert all(issue.status == "open" for issue in issues)


def test_review_reports_glossary_term_missing_when_translation_omits_required_target_term(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_for_glossary_review(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
        source_text="第1章 相遇\n程风到了。",
        translated_text="He arrived.",
        glossary_terms=[("程风", "Cheng Feng")],
    )

    result = ReviewService(db_session).run(
        request_id=request_id_factory("review-glossary-missing"),
        project_id=project_id,
        scope={"type": "all"},
        review_mode="hard_only",
    )

    issues = db_session.execute(
        select(ReviewIssue).where(ReviewIssue.review_run_id == result.run_id)
    ).scalars().all()

    assert result.issue_count == 1
    assert len(issues) == 1
    assert issues[0].issue_type == "glossary_term_missing"
    assert issues[0].severity == "medium"
    assert "程风" in issues[0].message
    assert "Cheng Feng" in issues[0].message


def test_review_allows_glossary_target_when_only_case_or_punctuation_differs(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_for_glossary_review(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
        source_text="第1章 相遇\n程风到了。",
        translated_text="“CHENG FENG,” arrived.",
        glossary_terms=[("程风", "Cheng Feng")],
    )

    result = ReviewService(db_session).run(
        request_id=request_id_factory("review-glossary-punctuation"),
        project_id=project_id,
        scope={"type": "all"},
        review_mode="hard_only",
    )

    issues = db_session.execute(
        select(ReviewIssue).where(ReviewIssue.review_run_id == result.run_id)
    ).scalars().all()

    assert result.issue_count == 0
    assert issues == []


def test_review_allows_glossary_target_with_hyphenated_transliteration(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_for_glossary_review(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
        source_text="第1章 邪术\n紫河车出现了。",
        translated_text="The zi-he-che appeared.",
        glossary_terms=[("紫河车", "Ziheche")],
    )

    result = ReviewService(db_session).run(
        request_id=request_id_factory("review-glossary-hyphenated"),
        project_id=project_id,
        scope={"type": "all"},
        review_mode="hard_only",
    )

    issues = db_session.execute(
        select(ReviewIssue).where(ReviewIssue.review_run_id == result.run_id)
    ).scalars().all()

    assert result.issue_count == 0
    assert issues == []


def test_review_ignores_single_cjk_character_glossary_overmatch(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_for_glossary_review(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
        source_text="第1章 阴云\n乌云遮住了月亮。",
        translated_text="Dark clouds covered the moon.",
        glossary_terms=[("云", "Yun")],
    )

    result = ReviewService(db_session).run(
        request_id=request_id_factory("review-glossary-single-cjk"),
        project_id=project_id,
        scope={"type": "all"},
        review_mode="hard_only",
    )

    issues = db_session.execute(
        select(ReviewIssue).where(ReviewIssue.review_run_id == result.run_id)
    ).scalars().all()

    assert result.issue_count == 0
    assert issues == []


def test_review_ignores_glossary_entries_not_hit_by_current_segment(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_for_glossary_review(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
        source_text="第1章 相遇\n他到了。",
        translated_text="He arrived.",
        glossary_terms=[("程风", "Cheng Feng")],
    )

    result = ReviewService(db_session).run(
        request_id=request_id_factory("review-glossary-no-hit"),
        project_id=project_id,
        scope={"type": "all"},
        review_mode="hard_only",
    )

    issues = db_session.execute(
        select(ReviewIssue).where(ReviewIssue.review_run_id == result.run_id)
    ).scalars().all()

    assert result.issue_count == 0
    assert issues == []


def test_review_and_export_support_chapter_list_scope(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_current_translations(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    review_result = ReviewService(db_session).run(
        request_id=request_id_factory("review-chapter-list"),
        project_id=project_id,
        scope={"type": "chapter_list", "chapters": [1]},
        review_mode="hard_only",
    )
    export_result = ExportService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("export-chapter-list"),
        project_id=project_id,
        scope={"type": "chapter_list", "chapters": [1]},
    )

    review_run = db_session.execute(
        select(ReviewRun).where(ReviewRun.project_id == project_id, ReviewRun.id == review_result.run_id)
    ).scalar_one()
    review_issues = db_session.execute(
        select(ReviewIssue).where(ReviewIssue.review_run_id == review_result.run_id)
    ).scalars().all()
    manifest = json.loads(Path(export_result.manifest_path).read_text(encoding="utf-8"))

    assert review_run.scope_type == "chapter_list"
    assert review_result.issue_count == len(review_issues)
    assert {issue.chapter_id for issue in review_issues} <= {manifest["translations"][0]["chapter_id"]}
    assert [item["chapter_index"] for item in manifest["translations"]] == [1]


def test_review_missing_only_reviews_unreviewed_and_needs_revision_segments(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_current_translations(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    first_result = ReviewService(db_session).run(
        request_id=request_id_factory("review-missing-only-first"),
        project_id=project_id,
        scope={"type": "chapter_list", "chapters": [1]},
        review_mode="hard_only",
    )

    first_issues = db_session.execute(
        select(ReviewIssue).where(ReviewIssue.review_run_id == first_result.run_id)
    ).scalars().all()
    assert len(first_issues) >= 1

    result = ReviewService(db_session).run(
        request_id=request_id_factory("review-missing-only-second"),
        project_id=project_id,
        scope={"type": "missing_only"},
        review_mode="hard_only",
    )

    review_run = db_session.execute(
        select(ReviewRun).where(ReviewRun.project_id == project_id, ReviewRun.id == result.run_id)
    ).scalar_one()
    review_issues = db_session.execute(
        select(ReviewIssue).where(ReviewIssue.review_run_id == result.run_id)
    ).scalars().all()
    segment_rows = db_session.execute(
        select(Chapter.chapter_index, ChapterSegment.review_status)
        .join(ChapterSegment, ChapterSegment.chapter_id == Chapter.id)
        .where(Chapter.project_id == project_id)
        .order_by(Chapter.chapter_index.asc())
    ).all()

    assert review_run.scope_type == "missing_only"
    assert result.issue_count == len(review_issues)
    assert {issue.chapter_id for issue in review_issues} <= {
        chapter_id
        for chapter_id, in db_session.execute(
            select(Chapter.id).where(Chapter.project_id == project_id, Chapter.chapter_index.in_([1, 2]))
        ).all()
    }
    assert result.needs_revision_segment_count == 2
    assert segment_rows == [(1, "needs_revision"), (2, "needs_revision")]


def test_review_run_summary_contains_translation_source_snapshot(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_current_translations(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    result = ReviewService(db_session).run(
        request_id=request_id_factory("review-source-snapshot"),
        project_id=project_id,
        scope={"type": "all"},
        review_mode="hard_only",
    )

    run = db_session.execute(
        select(ReviewRun).where(ReviewRun.id == result.run_id)
    ).scalar_one()
    summary = json.loads(run.summary)

    assert "translation_source" in summary
    assert summary["translation_source"]["segment_count"] >= 1
    assert summary["translation_source"]["version_count"] >= 1
    assert "translated_text" not in json.dumps(summary["translation_source"], ensure_ascii=False)


def test_export_reassembles_multi_segment_chapter_into_single_translation_record(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_sharded_translations(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    ReviewService(db_session).run(
        request_id=request_id_factory("review-export-sharded-review"),
        project_id=project_id,
        scope={"type": "all"},
        review_mode="hard_only",
    )
    result = ExportService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("review-export-sharded-export"),
        project_id=project_id,
        scope={"type": "all"},
    )

    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    export_text = Path(result.manifest_path).with_name("export.md").read_text(encoding="utf-8")

    assert len(manifest["translations"]) == 1
    chapter_translation = manifest["translations"][0]
    assert chapter_translation["chapter_index"] == 1
    assert chapter_translation["segment_count"] == 2
    assert "第一片正文" in chapter_translation["source_text"]
    assert "第二片正文" in chapter_translation["source_text"]
    assert chapter_translation["source_text"].index("第一片正文") < chapter_translation["source_text"].index("第二片正文")
    assert export_text.count("### 第1章 第1章 长夜") == 0
    assert export_text.count("### 第1章 长夜") == 1


def test_export_writes_manifest_and_export_artifacts(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_current_translations(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    ReviewService(db_session).run(
        request_id=request_id_factory("export-review"),
        project_id=project_id,
        scope={"type": "all"},
        review_mode="hard_only",
    )

    result = ExportService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("export-run"),
        project_id=project_id,
        scope={"type": "all"},
    )

    manifest_path = Path(result.manifest_path)
    assert manifest_path.is_file()
    assert result.artifact_count >= 2

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    export_text = manifest_path.with_name("export.md").read_text(encoding="utf-8")
    assert manifest["project_id"] == project_id
    assert manifest["artifacts"]
    assert manifest["translations"]
    assert manifest["glossary_entries"]
    assert manifest["review_summary"]["issue_count"] >= 1
    assert manifest["review_summary"]["review_status"] == "needs_revision"
    assert manifest["review_summary"]["review_risk"]["risk_level"] == "high"
    assert manifest["review_summary"]["needs_revision_segment_count"] >= 1
    assert manifest["translations"][0]["review_status"] == "needs_revision"
    assert manifest["translations"][0]["review_risk"]["needs_revision_segment_count"] >= 1
    assert "- review_status: needs_revision" in export_text
    assert "- needs_revision_segment_count:" in export_text
    assert "导出内容包含 needs_revision 分片" in export_text

    export_runs = db_session.execute(
        select(ExportRun).where(ExportRun.project_id == project_id)
    ).scalars().all()
    artifacts = db_session.execute(
        select(ExportArtifact).where(ExportArtifact.export_run_id == export_runs[0].id)
    ).scalars().all()

    assert len(export_runs) == 1
    assert len(artifacts) >= 2
    assert manifest_path.exists()
    assert any(Path(artifact.file_path).is_file() for artifact in artifacts if artifact.artifact_type != "manifest")


def test_review_and_export_inspect_expose_translation_source_at_top_level(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_current_translations(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    ReviewService(db_session).run(
        request_id=request_id_factory("review-inspect-source"),
        project_id=project_id,
        scope={"type": "chapter_list", "chapters": [1]},
        review_mode="hard_only",
    )
    ExportService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("export-inspect-source"),
        project_id=project_id,
        scope={"type": "chapter_list", "chapters": [1]},
    )

    review_payload = ReviewService(db_session).inspect(project_id=project_id)
    export_payload = ExportService(db_session, base_data_dir=project_workspace).inspect(project_id=project_id)

    assert review_payload["runs"][0]["translation_source"]["segment_count"] >= 1
    assert export_payload["runs"][0]["translation_source"]["segment_count"] >= 1
    assert "translated_text" not in json.dumps(review_payload["runs"][0]["translation_source"], ensure_ascii=False)
    assert "translated_text" not in json.dumps(export_payload["runs"][0]["translation_source"], ensure_ascii=False)


def test_export_review_summary_is_limited_to_export_scope(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_current_translations(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    target_version = None
    for version_row, _, segment_row, chapter_row in db_session.execute(
        select(SegmentTranslationVersion, SegmentTranslation, ChapterSegment, Chapter)
        .join(SegmentTranslation, SegmentTranslation.active_version_id == SegmentTranslationVersion.id)
        .join(ChapterSegment, ChapterSegment.id == SegmentTranslation.segment_id)
        .join(Chapter, Chapter.id == ChapterSegment.chapter_id)
        .where(SegmentTranslation.project_id == project_id)
    ).all():
        if chapter_row.chapter_index == 2 and segment_row.segment_index == 1:
            target_version = version_row
            source_text = Path(segment_row.source_text_path).read_text(encoding="utf-8").strip()
            target_version.translated_text = source_text
            break

    assert target_version is not None
    db_session.commit()

    ReviewService(db_session).run(
        request_id=request_id_factory("review-second-chapter"),
        project_id=project_id,
        scope={"type": "chapter_list", "chapters": [2]},
        review_mode="hard_only",
    )
    export_result = ExportService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("export-first-chapter"),
        project_id=project_id,
        scope={"type": "chapter_list", "chapters": [1]},
    )

    manifest = json.loads(Path(export_result.manifest_path).read_text(encoding="utf-8"))
    assert [item["chapter_index"] for item in manifest["translations"]] == [1]
    assert manifest["review_summary"]["issue_count"] == 0
    assert manifest["review_summary"]["issues"] == []
    assert manifest["review_summary"]["review_status"] == "pending"


def test_export_writes_synopsis_into_manifest_and_markdown(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_current_translations(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    synopsis = ProjectSynopsisRepository(db_session).ensure(project_id)
    synopsis.source_synopsis_text = "原文简介。"
    synopsis.source_synopsis_status = "ready"
    synopsis.source_synopsis_origin = "generated"
    synopsis.target_synopsis_text = "Target synopsis."
    synopsis.target_synopsis_status = "ready"
    synopsis.target_synopsis_origin = "translated"
    db_session.commit()

    result = ExportService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("export-synopsis"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
    )

    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    export_text = Path(result.manifest_path).with_name("export.md").read_text(encoding="utf-8")

    assert manifest["source_synopsis"] == "原文简介。"
    assert manifest["target_synopsis"] == "Target synopsis."
    assert "## 简介（原文）" in export_text
    assert "## 简介（译文）" in export_text
    assert "Target synopsis." in export_text
    assert export_text.index("## 简介（原文）") < export_text.index("## Translations")
    assert "原文简介。" not in export_text.split("## Translations", maxsplit=1)[-1]


def test_export_accepts_completed_target_synopsis(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_current_translations(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    synopsis = ProjectSynopsisRepository(db_session).ensure(project_id)
    synopsis.source_synopsis_text = "原文简介。"
    synopsis.source_synopsis_status = "ready"
    synopsis.source_synopsis_origin = "generated"
    synopsis.target_synopsis_text = "Completed synopsis."
    synopsis.target_synopsis_status = "completed"
    synopsis.target_synopsis_origin = "translated"
    db_session.commit()

    result = ExportService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("export-completed-synopsis"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
    )

    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["target_synopsis"] == "Completed synopsis."


def test_export_wraps_synopsis_text_in_fenced_blocks(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_current_translations(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    synopsis = ProjectSynopsisRepository(db_session).ensure(project_id)
    synopsis.source_synopsis_text = "# 原文简介\n- 第一行\n<div>原文</div>"
    synopsis.source_synopsis_status = "ready"
    synopsis.source_synopsis_origin = "generated"
    synopsis.target_synopsis_text = "# Target synopsis\n- line one\n<div>target</div>"
    synopsis.target_synopsis_status = "ready"
    synopsis.target_synopsis_origin = "translated"
    db_session.commit()

    result = ExportService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("export-fenced-synopsis"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
    )

    export_text = Path(result.manifest_path).with_name("export.md").read_text(encoding="utf-8")
    translations_prefix = export_text.split("## Translations", maxsplit=1)[0]

    assert "```text" in export_text
    assert translations_prefix.count("```text") == 2
    assert "# Target synopsis" not in translations_prefix.split("```text", maxsplit=1)[0]
    assert "## Translations" in export_text
    assert export_text.index("```text") < export_text.index("## Translations")


def test_export_rejects_blank_target_synopsis(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_current_translations(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    synopsis = ProjectSynopsisRepository(db_session).ensure(project_id)
    synopsis.source_synopsis_text = "原文简介。"
    synopsis.source_synopsis_status = "ready"
    synopsis.source_synopsis_origin = "generated"
    synopsis.target_synopsis_text = "   \n"
    synopsis.target_synopsis_status = "ready"
    synopsis.target_synopsis_origin = "translated"
    db_session.commit()

    with pytest.raises(ToolError, match="导出前缺少可用的目标语言简介"):
        ExportService(db_session, base_data_dir=project_workspace).run(
            request_id=request_id_factory("export-blank-synopsis"),
            project_id=project_id,
            scope={"type": "chapter_range", "start": 1, "end": 1},
        )


def test_export_uses_longer_fence_when_synopsis_contains_backticks(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_current_translations(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    synopsis = ProjectSynopsisRepository(db_session).ensure(project_id)
    synopsis.source_synopsis_text = "原文简介\n```"
    synopsis.source_synopsis_status = "ready"
    synopsis.source_synopsis_origin = "generated"
    synopsis.target_synopsis_text = "目标简介\n```"
    synopsis.target_synopsis_status = "ready"
    synopsis.target_synopsis_origin = "translated"
    db_session.commit()

    result = ExportService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("export-longer-fence"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
    )

    export_text = Path(result.manifest_path).with_name("export.md").read_text(encoding="utf-8")

    assert "````text" in export_text
    assert export_text.count("````text") == 2
    assert export_text.index("````text") < export_text.index("## Translations")
    assert "目标简介\n```" in export_text


def test_export_requires_target_synopsis_before_exporting(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_current_translations(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    synopsis = ProjectSynopsisRepository(db_session).ensure(project_id)
    synopsis.source_synopsis_text = "原文简介。"
    synopsis.source_synopsis_status = "ready"
    synopsis.source_synopsis_origin = "generated"
    synopsis.target_synopsis_text = None
    synopsis.target_synopsis_status = "missing"
    synopsis.target_synopsis_origin = None
    db_session.commit()

    with pytest.raises(ToolError, match="导出前缺少可用的目标语言简介"):
        ExportService(db_session, base_data_dir=project_workspace).run(
            request_id=request_id_factory("export-missing-synopsis"),
            project_id=project_id,
            scope={"type": "chapter_range", "start": 1, "end": 1},
        )


def test_cli_inspect_translation_review_export(
    database_url: str,
    project_workspace: Path,
    request_id_factory,
    capsys,
    db_session,
) -> None:
    project_id = _prepare_project_with_current_translations(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    review_exit_code = main(
        [
            "-Action",
            "stage.run",
            "-ProjectId",
            str(project_id),
            "-Stage",
            "review",
            "-ScopeType",
            "chapter_list",
            "-ScopeChapters",
            "1",
            "-RequestId",
            request_id_factory("inspect-review"),
            "-ReviewMode",
            "hard_only",
        ]
    )
    review_run_payload = json.loads(capsys.readouterr().out)
    export_exit_code = main(
        [
            "-Action",
            "stage.run",
            "-ProjectId",
            str(project_id),
            "-Stage",
            "export",
            "-ScopeType",
            "chapter_list",
            "-ScopeChapters",
            "1",
            "-RequestId",
            request_id_factory("inspect-export"),
        ]
    )
    export_run_payload = json.loads(capsys.readouterr().out)

    translation_exit_code = main(["-Action", "inspect.translation", "-ProjectId", str(project_id)])
    translation_payload = json.loads(capsys.readouterr().out)
    review_inspect_exit_code = main(["-Action", "inspect.review", "-ProjectId", str(project_id)])
    review_payload = json.loads(capsys.readouterr().out)
    export_inspect_exit_code = main(["-Action", "inspect.export", "-ProjectId", str(project_id)])
    export_payload = json.loads(capsys.readouterr().out)

    assert review_exit_code == 0
    assert review_run_payload["ok"] is True
    assert review_run_payload["action"] == "stage.run"
    assert review_run_payload["data"]["stage"] == "review"
    assert review_run_payload["data"]["issue_count"] >= 1
    assert review_run_payload["data"]["scope"]["type"] == "chapter_list"
    assert review_run_payload["data"]["scope"]["chapters"] == [1]

    assert export_exit_code == 0
    assert export_run_payload["ok"] is True
    assert export_run_payload["action"] == "stage.run"
    assert export_run_payload["data"]["stage"] == "export"
    assert export_run_payload["data"]["artifact_count"] >= 2
    assert export_run_payload["data"]["scope"]["type"] == "chapter_list"
    assert export_run_payload["data"]["scope"]["chapters"] == [1]

    assert translation_exit_code == 0
    assert translation_payload["ok"] is True
    assert translation_payload["action"] == "inspect.translation"
    assert len(translation_payload["data"]["translations"]) >= 2
    assert len(translation_payload["data"]["versions"]) >= 2

    assert review_inspect_exit_code == 0
    assert review_payload["ok"] is True
    assert review_payload["action"] == "inspect.review"
    assert len(review_payload["data"]["runs"]) == 1
    assert len(review_payload["data"]["issues"]) >= 1
    assert review_payload["data"]["runs"][0]["scope_type"] == "chapter_list"

    assert export_inspect_exit_code == 0
    assert export_payload["ok"] is True
    assert export_payload["action"] == "inspect.export"
    assert len(export_payload["data"]["runs"]) == 1
    assert len(export_payload["data"]["artifacts"]) >= 2
    assert export_payload["data"]["runs"][0]["scope_type"] == "chapter_list"
