from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import inspect, select, update

from tools.local_translation_workbench.app.cli import main
from tools.local_translation_workbench.app.db.models import (
    ChapterSegment,
    GlossaryEntry,
    ModelProfile,
    ProjectSynopsis,
    SegmentTranslation,
    SegmentTranslationVersion,
    StageRun,
    TranslationProject,
    WorkflowRun,
    WorkflowStepRun,
)
from tools.local_translation_workbench.app.errors import ToolError
from tools.local_translation_workbench.app.providers.base import TextGenerationResult
from tools.local_translation_workbench.app.providers.router import build_provider
from tools.local_translation_workbench.app.repositories.projects import ProjectService
from tools.local_translation_workbench.app.services.chaptering_service import ChapteringService
from tools.local_translation_workbench.app.services.provider_profile_service import ProviderProfileService
from tools.local_translation_workbench.app.services.stage_service import StageCommand, StageService
from tools.local_translation_workbench.app.services.translation_service import TranslationService


class FakeProvider:
    def __init__(
        self,
        outputs: list[str] | None = None,
        result_model_profile_ids: list[str] | None = None,
        fallback_depths: list[int] | None = None,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self.outputs = list(outputs or [])
        self.result_model_profile_ids = list(result_model_profile_ids or [])
        self.fallback_depths = list(fallback_depths or [])

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        self.calls.append(
            {
                "prompt": prompt,
                "model_name": model_name,
                "timeout_seconds": timeout_seconds,
            }
        )
        source_text = str(prompt).rsplit("\n\n", maxsplit=1)[-1]
        if self.outputs:
            content = self.outputs.pop(0)
        else:
            content = f"[{model_name}] {source_text}"
        result_model_profile_id = (
            self.result_model_profile_ids.pop(0) if self.result_model_profile_ids else None
        )
        fallback_depth = self.fallback_depths.pop(0) if self.fallback_depths else 0
        return TextGenerationResult(
            content=content,
            provider_name="fake_provider",
            model_name=model_name,
            model_profile_id=result_model_profile_id,
            fallback_depth=fallback_depth,
        )


class FailingProvider:
    def __init__(self, fail_on_call: int = 2) -> None:
        self.call_count = 0
        self.fail_on_call = fail_on_call

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        self.call_count += 1
        if self.call_count == self.fail_on_call:
            raise ToolError(code="provider_error", message="模拟第二段翻译失败。", status=502)
        source_text = str(prompt).split("\n\n", maxsplit=1)[-1]
        return TextGenerationResult(
            content=f"[{model_name}] {source_text}",
            provider_name="failing_provider",
            model_name=model_name,
        )


def _prepare_project_with_chapters(
    *,
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    source_text: str | None = None,
) -> int:
    source_file = project_workspace / "translation-source.txt"
    source_file.write_text(
        source_text or "第1章 开始\n第一段。\n\n第2章 继续\n第二段。",
        encoding="utf-8",
    )

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("translation-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("translation-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )
    return project.id


def test_translation_service_populates_missing_project_synopsis_before_segment_translation(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
        source_text="第1章 开始\n第一段。\n\n第2章 继续\n第二段。",
    )

    provider = FakeProvider(outputs=["源简介内容", "目标简介内容"])
    service = TranslationService(db_session, base_data_dir=project_workspace, provider=provider)
    result = service.run(
        request_id=request_id_factory("translation-synopsis-missing"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-a",
    )

    synopsis = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project_id)
    ).scalar_one()

    assert result.translated_segments == 1
    assert len(result.active_version_ids) == 1
    assert len(provider.calls) == 3
    assert "生成 source synopsis" in str(provider.calls[0]["prompt"])
    assert "翻译 target synopsis" in str(provider.calls[1]["prompt"])
    assert "翻译正文" in str(provider.calls[2]["prompt"])
    assert synopsis.source_synopsis_text == "源简介内容"
    assert synopsis.source_synopsis_status == "ready"
    assert synopsis.source_synopsis_origin == "generated"
    assert synopsis.source_synopsis_hash == hashlib.sha256("源简介内容".encode("utf-8")).hexdigest()
    assert synopsis.source_synopsis_model_profile_id == "profile-a"
    assert synopsis.source_synopsis_provider_name == "fake_provider"
    assert synopsis.source_synopsis_model_name == "profile-a"
    assert synopsis.target_synopsis_text == "目标简介内容"
    assert synopsis.target_synopsis_status == "ready"
    assert synopsis.target_synopsis_origin == "translated"
    assert synopsis.target_synopsis_hash == hashlib.sha256("目标简介内容".encode("utf-8")).hexdigest()
    assert synopsis.target_synopsis_model_profile_id == "profile-a"
    assert synopsis.target_synopsis_provider_name == "fake_provider"
    assert synopsis.target_synopsis_model_name == "profile-a"


def test_translation_service_reuses_extracted_source_synopsis_before_translating_target_and_segments(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
        source_text="## 简介\n原有简介。\n\n第1章 开始\n第一段。\n\n第2章 继续\n第二段。",
    )

    provider = FakeProvider(outputs=["目标简介内容"])
    service = TranslationService(db_session, base_data_dir=project_workspace, provider=provider)
    service.run(
        request_id=request_id_factory("translation-synopsis-existing"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-b",
    )

    synopsis = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project_id)
    ).scalar_one()

    assert len(provider.calls) == 2
    assert "生成 source synopsis" not in str(provider.calls[0]["prompt"])
    assert "翻译 target synopsis" in str(provider.calls[0]["prompt"])
    assert "翻译正文" in str(provider.calls[1]["prompt"])
    assert synopsis.source_synopsis_text == "原有简介。"
    assert synopsis.source_synopsis_status == "ready"
    assert synopsis.source_synopsis_origin == "extracted"
    assert synopsis.target_synopsis_text == "目标简介内容"
    assert synopsis.target_synopsis_status == "ready"
    assert synopsis.target_synopsis_origin == "translated"


