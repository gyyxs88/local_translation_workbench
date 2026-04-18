from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class GlossaryMatch:
    entry: object
    start: int
    end: int


class TranslationAssetsService:
    ROLE_PRIORITY = {
        "canonical": 0,
        "alias": 1,
        "title": 2,
        "variant": 3,
        "independent": 4,
    }

    def build_translation_prompt(
        self,
        *,
        source_language: str,
        target_language: str,
        chapter_index: int,
        segment_index: int,
        source_text: str,
        glossary_entries: list[object],
    ) -> str:
        prompt = (
            f"你是一个翻译引擎。请翻译正文，把{source_language}文本翻译成{target_language}。\n"
            f"章节: {chapter_index}\n"
            f"段落: {segment_index}\n"
            "只返回译文，不要解释。\n"
            "如果正文命中了术语表中的 source_term，译文必须优先使用该条目的 target_term。\n"
            "同组命中的多条表面形式必须分别按各自 source_term 对应 target_term 翻译，不能互换。\n"
            "不要把当前命中的 alias/title 改写成同组 canonical，反之亦然。\n"
            "同一术语在同一段落内不要出现多种译法。"
        )
        if glossary_entries:
            prompt += "\n术语表：\n" + self._render_glossary_groups(glossary_entries)
        return f"{prompt}\n\n{source_text}"

    def build_prompt_glossary_entries(
        self,
        *,
        glossary_entries: list[object],
        source_text: str,
    ) -> list[object]:
        matches = self._find_glossary_matches(
            glossary_entries=glossary_entries,
            source_text=source_text,
        )
        resolved = self._resolve_overlapping_matches(matches)
        unique_entries: dict[str, object] = {}
        for match in resolved:
            source_term = str(match.entry.source_term)
            if source_term not in unique_entries:
                unique_entries[source_term] = match.entry
        return list(unique_entries.values())

    def compute_glossary_snapshot_id(self, glossary_entries: list[object]) -> str:
        payload = json.dumps(
            [
                {
                    "source_term": entry.source_term,
                    "target_term": entry.target_term,
                    "category": entry.category,
                    "note": entry.note,
                    "gender": entry.gender,
                    "age_group": entry.age_group,
                    "status": entry.status,
                    "locked": entry.locked,
                    "term_group_key": entry.term_group_key,
                    "relation_role": entry.relation_role,
                }
                for entry in sorted(glossary_entries, key=lambda item: item.source_term)
            ],
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _find_glossary_matches(
        self,
        *,
        glossary_entries: list[object],
        source_text: str,
    ) -> list[GlossaryMatch]:
        matches: list[GlossaryMatch] = []
        for entry in glossary_entries:
            start = 0
            while True:
                index = source_text.find(entry.source_term, start)
                if index < 0:
                    break
                matches.append(
                    GlossaryMatch(
                        entry=entry,
                        start=index,
                        end=index + len(entry.source_term),
                    )
                )
                start = index + 1
        return matches

    def _resolve_overlapping_matches(self, matches: list[GlossaryMatch]) -> list[GlossaryMatch]:
        sorted_matches = sorted(
            matches,
            key=lambda item: (
                item.start,
                -(item.end - item.start),
                item.entry.source_term,
            ),
        )
        kept: list[GlossaryMatch] = []
        for match in sorted_matches:
            conflict_index = next(
                (
                    index
                    for index, existing in enumerate(kept)
                    if not (match.end <= existing.start or match.start >= existing.end)
                ),
                None,
            )
            if conflict_index is None:
                kept.append(match)
                continue
            existing = kept[conflict_index]
            if self._is_better_match(match, existing):
                kept[conflict_index] = match
        return sorted(kept, key=lambda item: (item.start, item.end, item.entry.source_term))

    def _is_better_match(self, candidate: GlossaryMatch, existing: GlossaryMatch) -> bool:
        candidate_length = candidate.end - candidate.start
        existing_length = existing.end - existing.start
        if candidate_length != existing_length:
            return candidate_length > existing_length
        if candidate.start != existing.start:
            return candidate.start < existing.start
        return candidate.entry.source_term < existing.entry.source_term

    def _format_glossary_entry(self, entry: object) -> str:
        note_suffix = f" | note: {entry.note}" if entry.note else ""
        category_suffix = f" | category: {entry.category}" if entry.category else ""
        gender_suffix = f" | gender: {entry.gender}" if entry.gender else ""
        age_group_suffix = f" | age_group: {entry.age_group}" if entry.age_group else ""
        return (
            f"- {entry.source_term} => {entry.target_term}"
            f" | role: {entry.relation_role}"
            f" | group: {entry.term_group_key}"
            f"{category_suffix}{gender_suffix}{age_group_suffix}{note_suffix}"
        )

    def _render_glossary_groups(self, glossary_entries: list[object]) -> str:
        grouped: dict[str, list[object]] = {}
        for entry in glossary_entries:
            grouped.setdefault(str(entry.term_group_key), []).append(entry)

        lines: list[str] = []
        for group_key, entries in grouped.items():
            lines.append(f"[group {group_key}]")
            for entry in sorted(
                entries,
                key=lambda item: (
                    int(self.ROLE_PRIORITY.get(str(item.relation_role), 99)),
                    str(item.source_term),
                ),
            ):
                lines.append(self._format_glossary_entry(entry))
            lines.append("")
        return "\n".join(lines).strip()
