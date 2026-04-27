from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from tools.local_translation_workbench.app.db.models import GlossaryDraftCandidate, WorkflowRun
from tools.local_translation_workbench.app.providers.base import TextGenerationResult
from tools.local_translation_workbench.app.repositories.projects import ProjectService
from tools.local_translation_workbench.app.services.chaptering_service import ChapteringService
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

    service = GlossaryWorkflowDomainService(db_session, provider=FakeGlossaryProvider())
    data = service.extract_draft_candidates(
        workflow_run_id=workflow_run.id,
        workflow_step_run_id=21,
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
