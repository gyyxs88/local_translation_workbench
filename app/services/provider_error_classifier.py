from __future__ import annotations

import json
from collections.abc import Mapping


def classify_provider_error(
    *,
    code: str | None,
    message: str | None,
    details: object | None = None,
) -> str:
    text = _build_error_text(code=code, message=message, details=details)
    normalized_code = (code or "").strip().lower()

    if _contains_any(text, ("content policy", "policy violation", "safety", "blocked", "敏感", "安全策略")):
        return "policy_block"
    if normalized_code == "rate_limit" or _contains_any(
        text,
        ("rate limit", "too many requests", "429", "quota exceeded", "insufficient_quota", "capacity"),
    ):
        return "rate_limit"
    if normalized_code == "timeout" or _contains_any(text, ("timeout", "timed out", "deadline exceeded", "超时")):
        return "timeout"
    if _contains_any(text, ("jsondecodeerror", "json parse", "invalid json", "无法解析", "不是有效的 json")):
        return "json_parse_failed"
    if _contains_any(text, ("empty response", "empty content", "未返回有效译文", "空响应")):
        return "empty_response"
    if _contains_any(
        text,
        ("api_key", "api key", "unauthorized", "invalid key", "invalid_api_key", "401", "403", "forbidden"),
    ):
        return "auth_error"
    if _contains_any(text, ("connection", "network", "ssl", "dns", "urlerror", "远端", "连接")):
        return "network_error"
    if _contains_any(text, ("500", "502", "503", "504", "server error", "bad gateway", "service unavailable")):
        return "server_error"
    if normalized_code == "not_found":
        return "not_found"
    if normalized_code == "invalid_arguments":
        return "invalid_arguments"
    return "unknown"


def _build_error_text(*, code: str | None, message: str | None, details: object | None) -> str:
    parts = [code or "", message or ""]
    if isinstance(details, Mapping):
        try:
            parts.append(json.dumps(details, ensure_ascii=False, sort_keys=True))
        except TypeError:
            parts.append(str(details))
    elif details is not None:
        parts.append(str(details))
    return " ".join(parts).lower()


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)
