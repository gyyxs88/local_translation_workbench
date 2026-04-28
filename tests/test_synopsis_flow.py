from __future__ import annotations

import json
from pathlib import Path

from tools.local_translation_workbench.app.action_router import route_action
from tools.local_translation_workbench.app.db.models import ProjectSynopsis
from tools.local_translation_workbench.app.providers.base import TextGenerationResult
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tools.local_translation_workbench.app.repositories.projects import ProjectService
from tools.local_translation_workbench.app.repositories.synopsis import ProjectSynopsisRepository


class FakeSynopsisProvider:
    def __init__(
        self,
        outputs: list[str] | None = None,
        result_model_profile_ids: list[str] | None = None,
        fallback_depths: list[int] | None = None,
    ) -> None:
        self.outputs = list(outputs or [])
        self.result_model_profile_ids = list(result_model_profile_ids or [])
        self.fallback_depths = list(fallback_depths or [])
        self.calls: list[dict[str, object]] = []

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        self.calls.append(
            {
                "prompt": prompt,
                "model_name": model_name,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.outputs:
            content = self.outputs.pop(0)
        else:
            content = f"[{model_name}] {prompt}"
        result_model_profile_id = (
            self.result_model_profile_ids.pop(0) if self.result_model_profile_ids else None
        )
        fallback_depth = self.fallback_depths.pop(0) if self.fallback_depths else 0
        return TextGenerationResult(
            content=content,
            provider_name="fake_synopsis_provider",
            model_name=model_name,
            model_profile_id=result_model_profile_id,
            fallback_depth=fallback_depth,
        )


def test_inspect_project_includes_synopsis_summary(
    database_url: str,
    request_id_factory: callable,
    db_session: Session,
) -> None:
    request_id = request_id_factory("synopsis-inspect")
    project = ProjectService(database_url).create_project(
        request_id=request_id,
        source_path="D:/inputs/source.txt",
        source_language="ja",
        target_language="zh-CN",
    )

    payload = route_action(
        {
            "action": "inspect.project",
            "project_id": str(project.id),
        }
    )

    synopsis = payload["data"]["synopsis"]

    assert synopsis["source"]["status"] == "missing"
    assert synopsis["source"]["origin"] is None
    assert synopsis["source"]["length"] == 0
    assert synopsis["target"]["status"] == "missing"
    assert synopsis["target"]["origin"] is None
    assert synopsis["target"]["length"] == 0


def test_inspect_project_maps_existing_synopsis_row(
    database_url: str,
    request_id_factory: callable,
    db_session: Session,
) -> None:
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("synopsis-existing"),
        source_path="D:/inputs/source.txt",
        source_language="ja",
        target_language="zh-CN",
    )
    synopsis_row = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project.id)
    ).scalar_one()
    synopsis_row.source_synopsis_text = "第一段摘要"
    synopsis_row.source_synopsis_status = "ready"
    synopsis_row.source_synopsis_origin = "manual"
    synopsis_row.source_synopsis_hash = "hash-source"
    synopsis_row.source_synopsis_model_profile_id = "profile-source"
    synopsis_row.source_synopsis_provider_name = "provider-source"
    synopsis_row.source_synopsis_model_name = "model-source"
    synopsis_row.target_synopsis_text = "第二段摘要"
    synopsis_row.target_synopsis_status = "completed"
    synopsis_row.target_synopsis_origin = "generated"
    synopsis_row.target_synopsis_hash = "hash-target"
    synopsis_row.target_synopsis_model_profile_id = "profile-target"
    synopsis_row.target_synopsis_provider_name = "provider-target"
    synopsis_row.target_synopsis_model_name = "model-target"
    db_session.commit()

    payload = route_action(
        {
            "action": "inspect.project",
            "project_id": str(project.id),
        }
    )

    synopsis = payload["data"]["synopsis"]

    assert synopsis["source"]["status"] == "ready"
    assert synopsis["source"]["origin"] == "manual"
    assert synopsis["source"]["length"] == len("第一段摘要")
    assert synopsis["target"]["status"] == "completed"
    assert synopsis["target"]["origin"] == "generated"
    assert synopsis["target"]["length"] == len("第二段摘要")


