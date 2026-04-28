from __future__ import annotations

import hashlib
import re
from pathlib import Path
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..db.models import ProjectSynopsis
from ..db.models import TranslationProject
from ..errors import ToolError
from ..providers.base import Provider, TextGenerationResult
from ..repositories.synopsis import ProjectSynopsisRepository
from ..token_usage import summarize_generation_results
from ..utils import normalize_newlines


@dataclass(frozen=True)
class SynopsisExtractionResult:
    content_without_synopsis: str
    synopsis_text: str | None


class SynopsisService:
    _synopsis_heading_pattern = re.compile(r"^##\s+(简介|内容简介|Synopsis|Summary)\s*$", re.IGNORECASE)
    _inline_synopsis_pattern = re.compile(r"^(简介|内容简介|Synopsis|Summary)\s*[:：]\s*(?P<text>.*)$", re.IGNORECASE)
    _boundary_pattern = re.compile(r"^(?:#{1,6}\s+\S|第\d+(?:章|回|节)(?:\s+.*)?$)")
    _chapter_boundary_pattern = re.compile(
        r"^第(?:\d+|[一二三四五六七八九十百千万〇零两]+)(?:章|回|节)(?:\s+.*)?$"
    )
    _volume_heading_pattern = re.compile(
        r"^第(?:\d+|[一二三四五六七八九十百千万〇零两]+)(?:卷|部|篇)(?:\s+.*)?$"
    )

    def __init__(self, session: Session) -> None:
        self.session = session
        self.synopses = ProjectSynopsisRepository(session)
        self._generation_results: list[TextGenerationResult] = []

    def build_summary(self, synopsis: ProjectSynopsis | None) -> dict[str, dict[str, object]]:
        if synopsis is None:
            return {
                "source": {"status": "missing", "origin": None, "length": 0},
                "target": {"status": "missing", "origin": None, "length": 0},
            }

        return {
            "source": {
                "status": synopsis.source_synopsis_status,
                "origin": synopsis.source_synopsis_origin if synopsis.source_synopsis_origin is not None else None,
                "length": len(synopsis.source_synopsis_text or ""),
            },
            "target": {
                "status": synopsis.target_synopsis_status,
                "origin": synopsis.target_synopsis_origin if synopsis.target_synopsis_origin is not None else None,
                "length": len(synopsis.target_synopsis_text or ""),
            },
        }

    def inspect(self, *, project_id: int) -> dict[str, object]:
        synopsis = self.synopses.get_by_project_id(project_id)
        if synopsis is None:
            return self._build_empty_inspect_payload(project_id=project_id)
        return self._build_inspect_payload(project_id=project_id, synopsis=synopsis)

    def ensure_project_synopsis(
        self,
        *,
        project_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
        provider: Provider,
    ) -> ProjectSynopsis:
        project = self.session.get(TranslationProject, project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        synopsis = self.synopses.ensure(project_id)
        actual_model_name = provider_model_name or model_profile_id

        if not self._has_ready_source_synopsis(synopsis):
            source_path = Path(project.source_path)
            if not source_path.is_file():
                raise ToolError(code="file_not_found", message=f"找不到项目源文件: {source_path}", status=404)

            source_text = source_path.read_text(encoding="utf-8")
            source_synopsis = self._generate_source_synopsis(
                source_text=source_text,
                source_language=project.source_language,
                model_name=actual_model_name,
                provider=provider,
            )
            self._generation_results.append(source_synopsis)
            self._apply_source_synopsis(
                synopsis=synopsis,
                source_synopsis=source_synopsis,
                model_profile_id=model_profile_id,
            )

        if self._needs_target_synopsis(synopsis):
            target_synopsis = self._translate_target_synopsis(
                source_synopsis_text=synopsis.source_synopsis_text or "",
                source_language=project.source_language,
                target_language=project.target_language,
                model_name=actual_model_name,
                provider=provider,
            )
            self._generation_results.append(target_synopsis)
            self._apply_target_synopsis(
                synopsis=synopsis,
                target_synopsis=target_synopsis,
                model_profile_id=model_profile_id,
            )

        self.session.flush()
        return synopsis

    def reset_generation_tracking(self) -> None:
        self._generation_results = []

    def build_generation_metadata(self) -> dict[str, object]:
        token_usage = summarize_generation_results(self._generation_results)
        if token_usage is None:
            return {}
        return {"token_usage": token_usage}

    def extract_explicit_synopsis(self, content: str) -> SynopsisExtractionResult:
        normalized_content = normalize_newlines(content).lstrip("\ufeff")
        lines = normalized_content.split("\n")
        heading_index = self._find_synopsis_heading_index(lines)
        if heading_index is None:
            inline_result = self._extract_inline_synopsis(lines)
            if inline_result is not None:
                return inline_result
            return SynopsisExtractionResult(content_without_synopsis=normalized_content, synopsis_text=None)

        boundary_index = self._find_synopsis_boundary_index(lines, heading_index)
        if boundary_index is None:
            return SynopsisExtractionResult(
                content_without_synopsis=normalized_content,
                synopsis_text=None,
            )

        synopsis_text = "\n".join(lines[heading_index + 1 : boundary_index]).strip("\n")
        if not synopsis_text.strip():
            return SynopsisExtractionResult(
                content_without_synopsis=normalized_content,
                synopsis_text=None,
            )

        cleaned_lines = lines[:heading_index] + lines[boundary_index:]
        return SynopsisExtractionResult(
            content_without_synopsis="\n".join(cleaned_lines),
            synopsis_text=synopsis_text,
        )

    def _extract_inline_synopsis(self, lines: list[str]) -> SynopsisExtractionResult | None:
        first_chapter_index = self._find_first_chapter_boundary_index(lines, start_index=0)
        for index, raw_line in enumerate(lines):
            if first_chapter_index is not None and index >= first_chapter_index:
                return None

            match = self._inline_synopsis_pattern.match(raw_line.strip())
            if match is None:
                continue

            synopsis_lines: list[str] = []
            first_line = match.group("text").strip()
            if first_line:
                synopsis_lines.append(first_line)

            scan_index = index + 1
            while scan_index < len(lines):
                stripped_line = lines[scan_index].strip()
                if stripped_line == "":
                    scan_index += 1
                    break
                if self._is_chapter_boundary(stripped_line) or self._volume_heading_pattern.match(stripped_line):
                    break
                synopsis_lines.append(lines[scan_index])
                scan_index += 1

            synopsis_text = "\n".join(synopsis_lines).strip("\n")
            if not synopsis_text.strip():
                return None

            boundary_index = self._find_first_chapter_boundary_index(lines, start_index=scan_index)
            content_lines = [] if boundary_index is None else lines[boundary_index:]
            return SynopsisExtractionResult(
                content_without_synopsis="\n".join(content_lines),
                synopsis_text=synopsis_text,
            )
        return None

    def apply_extracted_synopsis(
        self,
        *,
        project_id: int,
        synopsis_text: str | None,
    ) -> ProjectSynopsis:
        synopsis = self.synopses.ensure(project_id)
        if synopsis_text is None:
            if synopsis.source_synopsis_origin == "extracted":
                synopsis.source_synopsis_text = None
                synopsis.source_synopsis_status = "missing"
                synopsis.source_synopsis_origin = None
                synopsis.source_synopsis_hash = None
                synopsis.source_synopsis_model_profile_id = None
                synopsis.source_synopsis_provider_name = None
                synopsis.source_synopsis_model_name = None
            elif synopsis.source_synopsis_origin == "generated" and synopsis.source_synopsis_text is not None:
                synopsis.source_synopsis_status = "stale"
                if synopsis.target_synopsis_text is not None and synopsis.target_synopsis_origin != "manual":
                    synopsis.target_synopsis_status = "stale"
            if synopsis.target_synopsis_text and synopsis.target_synopsis_origin not in {"generated", "manual"}:
                synopsis.target_synopsis_status = "stale"
            self.session.flush()
            return synopsis

        normalized_synopsis_text = normalize_newlines(synopsis_text)
        synopsis_hash = hashlib.sha256(normalized_synopsis_text.encode("utf-8")).hexdigest()
        existing_source_hash = synopsis.source_synopsis_hash
        if existing_source_hash is None and synopsis.source_synopsis_text is not None:
            existing_source_hash = hashlib.sha256(
                normalize_newlines(synopsis.source_synopsis_text).encode("utf-8")
            ).hexdigest()
        source_changed = existing_source_hash != synopsis_hash

        synopsis.source_synopsis_text = synopsis_text
        synopsis.source_synopsis_status = "ready"
        synopsis.source_synopsis_origin = "extracted"
        synopsis.source_synopsis_hash = synopsis_hash
        synopsis.source_synopsis_model_profile_id = None
        synopsis.source_synopsis_provider_name = None
        synopsis.source_synopsis_model_name = None
        if source_changed and synopsis.target_synopsis_status != "missing" and synopsis.target_synopsis_origin != "manual":
            synopsis.target_synopsis_status = "stale"
        self.session.flush()
        return synopsis

    def _find_synopsis_heading_index(self, lines: list[str]) -> int | None:
        for index, raw_line in enumerate(lines):
            if self._synopsis_heading_pattern.match(raw_line.strip()):
                return index
        return None

    def _find_synopsis_boundary_index(self, lines: list[str], heading_index: int) -> int | None:
        for index in range(heading_index + 1, len(lines)):
            stripped_line = lines[index].strip()
            if stripped_line and self._boundary_pattern.match(stripped_line):
                return index

        trailing_lines = lines[heading_index + 1 :]
        if any(line.strip() for line in trailing_lines):
            return len(lines)
        if trailing_lines:
            return len(lines)
        return None

    def _find_first_chapter_boundary_index(self, lines: list[str], *, start_index: int) -> int | None:
        for index in range(start_index, len(lines)):
            if self._is_chapter_boundary(lines[index].strip()):
                return index
        return None

    def _is_chapter_boundary(self, stripped_line: str) -> bool:
        return bool(self._chapter_boundary_pattern.match(stripped_line))

    def _generate_source_synopsis(
        self,
        *,
        source_text: str,
        source_language: str,
        model_name: str,
        provider: Provider,
    ) -> TextGenerationResult:
        prompt = (
            "你是一个摘要引擎。请根据以下整部作品正文生成 source synopsis。\n"
            f"源语言: {source_language}\n"
            "只返回简介正文，不要解释。\n\n"
            f"{normalize_newlines(source_text)}"
        )
        return provider.generate_text(
            prompt=prompt,
            model_name=model_name,
            timeout_seconds=60,
        )

    def _translate_target_synopsis(
        self,
        *,
        source_synopsis_text: str,
        source_language: str,
        target_language: str,
        model_name: str,
        provider: Provider,
    ) -> TextGenerationResult:
        prompt = (
            "你是一个翻译引擎。请翻译 target synopsis，把 source synopsis 翻译成目标语言。\n"
            f"源语言: {source_language}\n"
            f"目标语言: {target_language}\n"
            "只返回译文，不要解释。\n\n"
            f"{normalize_newlines(source_synopsis_text)}"
        )
        return provider.generate_text(
            prompt=prompt,
            model_name=model_name,
            timeout_seconds=60,
        )

    def _apply_source_synopsis(
        self,
        *,
        synopsis: ProjectSynopsis,
        source_synopsis: TextGenerationResult,
        model_profile_id: str,
    ) -> None:
        normalized_text = normalize_newlines(source_synopsis.content)
        synopsis.source_synopsis_text = source_synopsis.content
        synopsis.source_synopsis_status = "ready"
        synopsis.source_synopsis_origin = "generated"
        synopsis.source_synopsis_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
        synopsis.source_synopsis_model_profile_id = source_synopsis.model_profile_id or model_profile_id
        synopsis.source_synopsis_provider_name = source_synopsis.provider_name
        synopsis.source_synopsis_model_name = source_synopsis.model_name

    def _apply_target_synopsis(
        self,
        *,
        synopsis: ProjectSynopsis,
        target_synopsis: TextGenerationResult,
        model_profile_id: str,
    ) -> None:
        normalized_text = normalize_newlines(target_synopsis.content)
        synopsis.target_synopsis_text = target_synopsis.content
        synopsis.target_synopsis_status = "ready"
        synopsis.target_synopsis_origin = "translated"
        synopsis.target_synopsis_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
        synopsis.target_synopsis_model_profile_id = target_synopsis.model_profile_id or model_profile_id
        synopsis.target_synopsis_provider_name = target_synopsis.provider_name
        synopsis.target_synopsis_model_name = target_synopsis.model_name

    def _has_ready_source_synopsis(self, synopsis: ProjectSynopsis) -> bool:
        return synopsis.source_synopsis_status == "ready" and synopsis.source_synopsis_text is not None

    def _needs_target_synopsis(self, synopsis: ProjectSynopsis) -> bool:
        return synopsis.target_synopsis_status in {"missing", "stale"}

    def _build_empty_inspect_payload(self, *, project_id: int) -> dict[str, object]:
        return {
            "project_id": project_id,
            "source_synopsis_text": None,
            "source_synopsis_status": "missing",
            "source_synopsis_origin": None,
            "source_synopsis_hash": None,
            "source_synopsis_model_profile_id": None,
            "source_synopsis_provider_name": None,
            "source_synopsis_model_name": None,
            "target_synopsis_text": None,
            "target_synopsis_status": "missing",
            "target_synopsis_origin": None,
            "target_synopsis_hash": None,
            "target_synopsis_model_profile_id": None,
            "target_synopsis_provider_name": None,
            "target_synopsis_model_name": None,
        }

    def _build_inspect_payload(self, *, project_id: int, synopsis: ProjectSynopsis) -> dict[str, object]:
        return {
            "project_id": project_id,
            "source_synopsis_text": synopsis.source_synopsis_text,
            "source_synopsis_status": synopsis.source_synopsis_status,
            "source_synopsis_origin": synopsis.source_synopsis_origin,
            "source_synopsis_hash": synopsis.source_synopsis_hash,
            "source_synopsis_model_profile_id": synopsis.source_synopsis_model_profile_id,
            "source_synopsis_provider_name": synopsis.source_synopsis_provider_name,
            "source_synopsis_model_name": synopsis.source_synopsis_model_name,
            "target_synopsis_text": synopsis.target_synopsis_text,
            "target_synopsis_status": synopsis.target_synopsis_status,
            "target_synopsis_origin": synopsis.target_synopsis_origin,
            "target_synopsis_hash": synopsis.target_synopsis_hash,
            "target_synopsis_model_profile_id": synopsis.target_synopsis_model_profile_id,
            "target_synopsis_provider_name": synopsis.target_synopsis_provider_name,
            "target_synopsis_model_name": synopsis.target_synopsis_model_name,
        }
