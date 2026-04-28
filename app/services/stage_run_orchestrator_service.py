from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..db.models import StageRun, TranslationProject
from ..errors import ToolError
from ..providers.base import Provider
from ..repositories.workflows import WorkflowRepository
from ..token_usage import merge_token_usage_payloads, normalize_token_usage_payload
from .chaptering_service import ChapteringResult
from .export_service import ExportResult
from .glossary_service import GlossaryResult
from .idempotency_service import IdempotencyService
from .lease_service import LeaseService
from .review_service import ReviewResult
from .scope_service import ensure_scope_supported, get_stage_scope_types
from .translation_service import TranslationResult
from .workflow_runtime_service import WorkflowRuntimeService

if TYPE_CHECKING:
    from .stage_service import StageCommand


StageResult = ChapteringResult | GlossaryResult | TranslationResult | ReviewResult | ExportResult


class StageRunOrchestratorService:
    def __init__(self, session: Session, *, base_data_dir: Path, provider: Provider | None = None) -> None:
        self.session = session
        self.base_data_dir = Path(base_data_dir)
        self.provider = provider
        self.leases = LeaseService(session)
        self.idempotency = IdempotencyService(session)
        self.workflows = WorkflowRepository(session)

    def run(
        self,
        *,
        command: StageCommand,
        dispatch: Callable[..., StageResult],
    ) -> StageResult:
        started_at = datetime.now(timezone.utc)
        project = self.session.get(TranslationProject, command.project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {command.project_id}。", status=404)
        if project.status == "cancelled":
            raise ToolError(
                code="conflict_error",
                message=f"项目 {command.project_id} 已 cancelled，不能继续执行 stage.run。",
                status=409,
            )
        ensure_scope_supported(
            command.scope,
            stage=command.stage,
            allowed_types=get_stage_scope_types(command.stage),
        )

        latest_run = self._find_latest_matching_stage_run(
            project_id=command.project_id,
            stage=command.stage,
            scope=command.scope,
        )
        recovery_target = self._validate_recovery_policy(command=command, latest_run=latest_run)

        lease_owner = f"stage.run:{command.stage.lower()}:{command.request_id}"
        lease = self.leases.acquire(
            project_id=command.project_id,
            lease_owner=lease_owner,
            ttl_seconds=600,
        )
        try:
            record = self.idempotency.record(
                request_id=command.request_id,
                operation_name=f"stage.run:{command.stage}",
                project_id=command.project_id,
            )
            if not record.created:
                replay_run = self._find_stage_run_by_request(
                    project_id=command.project_id,
                    stage=command.stage,
                    request_id=command.request_id,
                )
                if replay_run is None:
                    raise ToolError(
                        code="conflict_error",
                        message=f"请求 {command.request_id} 已存在，但找不到对应的阶段结果。",
                        status=409,
                    )
                return self._replay_existing_result(stage=command.stage, stage_run=replay_run)

            precreated_run = self._create_stage_run(
                project_id=command.project_id,
                stage=command.stage,
                scope=command.scope,
                status="running",
                summary=self._build_stage_summary(
                    command=command,
                    recovery_target=recovery_target,
                    started_at=started_at,
                ),
            )
            self.session.commit()

            try:
                result = dispatch(
                    project=project,
                    command=command,
                    stage_run_id=precreated_run.id,
                    heartbeat=self._build_heartbeat(
                        project_id=command.project_id,
                        lease_owner=lease_owner,
                        lease_token=lease.lease_token,
                        ttl_seconds=600,
                    ),
                )
            except Exception as exc:
                self.session.rollback()
                workflow_failure_context = getattr(exc, "_workflow_failure_context", None)
                if workflow_failure_context is not None:
                    WorkflowRuntimeService(self.session).persist_failure_context(workflow_failure_context)
                failure_summary_extra = self._build_failure_summary_extra(
                    command=command,
                    stage_run_id=precreated_run.id,
                    error=exc,
                )
                failed_run = self.session.get(StageRun, precreated_run.id)
                if failed_run is None:
                    failed_run = self._create_stage_run(
                        project_id=command.project_id,
                        stage=command.stage,
                        scope=command.scope,
                        status="failed",
                        summary=self._build_stage_summary(
                            command=command,
                            recovery_target=recovery_target,
                            error=exc,
                            started_at=started_at,
                            finished_at=datetime.now(timezone.utc),
                            extra_summary=failure_summary_extra,
                        ),
                    )
                else:
                    failed_run.status = "failed"
                    failed_run.summary = self._build_stage_summary(
                        command=command,
                        recovery_target=recovery_target,
                        error=exc,
                        started_at=started_at,
                        finished_at=datetime.now(timezone.utc),
                        extra_summary=failure_summary_extra,
                    )
                self.session.commit()
                raise

            completed_run = self.session.get(StageRun, precreated_run.id)
            if completed_run is not None:
                completed_run.status = "completed"
                completed_run.summary = self._build_stage_summary(
                    command=command,
                    recovery_target=recovery_target,
                    result=result,
                    existing_summary=completed_run.summary,
                    started_at=started_at,
                    finished_at=datetime.now(timezone.utc),
                )
                self.session.commit()
            return result
        finally:
            self.leases.release(
                project_id=command.project_id,
                lease_owner=lease_owner,
                lease_token=lease.lease_token,
            )

    def _validate_recovery_policy(self, *, command: StageCommand, latest_run: StageRun | None) -> StageRun | None:
        if command.resume and command.rerun:
            raise ToolError(
                code="invalid_arguments",
                message="resume 和 rerun 不能同时指定。",
                status=400,
            )

        if command.resume:
            if latest_run is None:
                raise ToolError(
                    code="invalid_arguments",
                    message=f"项目 {command.project_id} 当前没有可 resume 的 {command.stage} 运行。",
                    status=400,
                )
            if latest_run.status not in {"running", "failed"}:
                raise ToolError(
                    code="invalid_arguments",
                    message=f"最近一次 {command.stage} 运行状态为 {latest_run.status}，不能 resume，请改用 rerun。",
                    status=400,
                )
            return latest_run

        if latest_run is not None and latest_run.status == "running":
            raise ToolError(
                code="conflict_error",
                message=f"项目 {command.project_id} 最近一次 {command.stage} 运行仍未完成，请显式使用 resume 或 rerun。",
                status=409,
            )

        return latest_run if command.rerun else None

    def _find_latest_matching_stage_run(
        self,
        *,
        project_id: int,
        stage: str,
        scope: dict[str, object],
    ) -> StageRun | None:
        statement = (
            select(StageRun)
            .where(StageRun.project_id == project_id, StageRun.stage == stage.lower())
            .order_by(StageRun.id.desc())
        )
        for stage_run in self.session.execute(statement).scalars().all():
            if self._decode_summary(stage_run.scope_value) == scope:
                return stage_run
        return None

    def _find_stage_run_by_request(self, *, project_id: int, stage: str, request_id: str) -> StageRun | None:
        statement = (
            select(StageRun)
            .where(StageRun.project_id == project_id, StageRun.stage == stage.lower())
            .order_by(StageRun.id.desc())
        )
        for stage_run in self.session.execute(statement).scalars().all():
            summary = self._decode_summary(stage_run.summary)
            if isinstance(summary, dict) and summary.get("request_id") == request_id:
                return stage_run
        return None

    def _create_stage_run(
        self,
        *,
        project_id: int,
        stage: str,
        scope: dict[str, object],
        status: str,
        summary: str,
    ) -> StageRun:
        stage_run = StageRun(
            project_id=project_id,
            stage=stage.lower(),
            scope_type=str(scope["type"]),
            scope_value=json.dumps(scope, ensure_ascii=False),
            status=status,
            summary=summary,
        )
        self.session.add(stage_run)
        self.session.flush()
        return stage_run

    def _build_stage_summary(
        self,
        *,
        command: StageCommand,
        recovery_target: StageRun | None,
        result: StageResult | None = None,
        existing_summary: str | None = None,
        error: Exception | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        extra_summary: dict[str, object] | None = None,
    ) -> str:
        payload: dict[str, object] = {}
        existing_payload = self._decode_summary(existing_summary)
        if isinstance(existing_payload, dict):
            payload.update(existing_payload)

        payload["request_id"] = command.request_id
        payload["model_profile_id"] = command.model_profile_id
        if command.workflow_key is not None:
            payload["workflow_key"] = command.workflow_key
        if command.route_preset_key is not None:
            payload["route_preset_key"] = command.route_preset_key
        payload["resume"] = command.resume
        payload["rerun"] = command.rerun
        if recovery_target is not None:
            key = "resume_from_run_id" if command.resume else "rerun_from_run_id"
            payload[key] = recovery_target.id

        started_at_value = (
            self._serialize_timestamp(started_at)
            if started_at is not None
            else payload.get("started_at")
        )
        if isinstance(started_at_value, str) and started_at_value:
            payload["started_at"] = started_at_value

        if finished_at is not None:
            payload["finished_at"] = self._serialize_timestamp(finished_at)
            duration_ms = self._compute_duration_ms(
                started_at=None if not isinstance(payload.get("started_at"), str) else str(payload["started_at"]),
                finished_at=finished_at,
            )
            if duration_ms is not None:
                payload["duration_ms"] = duration_ms

        if result is not None:
            payload.update(self._result_to_summary_payload(result))

        if extra_summary:
            payload.update(extra_summary)

        if error is not None:
            if isinstance(error, ToolError):
                payload["error"] = {
                    "code": error.code,
                    "message": error.message,
                    "status": error.status,
                }
            else:
                payload["error"] = {
                    "code": "system_error",
                    "message": str(error),
                }

        return json.dumps(payload, ensure_ascii=False)

    def _result_to_summary_payload(self, result: StageResult) -> dict[str, object]:
        if isinstance(result, ChapteringResult):
            return {
                "chapter_count": result.chapter_count,
                "segment_count": result.segment_count,
                "synopsis_summary": result.synopsis_summary,
            }
        if isinstance(result, GlossaryResult):
            return {
                "candidate_count": result.candidate_count,
                **({"token_usage": result.token_usage} if result.token_usage is not None else {}),
            }
        if isinstance(result, TranslationResult):
            return {
                "translated_segments": result.translated_segments,
                "active_version_ids": result.active_version_ids,
                "synopsis_summary": result.synopsis_summary,
                **({"token_usage": result.token_usage} if result.token_usage is not None else {}),
            }
        if isinstance(result, ReviewResult):
            return {
                "issue_count": result.issue_count,
                "run_id": result.run_id,
                "mode": result.mode,
                "passed_segment_count": result.passed_segment_count,
                "needs_revision_segment_count": result.needs_revision_segment_count,
                "rewrite_segment_count": result.rewrite_segment_count,
                "rewrite_version_ids": result.rewrite_version_ids or [],
                **({"token_usage": result.token_usage} if result.token_usage is not None else {}),
            }
        return {
            "manifest_path": result.manifest_path,
            "artifact_count": result.artifact_count,
            "run_id": result.run_id,
        }

    def _replay_existing_result(self, *, stage: str, stage_run: StageRun) -> StageResult:
        if stage_run.status != "completed":
            raise ToolError(
                code="conflict_error",
                message=f"重复请求对应的 {stage} 运行状态为 {stage_run.status}，请使用新的 request_id。",
                status=409,
            )

        summary = self._decode_summary(stage_run.summary)
        if not isinstance(summary, dict):
            raise ToolError(
                code="conflict_error",
                message=f"重复请求对应的 {stage} 运行缺少可复用摘要。",
                status=409,
            )

        normalized_stage = stage.lower()
        if normalized_stage == "chaptering":
            return ChapteringResult(
                chapter_count=int(summary["chapter_count"]),
                segment_count=int(summary["segment_count"]),
                synopsis_summary=summary.get("synopsis_summary") if isinstance(summary.get("synopsis_summary"), dict) else None,
            )
        if normalized_stage == "glossary":
            return GlossaryResult(
                candidate_count=int(summary["candidate_count"]),
                token_usage=normalize_token_usage_payload(summary.get("token_usage")),
            )
        if normalized_stage == "translation":
            return TranslationResult(
                translated_segments=int(summary["translated_segments"]),
                active_version_ids=[int(item) for item in summary.get("active_version_ids", [])],
                synopsis_summary=summary.get("synopsis_summary") if isinstance(summary.get("synopsis_summary"), dict) else None,
                token_usage=normalize_token_usage_payload(summary.get("token_usage")),
            )
        if normalized_stage == "review":
            return ReviewResult(
                issue_count=int(summary["issue_count"]),
                run_id=int(summary["run_id"]),
                mode=str(summary.get("mode") or "hard_only"),
                passed_segment_count=int(summary.get("passed_segment_count") or 0),
                needs_revision_segment_count=int(summary.get("needs_revision_segment_count") or 0),
                rewrite_segment_count=int(summary.get("rewrite_segment_count") or 0),
                rewrite_version_ids=[int(item) for item in summary.get("rewrite_version_ids", [])],
                token_usage=normalize_token_usage_payload(summary.get("token_usage")),
            )
        return ExportResult(
            manifest_path=str(summary["manifest_path"]),
            artifact_count=int(summary["artifact_count"]),
            run_id=int(summary["run_id"]),
        )

    def _decode_summary(self, value: str | None) -> object:
        if value is None or value == "":
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    def _serialize_timestamp(self, value: datetime) -> str:
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return normalized.astimezone(timezone.utc).isoformat(timespec="seconds")

    def _compute_duration_ms(self, *, started_at: str | None, finished_at: datetime) -> int | None:
        if started_at is None:
            return None
        try:
            started_at_value = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        except ValueError:
            return None
        if started_at_value.tzinfo is None:
            started_at_value = started_at_value.replace(tzinfo=timezone.utc)
        duration_ms = int((finished_at - started_at_value.astimezone(timezone.utc)).total_seconds() * 1000)
        return max(duration_ms, 0)

    def _build_failure_summary_extra(
        self,
        *,
        command: StageCommand,
        stage_run_id: int,
        error: Exception,
    ) -> dict[str, object]:
        stage_token_usage = normalize_token_usage_payload(getattr(error, "_stage_token_usage", None))
        workflow_token_usage = self._load_workflow_token_usage(
            project_id=command.project_id,
            stage=command.stage,
            request_id=command.request_id,
            stage_run_id=stage_run_id,
        )
        merged_token_usage = merge_token_usage_payloads(
            [usage for usage in [stage_token_usage, workflow_token_usage] if usage is not None]
        )
        if merged_token_usage is None:
            return {}
        return {"token_usage": merged_token_usage}

    def _load_workflow_token_usage(
        self,
        *,
        project_id: int,
        stage: str,
        request_id: str,
        stage_run_id: int,
    ) -> dict[str, int] | None:
        workflow_run = self.workflows.find_latest_run_for_stage_context(
            project_id=project_id,
            stage=stage,
            request_id=request_id,
            stage_run_id=stage_run_id,
        )
        if workflow_run is None:
            return None
        summary_payload = self._decode_summary(workflow_run.summary)
        if not isinstance(summary_payload, dict):
            return None
        return normalize_token_usage_payload(summary_payload.get("token_usage"))

    def _build_heartbeat(
        self,
        *,
        project_id: int,
        lease_owner: str,
        lease_token: str,
        ttl_seconds: int,
    ) -> Callable[[], None]:
        def keepalive() -> None:
            if hasattr(self.leases, "refresh") and self.leases.__class__ is not LeaseService:
                self.leases.refresh(
                    project_id=project_id,
                    lease_owner=lease_owner,
                    lease_token=lease_token,
                    ttl_seconds=ttl_seconds,
                )
                return

            factory = sessionmaker(bind=self.session.get_bind(), future=True)
            lease_session = factory()
            try:
                LeaseService(lease_session).refresh(
                    project_id=project_id,
                    lease_owner=lease_owner,
                    lease_token=lease_token,
                    ttl_seconds=ttl_seconds,
                )
            finally:
                lease_session.close()

        return keepalive
