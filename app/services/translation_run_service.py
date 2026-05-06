from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, sessionmaker

from ..db.models import Chapter, ChapterSegment, SegmentTranslation, StageRun, TranslationProject, WorkflowRun, WorkflowStepRun
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
    workflow_run_id: int | None = None


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
        if self._should_enable_parallel_segments(workflow_definition):
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
            recovered_result = self._try_resume_existing_workflow_finalize(
                workflow_definition=workflow_definition,
                request_id=request_id,
                project_id=project_id,
                model_profile_id=model_profile_id,
                provider_model_name=provider_model_name,
                pipeline=pipeline,
                stage_run_id=stage_run_id,
                heartbeat=heartbeat,
            )
            if recovered_result is not None:
                result = recovered_result
            else:
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
                **({"workflow_run_id": result.workflow_run_id} if result.workflow_run_id is not None else {}),
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

    def _try_resume_existing_workflow_finalize(
        self,
        *,
        workflow_definition: dict[str, object],
        request_id: str,
        project_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
        pipeline: TranslationPipelineService,
        stage_run_id: int | None,
        heartbeat: Callable[[], None] | None,
    ) -> TranslationResult | None:
        if stage_run_id is None:
            return None
        stage_run = self.session.get(StageRun, stage_run_id)
        if stage_run is None:
            return None
        stage_summary = self._decode_json_object(stage_run.summary)
        resume_from_run_id = self._parse_optional_int(stage_summary.get("resume_from_run_id"))
        if resume_from_run_id is None:
            return None
        source_stage_run = self.session.get(StageRun, resume_from_run_id)
        if source_stage_run is None or source_stage_run.stage != "translation":
            return None
        source_summary = self._decode_json_object(source_stage_run.summary)
        source_request_id = str(source_summary.get("request_id") or "")
        workflow_run = self._find_workflow_run_for_stage_run(
            project_id=project_id,
            stage_run_id=int(source_stage_run.id),
            request_id=source_request_id,
        )
        if workflow_run is None or workflow_run.status == "completed":
            return None
        if not pipeline.workflow_drafts.translation_workflows.list_draft_versions(workflow_run_id=int(workflow_run.id)):
            return None
        if self._has_completed_finalize_step(workflow_run_id=int(workflow_run.id)):
            return None

        finalize_definition = self._find_finalize_step_definition(workflow_definition)
        if finalize_definition is None:
            return None
        finalize_step = self._get_or_create_finalize_step(
            workflow_run_id=int(workflow_run.id),
            step_definition=finalize_definition,
            model_profile_id=model_profile_id,
            provider_model_name=provider_model_name,
            request_id=request_id,
            stage_run_id=stage_run_id,
        )
        output_payload = pipeline.finalize(
            workflow_run_id=int(workflow_run.id),
            workflow_step_run_id=int(finalize_step.id),
            project_id=project_id,
            model_profile_id=model_profile_id,
            provider_model_name=provider_model_name,
            heartbeat=heartbeat,
        )
        output_payload = dict(output_payload)
        output_payload["recovered_from_workflow_run_id"] = int(workflow_run.id)
        output_payload["recovered_from_stage_run_id"] = int(source_stage_run.id)
        output_payload["recovered_by_stage_run_id"] = int(stage_run_id)
        output_payload["recovered_by_request_id"] = request_id
        finalize_step.status = "completed"
        finalize_step.output_payload = output_payload
        workflow_run.status = "completed"
        workflow_run.summary = json.dumps(
            {
                **self._decode_json_object(workflow_run.summary),
                "request_id": workflow_run.request_id,
                "workflow_key": workflow_run.workflow_key,
                "recovered": True,
                "recovered_by_stage_run_id": int(stage_run_id),
                "recovered_by_request_id": request_id,
                "result_source": "translation.finalize",
                "translated_segments": int(output_payload.get("translated_segments") or 0),
                "active_version_ids": list(output_payload.get("active_version_ids") or []),
            },
            ensure_ascii=False,
        )
        self.session.flush()
        return TranslationResult(
            translated_segments=int(output_payload.get("translated_segments") or 0),
            active_version_ids=[int(item) for item in output_payload.get("active_version_ids", [])],
            synopsis_summary=pipeline.inspect_synopsis_summary(project_id=project_id),
            workflow_run_id=int(workflow_run.id),
        )

    def _find_workflow_run_for_stage_run(
        self,
        *,
        project_id: int,
        stage_run_id: int,
        request_id: str,
    ) -> WorkflowRun | None:
        statement = (
            select(WorkflowRun)
            .where(WorkflowRun.project_id == project_id, WorkflowRun.stage == "translation")
            .order_by(WorkflowRun.id.desc())
        )
        if request_id:
            statement = statement.where(WorkflowRun.request_id == request_id)
        for workflow_run in self.session.execute(statement).scalars().all():
            summary = self._decode_json_object(workflow_run.summary)
            if self._parse_optional_int(summary.get("stage_run_id")) == stage_run_id:
                return workflow_run
        return None

    def _has_completed_finalize_step(self, *, workflow_run_id: int) -> bool:
        step = self.session.execute(
            select(WorkflowStepRun).where(
                WorkflowStepRun.workflow_run_id == workflow_run_id,
                WorkflowStepRun.action == "translation.finalize",
                WorkflowStepRun.status == "completed",
            )
        ).scalars().first()
        return step is not None

    def _find_finalize_step_definition(self, workflow_definition: dict[str, object]) -> dict[str, object] | None:
        definition_json = workflow_definition.get("definition_json", {})
        if not isinstance(definition_json, dict):
            return None
        steps = definition_json.get("steps", [])
        if not isinstance(steps, list):
            return None
        for step in steps:
            if isinstance(step, dict) and step.get("action") == "translation.finalize":
                return step
        return None

    def _get_or_create_finalize_step(
        self,
        *,
        workflow_run_id: int,
        step_definition: dict[str, object],
        model_profile_id: str,
        provider_model_name: str | None,
        request_id: str,
        stage_run_id: int,
    ) -> WorkflowStepRun:
        step_key = str(step_definition.get("step_key") or "finalize_segments")
        step = self.session.execute(
            select(WorkflowStepRun).where(
                WorkflowStepRun.workflow_run_id == workflow_run_id,
                WorkflowStepRun.step_key == step_key,
            )
        ).scalars().first()
        step_summary = json.dumps(
            {
                "request_id": request_id,
                "stage_run_id": stage_run_id,
                "provider_model_name": provider_model_name,
                "recovery": "resume_finalize",
            },
            ensure_ascii=False,
        )
        if step is not None:
            step.status = "running"
            step.output_payload = None
            step.summary = step_summary
            self.session.flush()
            return step
        step = WorkflowStepRun(
            workflow_run_id=workflow_run_id,
            step_key=step_key,
            action="translation.finalize",
            llm_role=str(step_definition.get("llm_role") or "finalizer"),
            model_profile_id=model_profile_id,
            status="running",
            input_ref=json.dumps({"workflow_run_id": workflow_run_id, "recovery": "resume_finalize"}, ensure_ascii=False),
            output_payload=None,
            summary=step_summary,
        )
        self.session.add(step)
        self.session.flush()
        return step

    def _decode_json_object(self, value: str | None) -> dict[str, object]:
        if value is None or value == "":
            return {}
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _parse_optional_int(self, value: object) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

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

    def _should_enable_parallel_segments(self, workflow_definition: dict[str, object]) -> bool:
        definition_json = workflow_definition.get("definition_json", {})
        if not isinstance(definition_json, dict):
            return False
        explicit_parallel = definition_json.get("parallel_segments")
        if isinstance(explicit_parallel, bool):
            return explicit_parallel
        steps = definition_json.get("steps", [])
        if not isinstance(steps, list):
            return False

        generate_draft_count = 0
        for step in steps:
            if not isinstance(step, dict):
                continue
            action = str(step.get("action") or "").strip()
            if action == "translation.generate_draft":
                generate_draft_count += 1
            if action in {"translation.review_draft", "translation.rewrite_draft"}:
                return True
            failure_mode = str(step.get("failure_mode") or "required").strip().lower()
            if action.startswith("translation.") and failure_mode != "required":
                return True
        return generate_draft_count > 1
