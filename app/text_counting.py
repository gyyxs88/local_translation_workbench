from __future__ import annotations

import re

_CJK_PATTERN = re.compile(
    "["
    "\u3040-\u30ff"
    "\u3400-\u4dbf"
    "\u4e00-\u9fff"
    "\uf900-\ufaff"
    "\uac00-\ud7af"
    "]"
)
_NON_WHITESPACE_PATTERN = re.compile(r"\S")
_WORD_PATTERN = re.compile(r"[^\W_]+(?:['’][^\W_]+)?(?:-[^\W_]+)*", re.UNICODE)


def count_text_units(text: str | None) -> int:
    normalized_text = text or ""
    if _contains_cjk(normalized_text):
        return len(_NON_WHITESPACE_PATTERN.findall(normalized_text))
    return len(_WORD_PATTERN.findall(normalized_text))


def text_count_unit(text: str | None) -> str:
    normalized_text = text or ""
    if normalized_text.strip() == "":
        return "characters"
    if _contains_cjk(normalized_text):
        return "characters"
    return "words"


def build_text_count_payload(text: str | None) -> dict[str, object]:
    return {
        "length": count_text_units(text),
        "length_unit": text_count_unit(text),
    }


def _contains_cjk(text: str) -> bool:
    return bool(_CJK_PATTERN.search(text))
