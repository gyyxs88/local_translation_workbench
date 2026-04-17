from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, sessionmaker

from ..db.models import (
    Chapter,
    ChapterSegment,
    ExportRun,
    GlossaryEntry,
    ReviewRun,
    SegmentTranslation,
    SegmentTranslationVersion,
    StageRun,
    TranslationDraftReview,
    TranslationDraftVersion,
    TranslationProject,
    WorkflowStepRun,
)
from ..errors import ToolError
from ..providers.base import Provider
from ..repositories.glossary import GlossaryRepository
from ..repositories.translations import TranslationRepository
from ..utils import ensure_directory
from .synopsis_service import SynopsisService
from .translation_pipeline_service import TranslationPipelineService
from .workflow_profile_service import WorkflowProfileService
from .workflow_runtime_service import WorkflowRuntimeService
from .scope_service import ensure_scope_supported, get_stage_scope_types, scope_matches_chapters


@dataclass(frozen=True)
class TranslationResult:
    translated_segments: int
    active_version_ids: list[int]
    synopsis_summary: dict[str, dict[str, object]] | None = None


@dataclass(frozen=True)
class GlossaryMatch:
    entry: GlossaryEntry
    start: int
    end: int


class TranslationService:
    def __init__(self, session: Session, *, base_data_dir: Path, provider: Provider | None = None) -> None:
        self.session = session
        self.base_data_dir = Path(base_data_dir)
        self.provider = provider
        self.glossary = GlossaryRepository(session)
        self.translations = TranslationRepository(session)
        self.synopses = SynopsisService(session)

    def run(
        self,
        *,
        request_id: str,
        project_id: int,
        scope: dict[str, object],
        model_profile_id: str,
        workflow_key: str | None = None,
        provider_model_name: str | None = None,
        stage_run_id: int | None = None,
        heartbeat: Callable[[], None] | None = None,
    ) -> TranslationResult:
        project = self.session.get(TranslationProject, project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)
        ensure_scope_supported(scope, stage="translation", allowed_types=get_stage_scope_types("translation"))
        if self.provider is None:
            raise ToolError(code="invalid_arguments", message="缺少翻译 provider。", status=400)
        segments = self._resolve_segments(project_id=project_id, scope=scope)
        if not segments:
            raise ToolError(code="invalid_arguments", message="scope 范围内没有可翻译的段落。", status=400)

        actual_model_name = provider_model_name or model_profile_id
        synopsis = self.synopses.ensure_project_synopsis(
            project_id=project_id,
            model_profile_id=model_profile_id,
            provider_model_name=actual_model_name,
            provider=self.provider,
        )
        self.session.commit()

        profile_service = WorkflowProfileService(self.session)
        if profile_service.ensure_builtin_profiles():
            if stage_run_id is None:
                self.session.commit()
            else:
                self.session.flush()

        workflow_runtime = WorkflowRuntimeService(self.session)
        workflow_definition = workflow_runtime.resolve_workflow_definition(stage="translation", workflow_key=workflow_key)
        parallel_session_factory = None
        if str(workflow_definition["workflow_key"]) == "translation_multi_llm_v1":
            parallel_session_factory = sessionmaker(
                bind=self.session.get_bind(),
                autoflush=False,
                expire_on_commit=False,
            )
        pipeline = TranslationPipelineService(
            self.session,
            base_data_dir=self.base_data_dir,
            provider=self.provider,
            parallel_session_factory=parallel_session_factory,
        )
        result = workflow_runtime.run_translation_workflow(
            workflow_definition=workflow_definition,
            workflow_key=str(workflow_definition["workflow_key"]),
            request_id=request_id,
            project_id=project_id,
            scope=scope,
            request_model_profile_id=model_profile_id,
            provider_model_name=provider_model_name,
            pipeline=pipeline,
            stage_run_id=stage_run_id,
            heartbeat=heartbeat,
        )

        summary = json.dumps(
            {
                "request_id": request_id,
                "model_profile_id": model_profile_id,
                "workflow_key": str(workflow_definition["workflow_key"]),
                "translated_segments": result.translated_segments,
                "active_version_ids": result.active_version_ids,
                "synopsis_summary": self.synopses.build_summary(synopsis),
            },
            ensure_ascii=False,
        )
        if stage_run_id is None:
            self.session.add(
                StageRun(
                    project_id=project_id,
                    stage="translation",
                    scope_type=str(scope["type"]),
                    scope_value=json.dumps(scope, ensure_ascii=False),
                    status="completed",
                    summary=summary,
                )
            )
            self.session.commit()
        else:
            stage_run = self.session.get(StageRun, stage_run_id)
            if stage_run is None:
                raise ToolError(code="not_found", message=f"找不到 stage_run {stage_run_id}。", status=404)
            self.session.flush()
        self.session.expire_all()
        return result

    def inspect(
        self,
        *,
        project_id: int,
        segment_id: int | None = None,
        chapter_index: int | None = None,
        segment_index: int | None = None,
        compare_version_id: int | None = None,
    ) -> dict[str, list[dict[str, object]]]:
        self._validate_inspect_translation_locator(
            segment_id=segment_id,
            chapter_index=chapter_index,
            segment_index=segment_index,
            compare_version_id=compare_version_id,
        )
        if segment_id is None and chapter_index is None and segment_index is None:
            return self._inspect_project_translations(project_id=project_id)

        chapter, segment, segment_translation, version = self._resolve_single_translation_row(
            project_id=project_id,
            segment_id=segment_id,
            chapter_index=chapter_index,
            segment_index=segment_index,
        )
        active_versions = [] if version is None else [version]
        provenance_by_version_id = self._build_translation_provenance_map(active_versions=active_versions)
        translation_row = self._build_translation_row_payload(
            project_id=project_id,
            chapter=chapter,
            segment=segment,
            segment_translation=segment_translation,
            version=version,
            provenance_by_version_id=provenance_by_version_id,
        )
        if compare_version_id is not None:
            translation_row["compare"] = self._build_translation_compare_payload(
                project_id=project_id,
                translation=segment_translation,
                current_version=version,
                compare_version_id=compare_version_id,
            )

        versions = []
        if segment_translation is not None:
            versions = [
                self._build_translation_version_list_payload(item)
                for item in self.translations.list_versions_for_translation(int(segment_translation.id))
            ]
        return {"translations": [translation_row], "versions": versions}

    def _inspect_project_translations(self, *, project_id: int) -> dict[str, list[dict[str, object]]]:
        statement = (
            select(Chapter, ChapterSegment, SegmentTranslation, SegmentTranslationVersion)
            .join(ChapterSegment, ChapterSegment.chapter_id == Chapter.id)
            .outerjoin(
                SegmentTranslation,
                SegmentTranslation.segment_id == ChapterSegment.id,
            )
            .outerjoin(SegmentTranslationVersion, SegmentTranslationVersion.id == SegmentTranslation.active_version_id)
            .where(
                Chapter.project_id == project_id,
                ChapterSegment.project_id == project_id,
            )
            .where((SegmentTranslation.project_id == project_id) | (SegmentTranslation.project_id.is_(None)))
            .order_by(Chapter.chapter_index.asc(), ChapterSegment.segment_index.asc())
        )
        rows = self.session.execute(statement).all()
        active_versions = [version for *_, version in rows if version is not None]
        provenance_by_version_id = self._build_translation_provenance_map(active_versions=active_versions)
        translations = [
            self._build_translation_row_payload(
                project_id=project_id,
                chapter=chapter,
                segment=segment,
                segment_translation=segment_translation,
                version=version,
                provenance_by_version_id=provenance_by_version_id,
            )
            for chapter, segment, segment_translation, version in rows
        ]
        versions = [
            self._build_translation_version_list_payload(version)
            for version in self.translations.list_segment_translation_versions(project_id)
        ]
        return {"translations": translations, "versions": versions}

    def _validate_inspect_translation_locator(
        self,
        *,
        segment_id: int | None,
        chapter_index: int | None,
        segment_index: int | None,
        compare_version_id: int | None,
    ) -> None:
        if segment_id is not None and (chapter_index is not None or segment_index is not None):
            raise ToolError(
                code="invalid_arguments",
                message="inspect.translation 不能同时提供 segment_id 与 chapter_index/segment_index。",
                status=400,
            )
        if compare_version_id is not None and segment_id is None and chapter_index is None and segment_index is None:
            raise ToolError(
                code="invalid_arguments",
                message="inspect.translation 使用 compare_version_id 时必须先定位到单个 segment。",
                status=400,
            )
        if segment_id is None and (chapter_index is None) != (segment_index is None):
            raise ToolError(
                code="invalid_arguments",
                message="inspect.translation 使用章节定位时必须同时提供 chapter_index 和 segment_index。",
                status=400,
            )

    def _resolve_single_translation_row(
        self,
        *,
        project_id: int,
        segment_id: int | None,
        chapter_index: int | None,
        segment_index: int | None,
    ) -> tuple[Chapter, ChapterSegment, SegmentTranslation | None, SegmentTranslationVersion | None]:
        statement = (
            select(Chapter, ChapterSegment, SegmentTranslation, SegmentTranslationVersion)
            .join(ChapterSegment, ChapterSegment.chapter_id == Chapter.id)
            .outerjoin(
                SegmentTranslation,
                and_(
                    SegmentTranslation.segment_id == ChapterSegment.id,
                    SegmentTranslation.project_id == project_id,
                ),
            )
            .outerjoin(SegmentTranslationVersion, SegmentTranslationVersion.id == SegmentTranslation.active_version_id)
            .where(Chapter.project_id == project_id, ChapterSegment.project_id == project_id)
        )
        if segment_id is not None:
            statement = statement.where(ChapterSegment.id == segment_id)
        else:
            statement = statement.where(
                Chapter.chapter_index == chapter_index,
                ChapterSegment.segment_index == segment_index,
            )
        row = self.session.execute(statement).one_or_none()
        if row is None:
            raise ToolError(code="not_found", message="找不到目标段落。", status=404)
        return row

    def _build_translation_version_payload(self, version: SegmentTranslationVersion) -> dict[str, object]:
        return {
            "id": int(version.id),
            "version_index": int(version.version_index),
            "source_hash": str(version.source_hash),
            "glossary_snapshot_id": str(version.glossary_snapshot_id),
            "provider_name": str(version.provider_name),
            "model_profile_id": str(version.model_profile_id),
            "model_name": str(version.model_name),
            "source_text": str(version.source_text),
            "translated_text": str(version.translated_text),
            "translated_text_path": str(version.translated_text_path),
            "status": str(version.status),
        }

    def _build_translation_version_list_payload(self, version: SegmentTranslationVersion) -> dict[str, object]:
        payload = self._build_translation_version_payload(version)
        return {
            "id": int(version.id),
            "project_id": int(version.project_id),
            "segment_translation_id": int(version.segment_translation_id),
            **payload,
        }

    def _build_translation_row_payload(
        self,
        *,
        project_id: int,
        chapter: Chapter,
        segment: ChapterSegment,
        segment_translation: SegmentTranslation | None,
        version: SegmentTranslationVersion | None,
        provenance_by_version_id: dict[int, dict[str, object]],
    ) -> dict[str, object]:
        return {
            "project_id": project_id,
            "chapter_id": int(chapter.id),
            "chapter_index": int(chapter.chapter_index),
            "chapter_title": str(chapter.chapter_title),
            "segment_id": int(segment.id),
            "segment_index": int(segment.segment_index),
            "translation_status": str(segment.translation_status),
            "review_status": str(segment.review_status),
            "active_version_id": (
                None
                if segment_translation is None or segment_translation.active_version_id is None
                else int(segment_translation.active_version_id)
            ),
            "version": None if version is None else self._build_translation_version_payload(version),
            "provenance": None if version is None else provenance_by_version_id.get(int(version.id)),
        }

    def _build_translation_compare_payload(
        self,
        *,
        project_id: int,
        translation: SegmentTranslation | None,
        current_version: SegmentTranslationVersion | None,
        compare_version_id: int,
    ) -> dict[str, object]:
        if translation is None or current_version is None or translation.active_version_id is None:
            raise ToolError(code="not_found", message="当前段落没有 active version，无法执行 compare。", status=404)
        if int(current_version.id) == compare_version_id:
            raise ToolError(
                code="invalid_arguments",
                message="compare_version_id 不能指向当前 active version。",
                status=400,
            )

        base_version = self.translations.get_version_by_id(compare_version_id)
        if (
            base_version is None
            or int(base_version.project_id) != project_id
            or int(base_version.segment_translation_id) != int(translation.id)
        ):
            raise ToolError(
                code="not_found",
                message=f"找不到可比较的历史正式版本 {compare_version_id}。",
                status=404,
            )

        summary = {
            "translated_text_changed": str(base_version.translated_text) != str(current_version.translated_text),
            "source_hash_changed": str(base_version.source_hash) != str(current_version.source_hash),
            "glossary_snapshot_changed": (
                str(base_version.glossary_snapshot_id) != str(current_version.glossary_snapshot_id)
            ),
            "model_profile_changed": str(base_version.model_profile_id) != str(current_version.model_profile_id),
            "model_name_changed": str(base_version.model_name) != str(current_version.model_name),
            "status_changed": str(base_version.status) != str(current_version.status),
        }
        return {
            "base_version": self._build_translation_version_payload(base_version),
            "current_version": self._build_translation_version_payload(current_version),
            "changed": any(summary.values()),
            "summary": summary,
        }

    def _build_translation_provenance_map(
        self,
        *,
        active_versions: list[SegmentTranslationVersion],
    ) -> dict[int, dict[str, object]]:
        tracked_versions = [
            version
            for version in active_versions
            if version.origin_step_run_id is not None and version.origin_draft_version_id is not None
        ]
        if not tracked_versions:
            return {}

        step_ids = sorted({int(version.origin_step_run_id) for version in tracked_versions})
        draft_ids = sorted({int(version.origin_draft_version_id) for version in tracked_versions})

        step_rows = {
            int(row.id): row
            for row in self.session.execute(
                select(WorkflowStepRun).where(WorkflowStepRun.id.in_(step_ids))
            ).scalars().all()
        }
        draft_rows = {
            int(row.id): row
            for row in self.session.execute(
                select(TranslationDraftVersion).where(TranslationDraftVersion.id.in_(draft_ids))
            ).scalars().all()
        }
        review_rows = self.session.execute(
            select(TranslationDraftReview)
            .where(TranslationDraftReview.draft_version_id.in_(draft_ids))
            .order_by(TranslationDraftReview.id.asc())
        ).scalars().all()

        reviews_by_draft: dict[int, list[TranslationDraftReview]] = {}
        for review in review_rows:
            reviews_by_draft.setdefault(int(review.draft_version_id), []).append(review)

        payload: dict[int, dict[str, object]] = {}
        for version in tracked_versions:
            step = step_rows.get(int(version.origin_step_run_id))
            draft = draft_rows.get(int(version.origin_draft_version_id))
            if step is None or draft is None:
                continue
            payload[int(version.id)] = {
                "finalize_step": {
                    "step_run_id": int(step.id),
                    "step_key": str(step.step_key),
                    "action": str(step.action),
                },
                "selected_draft": {
                    "id": int(draft.id),
                    "workflow_run_id": int(draft.workflow_run_id),
                    "step_run_id": int(draft.step_run_id),
                    "draft_role": str(draft.draft_role),
                    "parent_draft_id": None if draft.parent_draft_id is None else int(draft.parent_draft_id),
                    "provider_name": str(draft.provider_name),
                    "model_profile_id": str(draft.model_profile_id),
                    "model_name": str(draft.model_name),
                    "translated_text_path": str(draft.translated_text_path),
                    "status": str(draft.status),
                    "evidence_payload": draft.evidence_payload,
                    "reviews": [
                        {
                            "id": int(review.id),
                            "step_run_id": int(review.step_run_id),
                            "review_type": str(review.review_type),
                            "decision": str(review.decision),
                            "score": review.score,
                            "reason_codes": review.reason_codes,
                            "structured_payload": review.structured_payload,
                        }
                        for review in reviews_by_draft.get(int(draft.id), [])
                    ],
                },
            }
        return payload

    def _resolve_segments(
        self,
        *,
        project_id: int,
        scope: dict[str, object],
    ) -> list[tuple[Chapter, ChapterSegment]]:
        statement = (
            select(Chapter, ChapterSegment)
            .join(ChapterSegment, ChapterSegment.chapter_id == Chapter.id)
            .outerjoin(
                SegmentTranslation,
                and_(SegmentTranslation.segment_id == ChapterSegment.id, SegmentTranslation.project_id == project_id),
            )
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
        if scope_type == "stale_only":
            statement = statement.where(ChapterSegment.translation_status == "stale")
        if scope_type == "failed_only":
            statement = statement.where(ChapterSegment.translation_status == "failed")
        if scope_type == "missing_only":
            statement = statement.where(SegmentTranslation.active_version_id.is_(None))
        statement = statement.order_by(Chapter.chapter_index.asc(), ChapterSegment.segment_index.asc())
        rows = self.session.execute(statement).all()
        return [(chapter, segment) for chapter, segment in rows]

    def _mark_related_runs_stale(self, *, project_id: int, affected_chapter_indexes: list[int]) -> None:
        if not affected_chapter_indexes:
            return

        for review_run in self.session.execute(
            select(ReviewRun).where(ReviewRun.project_id == project_id)
        ).scalars().all():
            if self._scope_matches_chapters(self._decode_summary(review_run.scope_value), affected_chapter_indexes):
                review_run.status = "stale"

        for export_run in self.session.execute(
            select(ExportRun).where(ExportRun.project_id == project_id)
        ).scalars().all():
            if self._scope_matches_chapters(self._decode_summary(export_run.scope_value), affected_chapter_indexes):
                export_run.status = "stale"

        for stage_run in self.session.execute(
            select(StageRun).where(
                StageRun.project_id == project_id,
                StageRun.stage.in_(["review", "export"]),
            )
        ).scalars().all():
            if self._scope_matches_chapters(self._decode_summary(stage_run.scope_value), affected_chapter_indexes):
                stage_run.status = "stale"

    def _build_translation_prompt(
        self,
        *,
        source_language: str,
        target_language: str,
        chapter_index: int,
        segment_index: int,
        source_text: str,
        glossary_entries: list[GlossaryEntry],
    ) -> str:
        prompt = (
            f"你是一个翻译引擎。请翻译正文，把{source_language}文本翻译成{target_language}。\n"
            f"章节: {chapter_index}\n"
            f"段落: {segment_index}\n"
            "只返回译文，不要解释。\n"
            "如果正文命中了术语表中的 source_term，译文必须优先使用该条目的 target_term。\n"
            "不要把已命中的术语改写成同组其他表面形式。\n"
            "同一术语在同一段落内不要出现多种译法。"
        )
        if glossary_entries:
            prompt += "\n术语表：\n" + "\n".join(self._format_glossary_entry(item) for item in glossary_entries)
        return f"{prompt}\n\n{source_text}"

    def _build_prompt_glossary_entries(
        self,
        *,
        glossary_entries: list[GlossaryEntry],
        source_text: str,
    ) -> list[GlossaryEntry]:
        matches = self._find_glossary_matches(
            glossary_entries=glossary_entries,
            source_text=source_text,
        )
        resolved = self._resolve_overlapping_matches(matches)
        unique_entries: dict[str, GlossaryEntry] = {}
        for match in resolved:
            if match.entry.source_term not in unique_entries:
                unique_entries[match.entry.source_term] = match.entry
        return list(unique_entries.values())

    def _find_glossary_matches(
        self,
        *,
        glossary_entries: list[GlossaryEntry],
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

    def _format_glossary_entry(self, entry: GlossaryEntry) -> str:
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

    def _compute_glossary_snapshot_id(self, glossary_entries: list[GlossaryEntry]) -> str:
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

    def _scope_matches_chapters(self, scope_value: object, chapter_indexes: list[int]) -> bool:
        return scope_matches_chapters(scope_value, chapter_indexes)

    def _decode_summary(self, value: str | None) -> object:
        if value is None or value == "":
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    def _cleanup_written_outputs(
        self,
        *,
        written_version_paths: list[Path],
        current_file_snapshots: dict[Path, str | None],
        created_directories: set[Path],
    ) -> None:
        for version_path in written_version_paths:
            if version_path.exists():
                version_path.unlink()

        for current_path, previous_content in current_file_snapshots.items():
            if previous_content is None:
                if current_path.exists():
                    current_path.unlink()
            else:
                current_path.write_text(previous_content, encoding="utf-8")

        for directory in sorted(created_directories, key=lambda item: len(item.parts), reverse=True):
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