def test_translation_service_keeps_working_when_source_file_is_missing_but_synopsis_is_ready(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    project = db_session.get(TranslationProject, project_id)
    assert project is not None
    source_file = Path(project.source_path)
    source_file.unlink()

    synopsis = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project_id)
    ).scalar_one()
    synopsis.source_synopsis_text = "已有 source synopsis"
    synopsis.source_synopsis_status = "ready"
    synopsis.source_synopsis_origin = "generated"
    synopsis.source_synopsis_hash = hashlib.sha256("已有 source synopsis".encode("utf-8")).hexdigest()
    synopsis.source_synopsis_model_profile_id = "profile-existing-source"
    synopsis.source_synopsis_provider_name = "fake_provider"
    synopsis.source_synopsis_model_name = "profile-existing-source"
    synopsis.target_synopsis_text = "已有 target synopsis"
    synopsis.target_synopsis_status = "ready"
    synopsis.target_synopsis_origin = "translated"
    synopsis.target_synopsis_hash = hashlib.sha256("已有 target synopsis".encode("utf-8")).hexdigest()
    synopsis.target_synopsis_model_profile_id = "profile-existing-target"
    synopsis.target_synopsis_provider_name = "fake_provider"
    synopsis.target_synopsis_model_name = "profile-existing-target"
    db_session.commit()

    provider = FakeProvider()
    result = TranslationService(db_session, base_data_dir=project_workspace, provider=provider).run(
        request_id=request_id_factory("translation-source-missing"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-output",
    )

    assert result.translated_segments == 1
    assert len(provider.calls) == 1
    assert "翻译正文" in str(provider.calls[0]["prompt"])


def test_translation_service_preserves_manual_target_synopsis_when_generated_source_is_stale(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
        source_text="第1章 开始\n第一段。\n\n第2章 继续\n第二段。",
    )

    synopsis = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project_id)
    ).scalar_one()
    synopsis.source_synopsis_text = "旧的 source synopsis"
    synopsis.source_synopsis_status = "ready"
    synopsis.source_synopsis_origin = "generated"
    synopsis.source_synopsis_hash = hashlib.sha256("旧的 source synopsis".encode("utf-8")).hexdigest()
    synopsis.source_synopsis_model_profile_id = "profile-source"
    synopsis.source_synopsis_provider_name = "fake_provider"
    synopsis.source_synopsis_model_name = "profile-source"
    synopsis.target_synopsis_text = "保留的目标简介"
    synopsis.target_synopsis_status = "ready"
    synopsis.target_synopsis_origin = "manual"
    synopsis.target_synopsis_hash = hashlib.sha256("保留的目标简介".encode("utf-8")).hexdigest()
    synopsis.target_synopsis_model_profile_id = "profile-target"
    synopsis.target_synopsis_provider_name = "manual-provider"
    synopsis.target_synopsis_model_name = "manual-model"
    db_session.commit()

    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("translation-manual-target-chaptering"),
        project_id=project_id,
        source_file_path=project_workspace / "translation-source.txt",
        scope={"type": "all"},
    )

    refreshed_after_chaptering = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project_id)
    ).scalar_one()
    assert refreshed_after_chaptering.source_synopsis_status == "stale"
    assert refreshed_after_chaptering.target_synopsis_status == "ready"
    assert refreshed_after_chaptering.target_synopsis_origin == "manual"

    provider = FakeProvider()
    result = TranslationService(db_session, base_data_dir=project_workspace, provider=provider).run(
        request_id=request_id_factory("translation-manual-target"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-output",
    )

    refreshed_after_translation = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project_id)
    ).scalar_one()

    assert result.translated_segments == 1
    assert len(provider.calls) == 2
    assert "生成 source synopsis" in str(provider.calls[0]["prompt"])
    assert "翻译正文" in str(provider.calls[1]["prompt"])
    assert refreshed_after_translation.source_synopsis_status == "ready"
    assert refreshed_after_translation.target_synopsis_text == "保留的目标简介"
    assert refreshed_after_translation.target_synopsis_status == "ready"
    assert refreshed_after_translation.target_synopsis_origin == "manual"
    assert refreshed_after_translation.target_synopsis_hash == hashlib.sha256("保留的目标简介".encode("utf-8")).hexdigest()
    assert refreshed_after_translation.target_synopsis_model_profile_id == "profile-target"
    assert refreshed_after_translation.target_synopsis_provider_name == "manual-provider"
    assert refreshed_after_translation.target_synopsis_model_name == "manual-model"


def test_translation_service_does_not_overwrite_manual_target_synopsis_after_explicit_synopsis_changes(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    source_file = project_workspace / "explicit-manual-target-translation.md"
    source_file.write_text(
        "## 简介\n\n"
        "第一版简介。\n\n"
        "## 正文\n\n"
        "### 1\n\n"
        "第一章正文。\n",
        encoding="utf-8",
    )

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("explicit-manual-target-translation"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    service = ChapteringService(db_session, base_data_dir=project_workspace)
    service.run(
        request_id=request_id_factory("explicit-manual-target-translation-run-1"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    synopsis = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project.id)
    ).scalar_one()
    synopsis.target_synopsis_text = "手动目标简介"
    synopsis.target_synopsis_status = "ready"
    synopsis.target_synopsis_origin = "manual"
    synopsis.target_synopsis_hash = hashlib.sha256("手动目标简介".encode("utf-8")).hexdigest()
    synopsis.target_synopsis_model_profile_id = "manual-profile"
    synopsis.target_synopsis_provider_name = "manual-provider"
    synopsis.target_synopsis_model_name = "manual-model"
    db_session.commit()

    source_file.write_text(
        "## 简介\n\n"
        "第二版简介。\n\n"
        "## 正文\n\n"
        "### 1\n\n"
        "第一章正文。\n",
        encoding="utf-8",
    )
    service.run(
        request_id=request_id_factory("explicit-manual-target-translation-run-2"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    provider = FakeProvider()
    TranslationService(db_session, base_data_dir=project_workspace, provider=provider).run(
        request_id=request_id_factory("explicit-manual-target-translation"),
        project_id=project.id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-output",
    )

    refreshed = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project.id)
    ).scalar_one()

    assert len(provider.calls) == 1
    assert "翻译正文" in str(provider.calls[0]["prompt"])
    assert refreshed.source_synopsis_text == "第二版简介。"
    assert refreshed.source_synopsis_status == "ready"
    assert refreshed.source_synopsis_origin == "extracted"
    assert refreshed.target_synopsis_text == "手动目标简介"
    assert refreshed.target_synopsis_status == "ready"
    assert refreshed.target_synopsis_origin == "manual"
    assert refreshed.target_synopsis_hash == hashlib.sha256("手动目标简介".encode("utf-8")).hexdigest()
    assert refreshed.target_synopsis_model_profile_id == "manual-profile"
    assert refreshed.target_synopsis_provider_name == "manual-provider"
    assert refreshed.target_synopsis_model_name == "manual-model"


def test_translation_service_refreshes_stale_target_synopsis_before_segments(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
        source_text="## 简介\n原有简介。\n\n第1章 开始\n第一段。\n\n第2章 继续\n第二段。",
    )

    synopsis = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project_id)
    ).scalar_one()
    synopsis.target_synopsis_text = "旧目标简介"
    synopsis.target_synopsis_status = "stale"
    synopsis.target_synopsis_origin = "translated"
    synopsis.target_synopsis_hash = "old-target-hash"
    db_session.commit()

    provider = FakeProvider(outputs=["新的目标简介"])
    service = TranslationService(db_session, base_data_dir=project_workspace, provider=provider)
    result = service.run(
        request_id=request_id_factory("translation-synopsis-stale-target"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-stale-target",
    )

    refreshed = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project_id)
    ).scalar_one()

    assert result.translated_segments == 1
    assert len(provider.calls) == 2
    assert "翻译 target synopsis" in str(provider.calls[0]["prompt"])
    assert "翻译正文" in str(provider.calls[1]["prompt"])
    assert refreshed.source_synopsis_text == "原有简介。"
    assert refreshed.source_synopsis_status == "ready"
    assert refreshed.source_synopsis_origin == "extracted"
    assert refreshed.target_synopsis_text == "新的目标简介"
    assert refreshed.target_synopsis_status == "ready"
    assert refreshed.target_synopsis_origin == "translated"
    assert refreshed.target_synopsis_hash == hashlib.sha256("新的目标简介".encode("utf-8")).hexdigest()
    assert refreshed.target_synopsis_model_profile_id == "profile-stale-target"
    assert refreshed.target_synopsis_provider_name == "fake_provider"
    assert refreshed.target_synopsis_model_name == "profile-stale-target"


