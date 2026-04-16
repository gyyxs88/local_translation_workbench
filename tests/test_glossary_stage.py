from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from tools.local_translation_workbench.app.cli import main
from tools.local_translation_workbench.app.db.models import (
    Chapter,
    GlossaryCandidate,
    GlossaryCandidateReview,
    GlossaryDraftCandidate,
    GlossaryEntry,
    StageRun,
    TranslationProject,
    WorkflowRun,
    WorkflowStepRun,
)
from tools.local_translation_workbench.app.providers.base import TextGenerationResult
from tools.local_translation_workbench.app.repositories.glossary import GlossaryRepository
from tools.local_translation_workbench.app.repositories.projects import ProjectService
from tools.local_translation_workbench.app.services.chaptering_service import ChapteringService
from tools.local_translation_workbench.app.services.glossary_service import GlossaryService
from tools.local_translation_workbench.app.services.stage_service import StageCommand, StageService


class FakeGlossaryProvider:
    def __init__(
        self,
        outputs: list[str],
        result_model_profile_ids: list[str] | None = None,
        fallback_depths: list[int] | None = None,
    ) -> None:
        self.outputs = list(outputs)
        self.result_model_profile_ids = list(result_model_profile_ids or [])
        self.fallback_depths = list(fallback_depths or [])
        self.calls: list[dict[str, object]] = []

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        self.calls.append(
            {
                "prompt": prompt,
                "model_name": model_name,
                "timeout_seconds": timeout_seconds,
            }
        )
        content = self.outputs.pop(0) if self.outputs else '{"terms":[]}'
        result_model_profile_id = (
            self.result_model_profile_ids.pop(0) if self.result_model_profile_ids else None
        )
        fallback_depth = self.fallback_depths.pop(0) if self.fallback_depths else 0
        return TextGenerationResult(
            content=content,
            provider_name="fake_glossary_provider",
            model_name=model_name,
            model_profile_id=result_model_profile_id,
            fallback_depth=fallback_depth,
        )


class FailingGlossaryProvider:
    def __init__(self, error_message: str = "boom") -> None:
        self.error_message = error_message
        self.calls: list[dict[str, object]] = []

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        self.calls.append(
            {
                "prompt": prompt,
                "model_name": model_name,
                "timeout_seconds": timeout_seconds,
            }
        )
        raise RuntimeError(self.error_message)


def test_glossary_schema_includes_gender_columns(db_session) -> None:
    inspector = inspect(db_session.get_bind())

    draft_columns = {
        column["name"]: column
        for column in inspector.get_columns("ltw_glossary_draft_candidates")
    }
    candidate_columns = {
        column["name"]: column
        for column in inspector.get_columns("ltw_glossary_candidates")
    }
    entry_columns = {
        column["name"]: column
        for column in inspector.get_columns("ltw_glossary_entries")
    }

    assert "gender" in draft_columns
    assert draft_columns["gender"]["nullable"] is True

    assert "category" in candidate_columns
    assert "note" in candidate_columns
    assert "gender" in candidate_columns
    assert candidate_columns["note"]["nullable"] is True
    assert candidate_columns["gender"]["nullable"] is True

    assert "gender" in entry_columns
    assert entry_columns["gender"]["nullable"] is True


def _build_two_chapter_glossary_outputs() -> list[str]:
    return [
        """```json
{"terms":[
  {"source_term":"傅慕宁","translated_term":"Fu Muning","category":"character","note":"Character name, female"},
  {"source_term":"深蓝公寓","translated_term":"Deep Blue Apartments","category":"location","note":"Apartment building"}
]}
```""",
        json.dumps(
            {
                "terms": [
                    {
                        "source_term": "裴越泽",
                        "translated_term": "Pei Yueze",
                        "category": "character",
                        "note": "Character name, male",
                    },
                    {
                        "source_term": "海王守则",
                        "translated_term": "Playboy Rules",
                        "category": "slang",
                        "note": "Humorous phrase derived from 海王",
                    },
                ]
            },
            ensure_ascii=False,
        ),
        '{"items":[]}',
        '{"items":[]}',
        '{"terms":[]}',
    ]


