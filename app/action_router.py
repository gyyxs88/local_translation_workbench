from __future__ import annotations

from typing import Any, Callable

from .action_support import (
    _bootstrap_workflow_profiles,
    _build_synopsis_summary,
    _count_rows,
    _open_session,
    _parse_bool,
    _parse_json_argument,
    _parse_json_string_list_argument,
    _parse_optional_int,
    _read_argument,
    _read_optional_argument,
    _require_argument,
    _require_database_url,
    _resolve_stage_window,
    _summarize_stage_result,
)
from .errors import ToolError
from .providers.router import build_provider, build_provider_from_profile

ActionHandler = Callable[[dict[str, str]], dict[str, Any]]
ACTION_HANDLERS: dict[str, ActionHandler]


def route_action(arguments: dict[str, str]) -> dict[str, Any]:
    action = _require_argument(arguments, "action").lower()
    handler = ACTION_HANDLERS.get(action)
    if handler is None:
        raise ToolError(code="invalid_arguments", message=f"不支持的 action: {action}", status=400)
    return handler(arguments)


def _resolve_model_stage_provider(*, session, config, stage: str, model_profile_id: str):
    if stage not in {"glossary", "translation", "review"}:
        return None
    return build_provider_from_profile(session, config, model_profile_id)


from .action_handlers import ACTION_HANDLERS
