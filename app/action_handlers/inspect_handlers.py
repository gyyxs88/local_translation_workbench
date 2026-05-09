from __future__ import annotations

from sqlalchemy import func, select

from .. import action_support as support
from ..config import load_config
from ..db.models import Chapter, ExportRun, GlossaryEntry, ReviewRun, SegmentTranslation, StageRun
from ..errors import ToolError
from ..repositories.projects import ProjectRepository
from ..repositories.synopsis import ProjectSynopsisRepository
from ..services.chapter_query_service import ChapterQueryService
from ..services.export_service import ExportService
from ..services.glossary_service import GlossaryService
from ..services.provider_call_log_service import ProviderCallLogService
from ..services.review_service import ReviewService
from ..services.scope_service import ScopeService, ensure_scope_supported, get_stage_scope_types
from ..services.synopsis_service import SynopsisService
from ..services.translation_service import TranslationService


def _require_project(session, project_id: int):
    project = ProjectRepository(session).get_by_id(project_id)
    if project is None:
        raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)
    return project


def handle_inspect_project(arguments: dict[str, str]) -> dict[str, object]:
    project_id = int(support._require_argument(arguments, "project_id"))
    session = support._open_session()
    try:
        project = _require_project(session, project_id)
        synopsis = ProjectSynopsisRepository(session).get_by_project_id(project_id)
        data = {
            "project": {
                "id": project.id,
                "request_id": project.request_id,
                "project_key": project.project_key,
                "source_path": project.source_path,
                "source_language": project.source_language,
                "target_language": project.target_language,
                "status": project.status,
            },
            "synopsis": support._build_synopsis_summary(synopsis),
            "counts": {
                "chapters": support._count_rows(
                    session,
                    select(func.count()).select_from(Chapter).where(Chapter.project_id == project_id),
                ),
                "glossary_entries": support._count_rows(
                    session,
                    select(func.count()).select_from(GlossaryEntry).where(GlossaryEntry.project_id == project_id),
                ),
                "translations": support._count_rows(
                    session,
                    select(func.count()).select_from(SegmentTranslation).where(SegmentTranslation.project_id == project_id),
                ),
                "review_runs": support._count_rows(
                    session,
                    select(func.count()).select_from(ReviewRun).where(ReviewRun.project_id == project_id),
                ),
                "export_runs": support._count_rows(
                    session,
                    select(func.count()).select_from(ExportRun).where(ExportRun.project_id == project_id),
                ),
                "stage_runs": support._count_rows(
                    session,
                    select(func.count()).select_from(StageRun).where(StageRun.project_id == project_id),
                ),
            },
        }
        return {"ok": True, "action": "inspect.project", "data": data}
    finally:
        session.close()


def handle_inspect_glossary(arguments: dict[str, str]) -> dict[str, object]:
    project_id = int(support._require_argument(arguments, "project_id"))
    session = support._open_session()
    try:
        _require_project(session, project_id)
        data = GlossaryService(session).inspect(project_id=project_id)
        return {"ok": True, "action": "inspect.glossary", "data": data}
    finally:
        session.close()


def handle_inspect_synopsis(arguments: dict[str, str]) -> dict[str, object]:
    project_id = int(support._require_argument(arguments, "project_id"))
    session = support._open_session()
    try:
        _require_project(session, project_id)
        data = SynopsisService(session).inspect(project_id=project_id)
        return {"ok": True, "action": "inspect.synopsis", "data": data}
    finally:
        session.close()


def handle_inspect_chapter(arguments: dict[str, str]) -> dict[str, object]:
    project_id = int(support._require_argument(arguments, "project_id"))
    session = support._open_session()
    try:
        _require_project(session, project_id)
        data = ChapterQueryService(session).inspect_chapter(
            project_id=project_id,
            chapter_id=support._parse_optional_int(arguments.get("chapter_id")),
            chapter_index=support._parse_optional_int(arguments.get("chapter_index")),
        )
        return {"ok": True, "action": "inspect.chapter", "data": data}
    finally:
        session.close()


def handle_inspect_chapters(arguments: dict[str, str]) -> dict[str, object]:
    project_id = int(support._require_argument(arguments, "project_id"))
    scope = ScopeService().build_scope(
        arguments.get("scope_type", "all"),
        scope_start=arguments.get("scope_start"),
        scope_end=arguments.get("scope_end"),
        scope_chapters=arguments.get("scope_chapters"),
    )
    ensure_scope_supported(scope, stage="chaptering", allowed_types=get_stage_scope_types("chaptering"))

    session = support._open_session()
    try:
        _require_project(session, project_id)
        data = ChapterQueryService(session).inspect_chapters(
            project_id=project_id,
            scope=scope,
            include_segments=support._parse_bool(arguments.get("include_segments")),
        )
        return {"ok": True, "action": "inspect.chapters", "data": data}
    finally:
        session.close()


def handle_inspect_segment(arguments: dict[str, str]) -> dict[str, object]:
    project_id = int(support._require_argument(arguments, "project_id"))
    session = support._open_session()
    try:
        _require_project(session, project_id)
        data = ChapterQueryService(session).inspect_segment(
            project_id=project_id,
            segment_id=support._parse_optional_int(arguments.get("segment_id")),
            chapter_index=support._parse_optional_int(arguments.get("chapter_index")),
            segment_index=support._parse_optional_int(arguments.get("segment_index")),
        )
        return {"ok": True, "action": "inspect.segment", "data": data}
    finally:
        session.close()


