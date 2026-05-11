from __future__ import annotations

import json

from json_repair import loads as repair_json_loads


def strip_json_code_fence(content: str) -> str:
    stripped = content.strip()
    fenced_block = _extract_fenced_block(stripped)
    if fenced_block is not None:
        return fenced_block.strip()
    return stripped


def load_json_payload(content: str) -> object:
    normalized = strip_json_code_fence(content)
    try:
        return json.loads(normalized)
    except json.JSONDecodeError as first_error:
        decoder = json.JSONDecoder()
        for start_index in _json_start_indexes(normalized):
            candidate = normalized[start_index:].lstrip()
            try:
                payload, _ = decoder.raw_decode(candidate)
            except json.JSONDecodeError:
                continue
            return payload
        if _has_unclosed_json_container(normalized):
            raise first_error
        try:
            return repair_json_loads(normalized)
        except Exception:
            pass
        raise first_error


def _extract_fenced_block(content: str) -> str | None:
    lines = content.splitlines()
    start_index = None
    for index, line in enumerate(lines):
        if line.strip().startswith("```"):
            start_index = index + 1
            break
    if start_index is None:
        return None
    end_index = len(lines)
    for index in range(start_index, len(lines)):
        if lines[index].strip() == "```":
            end_index = index
            break
    return "\n".join(lines[start_index:end_index])


def _json_start_indexes(content: str) -> list[int]:
    return [index for index, char in enumerate(content) if char in {"{", "["}]


def _has_unclosed_json_container(content: str) -> bool:
    stack: list[str] = []
    in_string = False
    escaped = False
    for char in content:
        if in_string:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char in {"{", "["}:
            stack.append(char)
            continue
        if char == "}":
            if stack and stack[-1] == "{":
                stack.pop()
            continue
        if char == "]":
            if stack and stack[-1] == "[":
                stack.pop()
    return in_string or bool(stack)
