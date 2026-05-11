from __future__ import annotations

import re
from dataclasses import dataclass

from ..utils import normalize_newlines


@dataclass(frozen=True)
class SegmentShard:
    segment_index: int
    source_text: str


class SegmentShardingService:
    TARGET_CHARS = 2500
    HARD_MAX_CHARS = 4000
    SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[。！？；!?;])")

    def build_segments(self, *, body_source_text: str) -> list[SegmentShard]:
        normalized_text = normalize_newlines(body_source_text).strip()
        if not normalized_text:
            return []

        paragraphs = [
            item.strip()
            for item in re.split(r"\n\s*\n+", normalized_text)
            if item.strip()
        ]

        segment_texts: list[str] = []
        buffer: list[str] = []
        buffer_length = 0

        for paragraph in paragraphs:
            paragraph_chunks = (
                [paragraph]
                if len(paragraph) <= self.HARD_MAX_CHARS
                else self._split_oversized_paragraph(paragraph)
            )
            for chunk in paragraph_chunks:
                separator_length = 2 if buffer else 0
                proposed_length = buffer_length + separator_length + len(chunk)
                if buffer and proposed_length > self.TARGET_CHARS:
                    segment_texts.append("\n\n".join(buffer))
                    buffer = [chunk]
                    buffer_length = len(chunk)
                    continue
                buffer.append(chunk)
                buffer_length = proposed_length

        if buffer:
            segment_texts.append("\n\n".join(buffer))

        return [
            SegmentShard(segment_index=index, source_text=text)
            for index, text in enumerate(segment_texts, start=1)
        ]

    def _split_oversized_paragraph(self, paragraph: str) -> list[str]:
        sentences = [
            item.strip()
            for item in self.SENTENCE_BOUNDARY_PATTERN.split(paragraph)
            if item.strip()
        ]
        if len(sentences) <= 1:
            return self._hard_split(paragraph)

        result: list[str] = []
        buffer = ""
        for sentence in sentences:
            proposed = sentence if not buffer else f"{buffer}{sentence}"
            if buffer and len(proposed) > self.TARGET_CHARS:
                result.append(buffer.strip())
                buffer = sentence
                continue
            buffer = proposed

        if buffer:
            result.append(buffer.strip())

        flattened: list[str] = []
        for item in result:
            if len(item) <= self.HARD_MAX_CHARS:
                flattened.append(item)
                continue
            flattened.extend(self._hard_split(item))
        return flattened

    def _hard_split(self, text: str) -> list[str]:
        return [
            chunk.strip()
            for chunk in (
                text[index : index + self.HARD_MAX_CHARS]
                for index in range(0, len(text), self.HARD_MAX_CHARS)
            )
            if chunk.strip()
        ]
