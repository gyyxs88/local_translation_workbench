from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, sessionmaker

from ..db.models import Chapter, ChapterSegment, SegmentTranslation, StageRun, TranslationProject
from ..errors import ToolError
from ..providers.base import Provider
from ..token_usage import merge_token_usage_payloads, normalize_token_usage_payload
from .scope_service import ensure_scope_supported, get_stage_scope_types
from .synopsis_service import SynopsisService
from .translation_pipeline_service import TranslationPipelineService
from .workflow_profile_service import WorkflowProfileService
from .workflow_runtime_service import WorkflowRuntimeService


@dataclass(frozen=True)
class TranslationResult:
    translated_segments: int
    active_version_ids: list[int]
    synopsis_summary: dict[str, dict[str, object]] | None = None
    token_usage: dict[str, int] | None = None


class TranslationRunService:
    def __init__(self, session: Session, *, base_data_dir: Path, provider: Provider | None = None) -> None:
        self.session = session
        self.base_data_dir = Path(base_data_dir)
        self.provider = provider
        self.synopses = SynopsisService(session)

    def run(
        self,
        *,
        request_id: str,
        project_id: int,
        scope: dict[str, object],
        model_profile_id: str,
        workflow_key: str | None = None,
        route_preset_key: str | None = None,
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
        self.synopses.reset_generation_tracking()
        try:
            synopsis = self.synopses.ensure_project_synopsis(
                project_id=project_id,
                model_profile_id=model_profile_id,
                provider_model_name=actual_model_name,
                provider=self.provider,
            )
        except Exception as exc:
            synopsis_usage = normalize_token_usage_payload(
                self.synopses.build_generation_metadata().get("token_usage")
            )
            if synopsis_usage is not None:
                setattr(exc, "_stage_token_usage", synopsis_usage)
            raise
        self.session.commit()
        synopsis_usage = normalize_token_usage_payload(
            self.synopses.build_generation_metadata().get("token_usage")
        )

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
        try:
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
                route_preset_key=route_preset_key,
                heartbeat=heartbeat,
            )
        except Exception as exc:
            if synopsis_usage is not None:
                existing_usage = normalize_token_usage_payload(getattr(exc, "_stage_token_usage", None))
                merged_usage = merge_token_usage_payloads(
                    [usage for usage in [existing_usage, synopsis_usage] if usage is not None]
                )
                if merged_usage is not None:
                    setattr(exc, "_stage_token_usage", merged_usage)
            raise

        total_token_usage = merge_token_usage_payloads(
            [usage for usage in [result.token_usage, synopsis_usage] if usage is not None]
        )
        if total_token_usage is not None:
            result = replace(result, token_usage=total_token_usage)

        summary = json.dumps(
            {
                "request_id": request_id,
                "model_profile_id": model_profile_id,
                "workflow_key": str(workflow_definition["workflow_key"]),
                "translated_segments": result.translated_segments,
                "active_version_ids": result.active_version_ids,
                "synopsis_summary": self.synopses.build_summary(synopsis),
                **({"token_usage": result.token_usage} if result.token_usage is not None else {}),
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
