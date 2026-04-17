from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .. import action_router as router
from ..config import load_config
from ..errors import ToolError
from ..repositories.projects import ProjectRepository, ProjectService
from ..repositories.synopsis import ProjectSynopsisRepository
from ..services.project_query_service import ProjectQueryService
from ..services.stage_service import StageCommand, StageService


def handle_project_create(arguments: dict[str, str]) -> dict[str, Any]:
    request_id = router._require_argument(arguments, "request_id")
    source_path = router._require_argument(arguments, "source_path")
    source_language = router._require_argument(arguments, "source_language")
    target_language = router._require_argument(arguments, "target_language")

    service = ProjectService(load_config().database_url)
    record = service.create_project(
        request_id=request_id,
        source_path=source_path,
        source_language=source_language,
        target_language=target_language,
    )
    return {"ok": True, "action": "project.create", "data": asdict(record)}


def handle_project_list(arguments: dict[str, str]) -> dict[str, Any]:
    session = router._open_session()
    try:
        data = ProjectQueryService(session).list_projects()
        return {"ok": True, "action": "project.list", "data": data}
    finally:
        session.close()


def handle_project_cancel(arguments: dict[str, str]) -> dict[str, Any]:
    session = router._open_session()
    try:
        data = ProjectQueryService(session).cancel_project(
            project_id=int(router._require_argument(arguments, "project_id")),
            request_id=router._require_argument(arguments, "request_id"),
        )
        return {"ok": True, "action": "project.cancel", "data": data}
    finally:
        session.close()


def handle_project_run_full(arguments: dict[str, str]) -> dict[str, Any]:
    request_id = router._require_argument(arguments, "request_id")
    project_id = int(router._require_argument(arguments, "project_id"))
    model_profile_id = arguments.get("model_profile_id", "default")
    resume = router._parse_bool(arguments.get("resume"))
    rerun = router._parse_bool(arguments.get("rerun"))
    stage_names = router._resolve_stage_window(
        from_stage=arguments.get("from_stage"),
        until_stage=arguments.get("until_stage"),
    )
    config = load_config()
    session = router._open_session()
    try:
        project = ProjectRepository(session).get_by_id(project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        results: dict[str, Any] = {}
        scope = {"type": "all"}
        for stage_name in stage_names:
            resolved_provider = router._resolve_model_stage_provider(
                session=session,
                config=config,
                stage=stage_name,
                model_profile_id=model_profile_id,
            )
            stage_result = StageService(
                session,
                base_data_dir=config.data_dir,
                provider=None if resolved_provider is None else resolved_provider.provider,
            ).run(
                StageCommand(
                    request_id=f"{request_id}:{stage_name}",
                    project_id=project_id,
                    stage=stage_name,
                    scope=scope,
                    model_profile_id=(
                        resolved_provider.profile_key if resolved_provider is not None else model_profile_id
                    ),
                    provider_model_name=(
                        resolved_provider.model_name if resolved_provider is not None else None
                    ),
                    resume=resume,
                    rerun=rerun,
                )
            )
            results[stage_name] = router._summarize_stage_result(stage_name, stage_result)

        return {
            "ok": True,
            "action": "project.run_full",
            "data": {
                "project_id": project_id,
                "stages": list(stage_names),
                "results": results,
            },
        }
    finally:
        session.close()


PROJECT_ACTION_HANDLERS = {
    "project.create": handle_project_create,
    "project.list": handle_project_list,
    "project.cancel": handle_project_cancel,
    "project.run_full": handle_project_run_full,
}
