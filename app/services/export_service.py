from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..db.models import Chapter, ChapterSegment, ExportRun, SegmentTranslation, SegmentTranslationVersion, TranslationProject
from ..errors import ToolError
from ..repositories.exports import ExportRepository
from ..repositories.glossary import GlossaryRepository
from ..repositories.review import ReviewRepository
from ..repositories.synopsis import ProjectSynopsisRepository
from ..repositories.translations import TranslationRepository
from ..utils import ensure_directory
from .scope_service import ensure_scope_supported, get_stage_scope_types, scope_matches_chapters


@dataclass(frozen=True)
class ExportResult:
    manifest_path: str
    artifact_count: int
    run_id: int


class ExportService:
    def __init__(self, session: Session, *, base_data_dir: Path) -> None:
        self.session = session
        self.base_data_dir = Path(base_data_dir)
        self.exports = ExportRepository(session)
        self.glossary = GlossaryRepository(session)
        self.reviews = ReviewRepository(session)
        self.synopses = ProjectSynopsisRepository(session)
        self.translations = TranslationRepository(session)

    def run(
        self,
        *,
        request_id: str,
        project_id: int,
        scope: dict[str, object],
        heartbeat: Callable[[], None] | None = None,
    ) -> ExportResult:
        project = self.session.get(TranslationProject, project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)
        ensure_scope_supported(scope, stage="export", allowed_types=get_stage_scope_types("export"))

        rows = self._resolve_segment_rows(project_id=project_id, scope=scope)
        if not rows:
            raise ToolError(code="invalid_arguments", message="scope 范围内没有可导出的段落。", status=400)

        synopsis = self.synopses.get_by_project_id(project_id)
        if synopsis is None or synopsis.target_synopsis_status not in {"ready", "completed"} or not synopsis.target_synopsis_text or not synopsis.target_synopsis_text.strip():
            raise ToolError(
                code="invalid_arguments",
                message="导出前缺少可用的目标语言简介。",
                status=400,
            )

        project_root = ensure_directory(self.base_data_dir / project.project_key)
        export_root = ensure_directory(project_root / "exports")
        run_token = uuid4().hex[:12]
        run_dir = ensure_directory(export_root / f"run_{run_token}")
        manifest_path = run_dir / "manifest.json"
        export_path = run_dir / "export.md"

        translations = []
        for chapter, segment, _, version in rows:
            if heartbeat is not None:
                heartbeat()
            translations.append(self._build_translation_record(chapter, segment, version))
        chapter_ids = sorted({chapter.id for chapter, _, _, _ in rows})
        chapter_indexes = sorted({chapter.chapter_index for chapter, _, _, _ in rows})
        glossary_entries = [
            {
                "id": entry.id,
                "project_id": entry.project_id,
                "source_term": entry.source_term,
                "target_term": entry.target_term,
                "category": entry.category,
                "status": entry.status,
                "locked": entry.locked,
            }
            for entry in self.glossary.list_entries(project_id)
        ]
        review_summary = self._build_review_summary(
            project_id=project_id,
            chapter_ids=chapter_ids,
            chapter_indexes=chapter_indexes,
        )

        manifest = {
            "project_id": project_id,
            "project_key": project.project_key,
            "scope": scope,
            "request_id": request_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_synopsis": synopsis.source_synopsis_text,
            "target_synopsis": synopsis.target_synopsis_text,
            "translations": translations,
            "glossary_entries": glossary_entries,
            "review_summary": review_summary,
            "artifacts": [
                {"artifact_type": "manifest", "file_path": str(manifest_path)},
                {"artifact_type": "export_markdown", "file_path": str(export_path)},
            ],
        }

        export_run = self.exports.create_run(
            project_id=project_id,
            scope_type=str(scope["type"]),
            scope_value=json.dumps(scope, ensure_ascii=False),
            manifest_path=str(manifest_path),
            status="completed",
            summary=json.dumps(
                {
                    "request_id": request_id,
                    "translation_count": len(translations),
                    "glossary_entry_count": len(glossary_entries),
                    "artifact_count": 2,
                },
                ensure_ascii=False,
            ),
        )

        written_paths: list[Path] = []
        try:
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            written_paths.append(manifest_path)
            export_path.write_text(
                self._render_export_markdown(
                    translations,
                    glossary_entries,
                    review_summary,
                    source_synopsis_text=synopsis.source_synopsis_text,
                    target_synopsis_text=synopsis.target_synopsis_text,
                ),
                encoding="utf-8",
            )
            written_paths.append(export_path)

            self.exports.create_artifact(
                export_run_id=export_run.id,
                artifact_type="manifest",
                file_path=str(manifest_path),
            )
            self.exports.create_artifact(
                export_run_id=export_run.id,
                artifact_type="export_markdown",
                file_path=str(export_path),
            )

            self.session.commit()
        except Exception:
            self.session.rollback()
            self._cleanup_written_paths(written_paths)
            raise

        return ExportResult(manifest_path=str(manifest_path), artifact_count=2, run_id=export_run.id)

    def inspect(self, *, project_id: int) -> dict[str, list[dict[str, object]]]:
        runs = []
        for export_run in self.exports.list_runs(project_id):
            summary = self._decode_summary(export_run.summary)
            artifacts = self.exports.list_artifacts_for_run(export_run.id)
            runs.append(
                {
                    "id": export_run.id,
                    "project_id": export_run.project_id,
                    "scope_type": export_run.scope_type,
                    "scope_value": self._decode_summary(export_run.scope_value),
                    "status": export_run.status,
                    "manifest_path": export_run.manifest_path,
                    "summary": summary,
                    "artifact_count": len(artifacts),
                }
            )

        artifacts = [
            {
                "id": artifact.id,
                "export_run_id": artifact.export_run_id,
                "artifact_type": artifact.artifact_type,
                "file_path": artifact.file_path,
                "exists": Path(artifact.file_path).exists(),
            }
            for artifact in self.exports.list_artifacts(project_id)
        ]
        return {"runs": runs, "artifacts": artifacts}

    def _resolve_segment_rows(
        self,
        *,
        project_id: int,
        scope: dict[str, object],
    ) -> list[tuple[Chapter, ChapterSegment, SegmentTranslation | None, SegmentTranslationVersion | None]]:
        statement = (
            select(Chapter, ChapterSegment, SegmentTranslation, SegmentTranslationVersion)
            .join(ChapterSegment, ChapterSegment.chapter_id == Chapter.id)
            .outerjoin(
                SegmentTranslation,
                and_(SegmentTranslation.segment_id == ChapterSegment.id, SegmentTranslation.project_id == project_id),
            )
            .outerjoin(SegmentTranslationVersion, SegmentTranslationVersion.id == SegmentTranslation.active_version_id)
            .where(Chapter.project_id == project_id, ChapterSegment.project_id == project_id)
        )
        scope_type = str(scope["type"])
        if scope_type == "chapter_range":
            statement = statement.where(
                Chapter.chapter_index >= int(scope["start"]),
                Chapter.chapter_index <= int(scope["end"]),
            )
        if scope_type == "chapter_list":
            statement = statement.where(Chapter.chapter_index.in_(list(scope["chapters"])))
        statement = statement.order_by(Chapter.chapter_index.asc(), ChapterSegment.segment_index.asc())
        rows = self.session.execute(statement).all()
        return [(chapter, segment, translation, version) for chapter, segment, translation, version in rows]

    def _build_translation_record(
        self,
        chapter: Chapter,
        segment: ChapterSegment,
        version: SegmentTranslationVersion | None,
    ) -> dict[str, object]:
        source_text = Path(segment.source_text_path).read_text(encoding="utf-8")
        return {
            "chapter_id": chapter.id,
            "chapter_index": chapter.chapter_index,
            "chapter_title": chapter.chapter_title,
            "segment_id": segment.id,
            "segment_index": segment.segment_index,
            "source_text": source_text,
            "translated_text": "" if version is None else version.translated_text,
            "translation_status": segment.translation_status,
            "review_status": segment.review_status,
            "version": None
            if version is None
            else {
                "id": version.id,
                "version_index": version.version_index,
                "provider_name": version.provider_name,
                "model_profile_id": version.model_profile_id,
                "model_name": version.model_name,
                "translated_text_path": version.translated_text_path,
                "status": version.status,
            },
        }

    def _build_review_summary(
        self,
        *,
        project_id: int,
        chapter_ids: list[int],
        chapter_indexes: list[int],
    ) -> dict[str, object]:
        latest_run = self._find_latest_review_run_for_scope(
            project_id=project_id,
            chapter_indexes=chapter_indexes,
        )
        if latest_run is None:
            return {"run_id": None, "issue_count": 0, "summary": None, "issues": []}

        issues = [
            issue
            for issue in self.reviews.list_issues_for_run(latest_run.id)
            if issue.chapter_id in chapter_ids
        ]
        return {
            "run_id": latest_run.id,
            "issue_count": len(issues),
            "summary": self._decode_summary(latest_run.summary),
            "issues": [
                {
                    "id": issue.id,
                    "chapter_id": issue.chapter_id,
                    "issue_type": issue.issue_type,
                    "severity": issue.severity,
                    "message": issue.message,
                    "status": issue.status,
                }
                for issue in issues
            ],
        }

    def _find_latest_review_run_for_scope(self, *, project_id: int, chapter_indexes: list[int]):
        for review_run in self.reviews.list_runs(project_id):
            scope_value = self._decode_summary(review_run.scope_value)
            if self._scope_matches_chapters(scope_value, chapter_indexes):
                return review_run
        return None

    def _scope_matches_chapters(self, scope_value: object, chapter_indexes: list[int]) -> bool:
        return scope_matches_chapters(scope_value, chapter_indexes)

    def _render_export_markdown(
        self,
        translations: list[dict[str, object]],
        glossary_entries: list[dict[str, object]],
        review_summary: dict[str, object],
        *,
        source_synopsis_text: str | None,
        target_synopsis_text: str,
    ) -> str:
        lines: list[str] = ["# Local Translation Export", ""]
        lines.append("## 简介（原文）")
        lines.extend(self._render_fenced_text_block(source_synopsis_text or "（无）"))
        lines.append("")
        lines.append("## 简介（译文）")
        lines.extend(self._render_fenced_text_block(target_synopsis_text))
        lines.append("")
        lines.append("## Translations")
        for item in translations:
            lines.append(f"### 第{item['chapter_index']}章 {item['chapter_title']}")
            lines.append(f"- 段落: {item['segment_index']}")
            lines.append(f"- 原文: {item['source_text']}")
            lines.append(f"- 译文: {item['translated_text']}")
            lines.append("")

        lines.append("## Glossary")
        if glossary_entries:
            for entry in glossary_entries:
                lock_flag = "locked" if int(entry["locked"]) else "unlocked"
                lines.append(f"- {entry['source_term']} -> {entry['target_term']} ({lock_flag})")
        else:
            lines.append("- 无术语")
        lines.append("")

        lines.append("## Review Summary")
        lines.append(f"- issue_count: {review_summary['issue_count']}")
        for issue in review_summary["issues"]:
            lines.append(f"- {issue['issue_type']}: {issue['message']}")
        lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _render_fenced_text_block(self, text: str) -> list[str]:
        fence = "`" * max(3, self._max_backtick_run(text) + 1)
        return [f"{fence}text", text, fence]

    def _max_backtick_run(self, text: str) -> int:
        longest_run = 0
        current_run = 0
        for character in text:
            if character == "`":
                current_run += 1
                if current_run > longest_run:
                    longest_run = current_run
            else:
                current_run = 0
        return longest_run

    def _cleanup_written_paths(self, paths: list[Path]) -> None:
        for path in paths:
            if path.exists():
                path.unlink()
        if paths:
            directory = paths[0].parent
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()

    def _decode_summary(self, value: str | None) -> object:
        if value is None or value == "":
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
