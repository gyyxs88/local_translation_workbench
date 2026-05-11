from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import load_config
from .db.engine import get_session_factory
from .errors import ToolError
from .services.stage_service import STAGE_SEQUENCE
from .services.workflow_profile_service import WorkflowProfileService
from .text_counting import build_text_count_payload


def _bootstrap_workflow_profiles(session) -> None:
    service = WorkflowProfileService(session)
    if service.ensure_builtin_profiles():
        session.commit()


def _open_session():
    config = load_config()
    session_factory = get_session_factory(_require_database_url(config.database_url))
    return session_factory()


def _require_argument(arguments: dict[str, str], key: str) -> str:
    value = _read_optional_argument(arguments, key)
    if value is None or value == "":
        raise ToolError(code="invalid_arguments", message=f"缺少必填参数 {key}。", status=400)
    return value


def _read_argument(arguments: dict[str, str], key: str) -> str:
    value = _read_optional_argument(arguments, key)
    if value is None or value == "":
        raise ToolError(code="invalid_arguments", message=f"缺少必填参数 {key}。", status=400)
    return value


def _read_optional_argument(arguments: dict[str, str], key: str) -> str | None:
    compact_key = key.replace("_", "")
    for candidate in (key, compact_key):
        value = arguments.get(candidate)
        if value is not None:
            return _read_inline_or_file_value(value, argument_name=key)
    for candidate in (f"{key}_file", f"{compact_key}file"):
        value = arguments.get(candidate)
        if value is not None:
            return _read_argument_file(value, argument_name=f"{key}_file")
    return None


def _read_inline_or_file_value(value: str, *, argument_name: str) -> str:
    if not isinstance(value, str) or not value.startswith("@"):
        return value
    file_ref = value[1:].strip()
    if not file_ref:
        raise ToolError(code="invalid_arguments", message=f"{argument_name} 的 @file 路径不能为空。", status=400)
    path = Path(file_ref).expanduser()
    if not path.exists():
        return value
    return _read_text_file(path, argument_name=argument_name)


def _read_argument_file(value: str, *, argument_name: str) -> str:
    file_ref = str(value).strip()
    if not file_ref:
        raise ToolError(code="invalid_arguments", message=f"{argument_name} 路径不能为空。", status=400)
    path = Path(file_ref).expanduser()
    if not path.exists():
        raise ToolError(code="invalid_arguments", message=f"{argument_name} 文件不存在: {file_ref}", status=400)
    return _read_text_file(path, argument_name=argument_name)


def _read_text_file(path: Path, *, argument_name: str) -> str:
    if not path.is_file():
        raise ToolError(code="invalid_arguments", message=f"{argument_name} 不是文件: {path}", status=400)
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ToolError(code="invalid_arguments", message=f"{argument_name} 文件读取失败: {path}", status=400) from exc


def _parse_json_argument(value: str | dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise ToolError(code="invalid_arguments", message="definition_json 不是有效的 JSON。", status=400) from exc
    if not isinstance(parsed, dict):
        raise ToolError(code="invalid_arguments", message="definition_json 必须是对象。", status=400)
    return parsed


def _parse_json_list_argument(value: str | list[Any] | None, *, argument_name: str) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    normalized = value.strip()
    if not normalized:
        return []
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise ToolError(
            code="invalid_arguments",
            message=f"{argument_name} 不是有效的 JSON。",
            status=400,
        ) from exc
    if not isinstance(parsed, list):
        raise ToolError(
            code="invalid_arguments",
            message=f"{argument_name} 必须是数组。",
            status=400,
        )
    return parsed


def _parse_json_string_list_argument(value: str | None) -> list[str]:
    if value is None:
        return []
    normalized = value.strip()
    if not normalized:
        return []
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise ToolError(code="invalid_arguments", message="fallback_profile_keys_json 不是有效的 JSON。", status=400) from exc
    if not isinstance(parsed, list):
        raise ToolError(code="invalid_arguments", message="fallback_profile_keys_json 必须是字符串数组。", status=400)
    result: list[str] = []
    for item in parsed:
        if not isinstance(item, str):
            raise ToolError(code="invalid_arguments", message="fallback_profile_keys_json 必须是字符串数组。", status=400)
        result.append(item)
    return result


def _require_database_url(database_url: str | None) -> str:
    if database_url:
        return database_url
    raise ToolError(code="invalid_arguments", message="缺少 LTW_DATABASE_URL。", status=400)


def _count_rows(session, statement) -> int:
    return int(session.execute(statement).scalar_one())


def _build_synopsis_summary(synopsis: Any | None) -> dict[str, dict[str, Any]]:
    if synopsis is None:
        return {
            "source": {"status": "missing", "origin": None, **build_text_count_payload(None)},
            "target": {"status": "missing", "origin": None, **build_text_count_payload(None)},
        }
    return {
        "source": {
            "status": synopsis.source_synopsis_status,
            "origin": synopsis.source_synopsis_origin if synopsis.source_synopsis_origin is not None else None,
            **build_text_count_payload(synopsis.source_synopsis_text),
        },
        "target": {
            "status": synopsis.target_synopsis_status,
            "origin": synopsis.target_synopsis_origin if synopsis.target_synopsis_origin is not None else None,
            **build_text_count_payload(synopsis.target_synopsis_text),
        },
    }


def _parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() not in {"", "false", "0", "no"}


def _parse_optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    return _parse_int_value(value, argument_name="参数")


def _parse_required_int_argument(arguments: dict[str, str], key: str) -> int:
    return _parse_int_value(_require_argument(arguments, key), argument_name=key)


def _parse_int_value(value: object, *, argument_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ToolError(
            code="invalid_arguments",
            message=f"{argument_name} 必须是整数。",
            status=400,
        ) from exc


def _resolve_stage_window(*, from_stage: str | None, until_stage: str | None) -> tuple[str, ...]:
    start_index = 0
    end_index = len(STAGE_SEQUENCE) - 1

    if from_stage is not None:
        normalized_from_stage = from_stage.strip().lower()
        if normalized_from_stage not in STAGE_SEQUENCE:
            raise ToolError(code="invalid_arguments", message=f"不支持的 from_stage: {from_stage}", status=400)
        start_index = STAGE_SEQUENCE.index(normalized_from_stage)

    if until_stage is not None:
        normalized_until_stage = until_stage.strip().lower()
        if normalized_until_stage not in STAGE_SEQUENCE:
            raise ToolError(code="invalid_arguments", message=f"不支持的 until_stage: {until_stage}", status=400)
        end_index = STAGE_SEQUENCE.index(normalized_until_stage)

    if start_index > end_index:
        raise ToolError(code="invalid_arguments", message="from_stage 不能晚于 until_stage。", status=400)

    return STAGE_SEQUENCE[start_index : end_index + 1]


def _summarize_stage_result(stage_name: str, result: Any) -> dict[str, Any]:
    if stage_name == "chaptering":
        return {
            "chapter_count": result.chapter_count,
            "segment_count": result.segment_count,
        }
    if stage_name == "glossary":
        return {"candidate_count": result.candidate_count}
    if stage_name == "translation":
        return {
            "translated_segments": result.translated_segments,
            "active_version_ids": result.active_version_ids,
        }
    if stage_name == "review":
        return {
            "issue_count": result.issue_count,
            "run_id": result.run_id,
        }
    return {
        "artifact_count": result.artifact_count,
        "manifest_path": result.manifest_path,
        "run_id": result.run_id,
    }
