from __future__ import annotations

from pathlib import Path

from ..db.models import TranslationProject
from ..errors import ToolError
from ..repositories.glossary import GlossaryRepository
from .glossary_service import GlossaryService


class GlossaryWorkflowDomainService:
    def __init__(self, session, *, provider=None) -> None:
        self.session = session
        self.provider = provider
        self.glossary = GlossaryRepository(session)
        self.glossary_service = GlossaryService(session, provider=provider)

    def extract_draft_candidates(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        scope: dict[str, object],
        model_profile_id: str,
        provider_model_name: str | None,
    ) -> dict[str, object]:
        project = self.session.get(TranslationProject, project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        chapters = self.glossary_service._resolve_chapters(project_id=project_id, scope=scope)
        if not chapters:
            raise ToolError(code="invalid_arguments", message="scope 范围内没有可处理的章节。", status=400)

        created = 0
        actual_model_name = provider_model_name or model_profile_id
        self.glossary_service.reset_generation_tracking()
        for chapter in chapters:
            chapter_text = Path(chapter.normalized_path).read_text(encoding="utf-8")
            extracted_terms = self.glossary_service._extract_terms(
                chapter_text=chapter_text,
                chapter_index=chapter.chapter_index,
                chapter_title=chapter.chapter_title,
                source_language=project.source_language,
                target_language=project.target_language,
                model_name=actual_model_name,
            )
            decided_terms = self.glossary_service._decide_terms(
                project=project,
                chapter=chapter,
                extracted_terms=extracted_terms,
                model_name=actual_model_name,
            )
            for item in decided_terms:
                self.glossary.create_draft_candidate(
                    workflow_run_id=workflow_run_id,
                    project_id=project_id,
                    chapter_id=chapter.id,
                    source_term=item.source_term,
                    suggested_term=item.suggested_term,
                    category=item.category,
                    gender=item.gender,
                    age_group=item.age_group,
                    term_group_key=item.term_group_key,
                    relation_role=item.relation_role,
                    scope_level="project_term",
                    scope_chapter_id=None,
                    evidence_payload={
                        "workflow_step_run_id": workflow_step_run_id,
                        "chapter_id": chapter.id,
                        "chapter_index": chapter.chapter_index,
                        "chapter_title": chapter.chapter_title,
                        "note": item.note,
                        "gender": item.gender,
                        "age_group": item.age_group,
                    },
                    status="pending",
                )
                created += 1
        return {"draft_candidate_count": created} | self.glossary_service.build_generation_metadata()

    def normalize_candidates(self, *, workflow_run_id: int, workflow_step_run_id: int) -> dict[str, object]:
        draft_items = self.glossary.list_draft_candidates(workflow_run_id=workflow_run_id)
        unique_terms = {
            (
                item.chapter_id,
                item.source_term,
                item.suggested_term,
                item.category,
                item.gender,
                item.age_group,
                item.term_group_key,
                item.relation_role,
            )
            for item in draft_items
        }
        return {
            "draft_candidate_count": len(draft_items),
            "normalized_candidate_count": len(unique_terms),
            "workflow_step_run_id": workflow_step_run_id,
        }

    def review_relation_candidates(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
    ) -> dict[str, object]:
        draft_items = self.glossary.list_draft_candidates(workflow_run_id=workflow_run_id)
        self.glossary_service.reset_generation_tracking()
        decisions = self.glossary_service._review_relationships(
            draft_items=draft_items,
            model_name=provider_model_name or model_profile_id,
        )
        for item in decisions:
            self.glossary.create_candidate_review(
                draft_candidate_id=int(item["draft_candidate_id"]),
                step_run_id=workflow_step_run_id,
                review_type="relation",
                decision=str(item["relation_role"]),
                score=float(item["score"]) if item.get("score") is not None else None,
                reason_codes=[str(code) for code in item.get("reason_codes", [])],
                structured_payload=dict(item),
            )
        return {
            "draft_candidate_count": len(draft_items),
            "reviewed_count": len(decisions),
        } | self.glossary_service.build_generation_metadata()

    def review_scope_candidates(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
    ) -> dict[str, object]:
        draft_items = self.glossary.list_draft_candidates(workflow_run_id=workflow_run_id)
        self.glossary_service.reset_generation_tracking()
        decisions = self.glossary_service._review_scope_levels(
            draft_items=draft_items,
            model_name=provider_model_name or model_profile_id,
        )
        for item in decisions:
            self.glossary.create_candidate_review(
                draft_candidate_id=int(item["draft_candidate_id"]),
                step_run_id=workflow_step_run_id,
                review_type="scope",
                decision=str(item["scope_level"]),
                score=float(item["score"]) if item.get("score") is not None else None,
                reason_codes=[str(code) for code in item.get("reason_codes", [])],
                structured_payload=dict(item),
            )
        return {
            "draft_candidate_count": len(draft_items),
            "reviewed_count": len(decisions),
        } | self.glossary_service.build_generation_metadata()

    def finalize_candidates(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
    ) -> dict[str, object]:
        result = self.glossary_service.finalize_from_workflow(
            workflow_run_id=workflow_run_id,
            workflow_step_run_id=workflow_step_run_id,
            project_id=project_id,
            model_name=provider_model_name or model_profile_id,
        )
        return {
            "candidate_count": result.candidate_count,
            "workflow_step_run_id": workflow_step_run_id,
            "finalized_terms": self.glossary_service.build_finalized_terms_preview(
                workflow_run_id=workflow_run_id
            ),
        }
