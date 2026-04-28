from __future__ import annotations

import json
from typing import Any

from ..errors import ToolError
from ..repositories.workflows import WorkflowRepository
from .workflow_runtime_service import (
    SUPPORTED_GLOSSARY_WORKFLOW_ACTIONS,
    SUPPORTED_TRANSLATION_WORKFLOW_ACTIONS,
)


class WorkflowProfileService:
    BUILTIN_WORKFLOWS: dict[str, dict[str, Any]] = {
        "glossary_single_llm_v1": {
            "workflow_key": "glossary_single_llm_v1",
            "stage": "glossary",
            "status": "active",
            "is_default": True,
            "definition_json": {
                "name": "glossary_single_llm_v1",
                "steps": [
                    {
                        "step_key": "extract_primary",
                        "action": "glossary.extract",
                        "llm_role": "extractor",
                        "model_profile_id": "$request.default",
                    },
                    {
                        "step_key": "normalize_candidates",
                        "action": "glossary.normalize",
                        "llm_role": "normalizer",
                        "model_profile_id": "$request.default",
                    },
                    {
                        "step_key": "review_relations",
                        "action": "glossary.review_relations",
                        "llm_role": "relation_reviewer",
                        "model_profile_id": "$request.default",
                    },
                    {
                        "step_key": "review_scope",
                        "action": "glossary.review_scope",
                        "llm_role": "scope_reviewer",
                        "model_profile_id": "$request.default",
                    },
                    {
                        "step_key": "review_consistency",
                        "action": "glossary.review_consistency",
                        "llm_role": "consistency_reviewer",
                        "model_profile_id": "$request.default",
                    },
                    {
                        "step_key": "finalize_terms",
                        "action": "glossary.finalize",
                        "llm_role": "final_judge",
                        "model_profile_id": "$request.default",
                    },
                ],
            },
        },
        "glossary_multi_llm_v1": {
            "workflow_key": "glossary_multi_llm_v1",
            "stage": "glossary",
            "status": "active",
            "is_default": False,
            "definition_json": {
                "name": "glossary_multi_llm_v1",
                "steps": [
                    {
                        "step_key": "extract_primary",
                        "action": "glossary.extract",
                        "llm_role": "extractor",
                        "model_profile_id": "$request.default",
                        "failure_mode": "quorum",
                        "minimum_success": 1,
                    },
                    {
                        "step_key": "extract_secondary",
                        "action": "glossary.extract",
                        "llm_role": "extractor",
                        "model_profile_id": "$request.default",
                        "failure_mode": "quorum",
                        "minimum_success": 1,
                    },
                    {
                        "step_key": "normalize_candidates",
                        "action": "glossary.normalize",
                        "llm_role": "normalizer",
                        "model_profile_id": "$request.default",
                        "failure_mode": "required",
                    },
                    {
                        "step_key": "review_relations",
                        "action": "glossary.review_relations",
                        "llm_role": "relation_reviewer",
                        "model_profile_id": "$request.default",
                        "failure_mode": "required",
                    },
                    {
                        "step_key": "review_scope",
                        "action": "glossary.review_scope",
                        "llm_role": "scope_reviewer",
                        "model_profile_id": "$request.default",
                        "failure_mode": "required",
                    },
                    {
                        "step_key": "review_consistency",
                        "action": "glossary.review_consistency",
                        "llm_role": "consistency_reviewer",
                        "model_profile_id": "$request.default",
                        "failure_mode": "required",
                    },
                    {
                        "step_key": "finalize_terms",
                        "action": "glossary.finalize",
                        "llm_role": "final_judge",
                        "model_profile_id": "$request.default",
                        "failure_mode": "required",
                    },
                ],
                "terminal_status": {
                    "low_confidence": "insufficient_evidence",
                },
            },
        },
        "translation_single_llm_v1": {
            "workflow_key": "translation_single_llm_v1",
            "stage": "translation",
            "status": "active",
            "is_default": True,
            "definition_json": {
                "name": "translation_single_llm_v1",
                "steps": [
                    {
                        "step_key": "generate_primary",
                        "action": "translation.generate_draft",
                        "llm_role": "draft_generator",
                        "model_profile_id": "$request.default",
                        "draft_role": "primary",
                    },
                    {
                        "step_key": "finalize_segments",
                        "action": "translation.finalize",
                        "llm_role": "final_judge",
                        "model_profile_id": "$request.default",
                    },
                ],
            },
        },
        "translation_multi_llm_v1": {
            "workflow_key": "translation_multi_llm_v1",
            "stage": "translation",
            "status": "active",
            "is_default": False,
            "definition_json": {
                "name": "translation_multi_llm_v1",
                "steps": [
                    {
                        "step_key": "generate_primary",
                        "action": "translation.generate_draft",
                        "llm_role": "draft_generator",
                        "model_profile_id": "$request.default",
                        "draft_role": "primary",
                        "failure_mode": "quorum",
                        "minimum_success": 1,
                    },
                    {
                        "step_key": "generate_secondary",
                        "action": "translation.generate_draft",
                        "llm_role": "draft_generator",
                        "model_profile_id": "$request.default",
                        "draft_role": "secondary",
                        "failure_mode": "quorum",
                        "minimum_success": 1,
                    },
                    {
                        "step_key": "review_drafts",
                        "action": "translation.review_draft",
                        "llm_role": "reviewer",
                        "model_profile_id": "$request.default",
                        "failure_mode": "required",
                    },
                    {
                        "step_key": "rewrite_consensus",
                        "action": "translation.rewrite_draft",
                        "llm_role": "rewriter",
                        "model_profile_id": "$request.default",
                        "failure_mode": "required",
                    },
                    {
                        "step_key": "finalize_segments",
                        "action": "translation.finalize",
                        "llm_role": "final_judge",
                        "model_profile_id": "$request.default",
                        "failure_mode": "required",
                    },
                ],
                "terminal_status": {
                    "low_confidence": "insufficient_evidence",
                },
            },
        },
    }

    def __init__(self, session) -> None:
        self.session = session
        self.repository = WorkflowRepository(session)

    def ensure_builtin_profiles(self) -> bool:
        changed = False
        for builtin in self.BUILTIN_WORKFLOWS.values():
            existing = self.repository.get_profile(str(builtin["workflow_key"]))
            if existing is not None:
                expected_definition = dict(builtin["definition_json"])
                if (
                    existing.stage != str(builtin["stage"])
                    or existing.status != str(builtin["status"])
                    or existing.definition_json != expected_definition
                ):
                    existing.stage = str(builtin["stage"])
                    existing.status = str(builtin["status"])
                    existing.definition_json = expected_definition
                    changed = True
                continue
            self.repository.create_profile(
                workflow_key=str(builtin["workflow_key"]),
                stage=str(builtin["stage"]),
                status=str(builtin["status"]),
                is_default=bool(builtin["is_default"]),
                definition_json=dict(builtin["definition_json"]),
            )
            changed = True
        return changed

    def create_workflow(
        self,
        *,
        workflow_key: str,
        stage: str,
        status: str = "active",
        is_default: bool = False,
        definition_json: dict[str, Any] | str | None = None,
    ) -> dict[str, object]:
        normalized_workflow_key = workflow_key.strip()
        if not normalized_workflow_key:
            raise ToolError(code="invalid_arguments", message="workflow_key 不能为空。", status=400)
        if self.repository.get_profile(normalized_workflow_key) is not None:
            raise ToolError(code="conflict_error", message=f"workflow_key={normalized_workflow_key} 已存在。", status=409)

        record = self.repository.create_profile(
            workflow_key=normalized_workflow_key,
            stage=stage.strip(),
            status=status,
            is_default=is_default,
            definition_json=self._normalize_definition_json(stage=stage.strip(), definition_json=definition_json),
        )
        self.session.commit()
        return self._serialize_profile(record)

    def list_workflows(self, stage: str | None = None) -> dict[str, object]:
        profiles = self.repository.list_profiles(stage=stage)
        return {
            "workflows": [self._serialize_profile(profile) for profile in profiles],
        }

    def inspect_workflow(self, *, workflow_key: str) -> dict[str, object]:
        profile = self.repository.get_profile(workflow_key)
        if profile is None:
            raise ToolError(code="not_found", message=f"找不到 workflow {workflow_key}。", status=404)
        return self._serialize_profile(profile)

    def set_default(self, *, workflow_key: str, stage: str | None = None) -> dict[str, object]:
        profile = self.repository.get_profile(workflow_key)
        if profile is None:
            raise ToolError(code="not_found", message=f"找不到 workflow {workflow_key}。", status=404)

        target_stage = stage.strip() if stage is not None else profile.stage
        try:
            updated_profile = self.repository.set_default_for_stage(profile.workflow_key, target_stage)
        except ValueError as exc:
            raise ToolError(code="invalid_arguments", message=str(exc), status=400) from exc
        self.session.commit()
        if updated_profile is None:
            raise ToolError(code="not_found", message=f"找不到 workflow {workflow_key}。", status=404)
        return self._serialize_profile(updated_profile)

    def _serialize_profile(self, profile) -> dict[str, object]:
        return {
            "workflow_key": profile.workflow_key,
            "stage": profile.stage,
            "status": profile.status,
            "is_default": bool(profile.is_default),
            "definition_json": profile.definition_json,
        }

    def _normalize_definition_json(self, *, stage: str, definition_json: dict[str, Any] | str | None) -> dict[str, Any]:
        if definition_json is None:
            normalized_definition = {}
        elif isinstance(definition_json, dict):
            normalized_definition = definition_json
        else:
            normalized_definition_json = definition_json.strip()
            if not normalized_definition_json:
                normalized_definition = {}
            else:
                try:
                    parsed_definition = json.loads(normalized_definition_json)
                except json.JSONDecodeError as exc:
                    raise ToolError(code="invalid_arguments", message="definition_json 不是有效的 JSON。", status=400) from exc
                if not isinstance(parsed_definition, dict):
                    raise ToolError(code="invalid_arguments", message="definition_json 必须是对象。", status=400)
                normalized_definition = parsed_definition
        self._validate_definition_json(stage=stage, definition_json=normalized_definition)
        return normalized_definition

    def _validate_definition_json(self, *, stage: str, definition_json: dict[str, Any]) -> None:
        normalized_stage = stage.strip().lower()
        if normalized_stage == "glossary":
            supported_actions = SUPPORTED_GLOSSARY_WORKFLOW_ACTIONS
        elif normalized_stage == "translation":
            supported_actions = SUPPORTED_TRANSLATION_WORKFLOW_ACTIONS
        else:
            return
        steps = definition_json.get("steps", [])
        if not isinstance(steps, list):
            raise ToolError(code="invalid_arguments", message=f"{normalized_stage} workflow 的 steps 必须是数组。", status=400)
        for index, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                raise ToolError(code="invalid_arguments", message=f"{normalized_stage} workflow 的 step {index} 必须是对象。", status=400)
            action = str(step.get("action") or "").strip()
            if action not in supported_actions:
                raise ToolError(
                    code="invalid_arguments",
                    message=f"{normalized_stage} workflow 的 step action 不支持: {action or '<empty>'}。",
                    status=400,
                )
