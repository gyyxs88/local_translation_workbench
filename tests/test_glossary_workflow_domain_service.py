from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from sqlalchemy import select

from tools.local_translation_workbench.app.db.engine import get_session_factory
from tools.local_translation_workbench.app.db.models import (
    Chapter,
    GlossaryCandidateReview,
    GlossaryDraftCandidate,
    WorkflowRun,
    WorkflowStepRun,
)
from tools.local_translation_workbench.app.providers.base import TextGenerationResult
from tools.local_translation_workbench.app.repositories.glossary import GlossaryRepository
from tools.local_translation_workbench.app.repositories.projects import ProjectService
from tools.local_translation_workbench.app.services.chaptering_service import ChapteringService
from tools.local_translation_workbench.app.services.glossary_pipeline_service import GlossaryPipelineService
from tools.local_translation_workbench.app.services.glossary_workflow_domain_service import (
    GlossaryWorkflowDomainService,
)


class FakeGlossaryProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        self.calls.append(
            {
                "prompt": prompt,
                "model_name": model_name,
                "timeout_seconds": timeout_seconds,
            }
        )
        content = json.dumps(
            {
                "extraction_status": "terms_found",
                "terms": [
                    {
                        "source_term": "傅慕宁",
                        "translated_term": "Fu Muning",
                        "category": "character",
                        "note": "Character name",
                    }
                ],
                "reason": "fake extraction",
            },
            ensure_ascii=False,
        )
        return TextGenerationResult(
            content=content,
            provider_name="fake_glossary_provider",
            model_name=model_name,
        )


class ChapterParallelTracker:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.started_labels: list[str] = []
        self.active_workers = 0
        self.max_active_workers = 0
        self.second_started = threading.Event()

    def start(self, *, label: str) -> None:
        with self.lock:
            self.started_labels.append(label)
            self.active_workers += 1
            self.max_active_workers = max(self.max_active_workers, self.active_workers)
            if len(self.started_labels) >= 2:
                self.second_started.set()

    def wait_for_parallel_start(self) -> None:
        if not self.second_started.wait(timeout=5.0):
            raise AssertionError("第二个 glossary 章节 worker 没有在第一个 worker 完成前启动。")

    def finish(self) -> None:
        with self.lock:
            self.active_workers -= 1


class ParallelChapterGlossaryProvider:
    def __init__(self, *, tracker: ChapterParallelTracker) -> None:
        self.tracker = tracker
        self.calls: list[dict[str, object]] = []

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        self.calls.append({"prompt": prompt, "model_name": model_name, "timeout_seconds": timeout_seconds})
        if "术语抽取器" not in prompt:
            return TextGenerationResult(
                content='{"passed":true,"issues":[]}',
                provider_name="parallel_glossary_provider",
                model_name=model_name,
            )
        chapter_match = re.search(r"章节号:\s*(\d+)", prompt)
        chapter_index = chapter_match.group(1) if chapter_match else "unknown"
        label = f"chapter:{chapter_index}"
        self.tracker.start(label=label)
        try:
            self.tracker.wait_for_parallel_start()
            source_term = "傅慕宁" if chapter_index == "1" else "林溪"
            translated_term = "Fu Muning" if chapter_index == "1" else "Lin Xi"
            content = json.dumps(
                {
                    "extraction_status": "terms_found",
                    "terms": [
                        {
                            "source_term": source_term,
                            "translated_term": translated_term,
                            "category": "character",
                            "note": "parallel extraction marker",
                        }
                    ],
                    "reason": "fake parallel extraction",
                },
                ensure_ascii=False,
            )
            return TextGenerationResult(
                content=content,
                provider_name="parallel_glossary_provider",
                model_name=model_name,
            )
        finally:
            self.tracker.finish()


class ConsistencyReviewProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        self.calls.append({"prompt": prompt, "model_name": model_name, "timeout_seconds": timeout_seconds})
        draft_id_matches = re.findall(r'"draft_candidate_id":\s*(\d+)', prompt)
        draft_candidate_id = int(draft_id_matches[-1]) if draft_id_matches else 0
        content = json.dumps(
            {
                "items": [
                    {
                        "draft_candidate_id": draft_candidate_id,
                        "decision": "revise",
                        "suggested_term": "Xuanyue Sect",
                        "score": 0.91,
                        "reason_codes": ["style_mismatch"],
                        "issues": [
                            {
                                "code": "category_style_mismatch",
                                "severity": "warning",
                                "message": "organization terms should follow the existing Sect style",
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        )
        return TextGenerationResult(
            content=content,
            provider_name="consistency_review_provider",
            model_name=model_name,
        )


def _prepare_glossary_project(
    *,
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> int:
    source_file = project_workspace / "glossary-domain-source.txt"
    source_file.write_text(
        "第1章 相遇\n傅慕宁走进深蓝公寓。",
        encoding="utf-8",
    )

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("glossary-domain-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("glossary-domain-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )
    return project.id


def _prepare_two_chapter_glossary_project(
    *,
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> int:
    source_file = project_workspace / "glossary-domain-two-chapters.txt"
    source_file.write_text(
        "第1章 风起\n傅慕宁走进深蓝公寓。\n\n第2章 雨落\n林溪来到白塔街。",
        encoding="utf-8",
    )

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("glossary-domain-two-chapter-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("glossary-domain-two-chapter-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )
    return project.id


def test_glossary_workflow_domain_service_extracts_and_persists_draft_candidates(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_glossary_project(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    workflow_run = WorkflowRun(
        workflow_key="glossary_single_llm_v1",
        project_id=project_id,
        stage="glossary",
        scope_type="all",
        scope_value='{"type":"all"}',
        request_id=request_id_factory("glossary-domain-workflow-run"),
        status="running",
        summary=None,
    )
    db_session.add(workflow_run)
    db_session.flush()
    workflow_step_run = WorkflowStepRun(
        workflow_run_id=workflow_run.id,
        step_key="extract_primary",
        action="glossary.extract",
        llm_role="extractor",
        model_profile_id="profile-glossary-domain",
        status="running",
        input_ref='{"scope":{"type":"all"}}',
        output_payload=None,
        summary=None,
    )
    db_session.add(workflow_step_run)
    db_session.flush()

    service = GlossaryWorkflowDomainService(db_session, provider=FakeGlossaryProvider())
    data = service.extract_draft_candidates(
        workflow_run_id=workflow_run.id,
        workflow_step_run_id=workflow_step_run.id,
        project_id=project_id,
        scope={"type": "all"},
        model_profile_id="profile-glossary-domain",
        provider_model_name="resolved-glossary-domain-model",
    )

    drafts = db_session.execute(
        select(GlossaryDraftCandidate).where(GlossaryDraftCandidate.project_id == project_id)
    ).scalars().all()

    assert data["draft_candidate_count"] > 0
    assert len(drafts) > 0


def test_glossary_extract_runs_chapters_in_parallel_and_records_progress(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_two_chapter_glossary_project(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    workflow_run = WorkflowRun(
        workflow_key="glossary_single_llm_v1",
        project_id=project_id,
        stage="glossary",
        scope_type="all",
        scope_value='{"type":"all"}',
        request_id=request_id_factory("glossary-domain-parallel-workflow-run"),
        status="running",
        summary=None,
    )
    db_session.add(workflow_run)
    db_session.flush()
    workflow_step_run = WorkflowStepRun(
        workflow_run_id=workflow_run.id,
        step_key="extract_primary",
        action="glossary.extract",
        llm_role="extractor",
        model_profile_id="profile-glossary-parallel",
        status="running",
        input_ref='{"scope":{"type":"all"}}',
        output_payload=None,
        summary=None,
    )
    db_session.add(workflow_step_run)
    db_session.commit()

    tracker = ChapterParallelTracker()
    data = GlossaryPipelineService(
        db_session,
        provider=ParallelChapterGlossaryProvider(tracker=tracker),
        parallel_session_factory=get_session_factory(database_url),
        max_parallel_workers=2,
    ).extract(
        workflow_run_id=workflow_run.id,
        workflow_step_run_id=workflow_step_run.id,
        project_id=project_id,
        scope={"type": "all"},
        model_profile_id="profile-glossary-parallel",
        provider_model_name="model-glossary-parallel",
    )

    db_session.expire_all()
    stored_step = db_session.get(WorkflowStepRun, workflow_step_run.id)

    assert data["draft_candidate_count"] == 2
    assert tracker.max_active_workers >= 2
    assert set(tracker.started_labels[:2]) == {"chapter:1", "chapter:2"}
    assert data["progress"]["total_chapters"] == 2
    assert data["progress"]["completed_chapters"] == 2
    assert data["progress"]["failed_chapters"] == 0
    assert data["progress"]["max_parallel_workers"] == 2
    assert stored_step is not None
    assert stored_step.output_payload["progress"]["completed_chapters"] == 2


def test_glossary_consistency_review_uses_active_glossary_as_style_baseline(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_glossary_project(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    chapter = db_session.execute(
        select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.chapter_index.asc())
    ).scalars().first()
    assert chapter is not None

    workflow_run = WorkflowRun(
        workflow_key="glossary_single_llm_v1",
        project_id=project_id,
        stage="glossary",
        scope_type="all",
        scope_value='{"type":"all"}',
        request_id=request_id_factory("glossary-consistency-workflow-run"),
        status="running",
        summary=None,
    )
    db_session.add(workflow_run)
    db_session.flush()
    workflow_step_run = WorkflowStepRun(
        workflow_run_id=workflow_run.id,
        step_key="review_consistency",
        action="glossary.review_consistency",
        llm_role="consistency_reviewer",
        model_profile_id="profile-glossary-consistency",
        status="running",
        input_ref='{"scope":{"type":"all"}}',
        output_payload=None,
        summary=None,
    )
    db_session.add(workflow_step_run)
    db_session.flush()

    glossary = GlossaryRepository(db_session)
    glossary.create_entry(
        project_id=project_id,
        source_term="青云门",
        target_term="Qingyun Sect",
        category="organization",
        term_group_key="org_qingyun",
        relation_role="canonical",
    )
    glossary.create_draft_candidate(
        workflow_run_id=workflow_run.id,
        project_id=project_id,
        chapter_id=chapter.id,
        source_term="玄月门",
        suggested_term="Xuan Yue Gate",
        category="organization",
        term_group_key="org_xuanyue",
        relation_role="canonical",
    )
    db_session.commit()

    provider = ConsistencyReviewProvider()
    data = GlossaryPipelineService(db_session, provider=provider).review_consistency(
        workflow_run_id=workflow_run.id,
        workflow_step_run_id=workflow_step_run.id,
        project_id=project_id,
        model_profile_id="profile-glossary-consistency",
        provider_model_name="model-glossary-consistency",
    )

    reviews = db_session.execute(
        select(GlossaryCandidateReview)
        .where(GlossaryCandidateReview.step_run_id == workflow_step_run.id)
        .order_by(GlossaryCandidateReview.id.asc())
    ).scalars().all()

    assert data["draft_candidate_count"] == 1
    assert data["reviewed_count"] == 1
    assert data["active_baseline_count"] == 1
    assert len(provider.calls) == 1
    assert "已有正式术语风格基准" in str(provider.calls[0]["prompt"])
    assert "Qingyun Sect" in str(provider.calls[0]["prompt"])
    assert "Xuan Yue Gate" in str(provider.calls[0]["prompt"])
    assert len(reviews) == 1
    assert reviews[0].review_type == "consistency"
    assert reviews[0].decision == "revise"
    assert reviews[0].reason_codes == ["style_mismatch"]
    assert reviews[0].structured_payload["suggested_term"] == "Xuanyue Sect"
    assert reviews[0].structured_payload["style_baseline"]["source"] == "active_glossary"
    assert reviews[0].structured_payload["style_baseline"]["category"] == "organization"
    assert reviews[0].structured_payload["style_baseline"]["examples"][0]["target_term"] == "Qingyun Sect"


def test_glossary_consistency_review_flags_same_source_translation_conflicts(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_two_chapter_glossary_project(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    chapters = db_session.execute(
        select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.chapter_index.asc())
    ).scalars().all()
    assert len(chapters) == 2

    workflow_run = WorkflowRun(
        workflow_key="glossary_single_llm_v1",
        project_id=project_id,
        stage="glossary",
        scope_type="all",
        scope_value='{"type":"all"}',
        request_id=request_id_factory("glossary-conflict-workflow-run"),
        status="running",
        summary=None,
    )
    db_session.add(workflow_run)
    db_session.flush()
    workflow_step_run = WorkflowStepRun(
        workflow_run_id=workflow_run.id,
        step_key="review_consistency",
        action="glossary.review_consistency",
        llm_role="consistency_reviewer",
        model_profile_id="profile-glossary-consistency",
        status="running",
        input_ref='{"scope":{"type":"all"}}',
        output_payload=None,
        summary=None,
    )
    db_session.add(workflow_step_run)
    db_session.flush()

    glossary = GlossaryRepository(db_session)
    glossary.create_draft_candidate(
        workflow_run_id=workflow_run.id,
        project_id=project_id,
        chapter_id=chapters[0].id,
        source_term="林溪",
        suggested_term="Lin Xi",
        category="character",
        term_group_key="char_linxi",
        relation_role="canonical",
    )
    glossary.create_draft_candidate(
        workflow_run_id=workflow_run.id,
        project_id=project_id,
        chapter_id=chapters[1].id,
        source_term="林溪",
        suggested_term="Linxi",
        category="character",
        term_group_key="char_linxi",
        relation_role="canonical",
    )
    db_session.commit()

    data = GlossaryPipelineService(db_session, provider=None).review_consistency(
        workflow_run_id=workflow_run.id,
        workflow_step_run_id=workflow_step_run.id,
        project_id=project_id,
        model_profile_id="profile-glossary-consistency",
        provider_model_name=None,
    )

    reviews = db_session.execute(
        select(GlossaryCandidateReview)
        .where(GlossaryCandidateReview.step_run_id == workflow_step_run.id)
        .order_by(GlossaryCandidateReview.id.asc())
    ).scalars().all()

    assert data["reviewed_count"] == 2
    assert data["issue_counts"]["source_translation_conflict"] == 2
    assert [review.decision for review in reviews] == ["warning", "warning"]
    assert all(review.review_type == "consistency" for review in reviews)
    assert all("source_translation_conflict" in review.reason_codes for review in reviews)
    assert reviews[0].structured_payload["issues"][0]["code"] == "source_translation_conflict"
    assert sorted(reviews[0].structured_payload["issues"][0]["target_terms"]) == ["Lin Xi", "Linxi"]


def test_glossary_consistency_review_prefers_locked_active_glossary_target(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_glossary_project(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    chapter = db_session.execute(
        select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.chapter_index.asc())
    ).scalars().first()
    assert chapter is not None

    workflow_run = WorkflowRun(
        workflow_key="glossary_single_llm_v1",
        project_id=project_id,
        stage="glossary",
        scope_type="all",
        scope_value='{"type":"all"}',
        request_id=request_id_factory("glossary-locked-baseline-workflow-run"),
        status="running",
        summary=None,
    )
    db_session.add(workflow_run)
    db_session.flush()
    workflow_step_run = WorkflowStepRun(
        workflow_run_id=workflow_run.id,
        step_key="review_consistency",
        action="glossary.review_consistency",
        llm_role="consistency_reviewer",
        model_profile_id="profile-glossary-consistency",
        status="running",
        input_ref='{"scope":{"type":"all"}}',
        output_payload=None,
        summary=None,
    )
    db_session.add(workflow_step_run)
    db_session.flush()

    glossary = GlossaryRepository(db_session)
    glossary.create_entry(
        project_id=project_id,
        source_term="玄月门",
        target_term="Xuanyue Sect",
        category="organization",
        locked=1,
        term_group_key="org_xuanyue",
        relation_role="canonical",
    )
    glossary.create_draft_candidate(
        workflow_run_id=workflow_run.id,
        project_id=project_id,
        chapter_id=chapter.id,
        source_term="玄月门",
        suggested_term="Xuan Yue Gate",
        category="organization",
        term_group_key="org_xuanyue",
        relation_role="canonical",
    )
    db_session.commit()

    data = GlossaryPipelineService(db_session, provider=None).review_consistency(
        workflow_run_id=workflow_run.id,
        workflow_step_run_id=workflow_step_run.id,
        project_id=project_id,
        model_profile_id="profile-glossary-consistency",
        provider_model_name=None,
    )

    review = db_session.execute(
        select(GlossaryCandidateReview).where(GlossaryCandidateReview.step_run_id == workflow_step_run.id)
    ).scalar_one()

    assert data["issue_counts"]["active_glossary_target_conflict"] == 1
    assert review.decision == "conflict"
    assert review.reason_codes == ["active_glossary_target_conflict"]
    assert review.structured_payload["suggested_term"] == "Xuanyue Sect"
    assert review.structured_payload["issues"][0]["locked"] is True
    assert review.structured_payload["style_baseline"]["examples"][0]["target_term"] == "Xuanyue Sect"
