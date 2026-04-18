from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .. import action_support as support
from ..config import load_config
from ..errors import ToolError
from ..repositories.projects import ProjectRepository, ProjectService
from ..services.project_query_service import ProjectQueryService
from .stage_execution import execute_stage_command


def handle_project_create(arguments: dict[str, str]) -> dict[str, Any]:
    request_id = support._require_argument(arguments, "request_id")
    source_path = support._require_argument(arguments, "source_path")
    source_language = support._require_argument(arguments, "source_language")
    target_language = support._require_argument(arguments, "target_language")

    service = ProjectService(load_config().database_url)
    record = service.create_project(
        request_id=request_id,
        source_path=source_path,
        source_language=source_language,
        target_language=target_language,
    )
    return {"ok": True, "action": "project.create", "data": asdict(record)}


def handle_project_list(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        data = ProjectQueryService(session).list_projects()
        return {"ok": True, "action": "project.list", "data": data}
    finally:
        session.close()


def handle_project_cancel(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        data = ProjectQueryService(session).cancel_project(
            project_id=int(support._require_argument(arguments, "project_id")),
            request_id=support._require_argument(arguments, "request_id"),
        )
        return {"ok": True, "action": "project.cancel", "data": data}
    finally:
        session.close()


def handle_project_run_full(arguments: dict[str, str]) -> dict[str, Any]:
    request_id = support._require_argument(arguments, "request_id")
    project_id = int(support._require_argument(arguments, "project_id"))
    model_profile_id = arguments.get("model_profile_id", "default")
    resume = support._parse_bool(arguments.get("resume"))
    rerun = support._parse_bool(arguments.get("rerun"))
    stage_names = support._resolve_stage_window(
        from_stage=arguments.get("from_stage"),
        until_stage=arguments.get("until_stage"),
    )
    config = load_config()
    session = support._open_session()
    try:
        project = ProjectRepository(session).get_by_id(project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        results: dict[str, Any] = {}
        scope = {"type": "all"}
        for stage_name in stage_names:
            stage_result = execute_stage_command(
                session=session,
                config=config,
                request_id=f"{request_id}:{stage_name}",
                project_id=project_id,
                stage=stage_name,
                scope=scope,
                model_profile_id=model_profile_id,
                resume=resume,
                rerun=rerun,
            )
            results[stage_name] = support._summarize_stage_result(stage_name, stage_result)

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