def _prepare_project_with_chapters(
    *,
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> int:
    source_file = project_workspace / "glossary-source.txt"
    source_file.write_text(
        "第1章 相遇\n傅慕宁走进深蓝公寓。\n\n第2章 旧事\n裴越泽提到海王守则。",
        encoding="utf-8",
    )

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("glossary-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("glossary-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )
    return project.id


def test_glossary_extract_normalizes_character_gender(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    provider = FakeGlossaryProvider(
        outputs=[
            json.dumps(
                {
                    "terms": [
                        {
                            "source_term": "傅慕宁",
                            "translated_term": "Fu Muning",
                            "category": "character",
                            "gender": " Female ",
                            "note": "Character name",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            '{"items":[]}',
            '{"items":[]}',
            '{"terms":[]}',
        ]
    )

    GlossaryService(db_session, provider=provider).run(
        request_id=request_id_factory("glossary-gender-normalize"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-glossary-gender",
    )

    draft = db_session.execute(
        select(GlossaryDraftCandidate).where(GlossaryDraftCandidate.project_id == project_id)
    ).scalar_one()

    assert draft.gender == "female"


def test_glossary_extract_clears_gender_for_non_character_terms(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    provider = FakeGlossaryProvider(
        outputs=[
            json.dumps(
                {
                    "terms": [
                        {
                            "source_term": "深蓝公寓",
                            "translated_term": "Deep Blue Apartments",
                            "category": "location",
                            "gender": "male",
                            "note": "Apartment building",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            '{"items":[]}',
            '{"items":[]}',
            '{"terms":[]}',
        ]
    )

    GlossaryService(db_session, provider=provider).run(
        request_id=request_id_factory("glossary-gender-non-character"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-glossary-gender",
    )

    draft = db_session.execute(
        select(GlossaryDraftCandidate).where(GlossaryDraftCandidate.project_id == project_id)
    ).scalar_one()

    assert draft.category == "location"
    assert draft.gender is None


def test_glossary_finalize_persists_gender_to_candidate_and_entry(db_session) -> None:
    project = TranslationProject(
        request_id="glossary-finalize-gender-project",
        project_key="glossary-finalize-gender-project",
        source_path="source.txt",
        source_language="zh",
        target_language="en",
        status="created",
    )
    db_session.add(project)
    db_session.flush()
    chapter = Chapter(
        project_id=project.id,
        chapter_index=1,
        chapter_title="第1章",
        source_path="chapter-1.txt",
        normalized_path="chapter-1.txt",
        stage_status="ready",
    )
    db_session.add(chapter)
    db_session.flush()

    workflow_run = WorkflowRun(
        workflow_key="glossary_single_llm_v1",
        project_id=project.id,
        stage="glossary",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":1}',
        request_id="glossary-finalize-gender-run",
        status="running",
        summary=None,
    )
    db_session.add(workflow_run)
    db_session.flush()
    step_run = WorkflowStepRun(
        workflow_run_id=workflow_run.id,
        step_key="finalize",
        action="glossary.finalize",
        llm_role="terminologist",
        model_profile_id="profile-glossary",
        status="completed",
        input_ref="workflow:1",
        output_payload=None,
        summary=None,
    )
    db_session.add(step_run)
    db_session.flush()

    repository = GlossaryRepository(db_session)
    repository.create_draft_candidate(
        workflow_run_id=workflow_run.id,
        project_id=project.id,
        chapter_id=chapter.id,
        source_term="傅慕宁",
        suggested_term="Fu Muning",
        category="character",
        gender="female",
        term_group_key="character-fu-muning",
        relation_role="canonical",
        scope_level="chapter_term",
        scope_chapter_id=chapter.id,
        evidence_payload={"note": "Character name"},
    )

    result = GlossaryService(db_session).finalize_from_workflow(
        workflow_run_id=workflow_run.id,
        workflow_step_run_id=step_run.id,
        project_id=project.id,
        model_name="profile-glossary",
    )

    entry = db_session.execute(
        select(GlossaryEntry).where(GlossaryEntry.project_id == project.id)
    ).scalar_one()
    candidate = db_session.execute(
        select(GlossaryCandidate).where(GlossaryCandidate.project_id == project.id)
    ).scalar_one()

    assert result.candidate_count == 1
    assert entry.gender == "female"
    assert candidate.category == "character"
    assert candidate.note == "Character name"
    assert candidate.gender == "female"


def test_extract_glossary_creates_candidates_without_overwriting_locked_entries(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    provider = FakeGlossaryProvider(outputs=_build_two_chapter_glossary_outputs())
    service = GlossaryService(db_session, provider=provider)
    service.seed_locked_entry(project_id=project_id, source_term="裴越泽", target_term="Locked Pei Yueze")

    result = service.run(
        request_id=request_id_factory("glossary-run"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 2},
        model_profile_id="profile-glossary",
    )

    assert result.candidate_count == 4
    assert len(provider.calls) == 5
    assert "提取术语" in str(provider.calls[0]["prompt"])
    assert "JSON" in str(provider.calls[0]["prompt"])
    locked_entry = service.get_entry(project_id=project_id, source_term="裴越泽")
    assert locked_entry.target_term == "Locked Pei Yueze"

    entries = db_session.execute(
        select(GlossaryEntry).where(GlossaryEntry.project_id == project_id)
    ).scalars().all()
    candidates = db_session.execute(
        select(GlossaryCandidate).where(GlossaryCandidate.project_id == project_id)
    ).scalars().all()
    stage_runs = db_session.execute(
        select(StageRun).where(StageRun.project_id == project_id, StageRun.stage == "glossary")
    ).scalars().all()

    assert len(entries) >= 2
    assert len(candidates) >= 2
    assert len(stage_runs) == 1
    assert stage_runs[0].status == "completed"

    rerun_service = GlossaryService(
        db_session,
        provider=FakeGlossaryProvider(outputs=_build_two_chapter_glossary_outputs()),
    )
    rerun_result = rerun_service.run(
        request_id=request_id_factory("glossary-rerun"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 2},
        model_profile_id="profile-glossary",
    )
    assert rerun_result.candidate_count == result.candidate_count

    rerun_candidates = db_session.execute(
        select(GlossaryCandidate).where(GlossaryCandidate.project_id == project_id)
    ).scalars().all()
    rerun_stage_runs = db_session.execute(
        select(StageRun).where(StageRun.project_id == project_id, StageRun.stage == "glossary")
    ).scalars().all()

    assert len(rerun_candidates) == len(candidates)
    assert len(rerun_stage_runs) == 2

    # 模拟章节内容被改写后重新抽取，自动生成的未锁定术语应该收敛掉。
    from tools.local_translation_workbench.app.db.models import Chapter  # local import to keep test focused

    for chapter in db_session.execute(
        select(Chapter).where(Chapter.project_id == project_id)
    ).scalars().all():
        Path(chapter.normalized_path).write_text("普通内容", encoding="utf-8")

    cleanup_result = GlossaryService(
        db_session,
        provider=FakeGlossaryProvider(outputs=['{"terms":[]}', '{"terms":[]}', '{"items":[]}', '{"items":[]}', '{"terms":[]}']),
    ).run(
        request_id=request_id_factory("glossary-cleanup"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 2},
        model_profile_id="profile-glossary",
    )
    assert cleanup_result.candidate_count == 0

    remaining_entries = db_session.execute(
        select(GlossaryEntry).where(GlossaryEntry.project_id == project_id)
    ).scalars().all()
    remaining_candidates = db_session.execute(
        select(GlossaryCandidate).where(GlossaryCandidate.project_id == project_id)
    ).scalars().all()

    assert [(entry.source_term, entry.locked) for entry in remaining_entries] == [("裴越泽", 1)]
    assert remaining_candidates == []


def test_glossary_service_with_stage_run_id_does_not_mutate_stage_run(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )
    precreated_request_id = request_id_factory("glossary-precreated-stage-run")
    stage_run = StageRun(
        project_id=project_id,
        stage="glossary",
        scope_type="chapter_range",
        scope_value=json.dumps({"type": "chapter_range", "start": 1, "end": 2}, ensure_ascii=False),
        status="running",
        summary=json.dumps({"request_id": precreated_request_id}, ensure_ascii=False),
    )
    db_session.add(stage_run)
    db_session.commit()

    result = GlossaryService(
        db_session,
        provider=FakeGlossaryProvider(outputs=_build_two_chapter_glossary_outputs()),
    ).run(
        request_id=request_id_factory("glossary-stage-owned-run"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 2},
        model_profile_id="profile-glossary",
        stage_run_id=stage_run.id,
    )

    refreshed_stage_run = db_session.get(StageRun, stage_run.id)

    assert result.candidate_count == 4
    assert refreshed_stage_run is not None
    assert refreshed_stage_run.status == "running"
    assert json.loads(refreshed_stage_run.summary or "{}")["request_id"] == precreated_request_id


def test_stage_run_glossary_failure_persists_workflow_failure_logs(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    with pytest.raises(RuntimeError, match="workflow-step-failed"):
        StageService(
            db_session,
            base_data_dir=project_workspace,
            provider=FailingGlossaryProvider(error_message="workflow-step-failed"),
        ).run(
            StageCommand(
                request_id=request_id_factory("glossary-stage-failure"),
                project_id=project_id,
                stage="glossary",
                scope={"type": "chapter_range", "start": 1, "end": 1},
                model_profile_id="profile-glossary-failure",
                provider_model_name="resolved-failure-model",
            )
        )

    db_session.expire_all()
    stage_run = db_session.execute(
        select(StageRun)
        .where(StageRun.project_id == project_id, StageRun.stage == "glossary")
        .order_by(StageRun.id.desc())
    ).scalar_one()
    workflow_run = db_session.execute(
        select(WorkflowRun)
        .where(WorkflowRun.project_id == project_id, WorkflowRun.stage == "glossary")
        .order_by(WorkflowRun.id.desc())
    ).scalar_one()
    step_runs = db_session.execute(
        select(WorkflowStepRun)
        .where(WorkflowStepRun.workflow_run_id == workflow_run.id)
        .order_by(WorkflowStepRun.id.asc())
    ).scalars().all()

    assert stage_run.status == "failed"
    assert workflow_run.status == "failed"
    assert step_runs
    assert step_runs[0].status == "failed"
    assert step_runs[0].output_payload == {"error": "workflow-step-failed"}


def test_glossary_workflow_step_payload_records_actual_fallback_profile(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    provider = FakeGlossaryProvider(
        outputs=[
            json.dumps(
                {
                    "terms": [
                        {
                            "source_term": "傅慕宁",
                            "translated_term": "Fu Muning",
                            "category": "character",
                            "term_group_key": "fu-muning",
                            "relation_role": "independent",
                            "note": "Character name",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            '{"decisions":[]}',
            '{"items":[]}',
            '{"items":[]}',
        ],
        result_model_profile_ids=["profile-glossary-backup"] * 4,
        fallback_depths=[1, 1, 1, 1],
    )

    StageService(db_session, base_data_dir=project_workspace, provider=provider).run(
        StageCommand(
            request_id=request_id_factory("glossary-actual-profile"),
            project_id=project_id,
            stage="glossary",
            scope={"type": "chapter_range", "start": 1, "end": 1},
            model_profile_id="profile-glossary-main",
        )
    )

    step_runs = db_session.execute(
        select(WorkflowStepRun)
        .join(WorkflowRun, WorkflowRun.id == WorkflowStepRun.workflow_run_id)
        .where(WorkflowRun.project_id == project_id, WorkflowRun.stage == "glossary")
        .order_by(WorkflowStepRun.id.asc())
    ).scalars().all()
    step_payloads = {item.step_key: item.output_payload for item in step_runs}

    assert step_payloads["extract_primary"]["requested_model_profile_id"] == "profile-glossary-main"
    assert step_payloads["extract_primary"]["actual_model_profile_id"] == "profile-glossary-backup"
    assert step_payloads["extract_primary"]["fallback_depth"] == 1
    assert step_payloads["review_relations"]["actual_model_profile_id"] == "profile-glossary-backup"
    assert step_payloads["review_scope"]["actual_model_profile_id"] == "profile-glossary-backup"


def test_glossary_entries_store_term_group_and_relation_role(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    source_file = project_workspace / "glossary-group-source.txt"
    source_file.write_text(
        "第1章 相遇\n张望月看向望月。",
        encoding="utf-8",
    )

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("glossary-group-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("glossary-group-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    provider = FakeGlossaryProvider(
        outputs=[
            json.dumps(
                {
                    "terms": [
                        {
                            "source_term": "张望月",
                            "translated_term": "Zhang Wangyue",
                            "category": "character",
                            "term_group_key": "character-zhang-wangyue",
                            "relation_role": "canonical",
                            "note": "Formal full name",
                        },
                        {
                            "source_term": "望月",
                            "translated_term": "Wangyue",
                            "category": "character",
                            "term_group_key": "character-zhang-wangyue",
                            "relation_role": "alias",
                            "note": "Short form used by acquaintances",
                        },
                    ]
                },
                ensure_ascii=False,
            )
        ]
    )

    result = GlossaryService(db_session, provider=provider).run(
        request_id=request_id_factory("glossary-group-run"),
        project_id=project.id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-glossary-rel",
    )

    entries = db_session.execute(
        select(GlossaryEntry).where(GlossaryEntry.project_id == project.id).order_by(GlossaryEntry.source_term.asc())
    ).scalars().all()
    candidates = db_session.execute(
        select(GlossaryCandidate).where(GlossaryCandidate.project_id == project.id).order_by(GlossaryCandidate.source_term.asc())
    ).scalars().all()

    assert result.candidate_count == 2
    assert [(entry.source_term, entry.term_group_key, entry.relation_role) for entry in entries] == [
        ("张望月", "character-zhang-wangyue", "canonical"),
        ("望月", "character-zhang-wangyue", "alias"),
    ]
    assert [(candidate.source_term, candidate.term_group_key, candidate.relation_role) for candidate in candidates] == [
        ("张望月", "character-zhang-wangyue", "canonical"),
        ("望月", "character-zhang-wangyue", "alias"),
    ]


def test_glossary_entry_supports_scope_level_and_scope_chapter_id(db_session) -> None:
    project = TranslationProject(
        request_id="glossary-scope-project-request",
        project_key="glossary-scope-project",
        source_path="source.txt",
        source_language="zh",
        target_language="en",
        status="created",
    )
    db_session.add(project)
    db_session.flush()
    chapter = Chapter(
        project_id=project.id,
        chapter_index=1,
        chapter_title="第1章",
        source_path="chapter-1.txt",
        normalized_path="chapter-1.txt",
        stage_status="ready",
    )
    db_session.add(chapter)
    db_session.flush()

    repository = GlossaryRepository(db_session)
    entry = repository.create_entry(
        project_id=project.id,
        source_term="傅慕宁",
        target_term="Fu Muning",
        scope_level="chapter_term",
        scope_chapter_id=chapter.id,
    )

    stored_entry = db_session.execute(
        select(GlossaryEntry).where(GlossaryEntry.id == entry.id)
    ).scalar_one()

    assert stored_entry.scope_level == "chapter_term"
    assert stored_entry.scope_chapter_id == chapter.id
    assert stored_entry.scope_anchor == f"chapter:{chapter.id}"


def test_glossary_scoped_entries_can_coexist_and_cleanup_stays_in_scope(db_session) -> None:
    project = TranslationProject(
        request_id="glossary-coexist-project-request",
        project_key="glossary-coexist-project",
        source_path="source.txt",
        source_language="zh",
        target_language="en",
        status="created",
    )
    db_session.add(project)
    db_session.flush()
    chapter = Chapter(
        project_id=project.id,
        chapter_index=1,
        chapter_title="第1章",
        source_path="chapter-1.txt",
        normalized_path="chapter-1.txt",
        stage_status="ready",
    )
    db_session.add(chapter)
    db_session.flush()

    repository = GlossaryRepository(db_session)
    project_entry = repository.create_entry(
        project_id=project.id,
        source_term="傅慕宁",
        target_term="Fu Muning",
        scope_level="project_term",
    )
    chapter_entry = repository.create_entry(
        project_id=project.id,
        source_term="傅慕宁",
        target_term="Muning Fu",
        scope_level="chapter_term",
        scope_chapter_id=chapter.id,
    )
    chapter_only_entry = repository.create_entry(
        project_id=project.id,
        source_term="深蓝公寓",
        target_term="Deep Blue Apartments",
        scope_level="chapter_term",
        scope_chapter_id=chapter.id,
    )

    assert repository.get_entry(project.id, "傅慕宁").id == project_entry.id
    assert (
        repository.get_entry(
            project.id,
            "傅慕宁",
            scope_level="chapter_term",
            scope_chapter_id=chapter.id,
        ).id
        == chapter_entry.id
    )
    assert [item.id for item in repository.list_active_entries(project.id)] == [project_entry.id]
    assert {
        item.id
        for item in repository.list_active_entries(
            project.id,
            scope_level="chapter_term",
            scope_chapter_id=chapter.id,
        )
    } == {chapter_only_entry.id, chapter_entry.id}
    assert [item.id for item in repository.list_active_entries_for_matching(project.id)] == [project_entry.id]
    assert {
        item.id
        for item in repository.list_active_entries_for_matching(
            project.id,
            scope_level="chapter_term",
            scope_chapter_id=chapter.id,
        )
    } == {chapter_only_entry.id, chapter_entry.id}
    assert {
        item.id
        for item in repository.list_active_entries_for_matching(
            project.id,
            scope_level="chapter_term",
            scope_chapter_id=chapter.id,
            include_project_scope=True,
        )
    } == {project_entry.id, chapter_only_entry.id, chapter_entry.id}

    repository.delete_unlocked_entries_not_in_terms(
        project.id,
        ["傅慕宁"],
        scope_level="chapter_term",
        scope_chapter_id=chapter.id,
    )

    remaining = db_session.execute(
        select(GlossaryEntry)
        .where(GlossaryEntry.project_id == project.id)
        .order_by(GlossaryEntry.scope_level.asc(), GlossaryEntry.source_term.asc())
    ).scalars().all()

    assert [(item.scope_level, item.source_term, item.target_term) for item in remaining] == [
        ("chapter_term", "傅慕宁", "Muning Fu"),
        ("project_term", "傅慕宁", "Fu Muning"),
    ]


def test_glossary_entry_database_unique_constraint_blocks_duplicate_project_scope_terms(db_session) -> None:
    project = TranslationProject(
        request_id="glossary-entry-unique-project-request",
        project_key="glossary-entry-unique-project",
        source_path="source.txt",
        source_language="zh",
        target_language="en",
        status="created",
    )
    db_session.add(project)
    db_session.flush()

    first_entry = GlossaryEntry(
        project_id=project.id,
        source_term="傅慕宁",
        target_term="Fu Muning",
        category="character",
        status="active",
        locked=0,
        term_group_key="character-fu-muning",
        relation_role="canonical",
        scope_level="project_term",
        scope_chapter_id=None,
        scope_anchor="project",
    )
    duplicate_entry = GlossaryEntry(
        project_id=project.id,
        source_term="傅慕宁",
        target_term="Muning Fu",
        category="character",
        status="active",
        locked=0,
        term_group_key="character-fu-muning",
        relation_role="alias",
        scope_level="project_term",
        scope_chapter_id=None,
        scope_anchor="project",
    )
    db_session.add(first_entry)
    db_session.flush()
    db_session.add(duplicate_entry)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_glossary_chapter_scoped_entry_is_deleted_when_chapter_is_removed(db_session) -> None:
    project = TranslationProject(
        request_id="glossary-entry-delete-chapter-project-request",
        project_key="glossary-entry-delete-chapter-project",
        source_path="source.txt",
        source_language="zh",
        target_language="en",
        status="created",
    )
    db_session.add(project)
    db_session.flush()
    chapter = Chapter(
        project_id=project.id,
        chapter_index=1,
        chapter_title="第1章",
        source_path="chapter-1.txt",
        normalized_path="chapter-1.txt",
        stage_status="ready",
    )
    db_session.add(chapter)
    db_session.flush()

    repository = GlossaryRepository(db_session)
    entry = repository.create_entry(
        project_id=project.id,
        source_term="傅慕宁",
        target_term="Fu Muning",
        scope_level="chapter_term",
        scope_chapter_id=chapter.id,
    )
    entry_id = entry.id

    db_session.delete(chapter)
    db_session.flush()
    db_session.expire_all()

    assert db_session.execute(select(GlossaryEntry.id).where(GlossaryEntry.id == entry_id)).scalar_one_or_none() is None
    assert repository.get_entry(
        project.id,
        "傅慕宁",
        scope_level="chapter_term",
        scope_chapter_id=chapter.id,
    ) is None


def test_glossary_draft_candidate_and_review_can_be_persisted(db_session) -> None:
    project = TranslationProject(
        request_id="glossary-draft-project-request",
        project_key="glossary-draft-project",
        source_path="source.txt",
        source_language="zh",
        target_language="en",
        status="created",
    )
    db_session.add(project)
    db_session.flush()
    chapter = Chapter(
        project_id=project.id,
        chapter_index=1,
        chapter_title="第1章",
        source_path="chapter-1.txt",
        normalized_path="chapter-1.txt",
        stage_status="ready",
    )
    db_session.add(chapter)
    db_session.flush()

    workflow_run = WorkflowRun(
        workflow_key="glossary_workflow",
        project_id=project.id,
        stage="glossary",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":1}',
        request_id="glossary-draft-workflow-request",
        status="running",
        summary=None,
    )
    db_session.add(workflow_run)
    db_session.flush()

    step_run = WorkflowStepRun(
        workflow_run_id=workflow_run.id,
        step_key="glossary_review_step",
        action="review",
        llm_role="reviewer",
        model_profile_id="profile-review",
        status="running",
        input_ref="draft-candidate-001",
        output_payload=None,
        summary=None,
    )
    db_session.add(step_run)
    db_session.flush()

    repository = GlossaryRepository(db_session)
    draft_candidate = repository.create_draft_candidate(
        workflow_run_id=workflow_run.id,
        project_id=project.id,
        chapter_id=chapter.id,
        source_term="傅慕宁",
        suggested_term="Fu Muning",
        category="character",
        term_group_key="character-fu-muning",
        relation_role="canonical",
        scope_level="chapter_term",
        scope_chapter_id=chapter.id,
        evidence_payload={
            "chapter_index": 1,
            "evidence": ["傅慕宁走进深蓝公寓。"],
        },
    )
    review = repository.create_candidate_review(
        step_run_id=step_run.id,
        draft_candidate_id=draft_candidate.id,
        review_type="llm",
        decision="approve",
        score=92.5,
        reason_codes=["character_name", "stable_translation"],
        structured_payload={
            "approved": True,
            "summary": "保留为全章术语",
        },
    )

    stored_draft_candidates = repository.list_draft_candidates(workflow_run.id)
    inspected_draft_candidates = repository.inspect_draft_candidates(workflow_run.id)
    stored_reviews = repository.inspect_candidate_reviews(workflow_run.id)
    stored_draft = db_session.execute(
        select(GlossaryDraftCandidate).where(GlossaryDraftCandidate.id == draft_candidate.id)
    ).scalar_one()
    stored_review = db_session.execute(
        select(GlossaryCandidateReview).where(GlossaryCandidateReview.id == review.id)
    ).scalar_one()

    assert stored_draft.workflow_run_id == workflow_run.id
    assert stored_draft.category == "character"
    assert stored_draft.scope_level == "chapter_term"
    assert stored_draft.scope_chapter_id == chapter.id
    assert stored_draft.evidence_payload == {
        "chapter_index": 1,
        "evidence": ["傅慕宁走进深蓝公寓。"],
    }
    assert stored_review.step_run_id == step_run.id
    assert stored_review.review_type == "llm"
    assert stored_review.decision == "approve"
    assert stored_review.score == 92.5
    assert stored_review.reason_codes == ["character_name", "stable_translation"]
    assert stored_review.structured_payload == {
        "approved": True,
        "summary": "保留为全章术语",
    }
    assert len(stored_draft_candidates) == 1
    assert stored_draft_candidates[0].source_term == "傅慕宁"
    assert stored_draft_candidates[0].category == "character"
    assert stored_draft_candidates[0].evidence_payload["chapter_index"] == 1
    assert inspected_draft_candidates[0]["category"] == "character"
    assert inspected_draft_candidates[0]["evidence_payload"]["chapter_index"] == 1
    assert stored_reviews[0]["draft_candidate_id"] == draft_candidate.id
    assert stored_reviews[0]["step_run_id"] == step_run.id
    assert stored_reviews[0]["review_type"] == "llm"
    assert stored_reviews[0]["decision"] == "approve"
    assert stored_reviews[0]["score"] == 92.5
    assert stored_reviews[0]["reason_codes"] == ["character_name", "stable_translation"]
    assert stored_reviews[0]["structured_payload"] == {
        "approved": True,
        "summary": "保留为全章术语",
    }


def test_glossary_candidate_creation_rejects_mismatched_project_chapter(db_session) -> None:
    first_project = TranslationProject(
        request_id="glossary-candidate-project-1-request",
        project_key="glossary-candidate-project-1",
        source_path="source-1.txt",
        source_language="zh",
        target_language="en",
        status="created",
    )
    second_project = TranslationProject(
        request_id="glossary-candidate-project-2-request",
        project_key="glossary-candidate-project-2",
        source_path="source-2.txt",
        source_language="zh",
        target_language="en",
        status="created",
    )
    db_session.add_all([first_project, second_project])
    db_session.flush()
    second_chapter = Chapter(
        project_id=second_project.id,
        chapter_index=1,
        chapter_title="第1章",
        source_path="project-2-chapter-1.txt",
        normalized_path="project-2-chapter-1.txt",
        stage_status="ready",
    )
    db_session.add(second_chapter)
    db_session.flush()

    workflow_run = WorkflowRun(
        workflow_key="glossary_workflow",
        project_id=first_project.id,
        stage="glossary",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":1}',
        request_id="glossary-candidate-workflow-request",
        status="running",
        summary=None,
    )
    db_session.add(workflow_run)
    db_session.flush()

    repository = GlossaryRepository(db_session)

    with pytest.raises(ValueError, match="chapter_id=.*不属于 project_id="):
        repository.create_candidate(
            project_id=first_project.id,
            chapter_id=second_chapter.id,
            source_term="傅慕宁",
            suggested_term="Fu Muning",
        )

    with pytest.raises(ValueError, match="chapter_id=.*不属于 project_id="):
        repository.create_draft_candidate(
            workflow_run_id=workflow_run.id,
            project_id=first_project.id,
            chapter_id=second_chapter.id,
            source_term="傅慕宁",
            suggested_term="Fu Muning",
            category="character",
        )


def test_create_candidate_review_rejects_cross_workflow_run(db_session) -> None:
    project = TranslationProject(
        request_id="glossary-review-project-request",
        project_key="glossary-review-project",
        source_path="source.txt",
        source_language="zh",
        target_language="en",
        status="created",
    )
    db_session.add(project)
    db_session.flush()
    chapter = Chapter(
        project_id=project.id,
        chapter_index=1,
        chapter_title="第1章",
        source_path="chapter-1.txt",
        normalized_path="chapter-1.txt",
        stage_status="ready",
    )
    db_session.add(chapter)
    db_session.flush()

    first_workflow_run = WorkflowRun(
        workflow_key="glossary_workflow_a",
        project_id=project.id,
        stage="glossary",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":1}',
        request_id="glossary-review-workflow-request-a",
        status="running",
        summary=None,
    )
    second_workflow_run = WorkflowRun(
        workflow_key="glossary_workflow_b",
        project_id=project.id,
        stage="glossary",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":1}',
        request_id="glossary-review-workflow-request-b",
        status="running",
        summary=None,
    )
    db_session.add_all([first_workflow_run, second_workflow_run])
    db_session.flush()

    step_run = WorkflowStepRun(
        workflow_run_id=second_workflow_run.id,
        step_key="glossary_review_step_cross_run",
        action="review",
        llm_role="reviewer",
        model_profile_id="profile-review",
        status="running",
        input_ref="draft-candidate-cross-run",
        output_payload=None,
        summary=None,
    )
    db_session.add(step_run)
    db_session.flush()

    repository = GlossaryRepository(db_session)
    draft_candidate = repository.create_draft_candidate(
        workflow_run_id=first_workflow_run.id,
        project_id=project.id,
        chapter_id=chapter.id,
        source_term="傅慕宁",
        suggested_term="Fu Muning",
        category="character",
    )

    with pytest.raises(ValueError, match="step_run_id=.*workflow_run_id.*draft_candidate"):
        repository.create_candidate_review(
            draft_candidate_id=draft_candidate.id,
            step_run_id=step_run.id,
            review_type="llm",
            decision="approve",
        )


def test_glossary_keeps_canonical_and_alias_terms_together(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    source_file = project_workspace / "glossary-alias-source.txt"
    source_file.write_text(
        "第1章 相遇\n张望月看向望月。",
        encoding="utf-8",
    )

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("glossary-alias-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("glossary-alias-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    provider = FakeGlossaryProvider(
        outputs=[
            json.dumps(
                {
                    "terms": [
                        {
                            "source_term": "张望月",
                            "translated_term": "Zhang Wangyue",
                            "category": "character",
                            "term_group_key": "character-zhang-wangyue",
                            "relation_role": "canonical",
                            "note": "Formal full name",
                        },
                        {
                            "source_term": "望月",
                            "translated_term": "Wangyue",
                            "category": "character",
                            "term_group_key": "character-zhang-wangyue",
                            "relation_role": "alias",
                            "note": "Short form used by classmates",
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "decisions": [
                        {
                            "source_term": "张望月",
                            "keep": True,
                            "term_group_key": "character-zhang-wangyue",
                            "relation_role": "canonical",
                        },
                        {
                            "source_term": "望月",
                            "keep": True,
                            "term_group_key": "character-zhang-wangyue",
                            "relation_role": "alias",
                        },
                    ]
                },
                ensure_ascii=False,
            ),
        ]
    )

    result = GlossaryService(db_session, provider=provider).run(
        request_id=request_id_factory("glossary-alias-run"),
        project_id=project.id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-glossary-alias",
    )

    data = GlossaryService(db_session, provider=provider).inspect(project_id=project.id)

    assert result.candidate_count == 2
    assert len(provider.calls) == 5
    assert {(item["source_term"], item["relation_role"]) for item in data["entries"]} == {
        ("张望月", "canonical"),
        ("望月", "alias"),
    }


def test_glossary_strips_title_scaffold_but_keeps_title_term(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    source_file = project_workspace / "glossary-title-source.txt"
    source_file.write_text(
        "第1章 贴贴魔女\n张望月出门。",
        encoding="utf-8",
    )

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("glossary-title-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("glossary-title-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    provider = FakeGlossaryProvider(
        outputs=[
            json.dumps(
                {
                    "terms": [
                        {
                            "source_term": "第1章",
                            "translated_term": "Chapter 1",
                            "category": "other",
                            "term_group_key": "scaffold-ch1",
                            "relation_role": "independent",
                            "note": "Pure chapter scaffold",
                        },
                        {
                            "source_term": "贴贴魔女",
                            "translated_term": "Snuggle Witch",
                            "category": "title",
                            "term_group_key": "title-snuggle-witch",
                            "relation_role": "canonical",
                            "note": "Actual semantic chapter title",
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "decisions": [
                        {
                            "source_term": "第1章",
                            "keep": False,
                            "reason": "pure_scaffold",
                        },
                        {
                            "source_term": "贴贴魔女",
                            "keep": True,
                            "term_group_key": "title-snuggle-witch",
                            "relation_role": "canonical",
                        },
                    ]
                },
                ensure_ascii=False,
            ),
        ]
    )

    result = GlossaryService(db_session, provider=provider).run(
        request_id=request_id_factory("glossary-title-run"),
        project_id=project.id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-glossary-title",
    )
    data = GlossaryService(db_session, provider=provider).inspect(project_id=project.id)

    assert result.candidate_count == 1
    assert len(provider.calls) == 5
    assert {item["source_term"] for item in data["entries"]} == {"贴贴魔女"}
    assert {item["source_term"] for item in data["candidates"]} == {"贴贴魔女"}


def test_cli_stage_run_glossary_and_inspect_glossary(
    database_url: str,
    project_workspace: Path,
    request_id_factory,
    monkeypatch,
    capsys,
) -> None:
    source_file = project_workspace / "glossary-cli-source.txt"
    source_file.write_text(
        "第1章 相遇\n傅慕宁走进深蓝公寓。\n\n第2章 旧事\n裴越泽提到海王守则。",
        encoding="utf-8",
    )

    create_exit_code = main(
        [
            "-Action",
            "project.create",
            "-RequestId",
            request_id_factory("glossary-cli-create"),
            "-SourcePath",
            str(source_file),
            "-SourceLanguage",
            "zh",
            "-TargetLanguage",
            "en",
        ]
    )
    create_payload = json.loads(capsys.readouterr().out)
    assert create_exit_code == 0

    project_id = create_payload["data"]["id"]

    chaptering_exit_code = main(
        [
            "-Action",
            "stage.run",
            "-ProjectId",
            str(project_id),
            "-Stage",
            "chaptering",
            "-ScopeType",
            "all",
            "-RequestId",
            request_id_factory("glossary-cli-chaptering"),
        ]
    )
    chaptering_payload = json.loads(capsys.readouterr().out)
    assert chaptering_exit_code == 0
    assert chaptering_payload["data"]["chapter_count"] == 2

    from tools.local_translation_workbench.app import action_router as action_router_module
    from tools.local_translation_workbench.app.providers.router import ResolvedProviderProfile

    glossary_provider = FakeGlossaryProvider(
        outputs=[
            json.dumps(
                {
                    "terms": [
                        {
                            "source_term": "傅慕宁",
                            "translated_term": "Fu Muning",
                            "category": "character",
                            "note": "Character name, female",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "terms": [
                        {
                            "source_term": "海王守则",
                            "translated_term": "Playboy Rules",
                            "category": "slang",
                            "note": "Humorous phrase derived from 海王",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
        ]
    )
    monkeypatch.setattr(
        action_router_module,
        "build_provider_from_profile",
        lambda session, config, model_profile_id: ResolvedProviderProfile(
            provider=glossary_provider,
            profile_key=str(model_profile_id or "profile-glossary-cli"),
            model_name="resolved-glossary-cli-model",
        ),
    )

    glossary_exit_code = main(
        [
            "-Action",
            "stage.run",
            "-ProjectId",
            str(project_id),
            "-Stage",
            "glossary",
            "-ScopeType",
            "chapter_range",
            "-ScopeStart",
            "1",
            "-ScopeEnd",
            "2",
            "-RequestId",
            request_id_factory("glossary-cli-run"),
            "-ModelProfileId",
            "profile-glossary-cli",
        ]
    )
    glossary_payload = json.loads(capsys.readouterr().out)

    assert glossary_exit_code == 0
    assert glossary_payload["ok"] is True
    assert glossary_payload["action"] == "stage.run"
    assert glossary_payload["data"]["stage"] == "glossary"
    assert glossary_payload["data"]["candidate_count"] >= 2
    assert len(glossary_provider.calls) == 5

    inspect_exit_code = main(
        [
            "-Action",
            "inspect.glossary",
            "-ProjectId",
            str(project_id),
        ]
    )
    inspect_payload = json.loads(capsys.readouterr().out)

    assert inspect_exit_code == 0
    assert inspect_payload["ok"] is True
    assert inspect_payload["action"] == "inspect.glossary"
    assert len(inspect_payload["data"]["entries"]) >= 2
    assert len(inspect_payload["data"]["candidates"]) >= 2
