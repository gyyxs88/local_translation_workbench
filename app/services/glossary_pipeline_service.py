from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ..db.models import TranslationProject
from ..errors import ToolError
from ..repositories.glossary import GlossaryRepository
from .glossary_workflow_domain_service import GlossaryWorkflowDomainService


class GlossaryPipelineService:
    def __init__(self, session, *, provider=None) -> None:
        self.session = session
        self.provider = provider
        self.glossary = GlossaryRepository(session)
        self.domain = GlossaryWorkflowDomainService(session, provider=provider)
        self.glossary_service = self.domain.glossary_service

    def fork_for_session(self, session):
        return GlossaryPipelineService(session, provider=self.provider)

    def extract(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        scope: dict[str, object],
        model_profile_id: str,
        provider_model_name: str | None,
    ) -> dict[str, object]:
        return self.domain.extract_draft_candidates(
            workflow_run_id=workflow_run_id,
            workflow_step_run_id=workflow_step_run_id,
            project_id=project_id,
            scope=scope,
            model_profile_id=model_profile_id,
            provider_model_name=provider_model_name,
        )

    def normalize(self, *, workflow_run_id: int, workflow_step_run_id: int) -> dict[str, object]:
        return self.domain.normalize_candidates(
            workflow_run_id=workflow_run_id,
            workflow_step_run_id=workflow_step_run_id,
        )

    def review_relations(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
    ) -> dict[str, object]:
        return self.domain.review_relation_candidates(
            workflow_run_id=workflow_run_id,
            workflow_step_run_id=workflow_step_run_id,
            model_profile_id=model_profile_id,
            provider_model_name=provider_model_name,
        )

    def review_scope(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
    ) -> dict[str, object]:
        return self.domain.review_scope_candidates(
            workflow_run_id=workflow_run_id,
            workflow_step_run_id=workflow_step_run_id,
            model_profile_id=model_profile_id,
            provider_model_name=provider_model_name,
        )

    def finalize(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
    ) -> dict[str, object]:
        return self.domain.finalize_candidates(
            workflow_run_id=workflow_run_id,
            workflow_step_run_id=workflow_step_run_id,
            project_id=project_id,
            model_profile_id=model_profile_id,
            provider_model_name=provider_model_name,
        )

    def inspect_pipeline(self, *, workflow_run_id: int) -> dict[str, object]:
        finalized_terms = self.glossary_service.build_finalized_terms_preview(workflow_run_id=workflow_run_id)
        return {
            "draft_candidates": self.glossary.inspect_draft_candidates(workflow_run_id=workflow_run_id),
            "reviews": self.glossary.inspect_candidate_reviews(workflow_run_id=workflow_run_id),
            "finalized_terms": finalized_terms,
            "finalized_relation_groups": self.glossary_service.relation_groups.build_relation_groups(
                items=[SimpleNamespace(id=index + 1, **item) for index, item in enumerate(finalized_terms)],
                member_id_field="draft_candidate_id",
            ),
        }
