from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from tools.local_translation_workbench.app.db.models import (
    ChapterSegment,
    SegmentTranslation,
    SegmentTranslationVersion,
    TranslationProject,
    TranslationDraftReview,
    TranslationDraftVersion,
    WorkflowRun,
    WorkflowStepRun,
)
from tools.local_translation_workbench.app.errors import ToolError
from tools.local_translation_workbench.app.providers.base import TextGenerationResult
from tools.local_translation_workbench.app.repositories.projects import ProjectService
from tools.local_translation_workbench.app.services.chaptering_service import ChapteringService
from tools.local_translation_workbench.app.services.translation_pipeline_service import TranslationPipelineService


def _prepare_translation_project_only(
    *,
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> int:
    source_file = project_workspace / "translation-workflow-source.txt"
    source_file.write_text(
        "第1章 开始\n林溪看着赵馨宁。\n\n第2章 继续\n小溪继续前进。",
        encoding="utf-8",
    )
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("translation-workflow-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )
    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("translation-workflow-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )
    return project.id


def _prepare_translation_workflow_project(
    *,
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> tuple[int, int]:
    project_id = _prepare_translation_project_only(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    workflow_run = WorkflowRun(
        workflow_key="translation_single_llm_v1",
        project_id=project_id,
        stage="translation",
        scope_type="chapter_range",
        scope_value=json.dumps({"type": "chapter_range", "start": 1, "end": 1}, ensure_ascii=False),
        request_id=request_id_factory("translation-workflow-run"),
        status="running",
        summary=None,
    )
    db_session.add(workflow_run)
    db_session.flush()
    step_run = WorkflowStepRun(
        workflow_run_id=workflow_run.id,
        step_key="generate_primary",
        action="translation.generate_draft",
        llm_role="draft_generator",
        model_profile_id="default",
        status="running",
        input_ref=json.dumps({"project_id": project_id}, ensure_ascii=False),
        output_payload=None,
        summary=None,
    )
    db_session.add(step_run)
    db_session.flush()
    return project_id, step_run.id


def test_translation_draft_version_and_review_can_be_persisted(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id, step_run_id = _prepare_translation_workflow_project(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    workflow_run = db_session.execute(
        select(WorkflowRun).where(WorkflowRun.project_id == project_id, WorkflowRun.stage == "translation")
    ).scalar_one()
    segment_id = db_session.execute(
        select(ChapterSegment.id)
        .where(ChapterSegment.project_id == project_id)
        .order_by(ChapterSegment.id.asc())
    ).scalars().first()
    assert segment_id is not None

    draft = TranslationDraftVersion(
        workflow_run_id=workflow_run.id,
        project_id=project_id,
        segment_id=segment_id,
        step_run_id=step_run_id,
        parent_draft_id=None,
        draft_role="primary",
        source_hash="source-hash-1",
        glossary_snapshot_id="glossary-hash-1",
        provider_name="fake_provider",
        model_profile_id="profile-a",
        model_name="model-a",
        translated_text="Lin Xi looked at Zhao Xinning.",
        translated_text_path="drafts/segment-1-primary.txt",
        status="completed",
        evidence_payload={"source_length": 12},
    )
    db_session.add(draft)
    db_session.flush()

    review = TranslationDraftReview(
        draft_version_id=draft.id,
        step_run_id=step_run_id,
        review_type="quality",
        decision="keep",
        score=0.92,
        reason_codes=["faithful", "glossary_consistent"],
        structured_payload={"preferred": True, "issues": []},
    )
    db_session.add(review)
    db_session.flush()

    assert draft.draft_role == "primary"
    assert draft.translated_text_path.endswith("segment-1-primary.txt")
    assert review.decision == "keep"
    assert review.structured_payload == {"preferred": True, "issues": []}


class FakeTranslationProvider:
    def __init__(
        self,
        outputs: list[str] | None = None,
        result_model_profile_ids: list[str] | None = None,
        fallback_depths: list[int] | None = None,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self.outputs = list(outputs or [])
        self.result_model_profile_ids = list(result_model_profile_ids or [])
        self.fallback_depths = list(fallback_depths or [])

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        self.calls.append({"prompt": prompt, "model_name": model_name, "timeout_seconds": timeout_seconds})
        content = self.outputs.pop(0) if self.outputs else f"[{model_name}] {prompt.rsplit(chr(10) * 2, maxsplit=1)[-1]}"
        result_model_profile_id = (
            self.result_model_profile_ids.pop(0) if self.result_model_profile_ids else None
        )
        fallback_depth = self.fallback_depths.pop(0) if self.fallback_depths else 0
        return TextGenerationResult(
            content=content,
            provider_name="fake_provider",
            model_name=model_name,
            model_profile_id=result_model_profile_id,
            fallback_depth=fallback_depth,
        )


class FailOnPrimaryDraftProvider(FakeTranslationProvider):
    def __init__(self) -> None:
        super().__init__(
            outputs=[
                "源简介内容",
                "目标简介内容",
                "Secondary draft",
                json.dumps({"reviews": []}, ensure_ascii=False),
                json.dumps({"drafts": []}, ensure_ascii=False),
            ]
        )
        self.translation_call_count = 0

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        if "翻译正文" in prompt:
            self.translation_call_count += 1
            if self.translation_call_count == 1:
                raise ToolError(code="provider_error", message="primary draft failed", status=502)
        return super().generate_text(prompt=prompt, model_name=model_name, timeout_seconds=timeout_seconds)


def test_generate_draft_writes_only_draft_versions(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id, step_run_id = _prepare_translation_workflow_project(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    workflow_run = db_session.execute(
        select(WorkflowRun).where(WorkflowRun.project_id == project_id, WorkflowRun.stage == "translation")
    ).scalar_one()
    provider = FakeTranslationProvider(outputs=["源简介内容", "目标简介内容", "Draft translation output"])

    result = TranslationPipelineService(
        db_session,
        base_data_dir=project_workspace,
        provider=provider,
    ).generate_draft(
        workflow_run_id=workflow_run.id,
        workflow_step_run_id=step_run_id,
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-draft",
        provider_model_name="model-draft",
        draft_role="primary",
    )

    drafts = db_session.execute(
        select(TranslationDraftVersion).where(TranslationDraftVersion.workflow_run_id == workflow_run.id)
    ).scalars().all()
    official_versions = db_session.execute(
        select(SegmentTranslationVersion).where(SegmentTranslationVersion.project_id == project_id)
    ).scalars().all()
    translations = db_session.execute(
        select(SegmentTranslation).where(SegmentTranslation.project_id == project_id)
    ).scalars().all()

    assert result["draft_count"] == 1
    assert len(drafts) == 1
    assert official_versions == []
    assert translations == []


def test_finalize_promotes_selected_draft_into_official_version(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id, step_run_id = _prepare_translation_workflow_project(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    workflow_run = db_session.execute(
        select(WorkflowRun).where(WorkflowRun.project_id == project_id, WorkflowRun.stage == "translation")
    ).scalar_one()
    provider = FakeTranslationProvider(outputs=["源简介内容", "目标简介内容", "Draft translation output"])
    pipeline = TranslationPipelineService(
        db_session,
        base_data_dir=project_workspace,
        provider=provider,
    )
    pipeline.generate_draft(
        workflow_run_id=workflow_run.id,
        workflow_step_run_id=step_run_id,
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-draft",
        provider_model_name="model-draft",
        draft_role="primary",
    )

    finalize_step = WorkflowStepRun(
        workflow_run_id=workflow_run.id,
        step_key="finalize_segments",
        action="translation.finalize",
        llm_role="final_judge",
        model_profile_id="profile-draft",
        status="running",
        input_ref=json.dumps({"project_id": project_id}, ensure_ascii=False),
        output_payload=None,
        summary=None,
    )
    db_session.add(finalize_step)
    db_session.flush()

    result = pipeline.finalize(
        workflow_run_id=workflow_run.id,
        workflow_step_run_id=finalize_step.id,
        project_id=project_id,
        model_profile_id="profile-draft",
        provider_model_name="model-draft",
    )

    official_versions = db_session.execute(
        select(SegmentTranslationVersion).where(SegmentTranslationVersion.project_id == project_id)
    ).scalars().all()
    project = db_session.get(TranslationProject, project_id)

    assert project is not None
    assert result["translated_segments"] == 1
    assert len(result["active_version_ids"]) == 1
    assert len(official_versions) == 1
    assert official_versions[0].translated_text == "Draft translation output"
    assert (project_workspace / project.project_key / "translations").exists()


def test_translation_multi_llm_workflow_runs_generate_review_rewrite_finalize(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_translation_project_only(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    segment_id = db_session.execute(
        select(ChapterSegment.id)
        .where(ChapterSegment.project_id == project_id)
        .order_by(ChapterSegment.id.asc())
    ).scalars().first()
    assert segment_id is not None
    provider = FakeTranslationProvider(
        outputs=[
            "源简介内容",
            "目标简介内容",
            "Primary draft",
            "Secondary draft",
            json.dumps(
                {
                    "reviews": [
                        {
                            "segment_id": segment_id,
                            "draft_role": "primary",
                            "decision": "keep",
                            "score": 0.88,
                            "reason_codes": ["faithful", "natural"],
                            "issues": [],
                        },
                        {
                            "segment_id": segment_id,
                            "draft_role": "secondary",
                            "decision": "revise",
                            "score": 0.74,
                            "reason_codes": ["glossary_drift"],
                            "issues": ["赵馨宁 译名不一致"],
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "drafts": [
                        {
                            "segment_id": segment_id,
                            "translated_text": "Rewrite draft",
                            "parent_draft_role": "primary",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
        ]
    )

    from tools.local_translation_workbench.app.services.translation_service import TranslationService

    result = TranslationService(db_session, base_data_dir=project_workspace, provider=provider).run(
        request_id=request_id_factory("translation-multi-llm"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-multi",
        workflow_key="translation_multi_llm_v1",
    )

    workflow_runs = db_session.execute(
        select(WorkflowRun).where(WorkflowRun.project_id == project_id, WorkflowRun.stage == "translation")
    ).scalars().all()
    step_runs = db_session.execute(
        select(WorkflowStepRun)
        .join(WorkflowRun, WorkflowRun.id == WorkflowStepRun.workflow_run_id)
        .where(WorkflowRun.project_id == project_id, WorkflowRun.stage == "translation")
        .order_by(WorkflowStepRun.id.asc())
    ).scalars().all()
    draft_versions = db_session.execute(
        select(TranslationDraftVersion).where(TranslationDraftVersion.project_id == project_id)
    ).scalars().all()
    draft_reviews = db_session.execute(
        select(TranslationDraftReview)
        .join(TranslationDraftVersion, TranslationDraftVersion.id == TranslationDraftReview.draft_version_id)
        .where(TranslationDraftVersion.workflow_run_id == workflow_runs[0].id)
        .order_by(TranslationDraftReview.id.asc())
    ).scalars().all()
    official_versions = db_session.execute(
        select(SegmentTranslationVersion).where(SegmentTranslationVersion.project_id == project_id)
    ).scalars().all()

    assert result.translated_segments == 1
    assert len(workflow_runs) == 1
    assert workflow_runs[0].workflow_key == "translation_multi_llm_v1"
    assert [item.step_key for item in step_runs] == [
        "generate_primary",
        "generate_secondary",
        "review_drafts",
        "rewrite_consensus",
        "finalize_segments",
    ]
    assert {item.draft_role for item in draft_versions} == {"primary", "secondary", "rewrite"}
    assert len(draft_reviews) == 2
    assert len(official_versions) == 1
    assert official_versions[0].translated_text == "Rewrite draft"


def test_translation_multi_llm_workflow_marks_insufficient_evidence_when_one_draft_fails(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_translation_project_only(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    segment_id = db_session.execute(
        select(ChapterSegment.id)
        .where(ChapterSegment.project_id == project_id)
        .order_by(ChapterSegment.id.asc())
    ).scalars().first()
    assert segment_id is not None
    provider = FailOnPrimaryDraftProvider()

    from tools.local_translation_workbench.app.services.translation_service import TranslationService

    result = TranslationService(db_session, base_data_dir=project_workspace, provider=provider).run(
        request_id=request_id_factory("translation-multi-llm-degraded"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-multi",
        workflow_key="translation_multi_llm_v1",
    )

    workflow_run = db_session.execute(
        select(WorkflowRun)
        .where(WorkflowRun.project_id == project_id, WorkflowRun.stage == "translation")
        .order_by(WorkflowRun.id.desc())
    ).scalar_one()
    summary = json.loads(workflow_run.summary or "{}")
    official_versions = db_session.execute(
        select(SegmentTranslationVersion).where(SegmentTranslationVersion.project_id == project_id)
    ).scalars().all()

    assert result.translated_segments == 1
    assert len(official_versions) == 1
    assert official_versions[0].translated_text == "Secondary draft"
    assert workflow_run.status == "insufficient_evidence"
    assert summary["degraded"] is True
    assert summary["degradation_reason"] == "low_confidence"


def test_translation_workflow_step_payload_records_actual_fallback_profile(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_translation_project_only(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    segment_id = db_session.execute(
        select(ChapterSegment.id)
        .where(ChapterSegment.project_id == project_id)
        .order_by(ChapterSegment.id.asc())
    ).scalars().first()
    assert segment_id is not None
    provider = FakeTranslationProvider(
        outputs=[
            "源简介内容",
            "目标简介内容",
            "Primary draft",
            "Secondary draft",
            json.dumps(
                {
                    "reviews": [
                        {
                            "segment_id": segment_id,
                            "draft_role": "primary",
                            "decision": "keep",
                            "score": 0.88,
                            "reason_codes": ["faithful", "natural"],
                            "issues": [],
                        },
                        {
                            "segment_id": segment_id,
                            "draft_role": "secondary",
                            "decision": "revise",
                            "score": 0.74,
                            "reason_codes": ["glossary_drift"],
                            "issues": ["赵馨宁 译名不一致"],
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "drafts": [
                        {
                            "segment_id": segment_id,
                            "translated_text": "Rewrite draft",
                            "parent_draft_role": "primary",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
        ],
        result_model_profile_ids=["profile-translation-workflow-backup"] * 6,
        fallback_depths=[1, 1, 1, 1, 1, 1],
    )

    from tools.local_translation_workbench.app.services.translation_service import TranslationService

    TranslationService(db_session, base_data_dir=project_workspace, provider=provider).run(
        request_id=request_id_factory("translation-workflow-actual-profile"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-translation-workflow-main",
        workflow_key="translation_multi_llm_v1",
    )

    step_runs = db_session.execute(
        select(WorkflowStepRun)
        .join(WorkflowRun, WorkflowRun.id == WorkflowStepRun.workflow_run_id)
        .where(WorkflowRun.project_id == project_id, WorkflowRun.stage == "translation")
        .order_by(WorkflowStepRun.id.asc())
    ).scalars().all()
    step_payloads = {item.step_key: item.output_payload for item in step_runs}

    assert step_payloads["generate_primary"]["requested_model_profile_id"] == "profile-translation-workflow-main"
    assert step_payloads["generate_primary"]["actual_model_profile_id"] == "profile-translation-workflow-backup"
    assert step_payloads["generate_primary"]["fallback_depth"] == 1
    assert step_payloads["review_drafts"]["actual_model_profile_id"] == "profile-translation-workflow-backup"
    assert step_payloads["rewrite_consensus"]["actual_model_profile_id"] == "profile-translation-workflow-backup"
