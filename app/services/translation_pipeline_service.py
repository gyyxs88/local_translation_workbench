from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..db.models import (
    Chapter,
    ChapterSegment,
    GlossaryEntry,
    SegmentTranslation,
    TranslationProject,
)
from ..errors import ToolError
from ..providers.base import Provider
from ..repositories.glossary import GlossaryRepository
from ..repositories.translation_workflows import TranslationWorkflowRepository
from ..utils import ensure_directory
from .scope_service import ensure_scope_supported, get_stage_scope_types
from .synopsis_service import SynopsisService
from .translation_assets_service import TranslationAssetsService
from .translation_workflow_draft_service import TranslationWorkflowDraftService
from .translation_workflow_execution_service import TranslationWorkflowExecutionService


class TranslationPipelineService:
    def __init__(
        self,
        session: Session,
        *,
        base_data_dir: Path,
        provider: Provider | None = None,
        parallel_session_factory=None,
        max_parallel_workers: int = 4,
    ) -> None:
        self.session = session
        self.base_data_dir = Path(base_data_dir)
        self.provider = provider
        self.parallel_session_factory = parallel_session_factory
        self.max_parallel_workers = max_parallel_workers
        self.glossary = GlossaryRepository(session)
        self.translation_workflows = TranslationWorkflowRepository(session)
        self.synopses = SynopsisService(session)
        self.translation_assets = TranslationAssetsService()
        self.workflow_drafts = TranslationWorkflowDraftService(session)
        self.workflow_execution = TranslationWorkflowExecutionService(
            session,
            base_data_dir=self.base_data_dir,
            provider=provider,
            parallel_session_factory=parallel_session_factory,
            max_parallel_workers=max_parallel_workers,
        )

    def fork_for_session(self, session: Session) -> "TranslationPipelineService":
        return TranslationPipelineService(
            session,
            base_data_dir=self.base_data_dir,
            provider=self.provider,
            parallel_session_factory=self.parallel_session_factory,
            max_parallel_workers=self.max_parallel_workers,
        )

    def generate_draft(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        scope: dict[str, object],
        model_profile_id: str,
        provider_model_name: str | None,
        draft_role: str,
        heartbeat=None,
    ) -> dict[str, object]:
        project = self.session.get(TranslationProject, project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)
        if self.provider is None:
            raise ToolError(code="invalid_arguments", message="缺少翻译 provider。", status=400)
        ensure_scope_supported(scope, stage="translation", allowed_types=get_stage_scope_types("translation"))

        segments = self._resolve_segments(project_id=project_id, scope=scope)
        if not segments:
            raise ToolError(code="invalid_arguments", message="scope 范围内没有可翻译的段落。", status=400)

        actual_model_name = provider_model_name or model_profile_id
        self.synopses.ensure_project_synopsis(
            project_id=project_id,
            model_profile_id=model_profile_id,
            provider_model_name=actual_model_name,
            provider=self.provider,
        )
        glossary_entries = self.glossary.list_active_entries_for_matching(project_id)
        glossary_snapshot_id = self.translation_assets.compute_glossary_snapshot_id(glossary_entries)

        project_root = ensure_directory(self.base_data_dir / project.project_key)
        workflow_root = ensure_directory(project_root / "translations" / "workflows" / str(workflow_run_id))
        jobs = [
            self._build_generate_segment_job(
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=workflow_step_run_id,
                project_id=project_id,
                workflow_root=workflow_root,
                source_language=project.source_language,
                target_language=project.target_language,
                chapter_index=chapter.chapter_index,
                segment_index=segment.segment_index,
                segment_id=segment.id,
                source_text_path=segment.source_text_path,
                model_profile_id=model_profile_id,
                provider_model_name=actual_model_name,
                draft_role=draft_role,
                glossary_entries=self.translation_assets.build_prompt_glossary_entries(
                    glossary_entries=glossary_entries,
                    source_text=Path(segment.source_text_path).read_text(encoding="utf-8"),
                ),
                glossary_snapshot_id=glossary_snapshot_id,
            )
            for chapter, segment in segments
        ]
        if heartbeat is not None:
            heartbeat()
        if self.parallel_session_factory is None or len(jobs) == 1:
            results = [self._generate_draft_for_segment_in_session(job=job) for job in jobs]
        else:
            self.session.commit()
            results = self.workflow_execution.run_parallel_jobs(
                jobs=jobs,
                worker=lambda job: self._generate_draft_for_segment(job=job),
            )
        return self._build_parallel_generation_payload(results=results, model_profile_id=model_profile_id)

    def review_draft(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
        heartbeat=None,
    ) -> dict[str, object]:
        return self.workflow_execution.review_draft(
            workflow_run_id=workflow_run_id,
            workflow_step_run_id=workflow_step_run_id,
            model_profile_id=model_profile_id,
            provider_model_name=provider_model_name,
            heartbeat=heartbeat,
        )

    def rewrite_draft(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
        heartbeat=None,
    ) -> dict[str, object]:
        return self.workflow_execution.rewrite_draft(
            workflow_run_id=workflow_run_id,
            workflow_step_run_id=workflow_step_run_id,
            model_profile_id=model_profile_id,
            provider_model_name=provider_model_name,
            heartbeat=heartbeat,
        )

    def inspect_pipeline(self, *, workflow_run_id: int) -> dict[str, object]:
        return self.workflow_drafts.inspect_pipeline(workflow_run_id=workflow_run_id)

    def finalize(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
        heartbeat=None,
    ) -> dict[str, object]:
        return self.workflow_execution.finalize(
            workflow_run_id=workflow_run_id,
            workflow_step_run_id=workflow_step_run_id,
            project_id=project_id,
            model_profile_id=model_profile_id,
            provider_model_name=provider_model_name,
            heartbeat=heartbeat,
        )

    def inspect_synopsis_summary(self, *, project_id: int) -> dict[str, dict[str, object]]:
        payload = self.synopses.inspect(project_id=project_id)
        return {
            "source": {
                "status": payload["source_synopsis_status"],
                "origin": payload["source_synopsis_origin"],
                "length": len(payload["source_synopsis_text"] or ""),
            },
            "target": {
                "status": payload["target_synopsis_status"],
                "origin": payload["target_synopsis_origin"],
                "length": len(payload["target_synopsis_text"] or ""),
            },
        }

    def _build_generate_segment_job(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        workflow_root: Path,
        source_language: str,
        target_language: str,
        chapter_index: int,
        segment_index: int,
        segment_id: int,
        source_text_path: str,
        model_profile_id: str,
        provider_model_name: str,
        draft_role: str,
        glossary_entries: list[GlossaryEntry],
        glossary_snapshot_id: str,
    ) -> dict[str, object]:
        source_text = Path(source_text_path).read_text(encoding="utf-8")
        prompt = self.translation_assets.build_translation_prompt(
            source_language=source_language,
            target_language=target_language,
            chapter_index=chapter_index,
            segment_index=segment_index,
            source_text=source_text,
            glossary_entries=glossary_entries,
        )
        return {
            "workflow_run_id": workflow_run_id,
            "workflow_step_run_id": workflow_step_run_id,
            "project_id": project_id,
            "workflow_root": str(workflow_root),
            "chapter_index": chapter_index,
            "segment_index": segment_index,
            "segment_id": segment_id,
            "source_text_path": source_text_path,
            "source_hash": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
            "prompt": prompt,
            "model_profile_id": model_profile_id,
            "provider_model_name": provider_model_name,
            "draft_role": draft_role,
            "glossary_snapshot_id": glossary_snapshot_id,
        }

    def _generate_draft_for_segment(self, *, job: dict[str, object]) -> dict[str, object]:
        worker_session = self.workflow_execution.open_parallel_session()
        try:
            worker_pipeline = self.fork_for_session(worker_session)
            result = worker_pipeline._generate_draft_for_segment_in_session(job=job)
            worker_session.commit()
            return result
        except Exception:
            worker_session.rollback()
            raise
        finally:
            worker_session.close()

    def _generate_draft_for_segment_in_session(self, *, job: dict[str, object]) -> dict[str, object]:
        if self.provider is None:
            raise ToolError(code="invalid_arguments", message="缺少翻译 provider。", status=400)
        workflow_root = Path(str(job["workflow_root"]))
        segment_id = int(job["segment_id"])
        segment_dir = ensure_directory(workflow_root / "segments" / f"{segment_id:08d}")
        draft_path = segment_dir / f"{int(job['workflow_step_run_id'])}-{str(job['draft_role'])}.txt"
        created_directories = {segment_dir}
        written_paths: list[Path] = []
        try:
            provider_result = self.provider.generate_text(
                prompt=str(job["prompt"]),
                model_name=str(job["provider_model_name"]),
                timeout_seconds=60,
            )
            draft_path.write_text(provider_result.content, encoding="utf-8")
            written_paths.append(draft_path)
            self.translation_workflows.create_draft_version(
                workflow_run_id=int(job["workflow_run_id"]),
                project_id=int(job["project_id"]),
                segment_id=segment_id,
                step_run_id=int(job["workflow_step_run_id"]),
                parent_draft_id=None,
                draft_role=str(job["draft_role"]),
                source_hash=str(job["source_hash"]),
                glossary_snapshot_id=str(job["glossary_snapshot_id"]),
                provider_name=provider_result.provider_name,
                model_profile_id=provider_result.model_profile_id or str(job["model_profile_id"]),
                model_name=provider_result.model_name,
                translated_text=provider_result.content,
                translated_text_path=str(draft_path),
                status="completed",
                evidence_payload={
                    "chapter_index": int(job["chapter_index"]),
                    "segment_index": int(job["segment_index"]),
                    "fallback_depth": int(provider_result.fallback_depth or 0),
                    "actual_model_profile_id": provider_result.model_profile_id or str(job["model_profile_id"]),
                },
            )
            return {
                "segment_id": segment_id,
                "succeeded": True,
                "model_profile_id": provider_result.model_profile_id or str(job["model_profile_id"]),
                "model_name": provider_result.model_name,
                "provider_name": provider_result.provider_name,
                "fallback_depth": int(provider_result.fallback_depth or 0),
            }
        except Exception:
            self.workflow_execution.cleanup_workflow_outputs(
                written_paths=written_paths,
                created_directories=created_directories,
            )
            raise

    def _build_parallel_generation_payload(
        self,
        *,
        results: list[dict[str, object]],
        model_profile_id: str,
    ) -> dict[str, object]:
        actual_model_profiles = sorted(
            {str(item["model_profile_id"]) for item in results if item.get("model_profile_id")}
        )
        max_fallback_depth = max((int(item.get("fallback_depth") or 0) for item in results), default=0)
        payload: dict[str, object] = {
            "segment_count": len(results),
            "draft_count": len(results),
            "model_profile_id": actual_model_profiles[-1] if actual_model_profiles else model_profile_id,
            "model_name": next((item.get("model_name") for item in reversed(results) if item.get("model_name")), None),
            "provider_name": next((item.get("provider_name") for item in reversed(results) if item.get("provider_name")), None),
            "fallback_depth": max_fallback_depth,
            "actual_model_profiles": actual_model_profiles,
            "max_fallback_depth": max_fallback_depth,
            "succeeded_segment_count": len(results),
            "failed_segment_count": 0,
            "failed_segments": [],
        }
        return payload

    def _resolve_segments(self, *, project_id: int, scope: dict[str, object]) -> list[tuple[Chapter, ChapterSegment]]:
        ensure_scope_supported(scope, stage="translation", allowed_types=get_stage_scope_types("translation"))
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
        return [(chapter, segment) for chapter, segment in self.session.execute(statement).all()]