def test_inspect_synopsis_returns_full_text_and_metadata(
    database_url: str,
    request_id_factory: callable,
    db_session: Session,
) -> None:
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("synopsis-details"),
        source_path="D:/inputs/source.txt",
        source_language="ja",
        target_language="zh-CN",
    )
    synopsis_row = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project.id)
    ).scalar_one()
    synopsis_row.source_synopsis_text = "第一段摘要"
    synopsis_row.source_synopsis_status = "ready"
    synopsis_row.source_synopsis_origin = "generated"
    synopsis_row.source_synopsis_hash = "hash-source"
    synopsis_row.source_synopsis_model_profile_id = "profile-source"
    synopsis_row.source_synopsis_provider_name = "provider-source"
    synopsis_row.source_synopsis_model_name = "model-source"
    synopsis_row.target_synopsis_text = "第二段摘要"
    synopsis_row.target_synopsis_status = "ready"
    synopsis_row.target_synopsis_origin = "translated"
    synopsis_row.target_synopsis_hash = "hash-target"
    synopsis_row.target_synopsis_model_profile_id = "profile-target"
    synopsis_row.target_synopsis_provider_name = "provider-target"
    synopsis_row.target_synopsis_model_name = "model-target"
    db_session.commit()

    payload = route_action(
        {
            "action": "inspect.synopsis",
            "project_id": str(project.id),
        }
    )

    synopsis = payload["data"]

    assert synopsis["project_id"] == project.id
    assert synopsis["source_synopsis_text"] == "第一段摘要"
    assert synopsis["source_synopsis_status"] == "ready"
    assert synopsis["source_synopsis_origin"] == "generated"
    assert synopsis["source_synopsis_hash"] == "hash-source"
    assert synopsis["source_synopsis_model_profile_id"] == "profile-source"
    assert synopsis["source_synopsis_provider_name"] == "provider-source"
    assert synopsis["source_synopsis_model_name"] == "model-source"
    assert synopsis["target_synopsis_text"] == "第二段摘要"
    assert synopsis["target_synopsis_status"] == "ready"
    assert synopsis["target_synopsis_origin"] == "translated"
    assert synopsis["target_synopsis_hash"] == "hash-target"
    assert synopsis["target_synopsis_model_profile_id"] == "profile-target"
    assert synopsis["target_synopsis_provider_name"] == "provider-target"
    assert synopsis["target_synopsis_model_name"] == "model-target"


def test_project_synopsis_repository_ensure_creates_missing_record(
    database_url: str,
    request_id_factory: callable,
    db_session: Session,
) -> None:
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("synopsis-repository"),
        source_path="D:/inputs/source.txt",
        source_language="ja",
        target_language="zh-CN",
    )
    repository = ProjectSynopsisRepository(db_session)

    synopsis = repository.ensure(project_id=project.id)

    assert synopsis.project_id == project.id
    assert synopsis.source_synopsis_status == "missing"
    assert synopsis.source_synopsis_text is None
    assert synopsis.source_synopsis_origin is None
    assert synopsis.source_synopsis_hash is None
    assert synopsis.source_synopsis_model_profile_id is None
    assert synopsis.source_synopsis_provider_name is None
    assert synopsis.source_synopsis_model_name is None
    assert synopsis.target_synopsis_status == "missing"
    assert synopsis.target_synopsis_text is None
    assert synopsis.target_synopsis_origin is None
    assert synopsis.target_synopsis_hash is None
    assert synopsis.target_synopsis_model_profile_id is None
    assert synopsis.target_synopsis_provider_name is None
    assert synopsis.target_synopsis_model_name is None
    assert repository.get_by_project_id(project.id) is not None


def test_project_synopsis_repository_ensure_is_idempotent(
    database_url: str,
    request_id_factory: callable,
    db_session: Session,
) -> None:
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("synopsis-idempotent"),
        source_path="D:/inputs/source.txt",
        source_language="ja",
        target_language="zh-CN",
    )
    repository = ProjectSynopsisRepository(db_session)

    first = repository.ensure(project_id=project.id)
    second = repository.ensure(project_id=project.id)

    synopsis_count = db_session.execute(
        select(func.count()).select_from(ProjectSynopsis).where(ProjectSynopsis.project_id == project.id)
    ).scalar_one()

    assert first.id == second.id
    assert synopsis_count == 1


