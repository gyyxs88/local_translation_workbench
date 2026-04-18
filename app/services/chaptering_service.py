from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import ExportRun, ReviewRun, StageRun, TranslationProject
from ..errors import ToolError
from ..repositories.chapters import ChapterRepository
from .segment_sharding_service import SegmentShardingService
from .synopsis_service import SynopsisService
from .scope_service import ensure_scope_supported, get_stage_scope_types
from ..utils import ensure_directory, normalize_newlines


@dataclass(frozen=True)
class ChapteringResult:
    chapter_count: int
    segment_count: int
    synopsis_summary: dict[str, dict[str, object]] | None = None


class ChapteringService:
    def __init__(self, session: Session, *, base_data_dir: Path) -> None:
        self.session = session
        self.base_data_dir = Path(base_data_dir)
        self.chapters = ChapterRepository(session)
        self.synopsis = SynopsisService(session)
        self.segment_sharding = SegmentShardingService()

    def run(
        self,
        *,
        request_id: str,
        project_id: int,
        source_file_path: Path | None,
        scope: dict[str, object],
        stage_run_id: int | None = None,
        heartbeat: Callable[[], None] | None = None,
    ) -> ChapteringResult:
        project = self.session.get(TranslationProject, project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)
        ensure_scope_supported(scope, stage="chaptering", allowed_types=get_stage_scope_types("chaptering"))

        resolved_source_path = Path(source_file_path or project.source_path)
        if not resolved_source_path.is_file():
            raise ToolError(
                code="file_not_found",
                message=f"找不到章节源文件: {resolved_source_path}",
                status=404,
            )

        content = resolved_source_path.read_text(encoding="utf-8")
        synopsis_result = self.synopsis.extract_explicit_synopsis(content)
        synopsis_row = self.synopsis.apply_extracted_synopsis(
            project_id=project_id,
            synopsis_text=synopsis_result.synopsis_text,
        )
        synopsis_summary = self._build_synopsis_summary(synopsis_row)

        chapter_documents = self._split_into_chapters(synopsis_result.content_without_synopsis)
        project_root = ensure_directory(self.base_data_dir / project.project_key)
        chapter_dir = ensure_directory(project_root / "chapters")
        segment_dir = ensure_directory(project_root / "segments")

        self._mark_related_outputs_stale(project_id=project_id)
        self.chapters.delete_segments_for_project(project_id)
        self.chapters.delete_chapters_for_project(project_id)

        segment_total = 0
        for chapter_index, chapter_document in enumerate(chapter_documents, start=1):
            if heartbeat is not None:
                heartbeat()
            chapter_source_path = chapter_dir / f"{chapter_index:04d}_source.txt"
            chapter_normalized_path = chapter_dir / f"{chapter_index:04d}_normalized.txt"
            chapter_source_path.write_text(chapter_document["source_text"], encoding="utf-8")
            chapter_normalized_path.write_text(chapter_document["normalized_text"], encoding="utf-8")

            chapter_row = self.chapters.create_chapter(
                project_id=project_id,
                chapter_index=chapter_index,
                chapter_title=chapter_document["chapter_title"],
                source_path=str(chapter_source_path),
                normalized_path=str(chapter_normalized_path),
                stage_status="ready",
            )

            shards = self.segment_sharding.build_segments(
                body_source_text=chapter_document["body_source_text"],
            )
            for shard in shards:
                segment_path = segment_dir / f"{chapter_index:04d}_{shard.segment_index:04d}_source.txt"
                segment_path.write_text(shard.source_text, encoding="utf-8")
                self.chapters.create_segment(
                    project_id=project_id,
                    chapter_id=chapter_row.id,
                    segment_index=shard.segment_index,
                    source_text_path=str(segment_path),
                    translation_status="pending",
                    review_status="pending",
                )
                segment_total += 1

        summary = json.dumps(
            {
                "request_id": request_id,
                "chapter_count": len(chapter_documents),
                "segment_count": segment_total,
            },
            ensure_ascii=False,
        )
        if stage_run_id is None:
            self.chapters.create_stage_run(
                project_id=project_id,
                stage="chaptering",
                scope_type=str(scope["type"]),
                scope_value=json.dumps(scope, ensure_ascii=False),
                status="completed",
                summary=summary,
            )
        else:
            stage_run = self.session.get(StageRun, stage_run_id)
            if stage_run is None:
                raise ToolError(code="not_found", message=f"找不到 stage_run {stage_run_id}。", status=404)
            stage_run.status = "completed"
            stage_run.summary = summary
        self.session.commit()
        return ChapteringResult(
            chapter_count=len(chapter_documents),
            segment_count=segment_total,
            synopsis_summary=synopsis_summary,
        )

    def _split_into_chapters(self, content: str) -> list[dict[str, str]]:
        normalized_content = normalize_newlines(content)
        heading_pattern = re.compile(r"^第(?P<number>\d+)(?:章|回|节)\s*(?P<title>.*)$")
        markdown_heading_pattern = re.compile(
            r"^#{3,6}\s+(?P<number>\d+)(?:\s+(?P<title>.*))?$",
            re.MULTILINE,
        )

        if markdown_heading_pattern.search(normalized_content):
            return self._split_markdown_numeric_headings(
                normalized_content=normalized_content,
                heading_pattern=markdown_heading_pattern,
            )

        chapters: list[dict[str, str]] = []
        current_title: str | None = None
        current_source_lines: list[str] = []
        current_normalized_lines: list[str] = []
        current_body_source_lines: list[str] = []

        for raw_line in normalized_content.split("\n"):
            stripped_line = raw_line.strip()
            heading_match = heading_pattern.match(stripped_line)
            if heading_match:
                if current_title is not None:
                    chapters.append(
                        self._build_chapter_document(
                            chapter_title=current_title,
                            source_lines=current_source_lines,
                            normalized_lines=current_normalized_lines,
                            body_source_lines=current_body_source_lines,
                        )
                    )
                current_title = stripped_line
                current_source_lines = [raw_line]
                current_normalized_lines = []
                current_body_source_lines = []
                continue

            if current_title is None:
                if stripped_line == "":
                    continue
                current_title = "第1章"
                current_source_lines = [raw_line]
                current_normalized_lines = [stripped_line]
                current_body_source_lines = [raw_line]
                continue

            current_source_lines.append(raw_line)
            current_body_source_lines.append(raw_line)
            if stripped_line:
                current_normalized_lines.append(stripped_line)

        if current_title is not None:
            chapters.append(
                self._build_chapter_document(
                    chapter_title=current_title,
                    source_lines=current_source_lines,
                    normalized_lines=current_normalized_lines,
                    body_source_lines=current_body_source_lines,
                )
            )

        if not chapters and normalized_content.strip():
            stripped = normalized_content.strip()
            chapters.append(
                self._build_chapter_document(
                    chapter_title="第1章",
                    source_lines=[stripped],
                    normalized_lines=[stripped],
                    body_source_lines=[stripped],
                )
            )

        return chapters

    def _split_markdown_numeric_headings(
        self,
        *,
        normalized_content: str,
        heading_pattern: re.Pattern[str],
    ) -> list[dict[str, str]]:
        lines = normalized_content.split("\n")
        chapters: list[dict[str, str]] = []
        preface_source_lines: list[str] = []
        preface_normalized_lines: list[str] = []
        current_title: str | None = None
        current_source_lines: list[str] = []
        current_normalized_lines: list[str] = []
        current_body_source_lines: list[str] = []

        for raw_line in lines:
            stripped_line = raw_line.strip()
            heading_match = heading_pattern.match(stripped_line)
            if heading_match:
                if current_title is None:
                    current_title = self._build_markdown_chapter_title(heading_match)
                    current_source_lines = [*preface_source_lines, raw_line]
                    current_normalized_lines = [*preface_normalized_lines, stripped_line]
                    current_body_source_lines = []
                    continue

                chapters.append(
                    self._build_chapter_document(
                        chapter_title=current_title,
                        source_lines=current_source_lines,
                        normalized_lines=current_normalized_lines,
                        body_source_lines=current_body_source_lines,
                    )
                )
                current_title = self._build_markdown_chapter_title(heading_match)
                current_source_lines = [raw_line]
                current_normalized_lines = [stripped_line]
                current_body_source_lines = []
                continue

            if current_title is None:
                preface_source_lines.append(raw_line)
                if stripped_line:
                    preface_normalized_lines.append(stripped_line)
                continue

            current_source_lines.append(raw_line)
            current_body_source_lines.append(raw_line)
            if stripped_line:
                current_normalized_lines.append(stripped_line)

        if current_title is not None:
            chapters.append(
                self._build_chapter_document(
                    chapter_title=current_title,
                    source_lines=current_source_lines,
                    normalized_lines=current_normalized_lines,
                    body_source_lines=current_body_source_lines,
                )
            )

        if chapters:
            return chapters

        stripped = normalized_content.strip()
        if stripped:
            return [
                self._build_chapter_document(
                    chapter_title="第1章",
                    source_lines=[stripped],
                    normalized_lines=[stripped],
                    body_source_lines=[stripped],
                )
            ]
        return []

    def _build_markdown_chapter_title(self, heading_match: re.Match[str]) -> str:
        chapter_number = heading_match.group("number")
        chapter_suffix = (heading_match.group("title") or "").strip()
        if chapter_suffix:
            return f"第{chapter_number}章 {chapter_suffix}"
        return f"第{chapter_number}章"

    def _build_chapter_document(
        self,
        *,
        chapter_title: str,
        source_lines: list[str],
        normalized_lines: list[str],
        body_source_lines: list[str],
    ) -> dict[str, str]:
        source_text = "\n".join(source_lines).strip("\n")
        normalized_text = "\n".join(normalized_lines).strip()
        body_source_text = "\n".join(body_source_lines).strip("\n")
        return {
            "chapter_title": chapter_title,
            "source_text": source_text,
            "normalized_text": normalized_text,
            "body_source_text": body_source_text,
        }

    def _build_synopsis_summary(self, synopsis: object) -> dict[str, dict[str, object]]:
        return {
            "source": {
                "status": getattr(synopsis, "source_synopsis_status", "missing"),
                "origin": getattr(synopsis, "source_synopsis_origin", None),
                "length": len(getattr(synopsis, "source_synopsis_text", None) or ""),
            },
            "target": {
                "status": getattr(synopsis, "target_synopsis_status", "missing"),
                "origin": getattr(synopsis, "target_synopsis_origin", None),
                "length": len(getattr(synopsis, "target_synopsis_text", None) or ""),
            },
        }

    def _mark_related_outputs_stale(self, *, project_id: int) -> None:
        for review_run in self.session.execute(
            select(ReviewRun).where(ReviewRun.project_id == project_id)
        ).scalars().all():
            review_run.status = "stale"

        for export_run in self.session.execute(
            select(ExportRun).where(ExportRun.project_id == project_id)
        ).scalars().all():
            export_run.status = "stale"

        for stage_run in self.session.execute(
            select(StageRun).where(
                StageRun.project_id == project_id,
                StageRun.stage.in_(["translation", "review", "export"]),
            )
        ).scalars().all():
            stage_run.status = "stale"
