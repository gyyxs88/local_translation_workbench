from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

import yaml

from ..errors import ToolError

_PROJECT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")


def normalize_project_key(value: str) -> str:
    normalized = str(value).strip().lower()
    if not _PROJECT_KEY_RE.fullmatch(normalized):
        raise ToolError(
            code="invalid_arguments",
            message="project_key 只能使用 3-64 位小写字母、数字、下划线或连字符，且不能包含路径分隔符。",
            status=400,
        )
    return normalized


def ensure_within_root(root: Path, path: Path) -> Path:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise ToolError(code="invalid_arguments", message=f"路径越过项目根目录: {path}", status=400)
    return resolved_path


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ToolError(code="not_found", message=f"文件不可读: {path}", status=404) from exc


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ToolError(code="invalid_state", message=f"YAML 必须是对象: {path}", status=409)
    return payload


def write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )


def append_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")
