from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import (
    Chapter,
    ChapterSegment,
    ExportRun,
    GlossaryCandidate,
    GlossaryDraftCandidate,
    GlossaryEntry,
    ReviewRun,
    SegmentTranslation,
    SegmentTranslationVersion,
    StageRun,
    TranslationProject,
    WorkflowRun,
)
from ..errors import ToolError
from ..providers.base import Provider, TextGenerationResult
from ..repositories.glossary import GlossaryRepository
from .scope_service import ensure_scope_supported, get_stage_scope_types, scope_matches_chapters
from .workflow_profile_service import WorkflowProfileService
from .workflow_runtime_service import WorkflowRuntimeService


@dataclass(frozen=True)
class GlossaryResult:
    candidate_count: int


@dataclass(frozen=True)
class GlossaryExtraction:
    source_term: str
    suggested_term: str
    category: str
    note: str | None
    term_group_key: str
    relation_role: str


class GlossaryService:
    def __init__(self, session: Session, *, provider: Provider | None = None) -> None:
        self.session = session
        self.provider = provider
        self.glossary = GlossaryRepository(session)
        self._generation_results: list[TextGenerationResult] = []

    def seed_locked_entry(self, *, project_id: int, source_term: str, target_term: str) -> GlossaryEntry:
        existing = self.glossary.get_entry(project_id, source_term)
        if existing is None:
            entry = self.glossary.create_entry(
                project_id=project_id,
                source_term=source_term,
                target_term=target_term,
                locked=1,
                term_group_key=source_term,
                relation_role="independent",
            )
        else:
            existing.target_term = target_term
            existing.locked = 1
            entry = existing
        self.session.commit()
        return entry

    def get_entry(self, *, project_id: int, source_term: str) -> GlossaryEntry:
        entry = self.glossary.get_entry(project_id, source_term)
        if entry is None:
            raise ToolError(code="not_found", message=f"找不到术语 {source_term}。", status=404)
        return entry

    def run(
        self,
        *,
        request_id: str,
        project_id: int,
        scope: dict[str, object],
        model_profile_id: str = "default",
        provider_model_name: str | None = None,
        workflow_key: str | None = None,
        stage_run_id: int | None = None,
        heartbeat: Callable[[], None] | None = None,
    ) -> GlossaryResult:
        project = self.session.get(TranslationProject, project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)
        ensure_scope_supported(scope, stage="glossary", allowed_types=get_stage_scope_types("glossary"))
        if self.provider is None:
            raise ToolError(code="invalid_arguments", message="缺少术语提取 provider。", status=400)
        profile_service = WorkflowProfileService(self.session)
        if profile_service.ensure_builtin_profiles():
            if stage_run_id is None:
                self.session.commit()
            else:
                self.session.flush()

        workflow_runtime = WorkflowRuntimeService(self.session)
        workflow_definition = workflow_runtime.resolve_workflow_definition(stage="glossary", workflow_key=workflow_key)

        from .glossary_pipeline_service import GlossaryPipelineService

        result = workflow_runtime.run_glossary_workflow(
            workflow_definition=workflow_definition,
            workflow_key=str(workflow_definition["workflow_key"]),
            request_id=request_id,
            project_id=project_id,
            scope=scope,
            request_model_profile_id=model_profile_id,
            provider_model_name=provider_model_name,
            pipeline=GlossaryPipelineService(self.session, provider=self.provider),
            stage_run_id=stage_run_id,
            heartbeat=heartbeat,
        )

        summary = json.dumps(
            {
                "request_id": request_id,
                "candidate_count": result.candidate_count,
            },
            ensure_ascii=False,
        )
        if stage_run_id is None:
            self.session.add(
                StageRun(
                    project_id=project_id,
                    stage="glossary",
                    scope_type=str(scope["type"]),
                    scope_value=json.dumps(scope, ensure_ascii=False),
                    status="completed",
                    summary=summary,
                )
            )
            self.session.commit()
        else:
            stage_run = self.session.get(StageRun, stage_run_id)
            if stage_run is None:
                raise ToolError(code="not_found", message=f"找不到 stage_run {stage_run_id}。", status=404)
            self.session.flush()
        return result

    def inspect(self, *, project_id: int) -> dict[str, list[dict[str, object]]]:
        entries = [
            {
                "id": entry.id,
                "project_id": entry.project_id,
                "source_term": entry.source_term,
                "target_term": entry.target_term,
                "category": entry.category,
                "status": entry.status,
                "locked": entry.locked,
                "term_group_key": entry.term_group_key,
                "relation_role": entry.relation_role,
            }
            for entry in self.glossary.list_entries(project_id)
        ]
        candidates = [
            {
                "id": candidate.id,
                "project_id": candidate.project_id,
                "chapter_id": candidate.chapter_id,
                "source_term": candidate.source_term,
                "suggested_term": candidate.suggested_term,
                "status": candidate.status,
                "term_group_key": candidate.term_group_key,
                "relation_role": candidate.relation_role,
            }
            for candidate in self.glossary.list_candidates(project_id)
        ]
        return {"entries": entries, "candidates": candidates}

    def reset_generation_tracking(self) -> None:
        self._generation_results = []

    def build_generation_metadata(self) -> dict[str, object]:
        if not self._generation_results:
            return {}
        last_result = self._generation_results[-1]
        payload: dict[str, object] = {
            "model_name": last_result.model_name,
            "provider_name": last_result.provider_name,
            "fallback_depth": max(int(item.fallback_depth or 0) for item in self._generation_results),
        }
        if last_result.model_profile_id:
            payload["model_profile_id"] = last_result.model_profile_id
        return payload

    def _resolve_chapters(self, *, project_id: int, scope: dict[str, object]) -> list[Chapter]:
        ensure_scope_supported(scope, stage="glossary", allowed_types=get_stage_scope_types("glossary"))
        statement = select(Chapter).where(Chapter.project_id == project_id)
        scope_type = str(scope["type"])
        if scope_type == "chapter_range":
            statement = statement.where(
                Chapter.chapter_index >= int(scope["start"]),
                Chapter.chapter_index <= int(scope["end"]),
            )
        if scope_type == "chapter_list":
            statement = statement.where(Chapter.chapter_index.in_(list(scope["chapters"])))
        statement = statement.order_by(Chapter.chapter_index.asc())
        return list(self.session.execute(statement).scalars().all())

    def _extract_terms(
        self,
        *,
        chapter_text: str,
        chapter_index: int,
        chapter_title: str,
        source_language: str,
        target_language: str,
        model_name: str,
    ) -> list[GlossaryExtraction]:
        if self.provider is None:
            raise ToolError(code="invalid_arguments", message="缺少术语提取 provider。", status=400)
        prompt = self._build_extraction_prompt(
            chapter_text=chapter_text,
            chapter_index=chapter_index,
            chapter_title=chapter_title,
            source_language=source_language,
            target_language=target_language,
        )
        response = self.provider.generate_text(
            prompt=prompt,
            model_name=model_name,
            timeout_seconds=60,
        )
        self._generation_results.append(response)
        return self._parse_extraction_response(response.content)

    def _decide_terms(
        self,
        *,
        project: TranslationProject,
        chapter: Chapter,
        extracted_terms: list[GlossaryExtraction],
        model_name: str,
    ) -> list[GlossaryExtraction]:
        if not extracted_terms:
            return []
        if not self._should_run_decision_stage(extracted_terms):
            return extracted_terms
        if self.provider is None:
            return extracted_terms
        prompt = self._build_decision_prompt(
            project=project,
            chapter=chapter,
            extracted_terms=extracted_terms,
        )
        response = self.provider.generate_text(
            prompt=prompt,
            model_name=model_name,
            timeout_seconds=60,
        )
        self._generation_results.append(response)
        return self._apply_decisions(extracted_terms, response.content)

    def _build_extraction_prompt(
        self,
        *,
        chapter_text: str,
        chapter_index: int,
        chapter_title: str,
        source_language: str,
        target_language: str,
    ) -> str:
        return (
            "你是小说翻译平台的术语抽取器。请只根据给定章节正文，提取术语，并优先保留后续翻译需要保持一致的项目。\n"
            f"源语言: {source_language}\n"
            f"目标语言: {target_language}\n"
            f"章节号: {chapter_index}\n"
            f"章节标题: {chapter_title}\n"
            "优先提取：人名、地名、组织/势力、专有物件、固定称谓、世界观术语、俚语/梗。\n"
            "不要输出普通代词、泛化名词、完整句子或解释性段落。\n"
            "请直接返回 JSON，不要包额外说明。允许两种格式：数组，或 {\"terms\": [...]}。\n"
            "每个术语对象字段：source_term, translated_term, category, note, term_group_key, relation_role。\n"
            "category 推荐使用 character/location/organization/item/title/slang/term/other。\n"
            "relation_role 仅允许 canonical/alias/title/variant/independent。\n"
            "translated_term 必须给出建议译名；note 可为空。\n\n"
            "待提取章节正文：\n"
            f"{chapter_text}"
        )

    def _build_decision_prompt(
        self,
        *,
        project: TranslationProject,
        chapter: Chapter,
        extracted_terms: list[GlossaryExtraction],
    ) -> str:
        existing_entries = [
            {
                "source_term": entry.source_term,
                "target_term": entry.target_term,
                "category": entry.category,
                "term_group_key": entry.term_group_key,
                "relation_role": entry.relation_role,
                "locked": entry.locked,
            }
            for entry in self.glossary.list_active_entries_for_matching(project.id)
        ]
        candidates = [
            {
                "source_term": item.source_term,
                "translated_term": item.suggested_term,
                "category": item.category,
                "term_group_key": item.term_group_key,
                "relation_role": item.relation_role,
                "note": item.note,
            }
            for item in extracted_terms
        ]
        return (
            "你是小说翻译平台的术语裁决器。请对候选术语做保守裁决，只保留真正值得进入术语表的项目。\n"
            f"源语言: {project.source_language}\n"
            f"目标语言: {project.target_language}\n"
            f"章节号: {chapter.chapter_index}\n"
            f"章节标题: {chapter.chapter_title}\n"
            "规则：\n"
            "1. 允许正式名、简称、称号共存，不要按子串关系删词。\n"
            "2. 像“第1章”“第一卷”这类纯结构壳应剔除。\n"
            "3. 如果候选应与已有术语同组，请给出正确的 term_group_key 和 relation_role。\n"
            "4. 如果没有充分理由，不要改动已存在术语的目标写法。\n"
            "只返回 JSON：{\"decisions\":[{\"source_term\":\"...\",\"keep\":true,\"term_group_key\":\"...\",\"relation_role\":\"...\",\"reason\":\"...\"}]}\n\n"
            f"已有术语：\n{json.dumps(existing_entries, ensure_ascii=False)}\n\n"
            f"待裁决候选：\n{json.dumps(candidates, ensure_ascii=False)}"
        )

    def _parse_extraction_response(self, content: str) -> list[GlossaryExtraction]:
        normalized = self._strip_code_fence(content).strip()
        if normalized == "":
            return []
        try:
            payload = json.loads(normalized)
        except json.JSONDecodeError as exc:
            raise ToolError(
                code="provider_error",
                message=f"术语提取返回了无效 JSON：{exc}",
                status=502,
            ) from exc

        raw_terms: object
        if isinstance(payload, dict):
            raw_terms = payload.get("terms", [])
        else:
            raw_terms = payload
        if not isinstance(raw_terms, list):
            raise ToolError(
                code="provider_error",
                message="术语提取返回格式错误：terms 必须是数组。",
                status=502,
            )

        results: list[GlossaryExtraction] = []
        seen_terms: set[str] = set()
        for item in raw_terms:
            if not isinstance(item, dict):
                continue
            source_term = self._normalize_text(item.get("source_term"))
            suggested_term = self._normalize_text(
                item.get("translated_term") or item.get("target_term") or item.get("suggested_term")
            )
            if source_term == "" or suggested_term == "":
                continue
            if source_term in seen_terms:
                continue
            category = self._normalize_text(item.get("category")) or "term"
            note = self._normalize_optional_text(item.get("note"))
            term_group_key = self._normalize_text(item.get("term_group_key")) or source_term
            relation_role = self._normalize_text(item.get("relation_role")) or "independent"
            results.append(
                GlossaryExtraction(
                    source_term=source_term,
                    suggested_term=suggested_term,
                    category=category,
                    note=note,
                    term_group_key=term_group_key,
                    relation_role=relation_role,
                )
            )
            seen_terms.add(source_term)
        return results

    def _should_run_decision_stage(self, extracted_terms: list[GlossaryExtraction]) -> bool:
        return any(
            item.term_group_key != item.source_term or item.relation_role != "independent"
            for item in extracted_terms
        )

    def _apply_decisions(
        self,
        extracted_terms: list[GlossaryExtraction],
        content: str,
    ) -> list[GlossaryExtraction]:
        normalized = self._strip_code_fence(content).strip()
        if normalized == "":
            return extracted_terms
        try:
            payload = json.loads(normalized)
        except json.JSONDecodeError:
            return extracted_terms
        if not isinstance(payload, dict):
            return extracted_terms
        raw_decisions = payload.get("decisions")
        if not isinstance(raw_decisions, list):
            return extracted_terms

        decisions_by_term: dict[str, dict[str, object]] = {}
        for item in raw_decisions:
            if not isinstance(item, dict):
                continue
            source_term = self._normalize_text(item.get("source_term"))
            if source_term == "":
                continue
            decisions_by_term[source_term] = item

        decided_terms: list[GlossaryExtraction] = []
        for extracted in extracted_terms:
            decision = decisions_by_term.get(extracted.source_term)
            if decision is None:
                decided_terms.append(extracted)
                continue
            if bool(decision.get("keep")) is False:
                continue
            decided_terms.append(
                GlossaryExtraction(
                    source_term=extracted.source_term,
                    suggested_term=extracted.suggested_term,
                    category=extracted.category,
                    note=extracted.note,
                    term_group_key=(
                        self._normalize_text(decision.get("term_group_key")) or extracted.term_group_key
                    ),
                    relation_role=(
                        self._normalize_text(decision.get("relation_role")) or extracted.relation_role
                    ),
                )
            )
        return decided_terms

    def _review_relationships(
        self,
        *,
        draft_items: list[GlossaryDraftCandidate],
        model_name: str,
    ) -> list[dict[str, object]]:
        if not draft_items:
            return []
        default_items = [
            {
                "draft_candidate_id": item.id,
                "term_group_key": item.term_group_key,
                "relation_role": item.relation_role,
                "score": 1.0,
                "reason_codes": ["carry_forward"],
            }
            for item in draft_items
        ]
        if self.provider is None:
            return default_items
        payload = [
            {
                "draft_candidate_id": item.id,
                "source_term": item.source_term,
                "suggested_term": item.suggested_term,
                "category": item.category,
                "term_group_key": item.term_group_key,
                "relation_role": item.relation_role,
            }
            for item in draft_items
        ]
        prompt = (
            "你是小说术语关系审核器。请判断每个候选是 canonical/alias/title/variant/independent 中哪一种。"
            "只返回 JSON：{\"items\":[{\"draft_candidate_id\":1,\"term_group_key\":\"char_linxi\",\"relation_role\":\"alias\",\"score\":0.9,\"reason_codes\":[\"same_entity\"]}]}\n\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )
        response = self.provider.generate_text(prompt=prompt, model_name=model_name, timeout_seconds=120)
        self._generation_results.append(response)
        parsed_items = self._parse_review_items(response.content, "items")
        return self._merge_review_items_with_defaults(
            draft_items=draft_items,
            parsed_items=parsed_items,
            default_items=default_items,
        )

    def _review_scope_levels(
        self,
        *,
        draft_items: list[GlossaryDraftCandidate],
        model_name: str,
    ) -> list[dict[str, object]]:
        if not draft_items:
            return []
        default_items = [
            {
                "draft_candidate_id": item.id,
                "scope_level": item.scope_level,
                "scope_chapter_id": item.scope_chapter_id,
                "score": 1.0,
                "reason_codes": ["carry_forward"],
            }
            for item in draft_items
        ]
        if self.provider is None:
            return default_items
        payload = [
            {
                "draft_candidate_id": item.id,
                "source_term": item.source_term,
                "chapter_id": item.chapter_id,
                "category": item.category,
            }
            for item in draft_items
        ]
        prompt = (
            "你是小说术语 scope 审核器。请判断候选应为 project_term、chapter_term 或 discard。"
            "只返回 JSON：{\"items\":[{\"draft_candidate_id\":1,\"scope_level\":\"chapter_term\",\"scope_chapter_id\":1,\"score\":0.85,\"reason_codes\":[\"single_chapter_epithet\"]}]}\n\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )
        response = self.provider.generate_text(prompt=prompt, model_name=model_name, timeout_seconds=120)
        self._generation_results.append(response)
        parsed_items = self._parse_review_items(response.content, "items")
        return self._merge_review_items_with_defaults(
            draft_items=draft_items,
            parsed_items=parsed_items,
            default_items=default_items,
        )

    def finalize_from_workflow(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        model_name: str,
    ) -> GlossaryResult:
        project = self.session.get(TranslationProject, project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)
        workflow_run = self.session.get(WorkflowRun, workflow_run_id)
        if workflow_run is None:
            raise ToolError(code="not_found", message=f"找不到 workflow_run {workflow_run_id}。", status=404)

        draft_items = self.glossary.list_draft_candidates(workflow_run_id=workflow_run_id)
        chapters = self._resolve_workflow_chapters(
            project_id=project_id,
            workflow_run=workflow_run,
            draft_items=draft_items,
        )
        chapter_ids = [chapter.id for chapter in chapters]
        if chapter_ids:
            self.glossary.delete_candidates_for_chapters(project_id, chapter_ids)

        finalized_terms = self._build_finalized_terms(
            workflow_run_id=workflow_run_id,
            draft_items=draft_items,
            model_name=model_name,
        )
        candidate_count = 0
        project_scope_terms: list[str] = []
        chapter_scope_terms: dict[int, list[str]] = {}
        for item in finalized_terms:
            scope_level = str(item["scope_level"])
            scope_chapter_id = item.get("scope_chapter_id")
            if scope_level == "project_term":
                scope_chapter_id = None
                project_scope_terms.append(str(item["source_term"]))
            else:
                if scope_chapter_id is None:
                    scope_chapter_id = int(item["chapter_id"])
                chapter_scope_terms.setdefault(int(scope_chapter_id), []).append(str(item["source_term"]))
            entry = self.glossary.get_entry(
                project_id,
                str(item["source_term"]),
                scope_level=scope_level,
                scope_chapter_id=int(scope_chapter_id) if scope_chapter_id is not None else None,
            )
            if entry is None:
                self.glossary.create_entry(
                    project_id=project_id,
                    source_term=str(item["source_term"]),
                    target_term=str(item["target_term"]),
                    category=str(item["category"]),
                    note=self._normalize_optional_text(item.get("note")),
                    locked=0,
                    term_group_key=str(item["term_group_key"]),
                    relation_role=str(item["relation_role"]),
                    scope_level=scope_level,
                    scope_chapter_id=int(scope_chapter_id) if scope_chapter_id is not None else None,
                )
            elif entry.locked == 0:
                entry.target_term = str(item["target_term"])
                entry.category = str(item["category"])
                entry.note = self._normalize_optional_text(item.get("note"))
                entry.status = "active"
                entry.term_group_key = str(item["term_group_key"])
                entry.relation_role = str(item["relation_role"])
                entry.scope_level = scope_level
                entry.scope_chapter_id = int(scope_chapter_id) if scope_chapter_id is not None else None
                entry.scope_anchor = "project" if scope_level == "project_term" else f"chapter:{scope_chapter_id}"

            self.glossary.create_candidate(
                project_id=project_id,
                chapter_id=int(item["chapter_id"]),
                source_term=str(item["source_term"]),
                suggested_term=str(item["target_term"]),
                status="pending",
                term_group_key=str(item["term_group_key"]),
                relation_role=str(item["relation_role"]),
                scope_level=scope_level,
                scope_chapter_id=int(scope_chapter_id) if scope_chapter_id is not None else None,
                workflow_run_id=workflow_run_id,
            )
            candidate_count += 1

        self.glossary.delete_unlocked_entries_not_in_terms(
            project_id,
            project_scope_terms,
            scope_level="project_term",
        )
        for chapter_id in chapter_ids:
            self.glossary.delete_unlocked_entries_not_in_terms(
                project_id,
                chapter_scope_terms.get(chapter_id, []),
                scope_level="chapter_term",
                scope_chapter_id=chapter_id,
            )
        self._mark_related_outputs_stale(project_id=project_id, chapters=chapters)
        return GlossaryResult(candidate_count=candidate_count)

    def inspect_result(self, *, project_id: int, workflow_run_id: int) -> GlossaryResult:
        candidates = [
            candidate
            for candidate in self.glossary.list_candidates(project_id)
            if candidate.workflow_run_id == workflow_run_id
        ]
        return GlossaryResult(candidate_count=len(candidates))

    def _strip_code_fence(self, content: str) -> str:
        stripped = content.strip()
        if not stripped.startswith("```"):
            return stripped

        lines = stripped.splitlines()
        if not lines:
            return stripped
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)

    def _normalize_text(self, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def _normalize_optional_text(self, value: object) -> str | None:
        normalized = self._normalize_text(value)
        return normalized or None

    def _parse_review_items(self, content: str, key: str) -> list[dict[str, object]]:
        normalized = self._strip_code_fence(content).strip()
        if normalized == "":
            return []
        try:
            payload = json.loads(normalized)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, dict):
            return []
        raw_items = payload.get(key, [])
        if not isinstance(raw_items, list):
            return []
        return [dict(item) for item in raw_items if isinstance(item, dict)]

    def _merge_review_items_with_defaults(
        self,
        *,
        draft_items: list[GlossaryDraftCandidate],
        parsed_items: list[dict[str, object]],
        default_items: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        draft_ids = {item.id for item in draft_items}
        parsed_by_id: dict[int, dict[str, object]] = {}
        for item in parsed_items:
            draft_candidate_id = item.get("draft_candidate_id")
            if isinstance(draft_candidate_id, int) and draft_candidate_id in draft_ids:
                parsed_by_id[draft_candidate_id] = item
        merged_items: list[dict[str, object]] = []
        for default_item in default_items:
            draft_candidate_id = int(default_item["draft_candidate_id"])
            merged_items.append(parsed_by_id.get(draft_candidate_id, default_item))
        return merged_items

    def _build_finalized_terms(
        self,
        *,
        workflow_run_id: int,
        draft_items: list[GlossaryDraftCandidate],
        model_name: str,
    ) -> list[dict[str, object]]:
        review_items = self.glossary.inspect_candidate_reviews(workflow_run_id=workflow_run_id)
        provider_terms = self._request_finalized_terms(
            workflow_run_id=workflow_run_id,
            review_items=review_items,
            model_name=model_name,
        )
        relation_reviews, scope_reviews = self._index_review_items(review_items)
        if provider_terms:
            hydrated_terms = self._hydrate_provider_final_terms(
                provider_terms=provider_terms,
                draft_items=draft_items,
                relation_reviews=relation_reviews,
                scope_reviews=scope_reviews,
            )
            if hydrated_terms:
                return hydrated_terms
        finalized_terms: list[dict[str, object]] = []
        for item in draft_items:
            relation_review = relation_reviews.get(item.id, {})
            scope_review = scope_reviews.get(item.id, {})
            scope_level = str(scope_review.get("scope_level") or item.scope_level)
            if scope_level == "discard":
                continue
            scope_chapter_id = scope_review.get("scope_chapter_id")
            if scope_level == "project_term":
                scope_chapter_id = None
            elif scope_chapter_id is None:
                scope_chapter_id = item.scope_chapter_id or item.chapter_id
            evidence_payload = item.evidence_payload if isinstance(item.evidence_payload, dict) else {}
            finalized_terms.append(
                {
                    "draft_candidate_id": item.id,
                    "chapter_id": item.chapter_id,
                    "source_term": item.source_term,
                    "target_term": item.suggested_term,
                    "category": item.category,
                    "note": evidence_payload.get("note"),
                    "term_group_key": str(relation_review.get("term_group_key") or item.term_group_key),
                    "relation_role": str(relation_review.get("relation_role") or item.relation_role),
                    "scope_level": scope_level,
                    "scope_chapter_id": scope_chapter_id,
                }
            )
        return finalized_terms

    def _request_finalized_terms(
        self,
        *,
        workflow_run_id: int,
        review_items: list[dict[str, object]],
        model_name: str,
    ) -> list[dict[str, object]]:
        if self.provider is None:
            return []
        prompt = (
            "你是小说术语终审器。请综合 draft candidates 和 review 记录，只保留最终应进入 glossary 的项目。"
            "只返回 JSON：{\"terms\":[{\"source_term\":\"林溪\",\"target_term\":\"Lin Xi\",\"category\":\"character\",\"note\":null,\"term_group_key\":\"char_linxi\",\"relation_role\":\"canonical\",\"scope_level\":\"project_term\",\"scope_chapter_id\":null}]}\n\n"
            f"draft={json.dumps(self.glossary.inspect_draft_candidates(workflow_run_id=workflow_run_id), ensure_ascii=False)}\n"
            f"reviews={json.dumps(review_items, ensure_ascii=False)}"
        )
        response = self.provider.generate_text(prompt=prompt, model_name=model_name, timeout_seconds=120)
        return self._parse_review_items(response.content, "terms")

    def _index_review_items(
        self,
        review_items: list[dict[str, object]],
    ) -> tuple[dict[int, dict[str, object]], dict[int, dict[str, object]]]:
        relation_reviews: dict[int, dict[str, object]] = {}
        scope_reviews: dict[int, dict[str, object]] = {}
        for item in review_items:
            draft_candidate_id = item.get("draft_candidate_id")
            if not isinstance(draft_candidate_id, int):
                continue
            if item.get("review_type") == "relation":
                relation_reviews[draft_candidate_id] = item
            elif item.get("review_type") == "scope":
                scope_reviews[draft_candidate_id] = item
        return relation_reviews, scope_reviews

    def _hydrate_provider_final_terms(
        self,
        *,
        provider_terms: list[dict[str, object]],
        draft_items: list[GlossaryDraftCandidate],
        relation_reviews: dict[int, dict[str, object]],
        scope_reviews: dict[int, dict[str, object]],
    ) -> list[dict[str, object]]:
        draft_by_id = {item.id: item for item in draft_items}
        draft_by_source = {item.source_term: item for item in draft_items}
        hydrated_terms: list[dict[str, object]] = []
        for term in provider_terms:
            draft_candidate_id = term.get("draft_candidate_id")
            matched_draft = None
            if isinstance(draft_candidate_id, int):
                matched_draft = draft_by_id.get(draft_candidate_id)
            if matched_draft is None:
                matched_draft = draft_by_source.get(str(term.get("source_term") or ""))
            if matched_draft is None:
                continue
            relation_review = relation_reviews.get(matched_draft.id, {})
            scope_review = scope_reviews.get(matched_draft.id, {})
            scope_level = str(term.get("scope_level") or scope_review.get("scope_level") or matched_draft.scope_level)
            if scope_level == "discard":
                continue
            scope_chapter_id = term.get("scope_chapter_id", scope_review.get("scope_chapter_id"))
            if scope_level == "project_term":
                scope_chapter_id = None
            elif scope_chapter_id is None:
                scope_chapter_id = matched_draft.scope_chapter_id or matched_draft.chapter_id
            evidence_payload = matched_draft.evidence_payload if isinstance(matched_draft.evidence_payload, dict) else {}
            hydrated_terms.append(
                {
                    "draft_candidate_id": matched_draft.id,
                    "chapter_id": matched_draft.chapter_id,
                    "source_term": str(term.get("source_term") or matched_draft.source_term),
                    "target_term": str(
                        term.get("target_term")
                        or term.get("suggested_term")
                        or matched_draft.suggested_term
                    ),
                    "category": str(term.get("category") or matched_draft.category),
                    "note": term.get("note", evidence_payload.get("note")),
                    "term_group_key": str(
                        term.get("term_group_key")
                        or relation_review.get("term_group_key")
                        or matched_draft.term_group_key
                    ),
                    "relation_role": str(
                        term.get("relation_role")
                        or relation_review.get("relation_role")
                        or matched_draft.relation_role
                    ),
                    "scope_level": scope_level,
                    "scope_chapter_id": scope_chapter_id,
                }
            )
        return hydrated_terms

    def _resolve_draft_chapters(self, draft_items: list[GlossaryDraftCandidate]) -> list[Chapter]:
        chapter_ids = sorted({item.chapter_id for item in draft_items})
        if not chapter_ids:
            return []
        statement = select(Chapter).where(Chapter.id.in_(chapter_ids)).order_by(Chapter.chapter_index.asc())
        return list(self.session.execute(statement).scalars().all())

    def _resolve_workflow_chapters(
        self,
        *,
        project_id: int,
        workflow_run: WorkflowRun,
        draft_items: list[GlossaryDraftCandidate],
    ) -> list[Chapter]:
        chapters = self._resolve_draft_chapters(draft_items)
        if chapters:
            return chapters
        scope_value = self._decode_summary(workflow_run.scope_value)
        if isinstance(scope_value, dict) and scope_value.get("type") is not None:
            return self._resolve_chapters(project_id=project_id, scope=scope_value)
        return []

    def _mark_related_outputs_stale(self, *, project_id: int, chapters: list[Chapter]) -> None:
        if not chapters:
            return

        chapter_ids = [chapter.id for chapter in chapters]
        chapter_indexes = [chapter.chapter_index for chapter in chapters]

        segments = self.session.execute(
            select(ChapterSegment)
            .where(
                ChapterSegment.project_id == project_id,
                ChapterSegment.chapter_id.in_(chapter_ids),
            )
            .order_by(ChapterSegment.id.asc())
        ).scalars().all()
        segment_ids = [segment.id for segment in segments]

        for segment in segments:
            if segment.translation_status == "translated":
                segment.translation_status = "stale"
            if segment.review_status != "pending":
                segment.review_status = "pending"

        if segment_ids:
            active_versions = self.session.execute(
                select(SegmentTranslationVersion)
                .join(SegmentTranslation, SegmentTranslation.id == SegmentTranslationVersion.segment_translation_id)
                .where(
                    SegmentTranslation.project_id == project_id,
                    SegmentTranslation.segment_id.in_(segment_ids),
                    SegmentTranslation.active_version_id == SegmentTranslationVersion.id,
                )
            ).scalars().all()
            for version in active_versions:
                if version.status == "completed":
                    version.status = "stale"

        for stage_run in self.session.execute(
            select(StageRun).where(
                StageRun.project_id == project_id,
                StageRun.stage.in_(["translation", "review", "export"]),
            )
        ).scalars().all():
            if self._scope_matches_chapters(self._decode_summary(stage_run.scope_value), chapter_indexes):
                stage_run.status = "stale"

        for review_run in self.session.execute(
            select(ReviewRun).where(ReviewRun.project_id == project_id)
        ).scalars().all():
            if self._scope_matches_chapters(self._decode_summary(review_run.scope_value), chapter_indexes):
                review_run.status = "stale"

        for export_run in self.session.execute(
            select(ExportRun).where(ExportRun.project_id == project_id)
        ).scalars().all():
            if self._scope_matches_chapters(self._decode_summary(export_run.scope_value), chapter_indexes):
                export_run.status = "stale"

    def _scope_matches_chapters(self, scope_value: object, chapter_indexes: list[int]) -> bool:
        return scope_matches_chapters(scope_value, chapter_indexes)

    def _decode_summary(self, value: str | None) -> object:
        if value is None or value == "":
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
