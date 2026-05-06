from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from tools.local_translation_workbench.app.db.models import (
    Chapter,
    ReviewIssue,
    ReviewRun,
    StageRun,
    TranslationProject,
    WorkflowRun,
    WorkflowStepRun,
)
from tools.local_translation_workbench.app.services.glossary_service import GlossaryResult
from tools.local_translation_workbench.app.services.stage_completion_report_service import (
    StageCompletionReportService,
)
from tools.local_translation_workbench.app.services.stage_run_response_service import build_stage_run_response
from tools.local_translation_workbench.app.services.stage_service import StageCommand
from tools.local_translation_workbench.app.services.stage_run_orchestrator_service import (
    StageRunOrchestratorService,
)


def test_stage_orchestrator_stores_completion_report_for_degraded_workflow(
    db_session,
    tmp_path: Path,
) -> None:
    project = TranslationProject(
        request_id="stage-report-project",
        project_key="stage-report-project",
        source_path="source.txt",
        source_language="zh",
        target_language="en",
        status="created",
    )
    db_session.add(project)
    db_session.commit()
    runner = StageRunOrchestratorService(db_session, base_data_dir=tmp_path)

    def dispatch(**kwargs):  # type: ignore[no-untyped-def]
        stage_run_id = int(kwargs["stage_run_id"])
        workflow_run = WorkflowRun(
            workflow_key="glossary_multi_llm_v1",
            project_id=project.id,
            stage="glossary",
            scope_type="all",
            scope_value=json.dumps({"type": "all"}, ensure_ascii=False),
            request_id="stage-report-run",
            status="insufficient_evidence",
            summary=json.dumps(
                {
                    "request_id": "stage-report-run",
                    "workflow_key": "glossary_multi_llm_v1",
                    "stage_run_id": stage_run_id,
                    "degraded": True,
                    "degradation_reason": "low_confidence",
                    "degradation_events": [
                        {
                            "failure_mode": "tolerant",
                            "minimum_success": 1,
                            "success_count": 1,
                            "failed_step_keys": ["extract_secondary"],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        )
        db_session.add(workflow_run)
        db_session.flush()
        db_session.add_all(
            [
                WorkflowStepRun(
                    workflow_run_id=workflow_run.id,
                    step_key="extract_primary",
                    action="glossary.extract",
                    llm_role="extractor",
                    model_profile_id="gpt_5_5_aicodelink",
                    status="completed",
                    input_ref="{}",
                    output_payload={"draft_candidate_count": 2},
                    summary=None,
                ),
                WorkflowStepRun(
                    workflow_run_id=workflow_run.id,
                    step_key="extract_secondary",
                    action="glossary.extract",
                    llm_role="extractor",
                    model_profile_id="deepseek_v4_pro",
                    status="failed",
                    input_ref="{}",
                    output_payload={
                        "skipped_chapter_count": 1,
                        "skipped_chapters": [
                            {"chapter_index": 3, "code": "provider_error", "message": "timeout"}
                        ],
                    },
                    summary=json.dumps({"error": {"message": "timeout"}}, ensure_ascii=False),
                ),
            ]
        )
        db_session.flush()
        return GlossaryResult(candidate_count=2)

    result = runner.run(
        command=StageCommand(
            request_id="stage-report-run",
            project_id=project.id,
            stage="glossary",
            scope={"type": "all"},
        ),
        dispatch=dispatch,
    )
    stage_run = db_session.execute(
        select(StageRun).where(StageRun.project_id == project.id, StageRun.stage == "glossary")
    ).scalar_one()
    summary = json.loads(stage_run.summary or "{}")
    report = summary["stage_report"]

    assert result.candidate_count == 2
    assert report["status"] == "warning"
    assert report["degradation"]["degraded"] is True
    assert report["degradation"]["failed_step_keys"] == ["extract_secondary"]
    assert [problem["code"] for problem in report["problems"]] == [
        "workflow_degraded",
        "workflow_step_failed",
        "glossary_chapters_skipped",
    ]


def test_stage_completion_report_aggregates_review_issues(db_session) -> None:
    project = TranslationProject(
        request_id="review-report-project",
        project_key="review-report-project",
        source_path="source.txt",
        source_language="zh",
        target_language="en",
        status="created",
    )
    db_session.add(project)
    db_session.flush()
    chapters = [
        Chapter(
            project_id=project.id,
            chapter_index=1,
            chapter_title="第1章",
            source_path="source/chapter-1.txt",
            normalized_path="source/chapter-1.normalized.txt",
        ),
        Chapter(
            project_id=project.id,
            chapter_index=2,
            chapter_title="第2章",
            source_path="source/chapter-2.txt",
            normalized_path="source/chapter-2.normalized.txt",
        ),
    ]
    db_session.add_all(chapters)
    db_session.flush()
    stage_run = StageRun(
        project_id=project.id,
        stage="review",
        scope_type="all",
        scope_value=json.dumps({"type": "all"}, ensure_ascii=False),
        status="completed",
        summary=None,
    )
    review_run = ReviewRun(
        project_id=project.id,
        scope_type="all",
        scope_value=json.dumps({"type": "all"}, ensure_ascii=False),
        status="completed",
        summary=None,
    )
    db_session.add_all([stage_run, review_run])
    db_session.flush()
    db_session.add_all(
        [
            ReviewIssue(
                project_id=project.id,
                review_run_id=review_run.id,
                chapter_id=chapters[0].id,
                segment_id=None,
                version_id=None,
                issue_type="glossary_term_missing",
                severity="high",
                message="缺少术语译名",
                issue_source="hard",
                requires_rewrite=True,
            ),
            ReviewIssue(
                project_id=project.id,
                review_run_id=review_run.id,
                chapter_id=chapters[1].id,
                segment_id=None,
                version_id=None,
                issue_type="unchanged_translation",
                severity="medium",
                message="译文疑似未翻译",
                issue_source="hard",
                requires_rewrite=False,
            ),
        ]
    )
    db_session.flush()
    summary = {
        "request_id": "review-report-run",
        "run_id": int(review_run.id),
        "issue_count": 2,
        "needs_revision_segment_count": 1,
    }

    report = StageCompletionReportService(db_session).build_stage_report(
        stage_run=stage_run,
        summary_payload=summary,
    )

    assert report["status"] == "warning"
    assert report["problem_count"] == 1
    problem = report["problems"][0]
    assert problem["code"] == "review_issues"
    assert problem["details"]["issue_type_counts"] == {
        "glossary_term_missing": 1,
        "unchanged_translation": 1,
    }
    assert problem["details"]["issues"][0]["message"] == "缺少术语译名"


def test_stage_run_response_includes_stored_stage_report(db_session) -> None:
    project = TranslationProject(
        request_id="response-report-project",
        project_key="response-report-project",
        source_path="source.txt",
        source_language="zh",
        target_language="en",
        status="created",
    )
    db_session.add(project)
    db_session.flush()
    stage_run = StageRun(
        project_id=project.id,
        stage="glossary",
        scope_type="all",
        scope_value=json.dumps({"type": "all"}, ensure_ascii=False),
        status="completed",
        summary=json.dumps(
            {
                "request_id": "response-report-run",
                "candidate_count": 0,
                "stage_report": {
                    "schema_version": 1,
                    "status": "ok",
                    "problem_count": 0,
                    "problems": [],
                    "degradation": {"degraded": False},
                },
            },
            ensure_ascii=False,
        ),
    )
    db_session.add(stage_run)
    db_session.flush()

    payload = build_stage_run_response(
        session=db_session,
        project_id=project.id,
        stage="glossary",
        scope={"type": "all"},
        result=GlossaryResult(candidate_count=0),
        request_id="response-report-run",
    )

    assert payload["data"]["stage_run_id"] == stage_run.id
    assert payload["data"]["stage_report"]["status"] == "ok"