def handle_inspect_translation(arguments: dict[str, str]) -> dict[str, object]:
    project_id = int(support._require_argument(arguments, "project_id"))
    scope = None
    if any(arguments.get(key) is not None for key in ("scope_type", "scope_start", "scope_end", "scope_chapters")):
        scope = ScopeService().build_scope(
            arguments.get("scope_type", "all"),
            scope_start=arguments.get("scope_start"),
            scope_end=arguments.get("scope_end"),
            scope_chapters=arguments.get("scope_chapters"),
        )
        ensure_scope_supported(scope, stage="translation", allowed_types=get_stage_scope_types("translation"))
    config = load_config()
    session = support._open_session()
    try:
        _require_project(session, project_id)
        data = TranslationService(session, base_data_dir=config.data_dir).inspect(
            project_id=project_id,
            scope=scope,
            segment_id=support._parse_optional_int(arguments.get("segment_id")),
            chapter_index=support._parse_optional_int(arguments.get("chapter_index")),
            segment_index=support._parse_optional_int(arguments.get("segment_index")),
            version_id=support._parse_optional_int(arguments.get("version_id")),
            compare_version_id=support._parse_optional_int(arguments.get("compare_version_id")),
        )
        return {"ok": True, "action": "inspect.translation", "data": data}
    finally:
        session.close()


def handle_inspect_translation_samples(arguments: dict[str, str]) -> dict[str, object]:
    project_id = int(support._require_argument(arguments, "project_id"))
    scope = None
    if any(arguments.get(key) is not None for key in ("scope_type", "scope_start", "scope_end", "scope_chapters")):
        scope = ScopeService().build_scope(
            arguments.get("scope_type", "all"),
            scope_start=arguments.get("scope_start"),
            scope_end=arguments.get("scope_end"),
            scope_chapters=arguments.get("scope_chapters"),
        )
        ensure_scope_supported(scope, stage="translation", allowed_types=get_stage_scope_types("translation"))
    config = load_config()
    limit_per_source = support._parse_optional_int(arguments.get("limit")) or 3
    session = support._open_session()
    try:
        _require_project(session, project_id)
        data = TranslationService(session, base_data_dir=config.data_dir).inspect_quality_samples(
            project_id=project_id,
            scope=scope,
            limit_per_source=limit_per_source,
        )
        return {"ok": True, "action": "inspect.translation_samples", "data": data}
    finally:
        session.close()


def handle_inspect_review(arguments: dict[str, str]) -> dict[str, object]:
    project_id = int(support._require_argument(arguments, "project_id"))
    session = support._open_session()
    try:
        _require_project(session, project_id)
        data = ReviewService(session).inspect(project_id=project_id)
        return {"ok": True, "action": "inspect.review", "data": data}
    finally:
        session.close()


def handle_inspect_export(arguments: dict[str, str]) -> dict[str, object]:
    project_id = int(support._require_argument(arguments, "project_id"))
    config = load_config()
    session = support._open_session()
    try:
        _require_project(session, project_id)
        data = ExportService(session, base_data_dir=config.data_dir).inspect(project_id=project_id)
        return {"ok": True, "action": "inspect.export", "data": data}
    finally:
        session.close()


def handle_inspect_provider_calls(arguments: dict[str, str]) -> dict[str, object]:
    project_id = int(support._require_argument(arguments, "project_id"))
    session = support._open_session()
    try:
        _require_project(session, project_id)
        data = ProviderCallLogService(session).list_calls(
            project_id=project_id,
            stage=support._read_optional_argument(arguments, "stage"),
            status=support._read_optional_argument(arguments, "status"),
            limit=support._parse_optional_int(arguments.get("limit")) or 100,
        )
        return {"ok": True, "action": "inspect.provider_calls", "data": {"calls": data}}
    finally:
        session.close()


def handle_inspect_provider_costs(arguments: dict[str, str]) -> dict[str, object]:
    project_id = int(support._require_argument(arguments, "project_id"))
    session = support._open_session()
    try:
        _require_project(session, project_id)
        data = ProviderCallLogService(session).summarize_costs(
            project_id=project_id,
            stage=support._read_optional_argument(arguments, "stage"),
        )
        return {"ok": True, "action": "inspect.provider_costs", "data": data}
    finally:
        session.close()


INSPECT_ACTION_HANDLERS = {
    "inspect.project": handle_inspect_project,
    "inspect.glossary": handle_inspect_glossary,
    "inspect.synopsis": handle_inspect_synopsis,
    "inspect.chapter": handle_inspect_chapter,
    "inspect.chapters": handle_inspect_chapters,
    "inspect.segment": handle_inspect_segment,
    "inspect.translation": handle_inspect_translation,
    "inspect.translation_samples": handle_inspect_translation_samples,
    "inspect.review": handle_inspect_review,
    "inspect.export": handle_inspect_export,
    "inspect.provider_calls": handle_inspect_provider_calls,
    "inspect.provider_costs": handle_inspect_provider_costs,
}
