from __future__ import annotations

import json
from typing import Any

from .. import action_support as support
from ..editorial_runtime.config import default_editorial_home
from ..editorial_runtime.service import EditorialRuntimeService
from ..errors import ToolError


def _service() -> EditorialRuntimeService:
    return EditorialRuntimeService(default_editorial_home())


def _parse_json_list(value: str | None, *, argument_name: str) -> list[dict[str, Any]]:
    if value is None or not value.strip():
        return []
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ToolError(code="invalid_arguments", message=f"{argument_name} 不是有效 JSON。", status=400) from exc
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ToolError(code="invalid_arguments", message=f"{argument_name} 必须是对象数组。", status=400)
    return payload


def handle_project_init_editorial(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().init_project(
        project_key=support._require_argument(arguments, "project_key"),
        title=support._require_argument(arguments, "title"),
        source_language=support._require_argument(arguments, "source_language"),
        target_language=support._require_argument(arguments, "target_language"),
    )
    return {"ok": True, "action": "project.init_editorial", "data": data}


def handle_source_prepare(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().prepare_source(
        project_key=support._require_argument(arguments, "project_key"),
        synopsis=support._read_optional_argument(arguments, "synopsis") or "",
        chapters=_parse_json_list(
            support._require_argument(arguments, "chapters_json"),
            argument_name="chapters_json",
        ),
    )
    return {"ok": True, "action": "source.prepare", "data": data}


def handle_chapter_assign(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().assign_chapter(
        project_key=support._require_argument(arguments, "project_key"),
        chapter_key=support._require_argument(arguments, "chapter_key"),
        brief=support._read_optional_argument(arguments, "brief") or "",
    )
    return {"ok": True, "action": "chapter.assign", "data": data}


def handle_terms_prepare_pack(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().prepare_term_pack(
        project_key=support._require_argument(arguments, "project_key"),
        chapter_key=support._require_argument(arguments, "chapter_key"),
        terms=_parse_json_list(
            support._read_optional_argument(arguments, "terms_json"),
            argument_name="terms_json",
        ),
    )
    return {"ok": True, "action": "terms.prepare_pack", "data": data}


def handle_chapter_translate_raw(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().write_raw(
        project_key=support._require_argument(arguments, "project_key"),
        chapter_key=support._require_argument(arguments, "chapter_key"),
        content=support._require_argument(arguments, "content"),
        note=support._read_optional_argument(arguments, "note") or "",
    )
    return {"ok": True, "action": "chapter.translate_raw", "data": data}


def handle_chapter_review_bilingual(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().write_bilingual_review(
        project_key=support._require_argument(arguments, "project_key"),
        chapter_key=support._require_argument(arguments, "chapter_key"),
        content=support._require_argument(arguments, "content"),
        needs_annotation=support._parse_bool(support._read_optional_argument(arguments, "needs_annotation")),
    )
    return {"ok": True, "action": "chapter.review_bilingual", "data": data}


def handle_review_adjudicate(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().adjudicate_review(
        project_key=support._require_argument(arguments, "project_key"),
        chapter_key=support._require_argument(arguments, "chapter_key"),
        decision=support._require_argument(arguments, "decision"),
        content=support._require_argument(arguments, "content"),
    )
    return {"ok": True, "action": "review.adjudicate", "data": data}


def handle_chapter_revise(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().write_revision(
        project_key=support._require_argument(arguments, "project_key"),
        chapter_key=support._require_argument(arguments, "chapter_key"),
        content=support._require_argument(arguments, "content"),
        annotations=_parse_json_list(
            support._read_optional_argument(arguments, "annotations_json"),
            argument_name="annotations_json",
        ),
    )
    return {"ok": True, "action": "chapter.revise", "data": data}


def handle_chapter_accept(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().accept_chapter(
        project_key=support._require_argument(arguments, "project_key"),
        chapter_key=support._require_argument(arguments, "chapter_key"),
        note=support._read_optional_argument(arguments, "note") or "",
    )
    return {"ok": True, "action": "chapter.accept", "data": data}


def handle_memory_derive_from_accepted(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().derive_memory_from_accepted(project_key=support._require_argument(arguments, "project_key"))
    return {"ok": True, "action": "memory.derive_from_accepted", "data": data}


def handle_export_build(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().build_export(project_key=support._require_argument(arguments, "project_key"))
    return {"ok": True, "action": "export.build", "data": data}


def handle_cache_rebuild(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().rebuild_cache(project_key=support._require_argument(arguments, "project_key"))
    return {"ok": True, "action": "cache.rebuild", "data": data}


def handle_inspect_status(arguments: dict[str, str]) -> dict[str, Any]:
    data = _service().inspect_status(project_key=support._require_argument(arguments, "project_key"))
    return {"ok": True, "action": "inspect.status", "data": data}


EDITORIAL_RUNTIME_ACTION_HANDLERS = {
    "project.init_editorial": handle_project_init_editorial,
    "source.prepare": handle_source_prepare,
    "chapter.assign": handle_chapter_assign,
    "terms.prepare_pack": handle_terms_prepare_pack,
    "chapter.translate_raw": handle_chapter_translate_raw,
    "chapter.review_bilingual": handle_chapter_review_bilingual,
    "review.adjudicate": handle_review_adjudicate,
    "chapter.revise": handle_chapter_revise,
    "chapter.accept": handle_chapter_accept,
    "memory.derive_from_accepted": handle_memory_derive_from_accepted,
    "export.build": handle_export_build,
    "cache.rebuild": handle_cache_rebuild,
    "inspect.status": handle_inspect_status,
}