def test_translation_service_creates_versions_and_updates_active_pointer(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    provider = FakeProvider()
    service = TranslationService(db_session, base_data_dir=project_workspace, provider=provider)
    result = service.run(
        request_id=request_id_factory("translation-run"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 2},
        model_profile_id="profile-a",
    )

    assert result.translated_segments == 2
    assert len(result.active_version_ids) == 2
    assert len(provider.calls) == 4
    assert all(call["model_name"] == "profile-a" for call in provider.calls)
    assert "生成 source synopsis" in str(provider.calls[0]["prompt"])
    assert "翻译 target synopsis" in str(provider.calls[1]["prompt"])
    assert "翻译正文" in str(provider.calls[2]["prompt"])
    assert "翻译正文" in str(provider.calls[3]["prompt"])

    translations = db_session.execute(
        select(SegmentTranslation).where(SegmentTranslation.project_id == project_id)
    ).scalars().all()
    versions = db_session.execute(
        select(SegmentTranslationVersion).where(SegmentTranslationVersion.project_id == project_id)
    ).scalars().all()
    stage_runs = db_session.execute(
        select(StageRun).where(StageRun.project_id == project_id, StageRun.stage == "translation")
    ).scalars().all()

    assert len(translations) == 2
    assert len(versions) == 2
    assert len(stage_runs) == 1
    assert stage_runs[0].status == "completed"
    assert all(len(version.source_hash) == 64 for version in versions)
    assert {version.glossary_snapshot_id for version in versions} != {"glossary-current"}
    assert {version.model_name for version in versions} == {"profile-a"}
    assert {version.status for version in versions} == {"completed"}
    assert {version.provider_name for version in versions} == {"fake_provider"}

    for translation in translations:
        assert translation.active_version_id is not None

    segment_rows = db_session.execute(
        select(ChapterSegment).where(ChapterSegment.project_id == project_id)
    ).scalars().all()
    assert len(segment_rows) == 2

    # 验证版本文件已落盘，并且重跑会新增版本而不是覆盖旧版本。
    first_version_paths = [Path(version.translated_text_path) for version in versions]
    for version_path in first_version_paths:
        assert version_path.is_file()
        assert version_path.read_text(encoding="utf-8").startswith("[profile-a]")
        assert version_path.parent.joinpath("current.txt").is_file()

    rerun_result = service.run(
        request_id=request_id_factory("translation-rerun"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 2},
        model_profile_id="profile-b",
    )

    assert rerun_result.translated_segments == 2
    assert len(rerun_result.active_version_ids) == 2

    rerun_versions = db_session.execute(
        select(SegmentTranslationVersion).where(SegmentTranslationVersion.project_id == project_id)
    ).scalars().all()
    rerun_translations = db_session.execute(
        select(SegmentTranslation).where(SegmentTranslation.project_id == project_id)
    ).scalars().all()
    rerun_stage_runs = db_session.execute(
        select(StageRun).where(StageRun.project_id == project_id, StageRun.stage == "translation")
    ).scalars().all()

    assert len(rerun_versions) == 4
    assert len(rerun_stage_runs) == 2
    assert {version.version_index for version in rerun_versions} == {1, 2}
    assert all(translation.active_version_id in rerun_result.active_version_ids for translation in rerun_translations)


def test_translation_service_injects_matching_glossary_entries_and_records_snapshot(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
        source_text="第1章 开始\n傅慕宁走进深蓝公寓。\n\n第2章 继续\n第二段。",
    )

    synopsis = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project_id)
    ).scalar_one()
    synopsis.source_synopsis_text = "已有 source synopsis"
    synopsis.source_synopsis_status = "ready"
    synopsis.source_synopsis_origin = "generated"
    synopsis.source_synopsis_hash = hashlib.sha256("已有 source synopsis".encode("utf-8")).hexdigest()
    synopsis.source_synopsis_model_profile_id = "profile-synopsis-source"
    synopsis.source_synopsis_provider_name = "fake_provider"
    synopsis.source_synopsis_model_name = "profile-synopsis-source"
    synopsis.target_synopsis_text = "已有 target synopsis"
    synopsis.target_synopsis_status = "ready"
    synopsis.target_synopsis_origin = "translated"
    synopsis.target_synopsis_hash = hashlib.sha256("已有 target synopsis".encode("utf-8")).hexdigest()
    synopsis.target_synopsis_model_profile_id = "profile-synopsis-target"
    synopsis.target_synopsis_provider_name = "fake_provider"
    synopsis.target_synopsis_model_name = "profile-synopsis-target"

    db_session.add_all(
        [
            GlossaryEntry(
                project_id=project_id,
                source_term="傅慕宁",
                target_term="Fu Muning",
                category="character",
                note="Character name, female",
                status="active",
                locked=1,
                term_group_key="傅慕宁",
                relation_role="independent",
            ),
            GlossaryEntry(
                project_id=project_id,
                source_term="深蓝公寓",
                target_term="Deep Blue Apartments",
                category="location",
                note="Apartment building",
                status="active",
                locked=0,
                term_group_key="深蓝公寓",
                relation_role="independent",
            ),
            GlossaryEntry(
                project_id=project_id,
                source_term="无关术语",
                target_term="Irrelevant Term",
                category="other",
                note="Should not be injected",
                status="active",
                locked=0,
                term_group_key="无关术语",
                relation_role="independent",
            ),
        ]
    )
    db_session.commit()

    provider = FakeProvider()
    result = TranslationService(db_session, base_data_dir=project_workspace, provider=provider).run(
        request_id=request_id_factory("translation-glossary-prompt"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-glossary-translation",
    )

    version = db_session.execute(
        select(SegmentTranslationVersion)
        .where(SegmentTranslationVersion.project_id == project_id)
        .order_by(SegmentTranslationVersion.id.asc())
    ).scalar_one()

    glossary_snapshot_payload = json.dumps(
        [
            {
                "source_term": "傅慕宁",
                "target_term": "Fu Muning",
                "category": "character",
                "note": "Character name, female",
                "gender": None,
                "age_group": None,
                "status": "active",
                "locked": 1,
                "term_group_key": "傅慕宁",
                "relation_role": "independent",
            },
            {
                "source_term": "无关术语",
                "target_term": "Irrelevant Term",
                "category": "other",
                "note": "Should not be injected",
                "gender": None,
                "age_group": None,
                "status": "active",
                "locked": 0,
                "term_group_key": "无关术语",
                "relation_role": "independent",
            },
            {
                "source_term": "深蓝公寓",
                "target_term": "Deep Blue Apartments",
                "category": "location",
                "note": "Apartment building",
                "gender": None,
                "age_group": None,
                "status": "active",
                "locked": 0,
                "term_group_key": "深蓝公寓",
                "relation_role": "independent",
            },
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    expected_snapshot_id = hashlib.sha256(glossary_snapshot_payload.encode("utf-8")).hexdigest()

    assert result.translated_segments == 1
    assert len(provider.calls) == 1
    assert "术语表" in str(provider.calls[0]["prompt"])
    assert "傅慕宁 => Fu Muning" in str(provider.calls[0]["prompt"])
    assert "深蓝公寓 => Deep Blue Apartments" in str(provider.calls[0]["prompt"])
    assert "无关术语 => Irrelevant Term" not in str(provider.calls[0]["prompt"])
    assert version.glossary_snapshot_id == expected_snapshot_id


def test_translation_glossary_prompt_and_snapshot_include_gender(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
        source_text="第1章 开始\n傅慕宁走进深蓝公寓。",
    )

    synopsis = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project_id)
    ).scalar_one()
    synopsis.source_synopsis_text = "已有 source synopsis"
    synopsis.source_synopsis_status = "ready"
    synopsis.source_synopsis_origin = "generated"
    synopsis.source_synopsis_hash = hashlib.sha256("已有 source synopsis".encode("utf-8")).hexdigest()
    synopsis.source_synopsis_model_profile_id = "profile-synopsis-source"
    synopsis.source_synopsis_provider_name = "fake_provider"
    synopsis.source_synopsis_model_name = "profile-synopsis-source"
    synopsis.target_synopsis_text = "已有 target synopsis"
    synopsis.target_synopsis_status = "ready"
    synopsis.target_synopsis_origin = "translated"
    synopsis.target_synopsis_hash = hashlib.sha256("已有 target synopsis".encode("utf-8")).hexdigest()
    synopsis.target_synopsis_model_profile_id = "profile-synopsis-target"
    synopsis.target_synopsis_provider_name = "fake_provider"
    synopsis.target_synopsis_model_name = "profile-synopsis-target"

    db_session.add_all(
        [
            GlossaryEntry(
                project_id=project_id,
                source_term="傅慕宁",
                target_term="Fu Muning",
                category="character",
                note="Character name",
                gender="female",
                status="active",
                locked=0,
                term_group_key="character-fu-muning",
                relation_role="canonical",
            ),
            GlossaryEntry(
                project_id=project_id,
                source_term="深蓝公寓",
                target_term="Deep Blue Apartments",
                category="location",
                note="Apartment building",
                gender=None,
                status="active",
                locked=0,
                term_group_key="location-deep-blue-apartments",
                relation_role="independent",
            ),
        ]
    )
    db_session.commit()

    provider = FakeProvider()
    TranslationService(db_session, base_data_dir=project_workspace, provider=provider).run(
        request_id=request_id_factory("translation-gender-snapshot"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-translation-gender",
    )

    version = db_session.execute(
        select(SegmentTranslationVersion)
        .where(SegmentTranslationVersion.project_id == project_id)
        .order_by(SegmentTranslationVersion.id.asc())
    ).scalar_one()

    assert "gender: female" in str(provider.calls[0]["prompt"])
    assert "深蓝公寓 => Deep Blue Apartments" in str(provider.calls[0]["prompt"])
    assert "gender: None" not in str(provider.calls[0]["prompt"])

    payload_with_gender = json.dumps(
        [
            {
                "source_term": "傅慕宁",
                "target_term": "Fu Muning",
                "category": "character",
                "note": "Character name",
                "gender": "female",
                "age_group": None,
                "status": "active",
                "locked": 0,
                "term_group_key": "character-fu-muning",
                "relation_role": "canonical",
            },
            {
                "source_term": "深蓝公寓",
                "target_term": "Deep Blue Apartments",
                "category": "location",
                "note": "Apartment building",
                "gender": None,
                "age_group": None,
                "status": "active",
                "locked": 0,
                "term_group_key": "location-deep-blue-apartments",
                "relation_role": "independent",
            },
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    expected_snapshot_id = hashlib.sha256(payload_with_gender.encode("utf-8")).hexdigest()

    assert version.glossary_snapshot_id == expected_snapshot_id


def test_translation_glossary_prompt_and_snapshot_include_age_group(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
        source_text="第1章 开始\n林溪背着书包走进深蓝公寓。",
    )

    synopsis = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project_id)
    ).scalar_one()
    synopsis.source_synopsis_text = "已有 source synopsis"
    synopsis.source_synopsis_status = "ready"
    synopsis.source_synopsis_origin = "generated"
    synopsis.source_synopsis_hash = hashlib.sha256("已有 source synopsis".encode("utf-8")).hexdigest()
    synopsis.source_synopsis_model_profile_id = "profile-synopsis-source"
    synopsis.source_synopsis_provider_name = "fake_provider"
    synopsis.source_synopsis_model_name = "profile-synopsis-source"
    synopsis.target_synopsis_text = "已有 target synopsis"
    synopsis.target_synopsis_status = "ready"
    synopsis.target_synopsis_origin = "translated"
    synopsis.target_synopsis_hash = hashlib.sha256("已有 target synopsis".encode("utf-8")).hexdigest()
    synopsis.target_synopsis_model_profile_id = "profile-synopsis-target"
    synopsis.target_synopsis_provider_name = "fake_provider"
    synopsis.target_synopsis_model_name = "profile-synopsis-target"

    db_session.add_all(
        [
            GlossaryEntry(
                project_id=project_id,
                source_term="林溪",
                target_term="Lin Xi",
                category="character",
                note="Character name",
                gender="female",
                age_group="teen",
                status="active",
                locked=0,
                term_group_key="character-linxi",
                relation_role="canonical",
            ),
            GlossaryEntry(
                project_id=project_id,
                source_term="深蓝公寓",
                target_term="Deep Blue Apartments",
                category="location",
                note="Apartment building",
                gender=None,
                age_group=None,
                status="active",
                locked=0,
                term_group_key="location-deep-blue-apartments",
                relation_role="independent",
            ),
        ]
    )
    db_session.commit()

    provider = FakeProvider()
    TranslationService(db_session, base_data_dir=project_workspace, provider=provider).run(
        request_id=request_id_factory("translation-age-group-snapshot"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-translation-age-group",
    )

    version = db_session.execute(
        select(SegmentTranslationVersion)
        .where(SegmentTranslationVersion.project_id == project_id)
        .order_by(SegmentTranslationVersion.id.asc())
    ).scalar_one()

    assert "age_group: teen" in str(provider.calls[0]["prompt"])
    assert "age_group: None" not in str(provider.calls[0]["prompt"])

    payload_with_age_group = json.dumps(
        [
            {
                "source_term": "林溪",
                "target_term": "Lin Xi",
                "category": "character",
                "note": "Character name",
                "gender": "female",
                "age_group": "teen",
                "status": "active",
                "locked": 0,
                "term_group_key": "character-linxi",
                "relation_role": "canonical",
            },
            {
                "source_term": "深蓝公寓",
                "target_term": "Deep Blue Apartments",
                "category": "location",
                "note": "Apartment building",
                "gender": None,
                "age_group": None,
                "status": "active",
                "locked": 0,
                "term_group_key": "location-deep-blue-apartments",
                "relation_role": "independent",
            },
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    expected_snapshot_id = hashlib.sha256(payload_with_age_group.encode("utf-8")).hexdigest()

    assert version.glossary_snapshot_id == expected_snapshot_id


def test_translation_snapshot_includes_term_relationship_fields(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
        source_text="第1章 开始\n张望月站在门口。望月后来又挥了挥手。",
    )

    synopsis = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project_id)
    ).scalar_one()
    synopsis.source_synopsis_text = "已有 source synopsis"
    synopsis.source_synopsis_status = "ready"
    synopsis.source_synopsis_origin = "generated"
    synopsis.source_synopsis_hash = hashlib.sha256("已有 source synopsis".encode("utf-8")).hexdigest()
    synopsis.source_synopsis_model_profile_id = "profile-synopsis-source"
    synopsis.source_synopsis_provider_name = "fake_provider"
    synopsis.source_synopsis_model_name = "profile-synopsis-source"
    synopsis.target_synopsis_text = "已有 target synopsis"
    synopsis.target_synopsis_status = "ready"
    synopsis.target_synopsis_origin = "translated"
    synopsis.target_synopsis_hash = hashlib.sha256("已有 target synopsis".encode("utf-8")).hexdigest()
    synopsis.target_synopsis_model_profile_id = "profile-synopsis-target"
    synopsis.target_synopsis_provider_name = "fake_provider"
    synopsis.target_synopsis_model_name = "profile-synopsis-target"

    db_session.add_all(
        [
            GlossaryEntry(
                project_id=project_id,
                source_term="张望月",
                target_term="Zhang Wangyue",
                category="character",
                note="Formal full name",
                status="active",
                locked=0,
                term_group_key="character-zhang-wangyue",
                relation_role="canonical",
            ),
            GlossaryEntry(
                project_id=project_id,
                source_term="望月",
                target_term="Wangyue",
                category="character",
                note="Short form used by acquaintances",
                status="active",
                locked=0,
                term_group_key="character-zhang-wangyue",
                relation_role="alias",
            ),
        ]
    )
    db_session.commit()

    provider = FakeProvider()
    result = TranslationService(db_session, base_data_dir=project_workspace, provider=provider).run(
        request_id=request_id_factory("translation-glossary-relationship-snapshot"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-glossary-relationship-snapshot",
    )

    version = db_session.execute(
        select(SegmentTranslationVersion)
        .where(SegmentTranslationVersion.project_id == project_id)
        .order_by(SegmentTranslationVersion.id.asc())
    ).scalar_one()

    glossary_snapshot_payload = json.dumps(
        [
            {
                "source_term": "张望月",
                "target_term": "Zhang Wangyue",
                "category": "character",
                "note": "Formal full name",
                "gender": None,
                "age_group": None,
                "status": "active",
                "locked": 0,
                "term_group_key": "character-zhang-wangyue",
                "relation_role": "canonical",
            },
            {
                "source_term": "望月",
                "target_term": "Wangyue",
                "category": "character",
                "note": "Short form used by acquaintances",
                "gender": None,
                "age_group": None,
                "status": "active",
                "locked": 0,
                "term_group_key": "character-zhang-wangyue",
                "relation_role": "alias",
            },
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    expected_snapshot_id = hashlib.sha256(glossary_snapshot_payload.encode("utf-8")).hexdigest()

    assert result.translated_segments == 1
    assert version.glossary_snapshot_id == expected_snapshot_id


def test_translation_uses_span_level_overlap_resolution_for_glossary_injection(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
        source_text="第1章 开始\n张望月站在门口。魔女小姐走后，望月又回头了。",
    )

    synopsis = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project_id)
    ).scalar_one()
    synopsis.source_synopsis_text = "已有 source synopsis"
    synopsis.source_synopsis_status = "ready"
    synopsis.source_synopsis_origin = "generated"
    synopsis.source_synopsis_hash = hashlib.sha256("已有 source synopsis".encode("utf-8")).hexdigest()
    synopsis.source_synopsis_model_profile_id = "profile-synopsis-source"
    synopsis.source_synopsis_provider_name = "fake_provider"
    synopsis.source_synopsis_model_name = "profile-synopsis-source"
    synopsis.target_synopsis_text = "已有 target synopsis"
    synopsis.target_synopsis_status = "ready"
    synopsis.target_synopsis_origin = "translated"
    synopsis.target_synopsis_hash = hashlib.sha256("已有 target synopsis".encode("utf-8")).hexdigest()
    synopsis.target_synopsis_model_profile_id = "profile-synopsis-target"
    synopsis.target_synopsis_provider_name = "fake_provider"
    synopsis.target_synopsis_model_name = "profile-synopsis-target"

    db_session.add_all(
        [
            GlossaryEntry(
                project_id=project_id,
                source_term="张望月",
                target_term="Zhang Wangyue",
                category="character",
                note="Formal full name",
                status="active",
                locked=0,
                term_group_key="character-zhang-wangyue",
                relation_role="canonical",
            ),
            GlossaryEntry(
                project_id=project_id,
                source_term="望月",
                target_term="Wangyue",
                category="character",
                note="Short form used by acquaintances",
                status="active",
                locked=0,
                term_group_key="character-zhang-wangyue",
                relation_role="alias",
            ),
            GlossaryEntry(
                project_id=project_id,
                source_term="望",
                target_term="Wang",
                category="character",
                note="Single-character short form should not be injected from overlaps only",
                status="active",
                locked=0,
                term_group_key="character-zhang-wangyue",
                relation_role="variant",
            ),
            GlossaryEntry(
                project_id=project_id,
                source_term="魔女小姐",
                target_term="Miss Witch",
                category="title",
                note="Fixed title form",
                status="active",
                locked=0,
                term_group_key="title-miss-witch",
                relation_role="title",
            ),
            GlossaryEntry(
                project_id=project_id,
                source_term="魔女",
                target_term="witch",
                category="term",
                note="Generic witch term",
                status="active",
                locked=0,
                term_group_key="term-witch",
                relation_role="independent",
            ),
        ]
    )
    db_session.commit()

    provider = FakeProvider()
    result = TranslationService(db_session, base_data_dir=project_workspace, provider=provider).run(
        request_id=request_id_factory("translation-glossary-overlap-resolution"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-glossary-overlap-resolution",
    )

    prompt = str(provider.calls[0]["prompt"])

    assert result.translated_segments == 1
    assert "张望月 => Zhang Wangyue" in prompt
    assert "望月 => Wangyue" in prompt
    assert "魔女小姐 => Miss Witch" in prompt
    assert "望 => Wang" not in prompt
    assert "魔女 => witch" not in prompt


def test_cli_stage_run_translation_supports_model_profile_id(
    project_workspace: Path,
    request_id_factory,
    capsys,
    monkeypatch,
    database_url: str,
    db_session,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    fake_provider = FakeProvider()
    from tools.local_translation_workbench.app import action_router as action_router_module
    from tools.local_translation_workbench.app.providers.router import ResolvedProviderProfile

    monkeypatch.setattr(
        action_router_module,
        "build_provider_from_profile",
        lambda session, config, model_profile_id: ResolvedProviderProfile(
            provider=fake_provider,
            profile_key="profile-cli",
            model_name="resolved-cli-model",
        ),
    )

    exit_code = main(
        [
            "-Action",
            "stage.run",
            "-ProjectId",
            str(project_id),
            "-Stage",
            "translation",
            "-ScopeType",
            "chapter_range",
            "-ScopeStart",
            "1",
            "-ScopeEnd",
            "2",
            "-ModelProfileId",
            "profile-cli",
            "-RequestId",
            request_id_factory("translation-cli"),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["action"] == "stage.run"
    assert payload["data"]["stage"] == "translation"
    assert payload["data"]["translated_segments"] == 2
    assert len(payload["data"]["active_version_ids"]) == 2
    assert payload["data"]["synopsis"]["source"]["status"] == "ready"
    assert payload["data"]["synopsis"]["source"]["origin"] == "generated"
    assert payload["data"]["synopsis"]["target"]["status"] == "ready"
    assert payload["data"]["synopsis"]["target"]["origin"] == "translated"
    assert all(call["model_name"] == "resolved-cli-model" for call in fake_provider.calls)

    versions = db_session.execute(
        select(SegmentTranslationVersion).where(SegmentTranslationVersion.project_id == project_id)
    ).scalars().all()
    assert versions
    assert {version.model_profile_id for version in versions} == {"profile-cli"}
    assert {version.model_name for version in versions} == {"resolved-cli-model"}


def test_stage_run_translation_uses_translation_single_llm_workflow_by_default(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    provider = FakeProvider(outputs=["源简介内容", "目标简介内容", "Draft translation output"])
    result = StageService(db_session, base_data_dir=project_workspace, provider=provider).run(
        StageCommand(
            request_id=request_id_factory("translation-single-workflow-default"),
            project_id=project_id,
            stage="translation",
            scope={"type": "chapter_range", "start": 1, "end": 1},
            model_profile_id="profile-translation-single",
        )
    )

    workflow_runs = db_session.execute(
        select(WorkflowRun).where(WorkflowRun.project_id == project_id, WorkflowRun.stage == "translation")
    ).scalars().all()
    step_runs = db_session.execute(
        select(WorkflowStepRun)
        .join(WorkflowRun, WorkflowRun.id == WorkflowStepRun.workflow_run_id)
        .where(WorkflowRun.project_id == project_id, WorkflowRun.stage == "translation")
        .order_by(WorkflowStepRun.id.asc())
    ).scalars().all()

    assert result.translated_segments == 1
    assert len(provider.calls) == 3
    assert "生成 source synopsis" in str(provider.calls[0]["prompt"])
    assert "翻译 target synopsis" in str(provider.calls[1]["prompt"])
    assert "翻译正文" in str(provider.calls[2]["prompt"])
    assert len(workflow_runs) == 1
    assert workflow_runs[0].workflow_key == "translation_single_llm_v1"
    assert [item.step_key for item in step_runs] == ["generate_primary", "finalize_segments"]


def test_stage_run_translation_persists_actual_fallback_profile_id(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    provider = FakeProvider(
        outputs=["源简介内容", "目标简介内容", "Draft translation output"],
        result_model_profile_ids=["profile-translation-backup"] * 3,
        fallback_depths=[1, 1, 1],
    )
    result = StageService(db_session, base_data_dir=project_workspace, provider=provider).run(
        StageCommand(
            request_id=request_id_factory("translation-single-fallback-profile"),
            project_id=project_id,
            stage="translation",
            scope={"type": "chapter_range", "start": 1, "end": 1},
            model_profile_id="profile-translation-main",
        )
    )

    versions = db_session.execute(
        select(SegmentTranslationVersion).where(SegmentTranslationVersion.project_id == project_id)
    ).scalars().all()

    assert result.translated_segments == 1
    assert len(versions) == 1
    assert versions[0].model_profile_id == "profile-translation-backup"


def test_stage_run_translation_can_use_explicit_multi_llm_workflow(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
        source_text="第1章 开始\n林溪看着赵馨宁。",
    )
    segment_id = db_session.execute(
        select(ChapterSegment.id)
        .where(ChapterSegment.project_id == project_id)
        .order_by(ChapterSegment.id.asc())
    ).scalar_one()

    provider = FakeProvider(
        outputs=[
            "源简介内容",
            "目标简介内容",
            "Primary draft",
            "Secondary draft",
            json.dumps(
                {
                    "reviews": [
                        {
                            "segment_id": segment_id,
                            "draft_role": "primary",
                            "decision": "keep",
                            "score": 0.88,
                            "reason_codes": ["faithful", "natural"],
                            "issues": [],
                        },
                        {
                            "segment_id": segment_id,
                            "draft_role": "secondary",
                            "decision": "revise",
                            "score": 0.74,
                            "reason_codes": ["glossary_drift"],
                            "issues": ["赵馨宁 译名不一致"],
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "drafts": [
                        {
                            "segment_id": segment_id,
                            "translated_text": "Rewrite draft",
                            "parent_draft_role": "primary",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
        ]
    )
    result = StageService(db_session, base_data_dir=project_workspace, provider=provider).run(
        StageCommand(
            request_id=request_id_factory("translation-multi-workflow-stage"),
            project_id=project_id,
            stage="translation",
            scope={"type": "chapter_range", "start": 1, "end": 1},
            model_profile_id="profile-translation-multi",
            workflow_key="translation_multi_llm_v1",
        )
    )

    workflow_runs = db_session.execute(
        select(WorkflowRun).where(WorkflowRun.project_id == project_id, WorkflowRun.stage == "translation")
    ).scalars().all()
    step_runs = db_session.execute(
        select(WorkflowStepRun)
        .join(WorkflowRun, WorkflowRun.id == WorkflowStepRun.workflow_run_id)
        .where(WorkflowRun.project_id == project_id, WorkflowRun.stage == "translation")
        .order_by(WorkflowStepRun.id.asc())
    ).scalars().all()
    versions = db_session.execute(
        select(SegmentTranslationVersion).where(SegmentTranslationVersion.project_id == project_id)
    ).scalars().all()

    assert result.translated_segments == 1
    assert len(workflow_runs) == 1
    assert workflow_runs[0].workflow_key == "translation_multi_llm_v1"
    assert [item.step_key for item in step_runs] == [
        "generate_primary",
        "generate_secondary",
        "review_drafts",
        "rewrite_consensus",
        "finalize_segments",
    ]
    assert len(versions) == 1
    assert versions[0].translated_text == "Rewrite draft"


def test_inspect_translation_includes_untranslated_segments(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    provider = FakeProvider()
    TranslationService(db_session, base_data_dir=project_workspace, provider=provider).run(
        request_id=request_id_factory("translation-partial"),
        project_id=project_id,
        scope={"type": "chapter_list", "chapters": [1]},
        model_profile_id="profile-inspect",
    )

    data = TranslationService(db_session, base_data_dir=project_workspace).inspect(project_id=project_id)

    assert len(data["translations"]) == 2
    chapter_indexes = {item["chapter_index"] for item in data["translations"]}
    assert chapter_indexes == {1, 2}
    pending_rows = [item for item in data["translations"] if item["chapter_index"] == 2]
    assert len(pending_rows) == 1
    assert pending_rows[0]["active_version_id"] is None
    assert pending_rows[0]["version"] is None
    assert pending_rows[0]["provenance"] is None
    assert pending_rows[0]["translation_status"] == "pending"


def test_translation_inspect_includes_single_llm_active_version_provenance(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    provider = FakeProvider(
        outputs=[
            "源简介内容",
            "目标简介内容",
            "Single workflow draft",
        ]
    )
    TranslationService(db_session, base_data_dir=project_workspace, provider=provider).run(
        request_id=request_id_factory("translation-provenance-single"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-single-provenance",
    )

    data = TranslationService(db_session, base_data_dir=project_workspace).inspect(project_id=project_id)
    translated_row = next(item for item in data["translations"] if item["chapter_index"] == 1)
    version = db_session.execute(
        select(SegmentTranslationVersion).where(SegmentTranslationVersion.id == translated_row["active_version_id"])
    ).scalar_one()

    assert version.origin_workflow_run_id is not None
    assert version.origin_step_run_id is not None
    assert version.origin_draft_version_id is not None
    assert translated_row["provenance"]["finalize_step"]["step_key"] == "finalize_segments"
    assert translated_row["provenance"]["selected_draft"]["draft_role"] == "primary"
    assert translated_row["provenance"]["selected_draft"]["reviews"] == []


def test_translation_inspect_includes_multi_llm_rewrite_provenance(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    segment_id = db_session.execute(
        select(ChapterSegment.id)
        .where(ChapterSegment.project_id == project_id)
        .order_by(ChapterSegment.id.asc())
    ).scalars().first()
    assert segment_id is not None

    provider = FakeProvider(
        outputs=[
            "源简介内容",
            "目标简介内容",
            "Primary draft",
            "Secondary draft",
            json.dumps(
                {
                    "reviews": [
                        {
                            "segment_id": segment_id,
                            "draft_role": "primary",
                            "decision": "keep",
                            "score": 0.91,
                            "reason_codes": ["faithful"],
                            "issues": [],
                        },
                        {
                            "segment_id": segment_id,
                            "draft_role": "secondary",
                            "decision": "revise",
                            "score": 0.64,
                            "reason_codes": ["wording"],
                            "issues": ["措辞偏硬"],
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "drafts": [
                        {
                            "segment_id": segment_id,
                            "translated_text": "Rewrite draft",
                            "parent_draft_role": "primary",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
        ]
    )

    TranslationService(db_session, base_data_dir=project_workspace, provider=provider).run(
        request_id=request_id_factory("translation-provenance-multi"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-multi-provenance",
        workflow_key="translation_multi_llm_v1",
    )

    data = TranslationService(db_session, base_data_dir=project_workspace).inspect(project_id=project_id)
    translated_row = next(item for item in data["translations"] if item["chapter_index"] == 1)

    assert translated_row["version"]["translated_text"] == "Rewrite draft"
    assert translated_row["provenance"]["selected_draft"]["draft_role"] == "rewrite"
    assert translated_row["provenance"]["selected_draft"]["parent_draft_id"] is not None
    assert translated_row["provenance"]["selected_draft"]["reviews"] == []


def test_translation_inspect_returns_null_provenance_for_legacy_active_version(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=FakeProvider(outputs=["源简介内容", "目标简介内容", "Legacy draft"]),
    ).run(
        request_id=request_id_factory("translation-provenance-legacy"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-legacy-provenance",
    )

    active_version_id = db_session.execute(
        select(SegmentTranslation.active_version_id)
        .where(SegmentTranslation.project_id == project_id)
        .order_by(SegmentTranslation.id.asc())
    ).scalars().first()
    assert active_version_id is not None

    db_session.execute(
        update(SegmentTranslationVersion)
        .where(SegmentTranslationVersion.id == active_version_id)
        .values(
            origin_workflow_run_id=None,
            origin_step_run_id=None,
            origin_draft_version_id=None,
        )
    )
    db_session.commit()

    data = TranslationService(db_session, base_data_dir=project_workspace).inspect(project_id=project_id)
    translated_row = next(item for item in data["translations"] if item["chapter_index"] == 1)

    assert translated_row["active_version_id"] == active_version_id
    assert translated_row["provenance"] is None


def test_translation_service_missing_only_translates_only_missing_segments(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=FakeProvider(),
    ).run(
        request_id=request_id_factory("translation-missing-only-initial"),
        project_id=project_id,
        scope={"type": "chapter_list", "chapters": [1]},
        model_profile_id="profile-missing-only-initial",
    )

    missing_only_provider = FakeProvider()
    result = TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=missing_only_provider,
    ).run(
        request_id=request_id_factory("translation-missing-only-rerun"),
        project_id=project_id,
        scope={"type": "missing_only"},
        model_profile_id="profile-missing-only-rerun",
    )

    segment_rows = db_session.execute(
        select(ChapterSegment.segment_index, ChapterSegment.translation_status)
        .where(ChapterSegment.project_id == project_id)
        .order_by(ChapterSegment.id.asc())
    ).all()

    assert result.translated_segments == 1
    assert len(missing_only_provider.calls) == 1
    assert segment_rows == [(1, "translated"), (1, "translated")]


def test_translation_service_failed_only_translates_only_failed_segments(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=FakeProvider(),
    ).run(
        request_id=request_id_factory("translation-failed-only-initial"),
        project_id=project_id,
        scope={"type": "chapter_list", "chapters": [1]},
        model_profile_id="profile-failed-only-initial",
    )

    second_segment = db_session.execute(
        select(ChapterSegment)
        .where(ChapterSegment.project_id == project_id)
        .order_by(ChapterSegment.id.asc())
    ).scalars().all()[1]
    second_segment.translation_status = "failed"
    db_session.commit()

    failed_only_provider = FakeProvider()
    result = TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=failed_only_provider,
    ).run(
        request_id=request_id_factory("translation-failed-only-rerun"),
        project_id=project_id,
        scope={"type": "failed_only"},
        model_profile_id="profile-failed-only-rerun",
    )

    segment_rows = db_session.execute(
        select(ChapterSegment.segment_index, ChapterSegment.translation_status)
        .where(ChapterSegment.project_id == project_id)
        .order_by(ChapterSegment.id.asc())
    ).all()

    assert result.translated_segments == 1
    assert len(failed_only_provider.calls) == 1
    assert segment_rows == [(1, "translated"), (1, "translated")]


def test_build_provider_requires_explicit_provider_config(monkeypatch, database_url: str) -> None:
    monkeypatch.setenv("LTW_DATABASE_URL", database_url)
    monkeypatch.delenv("LTW_PROVIDER_BASE_URL", raising=False)
    monkeypatch.delenv("LTW_PROVIDER_API_KEY", raising=False)

    with pytest.raises(ToolError) as exc:
        from tools.local_translation_workbench.app.config import load_config

        build_provider(load_config())

    assert exc.value.code == "invalid_arguments"


def test_build_provider_prefers_database_profile(db_session, monkeypatch, database_url: str) -> None:
    from tools.local_translation_workbench.app.config import load_config
    from tools.local_translation_workbench.app.providers.router import build_provider_from_profile

    monkeypatch.setenv("LTW_DATABASE_URL", database_url)
    monkeypatch.delenv("LTW_PROVIDER_BASE_URL", raising=False)
    monkeypatch.delenv("LTW_PROVIDER_API_KEY", raising=False)
    monkeypatch.setenv("LTW_PROVIDER_API_KEY_CODEX_HK_TEST", "sk-db-provider")

    service = ProviderProfileService(db_session)
    service.create_provider(
        provider_key="codex_hk_translation_test",
        provider_type="openai_compatible",
        display_name="Codex HK",
        base_url="https://codex-api.hk.pe",
        api_key_env_name="LTW_PROVIDER_API_KEY_CODEX_HK_TEST",
        status="active",
        note=None,
    )
    service.create_profile(
        profile_key="claude_hk_sonnet_4_6_translation_test",
        provider_key="codex_hk_translation_test",
        model_name="claude-sonnet-4-6",
        timeout_seconds=60,
        temperature=0,
        is_default=True,
        status="active",
        note=None,
    )

    resolved = build_provider_from_profile(
        db_session,
        load_config(),
        "claude_hk_sonnet_4_6_translation_test",
    )

    assert resolved.profile_key == "claude_hk_sonnet_4_6_translation_test"
    assert resolved.model_name == "claude-sonnet-4-6"
    assert resolved.provider.base_url == "https://codex-api.hk.pe"
    assert resolved.provider.api_key == "sk-db-provider"


def test_build_provider_from_profile_returns_anthropic_provider(
    db_session,
    monkeypatch,
    database_url: str,
) -> None:
    from tools.local_translation_workbench.app.config import load_config
    from tools.local_translation_workbench.app.providers.anthropic_messages import AnthropicMessagesProvider
    from tools.local_translation_workbench.app.providers.router import build_provider_from_profile

    monkeypatch.setenv("LTW_DATABASE_URL", database_url)
    monkeypatch.delenv("LTW_PROVIDER_BASE_URL", raising=False)
    monkeypatch.delenv("LTW_PROVIDER_API_KEY", raising=False)
    monkeypatch.setenv("LTW_PROVIDER_API_KEY_ANTHROPIC_TEST", "sk-anthropic-db-provider")

    service = ProviderProfileService(db_session)
    service.create_provider(
        provider_key="anthropic_translation_test",
        provider_type="anthropic_messages",
        display_name="Anthropic Test",
        base_url="https://anthropic-proxy.example.com",
        api_key_env_name="LTW_PROVIDER_API_KEY_ANTHROPIC_TEST",
        status="active",
        note=None,
    )
    service.create_profile(
        profile_key="claude_hk_sonnet_4_6_anthropic_test",
        provider_key="anthropic_translation_test",
        model_name="claude-sonnet-4-6",
        timeout_seconds=60,
        temperature=0,
        is_default=False,
        status="active",
        note=None,
    )

    resolved = build_provider_from_profile(
        db_session,
        load_config(),
        "claude_hk_sonnet_4_6_anthropic_test",
    )

    assert resolved.profile_key == "claude_hk_sonnet_4_6_anthropic_test"
    assert resolved.model_name == "claude-sonnet-4-6"
    assert isinstance(resolved.provider, AnthropicMessagesProvider)
    assert resolved.provider.base_url == "https://anthropic-proxy.example.com"
    assert resolved.provider.api_key == "sk-anthropic-db-provider"


def test_build_provider_from_profile_treats_default_as_default_profile(
    db_session,
    monkeypatch,
    database_url: str,
) -> None:
    from tools.local_translation_workbench.app.config import load_config
    from tools.local_translation_workbench.app.providers.router import build_provider_from_profile

    monkeypatch.setenv("LTW_DATABASE_URL", database_url)
    monkeypatch.setenv("LTW_PROVIDER_BASE_URL", "https://env-provider.example.com")
    monkeypatch.setenv("LTW_PROVIDER_API_KEY", "sk-env-provider")
    monkeypatch.setenv("LTW_PROVIDER_API_KEY_DEFAULT_PROFILE_TEST", "sk-default-profile")

    service = ProviderProfileService(db_session)
    service.create_provider(
        provider_key="default_profile_provider_test",
        provider_type="openai_compatible",
        display_name="Default Profile Provider",
        base_url="https://db-provider.example.com",
        api_key_env_name="LTW_PROVIDER_API_KEY_DEFAULT_PROFILE_TEST",
        status="active",
        note=None,
    )
    service.create_profile(
        profile_key="default_profile_translation_test",
        provider_key="default_profile_provider_test",
        model_name="claude-sonnet-default",
        timeout_seconds=60,
        temperature=0,
        is_default=True,
        status="active",
        note=None,
    )

    resolved = build_provider_from_profile(
        db_session,
        load_config(),
        "default",
    )

    assert resolved.profile_key == "default_profile_translation_test"
    assert resolved.model_name == "claude-sonnet-default"
    assert resolved.provider.base_url == "https://db-provider.example.com"
    assert resolved.provider.api_key == "sk-default-profile"


def test_build_provider_from_profile_raises_not_found_for_missing_explicit_profile(
    db_session,
    monkeypatch,
    database_url: str,
) -> None:
    from tools.local_translation_workbench.app.config import load_config
    from tools.local_translation_workbench.app.providers.router import build_provider_from_profile

    monkeypatch.setenv("LTW_DATABASE_URL", database_url)
    monkeypatch.setenv("LTW_PROVIDER_BASE_URL", "https://env-provider.example.com")
    monkeypatch.setenv("LTW_PROVIDER_API_KEY", "sk-env-provider")

    with pytest.raises(ToolError) as exc:
        build_provider_from_profile(
            db_session,
            load_config(),
            "missing_profile_key",
        )

    assert exc.value.code == "not_found"
    assert exc.value.status == 404
    assert "missing_profile_key" in exc.value.message


def test_build_provider_from_profile_uses_env_fallback_for_default_when_database_default_missing(
    db_session,
    monkeypatch,
    database_url: str,
) -> None:
    from tools.local_translation_workbench.app.config import load_config
    from tools.local_translation_workbench.app.providers.openai_compatible import OpenAICompatibleProvider
    from tools.local_translation_workbench.app.providers.router import build_provider_from_profile

    monkeypatch.setenv("LTW_DATABASE_URL", database_url)
    monkeypatch.setenv("LTW_PROVIDER_BASE_URL", "https://env-provider.example.com")
    monkeypatch.setenv("LTW_PROVIDER_API_KEY", "sk-env-provider")
    db_session.execute(update(ModelProfile).values(is_default=0))
    db_session.commit()

    resolved = build_provider_from_profile(
        db_session,
        load_config(),
        "default",
    )

    assert resolved.profile_key == "default"
    assert resolved.model_name == "default"
    assert isinstance(resolved.provider, OpenAICompatibleProvider)
    assert resolved.provider.base_url == "https://env-provider.example.com"
    assert resolved.provider.api_key == "sk-env-provider"


def test_translation_failure_rolls_back_database_and_output_files(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    project = db_session.get(TranslationProject, project_id)
    assert project is not None

    service = TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=FailingProvider(),
    )

    with pytest.raises(ToolError) as exc:
        service.run(
            request_id=request_id_factory("translation-fail"),
            project_id=project_id,
            scope={"type": "chapter_range", "start": 1, "end": 2},
            model_profile_id="profile-fail",
        )

    assert exc.value.code == "provider_error"
    db_session.rollback()

    translations = db_session.execute(
        select(SegmentTranslation).where(SegmentTranslation.project_id == project_id)
    ).scalars().all()
    versions = db_session.execute(
        select(SegmentTranslationVersion).where(SegmentTranslationVersion.project_id == project_id)
    ).scalars().all()
    stage_runs = db_session.execute(
        select(StageRun).where(StageRun.project_id == project_id, StageRun.stage == "translation")
    ).scalars().all()

    assert translations == []
    assert versions == []
    assert stage_runs == []

    translation_root = project_workspace / project.project_key / "translations"
    assert list(translation_root.rglob("*.txt")) == []


def test_translation_failure_keeps_successful_project_synopsis(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    service = TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=FailingProvider(fail_on_call=4),
    )

    with pytest.raises(ToolError) as exc:
        service.run(
            request_id=request_id_factory("translation-fail-keep-synopsis"),
            project_id=project_id,
            scope={"type": "chapter_range", "start": 1, "end": 2},
            model_profile_id="profile-fail-keep-synopsis",
        )

    assert exc.value.code == "provider_error"
    db_session.rollback()

    synopsis = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project_id)
    ).scalar_one()
    translations = db_session.execute(
        select(SegmentTranslation).where(SegmentTranslation.project_id == project_id)
    ).scalars().all()
    versions = db_session.execute(
        select(SegmentTranslationVersion).where(SegmentTranslationVersion.project_id == project_id)
    ).scalars().all()

    assert synopsis.source_synopsis_status == "ready"
    assert synopsis.source_synopsis_origin == "generated"
    assert synopsis.source_synopsis_text is not None
    assert synopsis.target_synopsis_status == "ready"
    assert synopsis.target_synopsis_origin == "translated"
    assert synopsis.target_synopsis_text is not None
    assert translations == []
    assert versions == []


def test_translation_schema_includes_version_provenance_columns(db_session) -> None:
    inspector = inspect(db_session.get_bind())
    columns = {
        column["name"]: column
        for column in inspector.get_columns("ltw_segment_translation_versions")
    }

    assert "origin_workflow_run_id" in columns
    assert "origin_step_run_id" in columns
    assert "origin_draft_version_id" in columns
    assert columns["origin_workflow_run_id"]["nullable"] is True
    assert columns["origin_step_run_id"]["nullable"] is True
    assert columns["origin_draft_version_id"]["nullable"] is True


def test_translation_schema_uses_unbounded_text_for_output_path(db_session) -> None:
    inspector = inspect(db_session.get_bind())
    columns = inspector.get_columns("ltw_segment_translation_versions")
    translated_text_path = next(column for column in columns if column["name"] == "translated_text_path")

    assert getattr(translated_text_path["type"], "length", None) is None
