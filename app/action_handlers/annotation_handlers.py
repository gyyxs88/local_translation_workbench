from __future__ import annotations

from typing import Any

from .. import action_support as support
from ..config import load_config
from ..providers.router import build_provider_from_profile
from ..services.annotation_service import AnnotationService
from ..services.scope_service import ScopeService, ensure_scope_supported


_ANNOTATION_SCOPE_TYPES = {"all", "chapter_range", "chapter_list"}


def handle_annotation_extract(arguments: dict[str, str]) -> dict[str, Any]:
    project_id = int(support._require_argument(arguments, "project_id"))
    request_id = support._require_argument(arguments, "request_id")
    model_profile_id = arguments.get("model_profile_id", "default")
    scope = ScopeService().build_scope(
        arguments.get("scope_type", "all"),
        scope_start=arguments.get("scope_start"),
        scope_end=arguments.get("scope_end"),
        scope_chapters=arguments.get("scope_chapters"),
    )
    ensure_scope_supported(scope, stage="annotation", allowed_types=_ANNOTATION_SCOPE_TYPES)

    config = load_config()
    session = support._open_session()
    try:
        support._bootstrap_workflow_profiles(session)
        resolved = build_provider_from_profile(session, config, model_profile_id)
        data = AnnotationService(session, provider=resolved.provider).extract(
            request_id=request_id,
            project_id=project_id,
            scope=scope,
            model_profile_id=resolved.profile_key,
            provider_model_name=resolved.model_name,
        )
        session.commit()
        return {"ok": True, "action": "annotation.extract", "data": data}
    finally:
        session.close()


def handle_annotation_inspect(arguments: dict[str, str]) -> dict[str, Any]:
    project_id = int(support._require_argument(arguments, "project_id"))
    session = support._open_session()
    try:
        data = AnnotationService(session).inspect(project_id=project_id)
        return {"ok": True, "action": "annotation.inspect", "data": data}
    finally:
        session.close()


def handle_annotation_approve(arguments: dict[str, str]) -> dict[str, Any]:
    annotation_id = int(support._require_argument(arguments, "annotation_id"))
    locked = support._parse_bool(arguments.get("locked"))
    session = support._open_session()
    try:
        data = AnnotationService(session).approve(annotation_id=annotation_id, locked=locked)
        session.commit()
        return {"ok": True, "action": "annotation.approve", "data": data}
    finally:
        session.close()


def handle_annotation_reject(arguments: dict[str, str]) -> dict[str, Any]:
    annotation_id = int(support._require_argument(arguments, "annotation_id"))
    session = support._open_session()
    try:
        data = AnnotationService(session).reject(annotation_id=annotation_id)
        session.commit()
        return {"ok": True, "action": "annotation.reject", "data": data}
    finally:
        session.close()


ANNOTATION_ACTION_HANDLERS = {
    "annotation.extract": handle_annotation_extract,
    "annotation.inspect": handle_annotation_inspect,
    "annotation.approve": handle_annotation_approve,
    "annotation.reject": handle_annotation_reject,
}
