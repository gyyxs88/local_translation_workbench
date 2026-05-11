from __future__ import annotations

import json
from collections import Counter
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import ReviewIssue, StageRun, WorkflowRun, WorkflowStepRun
from ..repositories.review import ReviewRepository
from ..repositories.workflows import WorkflowRepository


class StageCompletionReportService:
    MAX_ITEMS = 20

    def __init__(self, session: Session) -> None:
        self.session = session
        self.workflows = WorkflowRepository(session)
        self.reviews = ReviewRepository(session)

    def build_stage_report(
        self,
        *,
        stage_run: StageRun,
        summary_payload: Mapping[str, object] | None,
    ) -> dict[str, object]:
        summary = dict(summary_payload or {})
        workflow_run = self._resolve_workflow_run(stage_run=stage_run, summary_payload=summary)
        workflow_summary = self._decode_json_object(None if workflow_run is None else workflow_run.summary)
        problems: list[dict[str, object]] = []

        stage_problem = self._build_stage_status_problem(stage_run=stage_run, summary_payload=summary)
        if stage_problem is not None:
            problems.append(stage_problem)

        if workflow_run is not None:
            problems.extend(
                self._build_workflow_problems(
                    stage_run=stage_run,
                    workflow_run=workflow_run,
                    workflow_summary=workflow_summary,
                )
            )

        if stage_run.stage == "review":
            review_problem = self._build_review_issue_problem(summary_payload=summary)
            if review_problem is not None:
                problems.append(review_problem)

        return {
            "schema_version": 1,
            "status": self._resolve_report_status(stage_status=stage_run.status, problems=problems),
            "problem_count": len(problems),
            "problems": problems,
            "degradation": self._build_degradation_payload(
                workflow_run=workflow_run,
                workflow_summary=workflow_summary,
            ),
        }

    def _build_stage_status_problem(
        self,
        *,
        stage_run: StageRun,
        summary_payload: Mapping[str, object],
    ) -> dict[str, object] | None:
        if stage_run.status not in {"failed", "cancelled"}:
            return None
        error = summary_payload.get("error")
        error_payload = dict(error) if isinstance(error, Mapping) else {}
        code = "stage_cancelled" if stage_run.status == "cancelled" else "stage_failed"
        return {
            "code": code,
            "severity": "warning" if stage_run.status == "cancelled" else "error",
            "source": "stage",
            "message": error_payload.get("message") or f"{stage_run.stage} 阶段状态为 {stage_run.status}。",
            "details": {
                "stage_run_id": int(stage_run.id),
                "stage": str(stage_run.stage),
                "error": error_payload or None,
            },
        }

    def _build_workflow_problems(
        self,
        *,
        stage_run: StageRun,
        workflow_run: WorkflowRun,
        workflow_summary: Mapping[str, object],
    ) -> list[dict[str, object]]:
        problems: list[dict[str, object]] = []
        if bool(workflow_summary.get("degraded")) or workflow_run.status == "insufficient_evidence":
            events = self._read_mapping_list(workflow_summary.get("degradation_events"))
            failed_step_keys = self._collect_failed_step_keys(events=events, workflow_run=workflow_run)
            problems.append(
                {
                    "code": "workflow_degraded",
                    "severity": "warning",
                    "source": "workflow",
                    "message": f"{stage_run.stage} workflow 降级完成，结果可信度需要复核。",
                    "details": {
                        "workflow_run_id": int(workflow_run.id),
                        "workflow_key": str(workflow_run.workflow_key),
                        "workflow_status": str(workflow_run.status),
                        "degradation_reason": workflow_summary.get("degradation_reason"),
                        "failed_step_keys": failed_step_keys,
                        "events": events[: self.MAX_ITEMS],
                    },
                }
            )

        failed_steps = self._list_failed_steps(workflow_run=workflow_run)
        if failed_steps:
            severity = "warning" if workflow_run.status == "insufficient_evidence" else "error"
            problems.append(
                {
                    "code": "workflow_step_failed",
                    "severity": severity,
                    "source": "workflow",
                    "message": f"{len(failed_steps)} 个 workflow step 失败。",
                    "details": {
                        "workflow_run_id": int(workflow_run.id),
                        "failed_steps": failed_steps[: self.MAX_ITEMS],
                        "truncated": len(failed_steps) > self.MAX_ITEMS,
                    },
                }
            )

        skipped_chapter_items = self._collect_skipped_chapters(workflow_run=workflow_run)
        if skipped_chapter_items:
            skipped_count = sum(int(item["skipped_chapter_count"]) for item in skipped_chapter_items)
            problems.append(
                {
                    "code": "glossary_chapters_skipped",
                    "severity": "warning",
                    "source": "workflow",
                    "message": f"术语抽取跳过了 {skipped_count} 个章节。",
                    "details": {
                        "workflow_run_id": int(workflow_run.id),
                        "steps": skipped_chapter_items[: self.MAX_ITEMS],
                        "truncated": len(skipped_chapter_items) > self.MAX_ITEMS,
                    },
                }
            )

        return problems

    def _build_review_issue_problem(self, *, summary_payload: Mapping[str, object]) -> dict[str, object] | None:
        review_run_id = self._parse_optional_int(summary_payload.get("run_id"))
        issue_count = self._parse_optional_int(summary_payload.get("issue_count")) or 0
        if review_run_id is None or issue_count <= 0:
            return None

        issues = self.reviews.list_issues_for_run(review_run_id)
        issue_type_counts = Counter(str(issue.issue_type) for issue in issues)
        severity_counts = Counter(str(issue.severity) for issue in issues)
        issue_source_counts = Counter(str(issue.issue_source) for issue in issues)
        needs_revision_count = self._parse_optional_int(summary_payload.get("needs_revision_segment_count")) or 0
        return {
            "code": "review_issues",
            "severity": "warning",
            "source": "review",
            "message": f"审校发现 {issue_count} 个问题，{needs_revision_count} 个分片需要修订。",
            "details": {
                "review_run_id": review_run_id,
                "issue_count": issue_count,
                "needs_revision_segment_count": needs_revision_count,
                "issue_type_counts": dict(issue_type_counts),
                "severity_counts": dict(severity_counts),
                "issue_source_counts": dict(issue_source_counts),
                "issues": [self._serialize_review_issue(issue) for issue in issues[: self.MAX_ITEMS]],
                "truncated": len(issues) > self.MAX_ITEMS,
            },
        }

    def _build_degradation_payload(
        self,
        *,
        workflow_run: WorkflowRun | None,
        workflow_summary: Mapping[str, object],
    ) -> dict[str, object]:
        if workflow_run is None:
            return {"degraded": False, "workflow_run_id": None, "workflow_status": None, "events": []}
        events = self._read_mapping_list(workflow_summary.get("degradation_events"))
        degraded = bool(workflow_summary.get("degraded")) or workflow_run.status == "insufficient_evidence"
        return {
            "degraded": degraded,
            "workflow_run_id": int(workflow_run.id),
            "workflow_status": str(workflow_run.status),
            "degradation_reason": workflow_summary.get("degradation_reason"),
            "failed_step_keys": self._collect_failed_step_keys(events=events, workflow_run=workflow_run),
            "events": events[: self.MAX_ITEMS],
            "truncated": len(events) > self.MAX_ITEMS,
        }

    def _resolve_workflow_run(
        self,
        *,
        stage_run: StageRun,
        summary_payload: Mapping[str, object],
    ) -> WorkflowRun | None:
        workflow_run_id = self._parse_optional_int(summary_payload.get("workflow_run_id"))
        if workflow_run_id is not None:
            workflow_run = self.session.get(WorkflowRun, workflow_run_id)
            if workflow_run is not None and int(workflow_run.project_id) == int(stage_run.project_id):
                return workflow_run

        request_id = None if summary_payload.get("request_id") is None else str(summary_payload["request_id"])
        workflow_run = self.workflows.find_latest_run_for_stage_context(
            project_id=int(stage_run.project_id),
            stage=str(stage_run.stage),
            request_id=request_id,
            stage_run_id=int(stage_run.id),
        )
        if workflow_run is not None:
            return workflow_run

        statement = (
            select(WorkflowRun)
            .where(
                WorkflowRun.project_id == stage_run.project_id,
                WorkflowRun.stage == stage_run.stage,
            )
            .order_by(WorkflowRun.id.desc())
        )
        if request_id is not None:
            statement = statement.where(WorkflowRun.request_id == request_id)
        return self.session.execute(statement).scalars().first()

    def _list_failed_steps(self, *, workflow_run: WorkflowRun) -> list[dict[str, object]]:
        failed_steps = self.workflows.list_failed_steps_for_run(int(workflow_run.id))
        return [self._serialize_failed_step(step) for step in failed_steps]

    def _serialize_failed_step(self, step: WorkflowStepRun) -> dict[str, object]:
        summary_payload = self._decode_json_object(step.summary)
        output_payload = step.output_payload if isinstance(step.output_payload, dict) else {}
        return {
            "step_run_id": int(step.id),
            "step_key": str(step.step_key),
            "action": str(step.action),
            "model_profile_id": str(step.model_profile_id),
            "message": self._resolve_step_error_message(summary_payload=summary_payload, output_payload=output_payload),
        }

    def _resolve_step_error_message(
        self,
        *,
        summary_payload: Mapping[str, object],
        output_payload: Mapping[str, object],
    ) -> str | None:
        for payload in (summary_payload, output_payload):
            error = payload.get("error")
            if isinstance(error, Mapping):
                message = error.get("message")
                if message not in {None, ""}:
                    return str(message)
            message = payload.get("message")
            if message not in {None, ""}:
                return str(message)
        return None

    def _collect_skipped_chapters(self, *, workflow_run: WorkflowRun) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        step_ids = list(
            self.session.execute(
                select(WorkflowStepRun.id)
                .where(WorkflowStepRun.workflow_run_id == workflow_run.id)
                .order_by(WorkflowStepRun.id.asc())
            ).scalars().all()
        )
        for step_id in step_ids:
            step = self.session.get(WorkflowStepRun, int(step_id))
            if step is None:
                continue
            output_payload = step.output_payload if isinstance(step.output_payload, dict) else {}
            skipped_count = self._parse_optional_int(output_payload.get("skipped_chapter_count")) or 0
            if skipped_count <= 0:
                continue
            skipped_chapters = output_payload.get("skipped_chapters")
            items.append(
                {
                    "step_run_id": int(step.id),
                    "step_key": str(step.step_key),
                    "skipped_chapter_count": skipped_count,
                    "skipped_chapters": (
                        [dict(item) for item in skipped_chapters[: self.MAX_ITEMS] if isinstance(item, Mapping)]
                        if isinstance(skipped_chapters, list)
                        else []
                    ),
                    "truncated": isinstance(skipped_chapters, list) and len(skipped_chapters) > self.MAX_ITEMS,
                }
            )
        return items

    def _collect_failed_step_keys(
        self,
        *,
        events: list[dict[str, object]],
        workflow_run: WorkflowRun,
    ) -> list[str]:
        keys: set[str] = set()
        for event in events:
            raw_keys = event.get("failed_step_keys")
            if isinstance(raw_keys, list):
                keys.update(str(item) for item in raw_keys if item not in {None, ""})
        keys.update(str(item["step_key"]) for item in self._list_failed_steps(workflow_run=workflow_run))
        return sorted(keys)

    def _serialize_review_issue(self, issue: ReviewIssue) -> dict[str, object]:
        return {
            "issue_id": int(issue.id),
            "chapter_id": int(issue.chapter_id),
            "segment_id": None if issue.segment_id is None else int(issue.segment_id),
            "version_id": None if issue.version_id is None else int(issue.version_id),
            "issue_type": str(issue.issue_type),
            "severity": str(issue.severity),
            "status": str(issue.status),
            "issue_source": str(issue.issue_source),
            "requires_rewrite": bool(issue.requires_rewrite),
            "message": self._truncate_text(issue.message),
        }

    def _resolve_report_status(self, *, stage_status: str, problems: list[dict[str, object]]) -> str:
        if stage_status in {"failed", "cancelled"}:
            return stage_status
        if any(problem.get("severity") == "error" for problem in problems):
            return "error"
        if problems:
            return "warning"
        return "ok"

    def _read_mapping_list(self, value: object) -> list[dict[str, object]]:
        if not isinstance(value, list):
            return []
        return [dict(item) for item in value if isinstance(item, Mapping)]

    def _decode_json_object(self, raw_value: str | None) -> dict[str, object]:
        if raw_value is None or raw_value == "":
            return {}
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError:
            return {}
        return dict(value) if isinstance(value, Mapping) else {}

    def _parse_optional_int(self, value: object) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _truncate_text(self, value: str, limit: int = 200) -> str:
        if len(value) <= limit:
            return value
        return f"{value[:limit]}..."
