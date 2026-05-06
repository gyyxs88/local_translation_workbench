from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from ..db.models import StageRun
from ..errors import ToolError
from ..repositories.synopsis import ProjectSynopsisRepository
from ..text_counting import build_text_count_payload
from .stage_completion_report_service import StageCompletionReportService


def build_stage_run_response(
    *,
    session,
    project_id: int,
    stage: str,
    scope: dict[str, object],
    result,
    request_id: str | None = None,
) -> dict[str, Any]:
    normalized_stage = stage.lower()
    data: dict[str, Any] = {
        "project_id": project_id,
        "stage": normalized_stage,
        "scope": scope,
    }

    if normalized_stage == "chaptering":
        data["chapter_count"] = result.chapter_count
        data["segment_count"] = result.segment_count
        data["synopsis"] = (
            result.synopsis_summary
            if result.synopsis_summary is not None
            else _load_synopsis_summary(session=session, project_id=project_id)
        )
    elif normalized_stage == "glossary":
        data["candidate_count"] = result.candidate_count
    elif normalized_stage == "translation":
        data["translated_segments"] = result.translated_segments
        data["active_version_ids"] = result.active_version_ids
        data["synopsis"] = (
            result.synopsis_summary
            if result.synopsis_summary is not None
            else _load_synopsis_summary(session=session, project_id=project_id)
        )
    elif normalized_stage == "review":
        data["issue_count"] = result.issue_count
        data["run_id"] = result.run_id
        data["mode"] = result.mode
        data["passed_segment_count"] = result.passed_segment_count
        data["needs_revision_segment_count"] = result.needs_revision_segment_count
        data["rewrite_segment_count"] = result.rewrite_segment_count
        data["rewrite_version_ids"] = result.rewrite_version_ids or []
        if result.token_usage is not None:
            data["token_usage"] = result.token_usage
    elif normalized_stage == "export":
        data["artifact_count"] = result.artifact_count
        data["manifest_path"] = result.manifest_path
        data["run_id"] = result.run_id
        data["synopsis"] = _load_synopsis_summary(session=session, project_id=project_id)
    else:
        raise ToolError(
            code="invalid_arguments",
            message="目前只支持 stage=chaptering、glossary、translation、review 或 export。",
            status=400,
        )

    stage_run_payload = _load_stage_run_report(
        session=session,
        project_id=project_id,
        stage=normalized_stage,
        request_id=request_id,
    )
    if stage_run_payload is not None:
        data.update(stage_run_payload)

    return {
        "ok": True,
        "action": "stage.run",
        "data": data,
    }


def _load_synopsis_summary(*, session, project_id: int) -> dict[str, dict[str, Any]]:
    synopsis = ProjectSynopsisRepository(session).get_by_project_id(project_id)
    if synopsis is None:
        return {
            "source": {"status": "missing", "origin": None, **build_text_count_payload(None)},
            "target": {"status": "missing", "origin": None, **build_text_count_payload(None)},
        }
    return {
        "source": {
            "status": synopsis.source_synopsis_status,
            "origin": synopsis.source_synopsis_origin if synopsis.source_synopsis_origin is not None else None,
            **build_text_count_payload(synopsis.source_synopsis_text),
        },
        "target": {
            "status": synopsis.target_synopsis_status,
            "origin": synopsis.target_synopsis_origin if synopsis.target_synopsis_origin is not None else None,
            **build_text_count_payload(synopsis.target_synopsis_text),
        },
    }


def _load_stage_run_report(
    *,
    session,
    project_id: int,
    stage: str,
    request_id: str | None,
) -> dict[str, object] | None:
    if request_id is None or not hasattr(session, "execute"):
        return None
    statement = (
        select(StageRun)
        .where(StageRun.project_id == project_id, StageRun.stage == stage)
        .order_by(StageRun.id.desc())
        .limit(20)
    )
    for stage_run in session.execute(statement).scalars().all():
        summary_payload = _decode_summary_payload(stage_run.summary)
        if not isinstance(summary_payload, dict) or summary_payload.get("request_id") != request_id:
            continue
        report = summary_payload.get("stage_report")
        if not isinstance(report, dict):
            report = StageCompletionReportService(session).build_stage_report(
                stage_run=stage_run,
                summary_payload=summary_payload,
            )
        return {
            "stage_run_id": int(stage_run.id),
            "stage_report": dict(report),
        }
    return None


def _decode_summary_payload(raw_summary: str | None) -> dict[str, object] | None:
    if raw_summary is None or raw_summary == "":
        return None
    try:
        payload = json.loads(raw_summary)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
