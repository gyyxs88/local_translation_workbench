from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GlossaryExtraction:
    source_term: str
    suggested_term: str
    category: str
    note: str | None
    term_group_key: str
    relation_role: str
    gender: str | None
    age_group: str | None