def test_synopsis_flow_through_stage_run_and_inspect(
    monkeypatch,
    database_url: str,
    project_workspace: Path,
    request_id_factory: callable,
    db_session: Session,
) -> None:
    source_file = project_workspace / "synopsis-flow.md"
    source_file.write_text(
        "# 地下室最后一张照片\n\n"
        "## 简介\n"
        "这是原文简介。\n\n"
        "## 正文\n\n"
        "### 1\n"
        "第一章正文。\n",
        encoding="utf-8",
    )

    create_payload = route_action(
        {
            "action": "project.create",
            "request_id": request_id_factory("synopsis-flow-create"),
            "source_path": str(source_file),
            "source_language": "zh",
            "target_language": "en",
        }
    )
    project_id = create_payload["data"]["id"]

    chaptering_payload = route_action(
        {
            "action": "stage.run",
            "request_id": request_id_factory("synopsis-flow-chaptering"),
            "project_id": str(project_id),
            "stage": "chaptering",
            "scope_type": "all",
        }
    )

    assert chaptering_payload["ok"] is True
    assert chaptering_payload["data"]["stage"] == "chaptering"
    assert chaptering_payload["data"]["chapter_count"] == 1
    assert chaptering_payload["data"]["segment_count"] == 1
    assert chaptering_payload["data"]["synopsis"]["source"]["status"] == "ready"
    assert chaptering_payload["data"]["synopsis"]["source"]["origin"] == "extracted"
    assert chaptering_payload["data"]["synopsis"]["source"]["length"] == len("这是原文简介。")
    assert chaptering_payload["data"]["synopsis"]["target"]["status"] == "missing"

    fake_provider = FakeSynopsisProvider(outputs=["Target synopsis."])
    from tools.local_translation_workbench.app import action_router as action_router_module
    from tools.local_translation_workbench.app.providers.router import ResolvedProviderProfile

    monkeypatch.setattr(
        action_router_module,
        "build_provider_from_profile",
        lambda session, config, model_profile_id: ResolvedProviderProfile(
            provider=fake_provider,
            profile_key=str(model_profile_id or "profile-synopsis-flow"),
            model_name="resolved-synopsis-flow-model",
        ),
    )

    translation_payload = route_action(
        {
            "action": "stage.run",
            "request_id": request_id_factory("synopsis-flow-translation"),
            "project_id": str(project_id),
            "stage": "translation",
            "scope_type": "chapter_range",
            "scope_start": "1",
            "scope_end": "1",
            "model_profile_id": "profile-synopsis-flow",
        }
    )

    assert translation_payload["ok"] is True
    assert translation_payload["data"]["stage"] == "translation"
    assert translation_payload["data"]["translated_segments"] == 1
    assert translation_payload["data"]["synopsis"]["source"]["status"] == "ready"
    assert translation_payload["data"]["synopsis"]["target"]["status"] == "ready"
    assert translation_payload["data"]["synopsis"]["target"]["origin"] == "translated"
    assert len(fake_provider.calls) == 2
    assert "翻译 target synopsis" in str(fake_provider.calls[0]["prompt"])
    assert "翻译正文" in str(fake_provider.calls[1]["prompt"])

    inspect_payload = route_action(
        {
            "action": "inspect.synopsis",
            "project_id": str(project_id),
        }
    )

    assert inspect_payload["ok"] is True
    assert inspect_payload["data"]["source_synopsis_text"] == "这是原文简介。"
    assert inspect_payload["data"]["target_synopsis_text"] == "Target synopsis."
    assert inspect_payload["data"]["source_synopsis_origin"] == "extracted"
    assert inspect_payload["data"]["target_synopsis_origin"] == "translated"

    export_payload = route_action(
        {
            "action": "stage.run",
            "request_id": request_id_factory("synopsis-flow-export"),
            "project_id": str(project_id),
            "stage": "export",
            "scope_type": "chapter_range",
            "scope_start": "1",
            "scope_end": "1",
        }
    )

    assert export_payload["ok"] is True
    assert export_payload["data"]["stage"] == "export"
    assert export_payload["data"]["synopsis"]["source"]["status"] == "ready"
    assert export_payload["data"]["synopsis"]["target"]["status"] == "ready"
    assert Path(export_payload["data"]["manifest_path"]).is_file()

    manifest = json.loads(Path(export_payload["data"]["manifest_path"]).read_text(encoding="utf-8"))
    export_text = Path(export_payload["data"]["manifest_path"]).with_name("export.md").read_text(encoding="utf-8")

    assert manifest["source_synopsis"] == "这是原文简介。"
    assert manifest["target_synopsis"] == "Target synopsis."
    assert "## 简介（原文）" in export_text
    assert "## 简介（译文）" in export_text


