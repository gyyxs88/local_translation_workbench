from __future__ import annotations

from collections.abc import Iterable, Mapping

TOKEN_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)
TOKEN_USAGE_COUNTER_FIELDS = (
    "call_count",
    "measured_call_count",
)


def normalize_token_usage_payload(value: object) -> dict[str, int] | None:
    if value is None:
        return None

    if hasattr(value, "to_payload") and callable(getattr(value, "to_payload")):
        value = value.to_payload()

    if not isinstance(value, Mapping):
        return None

    payload: dict[str, int] = {}
    for key in TOKEN_USAGE_FIELDS + TOKEN_USAGE_COUNTER_FIELDS:
        raw_value = value.get(key)
        if raw_value is None or raw_value == "":
            continue
        try:
            payload[key] = int(raw_value)
        except (TypeError, ValueError):
            continue

    if "total_tokens" not in payload and (
        "input_tokens" in payload or "output_tokens" in payload
    ):
        payload["total_tokens"] = payload.get("input_tokens", 0) + payload.get("output_tokens", 0)

    return payload or None


def summarize_generation_results(results: Iterable[object]) -> dict[str, int] | None:
    items = list(results)
    if not items:
        return None

    totals: dict[str, int] = {
        "call_count": len(items),
        "measured_call_count": 0,
    }
    for item in items:
        usage_payload = normalize_token_usage_payload(getattr(item, "usage", None))
        if usage_payload is None:
            continue
        totals["measured_call_count"] += 1
        for key in TOKEN_USAGE_FIELDS:
            if key in usage_payload:
                totals[key] = totals.get(key, 0) + int(usage_payload[key])

    return totals


def merge_token_usage_payloads(values: Iterable[object]) -> dict[str, int] | None:
    normalized_items = [
        payload
        for payload in (normalize_token_usage_payload(value) for value in values)
        if payload is not None
    ]
    if not normalized_items:
        return None

    totals: dict[str, int] = {}
    saw_counter = False
    for payload in normalized_items:
        for key in TOKEN_USAGE_FIELDS:
            if key in payload:
                totals[key] = totals.get(key, 0) + int(payload[key])
        for key in TOKEN_USAGE_COUNTER_FIELDS:
            if key in payload:
                totals[key] = totals.get(key, 0) + int(payload[key])
                saw_counter = True

    if "total_tokens" not in totals and (
        "input_tokens" in totals or "output_tokens" in totals
    ):
        totals["total_tokens"] = totals.get("input_tokens", 0) + totals.get("output_tokens", 0)

    if not saw_counter:
        totals.pop("call_count", None)
        totals.pop("measured_call_count", None)

    return totals or None
