from __future__ import annotations

from typing import Any

from .. import action_support as support
from ..config import load_config
from ..services.provider_profile_service import ProviderProfileService
from ..services.provider_resolution_service import ProviderResolutionService
from ..services.workflow_profile_service import WorkflowProfileService


def handle_provider_create(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        data = ProviderProfileService(session).create_provider(
            provider_key=support._require_argument(arguments, "provider_key"),
            provider_type=support._require_argument(arguments, "provider_type"),
            display_name=support._require_argument(arguments, "display_name"),
            base_url=support._require_argument(arguments, "base_url"),
            api_key_env_name=support._require_argument(arguments, "api_key_env_name"),
            status=arguments.get("status", "active"),
            note=arguments.get("note"),
        )
        return {"ok": True, "action": "provider.create", "data": data}
    finally:
        session.close()


def handle_provider_list(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        data = ProviderProfileService(session).list_providers()
        return {"ok": True, "action": "provider.list", "data": data}
    finally:
        session.close()


def handle_provider_inspect(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        data = ProviderProfileService(session).inspect_provider(
            provider_key=support._require_argument(arguments, "provider_key")
        )
        return {"ok": True, "action": "provider.inspect", "data": data}
    finally:
        session.close()


def handle_provider_health_check(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        include_fallbacks_value = support._read_optional_argument(arguments, "include_fallbacks")
        data = ProviderResolutionService(session, load_config()).health_check(
            model_profile_id=support._read_optional_argument(arguments, "model_profile_id") or "default",
            include_fallbacks=True if include_fallbacks_value is None else support._parse_bool(include_fallbacks_value),
        )
        return {"ok": True, "action": "provider.health_check", "data": data}
    finally:
        session.close()


def handle_profile_create(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        data = ProviderProfileService(session).create_profile(
            profile_key=support._require_argument(arguments, "profile_key"),
            provider_key=support._require_argument(arguments, "provider_key"),
            model_name=support._require_argument(arguments, "model_name"),
            timeout_seconds=support._parse_optional_int(arguments.get("timeout_seconds")),
            temperature=support._parse_optional_int(arguments.get("temperature")),
            fallback_profile_keys=support._parse_json_string_list_argument(
                support._read_optional_argument(arguments, "fallback_profile_keys_json")
            ),
            is_default=support._parse_bool(arguments.get("is_default")),
            status=arguments.get("status", "active"),
            note=arguments.get("note"),
        )
        return {"ok": True, "action": "profile.create", "data": data}
    finally:
        session.close()


def handle_profile_list(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        data = ProviderProfileService(session).list_profiles()
        return {"ok": True, "action": "profile.list", "data": data}
    finally:
        session.close()


def handle_profile_inspect(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        data = ProviderProfileService(session).inspect_profile(
            profile_key=support._require_argument(arguments, "profile_key")
        )
        return {"ok": True, "action": "profile.inspect", "data": data}
    finally:
        session.close()


def handle_profile_set_fallbacks(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        data = ProviderProfileService(session).set_profile_fallbacks(
            profile_key=support._require_argument(arguments, "profile_key"),
            fallback_profile_keys=support._parse_json_string_list_argument(
                support._read_argument(arguments, "fallback_profile_keys_json")
            ),
        )
        return {"ok": True, "action": "profile.set_fallbacks", "data": data}
    finally:
        session.close()


def handle_workflow_create(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        support._bootstrap_workflow_profiles(session)
        service = WorkflowProfileService(session)
        data = service.create_workflow(
            workflow_key=support._read_argument(arguments, "workflow_key"),
            stage=support._read_argument(arguments, "stage"),
            status=arguments.get("status", "active"),
            is_default=support._parse_bool(arguments.get("is_default")),
            definition_json=support._parse_json_argument(
                arguments.get("definition_json") or arguments.get("definitionjson")
            ),
        )
        return {"ok": True, "action": "workflow.create", "data": data}
    finally:
        session.close()


def handle_workflow_list(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        support._bootstrap_workflow_profiles(session)
        service = WorkflowProfileService(session)
        data = service.list_workflows(stage=support._read_optional_argument(arguments, "stage"))
        return {"ok": True, "action": "workflow.list", "data": data}
    finally:
        session.close()


def handle_workflow_inspect(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        support._bootstrap_workflow_profiles(session)
        service = WorkflowProfileService(session)
        data = service.inspect_workflow(workflow_key=support._read_argument(arguments, "workflow_key"))
        return {"ok": True, "action": "workflow.inspect", "data": data}
    finally:
        session.close()


def handle_workflow_set_default(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        support._bootstrap_workflow_profiles(session)
        service = WorkflowProfileService(session)
        data = service.set_default(
            workflow_key=support._read_argument(arguments, "workflow_key"),
            stage=support._read_optional_argument(arguments, "stage"),
        )
        return {"ok": True, "action": "workflow.set_default", "data": data}
    finally:
        session.close()


PROVIDER_ACTION_HANDLERS = {
    "provider.create": handle_provider_create,
    "provider.list": handle_provider_list,
    "provider.inspect": handle_provider_inspect,
    "provider.health_check": handle_provider_health_check,
    "profile.create": handle_profile_create,
    "profile.list": handle_profile_list,
    "profile.inspect": handle_profile_inspect,
    "profile.set_fallbacks": handle_profile_set_fallbacks,
    "workflow.create": handle_workflow_create,
    "workflow.list": handle_workflow_list,
    "workflow.inspect": handle_workflow_inspect,
    "workflow.set_default": handle_workflow_set_default,
}