def test_chaptering_extracts_explicit_synopsis_from_utf8_bom_file(
    project_workspace: Path,
    request_id_factory: callable,
) -> None:
    source_file = project_workspace / "synopsis-bom-flow.md"
    source_file.write_text(
        "## 简介\n\n"
        "这是带 BOM 的简介。\n\n"
        "## 正文\n\n"
        "### 1\n\n"
        "第一章正文。\n",
        encoding="utf-8-sig",
    )

    create_payload = route_action(
        {
            "action": "project.create",
            "request_id": request_id_factory("synopsis-bom-create"),
            "source_path": str(source_file),
            "source_language": "zh",
            "target_language": "en",
        }
    )
    project_id = create_payload["data"]["id"]

    chaptering_payload = route_action(
        {
            "action": "stage.run",
            "request_id": request_id_factory("synopsis-bom-chaptering"),
            "project_id": str(project_id),
            "stage": "chaptering",
            "scope_type": "all",
        }
    )

    assert chaptering_payload["ok"] is True
    assert chaptering_payload["data"]["synopsis"]["source"]["status"] == "ready"
    assert chaptering_payload["data"]["synopsis"]["source"]["origin"] == "extracted"
    assert chaptering_payload["data"]["synopsis"]["source"]["length"] == 10
    assert chaptering_payload["data"]["synopsis"]["source"]["length_unit"] == "characters"

    inspect_payload = route_action(
        {
            "action": "inspect.synopsis",
            "project_id": str(project_id),
        }
    )

    assert inspect_payload["ok"] is True
    assert inspect_payload["data"]["source_synopsis_text"] == "这是带 BOM 的简介。"


def test_stage_run_translation_persists_actual_fallback_profile_ids_in_synopsis(
    monkeypatch,
    database_url: str,
    project_workspace: Path,
    request_id_factory: callable,
    db_session: Session,
) -> None:
    source_file = project_workspace / "synopsis-fallback-flow.md"
    source_file.write_text(
        "# 地下室最后一张照片\n\n"
        "## 正文\n\n"
        "### 1\n"
        "第一章正文。\n",
        encoding="utf-8",
    )

    create_payload = route_action(
        {
            "action": "project.create",
            "request_id": request_id_factory("synopsis-fallback-create"),
            "source_path": str(source_file),
            "source_language": "zh",
            "target_language": "en",
        }
    )
    project_id = create_payload["data"]["id"]

    route_action(
        {
            "action": "stage.run",
            "request_id": request_id_factory("synopsis-fallback-chaptering"),
            "project_id": str(project_id),
            "stage": "chaptering",
            "scope_type": "all",
        }
    )

    fake_provider = FakeSynopsisProvider(
        outputs=["生成的源简介", "Translated synopsis.", "Translated segment."],
        result_model_profile_ids=["profile-synopsis-backup"] * 3,
        fallback_depths=[1, 1, 1],
    )
    from tools.local_translation_workbench.app import action_router as action_router_module
    from tools.local_translation_workbench.app.providers.router import ResolvedProviderProfile

    monkeypatch.setattr(
        action_router_module,
        "build_provider_from_profile",
        lambda session, config, model_profile_id: ResolvedProviderProfile(
            provider=fake_provider,
            profile_key=str(model_profile_id or "profile-synopsis-main"),
            model_name="resolved-synopsis-main-model",
        ),
    )

    translation_payload = route_action(
        {
            "action": "stage.run",
            "request_id": request_id_factory("synopsis-fallback-translation"),
            "project_id": str(project_id),
            "stage": "translation",
            "scope_type": "chapter_range",
            "scope_start": "1",
            "scope_end": "1",
            "model_profile_id": "profile-synopsis-main",
        }
    )

    assert translation_payload["ok"] is True

    inspect_payload = route_action(
        {
            "action": "inspect.synopsis",
            "project_id": str(project_id),
        }
    )

    assert inspect_payload["data"]["source_synopsis_model_profile_id"] == "profile-synopsis-backup"
    assert inspect_payload["data"]["target_synopsis_model_profile_id"] == "profile-synopsis-backup"
