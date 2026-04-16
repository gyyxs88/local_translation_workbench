from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..db.models import (
    Chapter,
    ChapterSegment,
    ExportRun,
    GlossaryEntry,
    ReviewRun,
    SegmentTranslation,
    StageRun,
    TranslationProject,
)
from ..errors import ToolError
from ..providers.base import Provider
from ..repositories.glossary import GlossaryRepository
from ..repositories.translation_workflows import TranslationWorkflowRepository
from ..repositories.translations import TranslationRepository
from ..utils import ensure_directory
from .scope_service import ensure_scope_supported, get_stage_scope_types, scope_matches_chapters
from .synopsis_service import SynopsisService


class TranslationPipelineService:
    def __init__(
        self,
        session: Session,
        *,
        base_data_dir: Path,
        provider: Provider | None = None,
        parallel_session_factory=None,
        max_parallel_workers: int = 4,
    ) -> None:
        self.session = session
        self.base_data_dir = Path(base_data_dir)
        self.provider = provider
        self.parallel_session_factory = parallel_session_factory
        self.max_parallel_workers = max_parallel_workers
        self.glossary = GlossaryRepository(session)
        self.translations = TranslationRepository(session)
        self.translation_workflows = TranslationWorkflowRepository(session)
        self.synopses = SynopsisService(session)

    def fork_for_session(self, session: Session) -> "TranslationPipelineService":
        return TranslationPipelineService(
            session,
            base_data_dir=self.base_data_dir,
            provider=self.provider,
            parallel_session_factory=self.parallel_session_factory,
            max_parallel_workers=self.max_parallel_workers,
        )

    def generate_draft(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        scope: dict[str, object],
        model_profile_id: str,
        provider_model_name: str | None,
        draft_role: str,
        heartbeat=None,
    ) -> dict[str, object]:
        project = self.session.get(TranslationProject, project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)
        if self.provider is None:
            raise ToolError(code="invalid_arguments", message="缺少翻译 provider。", status=400)
        ensure_scope_supported(scope, stage="translation", allowed_types=get_stage_scope_types("translation"))

        segments = self._resolve_segments(project_id=project_id, scope=scope)
        if not segments:
            raise ToolError(code="invalid_arguments", message="scope 范围内没有可翻译的段落。", status=400)

        actual_model_name = provider_model_name or model_profile_id
        self.synopses.ensure_project_synopsis(
            project_id=project_id,
            model_profile_id=model_profile_id,
            provider_model_name=actual_model_name,
            provider=self.provider,
        )
        glossary_entries = self.glossary.list_active_entries_for_matching(project_id)
        glossary_snapshot_id = self._compute_glossary_snapshot_id(glossary_entries)

        project_root = ensure_directory(self.base_data_dir / project.project_key)
        workflow_root = ensure_directory(project_root / "translations" / "workflows" / str(workflow_run_id))
        jobs = [
            self._build_generate_segment_job(
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=workflow_step_run_id,
                project_id=project_id,
                workflow_root=workflow_root,
                source_language=project.source_language,
                target_language=project.target_language,
                chapter_index=chapter.chapter_index,
                segment_index=segment.segment_index,
                segment_id=segment.id,
                source_text_path=segment.source_text_path,
                model_profile_id=model_profile_id,
                provider_model_name=actual_model_name,
                draft_role=draft_role,
                glossary_entries=self._build_prompt_glossary_entries(
                    glossary_entries=glossary_entries,
                    source_text=Path(segment.source_text_path).read_text(encoding="utf-8"),
                ),
                glossary_snapshot_id=glossary_snapshot_id,
            )
            for chapter, segment in segments
        ]
        if heartbeat is not None:
            heartbeat()
        if self.parallel_session_factory is None or len(jobs) == 1:
            results = [self._generate_draft_for_segment_in_session(job=job) for job in jobs]
        else:
            self.session.commit()
            results = self._run_parallel_jobs(
                jobs=jobs,
                worker=lambda job: self._generate_draft_for_segment(job=job),
            )
        return self._build_parallel_generation_payload(results=results, model_profile_id=model_profile_id)

    def review_draft(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
        heartbeat=None,
    ) -> dict[str, object]:
        if self.provider is None:
            raise ToolError(code="invalid_arguments", message="缺少翻译 provider。", status=400)

        draft_versions = self.translation_workflows.list_draft_versions(workflow_run_id=workflow_run_id)
        if not draft_versions:
            raise ToolError(code="invalid_arguments", message="workflow 内没有可审核的 draft。", status=400)

        segment_map = self._load_segment_map(project_id=draft_versions[0].project_id)
        actual_model_name = provider_model_name or model_profile_id
        drafts_by_segment = self._group_drafts_by_segment(draft_versions)
        jobs = [
            self._build_review_segment_job(
                workflow_step_run_id=workflow_step_run_id,
                segment_id=segment_id,
                drafts=segment_drafts,
                segment_map=segment_map,
                model_profile_id=model_profile_id,
                provider_model_name=actual_model_name,
            )
            for segment_id, segment_drafts in sorted(drafts_by_segment.items())
        ]
        if heartbeat is not None:
            heartbeat()
        if self.parallel_session_factory is None or len(jobs) == 1:
            results = [self._review_draft_for_segment_in_session(job=job) for job in jobs]
        else:
            self.session.commit()
            results = self._run_parallel_jobs(
                jobs=jobs,
                worker=lambda job: self._review_draft_for_segment(job=job),
            )
        return self._build_parallel_review_payload(results=results, model_profile_id=model_profile_id)

    def rewrite_draft(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
        heartbeat=None,
    ) -> dict[str, object]:
        if self.provider is None:
            raise ToolError(code="invalid_arguments", message="缺少翻译 provider。", status=400)

        draft_versions = self.translation_workflows.list_draft_versions(workflow_run_id=workflow_run_id)
        if not draft_versions:
            raise ToolError(code="invalid_arguments", message="workflow 内没有可重写的 draft。", status=400)
        reviews = self.translation_workflows.list_draft_reviews(workflow_run_id=workflow_run_id)
        project_id = int(draft_versions[0].project_id)
        project = self.session.get(TranslationProject, project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        actual_model_name = provider_model_name or model_profile_id
        segment_map = self._load_segment_map(project_id=project_id)
        workflow_root = ensure_directory(
            ensure_directory(self.base_data_dir / project.project_key) / "translations" / "workflows" / str(workflow_run_id)
        )
        drafts_by_segment = self._group_drafts_by_segment(draft_versions)
        reviews_by_draft = self._group_reviews_by_draft(reviews)
        jobs = [
            self._build_rewrite_segment_job(
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=workflow_step_run_id,
                project_id=project_id,
                workflow_root=workflow_root,
                segment_id=segment_id,
                drafts=segment_drafts,
                reviews_by_draft=reviews_by_draft,
                segment_map=segment_map,
                model_profile_id=model_profile_id,
                provider_model_name=actual_model_name,
            )
            for segment_id, segment_drafts in sorted(drafts_by_segment.items())
        ]
        if heartbeat is not None:
            heartbeat()
        if self.parallel_session_factory is None or len(jobs) == 1:
            results = [self._rewrite_draft_for_segment_in_session(job=job) for job in jobs]
        else:
            self.session.commit()
            results = self._run_parallel_jobs(
                jobs=jobs,
                worker=lambda job: self._rewrite_draft_for_segment(job=job),
            )
        return self._build_parallel_rewrite_payload(results=results, model_profile_id=model_profile_id)

    def inspect_pipeline(self, *, workflow_run_id: int) -> dict[str, object]:
        draft_versions = self.translation_workflows.list_draft_versions(workflow_run_id=workflow_run_id)
        reviews = self.translation_workflows.list_draft_reviews(workflow_run_id=workflow_run_id)
        final_candidates = []
        drafts_by_segment = self._group_drafts_by_segment(draft_versions)
        reviews_by_draft = self._group_reviews_by_draft(reviews)
        for segment_id in sorted(drafts_by_segment):
            selected = self._select_final_draft(
                drafts=drafts_by_segment[segment_id],
                reviews_by_draft=reviews_by_draft,
            )
            final_candidates.append(
                {
                    "segment_id": segment_id,
                    "selected_draft_role": None if selected is None else selected.draft_role,
                    "selected_draft_id": None if selected is None else selected.id,
                }
            )
        return {
            "workflow_run_id": workflow_run_id,
            "drafts": [
                {
                    "id": draft.id,
                    "segment_id": draft.segment_id,
                    "draft_role": draft.draft_role,
                    "parent_draft_id": draft.parent_draft_id,
                    "model_profile_id": draft.model_profile_id,
                    "model_name": draft.model_name,
                    "status": draft.status,
                    "translated_text": draft.translated_text,
                }
                for draft in draft_versions
            ],
            "reviews": [
                {
                    "id": review.id,
                    "draft_version_id": review.draft_version_id,
                    "step_run_id": review.step_run_id,
                    "review_type": review.review_type,
                    "decision": review.decision,
                    "score": review.score,
                    "reason_codes": review.reason_codes,
                    "structured_payload": review.structured_payload,
                }
                for review in reviews
            ],
            "final_candidates": final_candidates,
        }

    def finalize(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        model_profile_id: str,
        provider_model_name: str | None,
        heartbeat=None,
    ) -> dict[str, object]:
        project = self.session.get(TranslationProject, project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        draft_versions = self.translation_workflows.list_draft_versions(workflow_run_id=workflow_run_id)
        if not draft_versions:
            raise ToolError(code="invalid_arguments", message="workflow 内没有可定稿的 draft。", status=400)

        project_root = ensure_directory(self.base_data_dir / project.project_key)
        translation_root = ensure_directory(project_root / "translations")
        segment_map = self._load_segment_map(project_id=project_id)
        drafts_by_segment = self._group_drafts_by_segment(draft_versions)
        reviews_by_draft = self._group_reviews_by_draft(
            self.translation_workflows.list_draft_reviews(workflow_run_id=workflow_run_id)
        )
        jobs = [
            self._build_finalize_segment_job(
                project_id=project_id,
                workflow_step_run_id=workflow_step_run_id,
                translation_root=translation_root,
                segment_id=segment_id,
                segment_map=segment_map,
                selected=self._select_final_draft(
                    drafts=segment_drafts,
                    reviews_by_draft=reviews_by_draft,
                ),
            )
            for segment_id, segment_drafts in sorted(drafts_by_segment.items())
            if self._select_final_draft(
                drafts=segment_drafts,
                reviews_by_draft=reviews_by_draft,
            )
            is not None
        ]
        if heartbeat is not None:
            heartbeat()
        if self.parallel_session_factory is None or len(jobs) == 1:
            results = [self._finalize_segment_job_in_session(job=job) for job in jobs]
        else:
            self.session.commit()
            results = self._run_parallel_jobs(
                jobs=jobs,
                worker=lambda job: self._finalize_segment_job(job=job),
            )
        self._mark_related_runs_stale(
            project_id=project_id,
            affected_chapter_indexes=sorted(
                {
                    int(item["chapter_index"])
                    for item in results
                    if item.get("succeeded")
                }
            ),
        )
        return self._build_parallel_finalize_payload(results=results, model_profile_id=model_profile_id)

    def inspect_synopsis_summary(self, *, project_id: int) -> dict[str, dict[str, object]]:
        payload = self.synopses.inspect(project_id=project_id)
        return {
            "source": {
                "status": payload["source_synopsis_status"],
                "origin": payload["source_synopsis_origin"],
                "length": len(payload["source_synopsis_text"] or ""),
            },
            "target": {
                "status": payload["target_synopsis_status"],
                "origin": payload["target_synopsis_origin"],
                "length": len(payload["target_synopsis_text"] or ""),
            },
        }

    def _build_review_prompt(
        self,
        *,
        draft_versions: list[Any],
        segment_map: dict[int, tuple[Chapter, ChapterSegment]],
    ) -> str:
        drafts_by_segment = self._group_drafts_by_segment(draft_versions)
        payload: list[dict[str, object]] = []
        for segment_id, drafts in sorted(drafts_by_segment.items()):
            _, segment = segment_map[segment_id]
            payload.append(
                {
                    "segment_id": segment_id,
                    "source_text": Path(segment.source_text_path).read_text(encoding="utf-8"),
                    "drafts": [
                        {
                            "draft_role": draft.draft_role,
                            "translated_text": draft.translated_text,
                            "model_name": draft.model_name,
                        }
                        for draft in drafts
                    ],
                }
            )
        return (
            "你是小说翻译审核器。请比较每个段落的多个 draft，输出结构化审核意见。"
            "只返回 JSON：{\"reviews\":[{\"segment_id\":1,\"draft_role\":\"primary\",\"decision\":\"keep\",\"score\":0.9,\"reason_codes\":[\"faithful\"],\"issues\":[]}]}。\n\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

    def _build_review_prompt_for_segment(
        self,
        *,
        segment_id: int,
        drafts: list[Any],
        segment_map: dict[int, tuple[Chapter, ChapterSegment]],
    ) -> str:
        _, segment = segment_map[segment_id]
        payload = {
            "segment_id": segment_id,
            "source_text": Path(segment.source_text_path).read_text(encoding="utf-8"),
            "drafts": [
                {
                    "draft_role": draft.draft_role,
                    "translated_text": draft.translated_text,
                    "model_name": draft.model_name,
                }
                for draft in drafts
            ],
        }
        return (
            "你是小说翻译审核器。请比较当前段落的多个 draft，输出结构化审核意见。"
            "只返回 JSON：{\"reviews\":[{\"segment_id\":1,\"draft_role\":\"primary\",\"decision\":\"keep\",\"score\":0.9,\"reason_codes\":[\"faithful\"],\"issues\":[]}]}。\n\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

    def _build_rewrite_prompt(
        self,
        *,
        draft_versions: list[Any],
        reviews: list[Any],
        segment_map: dict[int, tuple[Chapter, ChapterSegment]],
    ) -> str:
        drafts_by_segment = self._group_drafts_by_segment(draft_versions)
        reviews_by_draft = self._group_reviews_by_draft(reviews)
        payload: list[dict[str, object]] = []
        for segment_id, drafts in sorted(drafts_by_segment.items()):
            _, segment = segment_map[segment_id]
            payload.append(
                {
                    "segment_id": segment_id,
                    "source_text": Path(segment.source_text_path).read_text(encoding="utf-8"),
                    "drafts": [
                        {
                            "draft_role": draft.draft_role,
                            "translated_text": draft.translated_text,
                            "reviews": [
                                {
                                    "decision": review.decision,
                                    "score": review.score,
                                    "reason_codes": review.reason_codes,
                                    "structured_payload": review.structured_payload,
                                }
                                for review in reviews_by_draft.get(draft.id, [])
                            ],
                        }
                        for draft in drafts
                    ],
                }
            )
        return (
            "你是小说翻译重写器。请综合多个 draft 及其 review，输出更稳的 rewrite 版本。"
            "只返回 JSON：{\"drafts\":[{\"segment_id\":1,\"translated_text\":\"...\",\"parent_draft_role\":\"primary\"}]}。\n\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

    def _build_rewrite_prompt_for_segment(
        self,
        *,
        segment_id: int,
        drafts: list[Any],
        reviews_by_draft: dict[int, list[Any]],
        segment_map: dict[int, tuple[Chapter, ChapterSegment]],
    ) -> str:
        _, segment = segment_map[segment_id]
        payload = {
            "segment_id": segment_id,
            "source_text": Path(segment.source_text_path).read_text(encoding="utf-8"),
            "drafts": [
                {
                    "draft_role": draft.draft_role,
                    "translated_text": draft.translated_text,
                    "reviews": [
                        {
                            "decision": review.decision,
                            "score": review.score,
                            "reason_codes": review.reason_codes,
                            "structured_payload": review.structured_payload,
                        }
                        for review in reviews_by_draft.get(draft.id, [])
                    ],
                }
                for draft in drafts
            ],
        }
        return (
            "你是小说翻译重写器。请综合当前段落的多个 draft 及其 review，输出更稳的 rewrite 版本。"
            "只返回 JSON：{\"drafts\":[{\"segment_id\":1,\"translated_text\":\"...\",\"parent_draft_role\":\"primary\"}]}。\n\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

    def _parse_json_response(self, content: str) -> dict[str, object]:
        normalized = self._strip_code_fence(content).strip()
        if normalized == "":
            return {}
        try:
            payload = json.loads(normalized)
        except json.JSONDecodeError as exc:
            raise ToolError(code="provider_error", message=f"translation workflow 返回了无效 JSON：{exc}", status=502) from exc
        if not isinstance(payload, dict):
            raise ToolError(code="provider_error", message="translation workflow 返回结果必须是对象 JSON。", status=502)
        return payload

    def _group_drafts_by_segment(self, draft_versions: list[Any]) -> dict[int, list[Any]]:
        grouped: dict[int, list[Any]] = {}
        for draft in draft_versions:
            grouped.setdefault(int(draft.segment_id), []).append(draft)
        for drafts in grouped.values():
            drafts.sort(key=lambda item: item.id)
        return grouped

    def _group_reviews_by_draft(self, reviews: list[Any]) -> dict[int, list[Any]]:
        grouped: dict[int, list[Any]] = {}
        for review in reviews:
            grouped.setdefault(int(review.draft_version_id), []).append(review)
        for items in grouped.values():
            items.sort(
                key=lambda item: (
                    float(item.score) if item.score is not None else float("-inf"),
                    self._review_priority(item.decision),
                    item.id,
                ),
                reverse=True,
            )
        return grouped

    def _resolve_parent_draft(self, *, drafts: list[Any], parent_draft_role: str) -> Any | None:
        if parent_draft_role:
            for draft in reversed(drafts):
                if draft.draft_role == parent_draft_role:
                    return draft
        return drafts[-1] if drafts else None

    def _select_final_draft(self, *, drafts: list[Any], reviews_by_draft: dict[int, list[Any]]) -> Any | None:
        rewrite_drafts = [draft for draft in drafts if draft.draft_role == "rewrite"]
        if rewrite_drafts:
            return rewrite_drafts[-1]

        scored_candidates: list[tuple[float, int, int, Any]] = []
        for draft in drafts:
            draft_reviews = reviews_by_draft.get(int(draft.id), [])
            if not draft_reviews:
                continue
            best_review = draft_reviews[0]
            score = float(best_review.score) if best_review.score is not None else 0.0
            scored_candidates.append((score, self._review_priority(best_review.decision), draft.id, draft))
        if scored_candidates:
            scored_candidates.sort(reverse=True)
            return scored_candidates[0][3]
        return drafts[-1] if drafts else None

    def _review_priority(self, decision: str | None) -> int:
        normalized = str(decision or "").strip().lower()
        if normalized == "keep":
            return 3
        if normalized == "revise":
            return 2
        if normalized == "reject":
            return 1
        return 0

    def _strip_code_fence(self, content: str) -> str:
        stripped = content.strip()
        if not stripped.startswith("```"):
            return stripped
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)

    def _parse_int(self, value: object) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _parse_float(self, value: object) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _normalize_reason_codes(self, value: object) -> list[str] | None:
        if not isinstance(value, list):
            return None
        normalized = [str(item).strip() for item in value if str(item).strip()]
        return normalized or None

    def _cleanup_workflow_outputs(
        self,
        *,
        written_paths: list[Path],
        created_directories: set[Path],
    ) -> None:
        for path in written_paths:
            if path.exists():
                path.unlink()
        for directory in sorted(created_directories, key=lambda item: len(item.parts), reverse=True):
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()

    def _build_review_segment_job(
        self,
        *,
        workflow_step_run_id: int,
        segment_id: int,
        drafts: list[Any],
        segment_map: dict[int, tuple[Chapter, ChapterSegment]],
        model_profile_id: str,
        provider_model_name: str,
    ) -> dict[str, object]:
        return {
            "workflow_step_run_id": workflow_step_run_id,
            "segment_id": segment_id,
            "draft_refs": [
                {
                    "draft_version_id": int(draft.id),
                    "draft_role": str(draft.draft_role),
                }
                for draft in drafts
            ],
            "prompt": self._build_review_prompt_for_segment(
                segment_id=segment_id,
                drafts=drafts,
                segment_map=segment_map,
            ),
            "model_profile_id": model_profile_id,
            "provider_model_name": provider_model_name,
        }

    def _review_draft_for_segment(self, *, job: dict[str, object]) -> dict[str, object]:
        worker_session = self._open_parallel_session()
        try:
            worker_pipeline = self.fork_for_session(worker_session)
            result = worker_pipeline._review_draft_for_segment_in_session(job=job)
            worker_session.commit()
            return result
        except Exception:
            worker_session.rollback()
            raise
        finally:
            worker_session.close()

    def _review_draft_for_segment_in_session(self, *, job: dict[str, object]) -> dict[str, object]:
        if self.provider is None:
            raise ToolError(code="invalid_arguments", message="缺少翻译 provider。", status=400)
        provider_result = self.provider.generate_text(
            prompt=str(job["prompt"]),
            model_name=str(job["provider_model_name"]),
            timeout_seconds=120,
        )
        payload = self._parse_json_response(provider_result.content)
        raw_reviews = payload.get("reviews", [])
        if not isinstance(raw_reviews, list):
            raise ToolError(code="provider_error", message="translation.review_draft 必须返回 reviews 数组。", status=502)

        segment_id = int(job["segment_id"])
        drafts_by_role = {
            str(item["draft_role"]): int(item["draft_version_id"])
            for item in list(job["draft_refs"])
        }
        review_count = 0
        for item in raw_reviews:
            if not isinstance(item, dict):
                continue
            review_segment_id = self._parse_int(item.get("segment_id"))
            draft_role = str(item.get("draft_role") or "").strip()
            if review_segment_id != segment_id or draft_role == "":
                continue
            draft_version_id = drafts_by_role.get(draft_role)
            if draft_version_id is None:
                continue
            self.translation_workflows.create_draft_review(
                draft_version_id=draft_version_id,
                step_run_id=int(job["workflow_step_run_id"]),
                review_type=str(item.get("review_type") or "quality"),
                decision=str(item.get("decision") or "keep"),
                score=self._parse_float(item.get("score")),
                reason_codes=self._normalize_reason_codes(item.get("reason_codes")),
                structured_payload={
                    "issues": item.get("issues", []),
                    "reviewer_model": provider_result.model_name,
                },
            )
            review_count += 1
        return {
            "segment_id": segment_id,
            "succeeded": True,
            "review_count": review_count,
            "reviewed_segment_count": 1 if review_count > 0 else 0,
            "model_profile_id": provider_result.model_profile_id or str(job["model_profile_id"]),
            "model_name": provider_result.model_name,
            "provider_name": provider_result.provider_name,
            "fallback_depth": int(provider_result.fallback_depth or 0),
        }

    def _build_parallel_review_payload(
        self,
        *,
        results: list[dict[str, object]],
        model_profile_id: str,
    ) -> dict[str, object]:
        actual_model_profiles = sorted(
            {str(item["model_profile_id"]) for item in results if item.get("model_profile_id")}
        )
        max_fallback_depth = max((int(item.get("fallback_depth") or 0) for item in results), default=0)
        return {
            "reviewed_segment_count": sum(int(item.get("reviewed_segment_count") or 0) for item in results),
            "review_count": sum(int(item.get("review_count") or 0) for item in results),
            "model_profile_id": actual_model_profiles[-1] if actual_model_profiles else model_profile_id,
            "model_name": next((item.get("model_name") for item in reversed(results) if item.get("model_name")), None),
            "provider_name": next((item.get("provider_name") for item in reversed(results) if item.get("provider_name")), None),
            "fallback_depth": max_fallback_depth,
            "actual_model_profiles": actual_model_profiles,
            "max_fallback_depth": max_fallback_depth,
            "succeeded_segment_count": len(results),
            "failed_segment_count": 0,
            "failed_segments": [],
        }

    def _build_rewrite_segment_job(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        workflow_root: Path,
        segment_id: int,
        drafts: list[Any],
        reviews_by_draft: dict[int, list[Any]],
        segment_map: dict[int, tuple[Chapter, ChapterSegment]],
        model_profile_id: str,
        provider_model_name: str,
    ) -> dict[str, object]:
        return {
            "workflow_run_id": workflow_run_id,
            "workflow_step_run_id": workflow_step_run_id,
            "project_id": project_id,
            "workflow_root": str(workflow_root),
            "segment_id": segment_id,
            "draft_refs": [
                {
                    "draft_version_id": int(draft.id),
                    "draft_role": str(draft.draft_role),
                    "source_hash": str(draft.source_hash),
                    "glossary_snapshot_id": str(draft.glossary_snapshot_id),
                }
                for draft in drafts
            ],
            "prompt": self._build_rewrite_prompt_for_segment(
                segment_id=segment_id,
                drafts=drafts,
                reviews_by_draft=reviews_by_draft,
                segment_map=segment_map,
            ),
            "model_profile_id": model_profile_id,
            "provider_model_name": provider_model_name,
        }

    def _rewrite_draft_for_segment(self, *, job: dict[str, object]) -> dict[str, object]:
        worker_session = self._open_parallel_session()
        try:
            worker_pipeline = self.fork_for_session(worker_session)
            result = worker_pipeline._rewrite_draft_for_segment_in_session(job=job)
            worker_session.commit()
            return result
        except Exception:
            worker_session.rollback()
            raise
        finally:
            worker_session.close()

    def _rewrite_draft_for_segment_in_session(self, *, job: dict[str, object]) -> dict[str, object]:
        if self.provider is None:
            raise ToolError(code="invalid_arguments", message="缺少翻译 provider。", status=400)
        provider_result = self.provider.generate_text(
            prompt=str(job["prompt"]),
            model_name=str(job["provider_model_name"]),
            timeout_seconds=120,
        )
        payload = self._parse_json_response(provider_result.content)
        raw_drafts = payload.get("drafts", [])
        if not isinstance(raw_drafts, list):
            raise ToolError(code="provider_error", message="translation.rewrite_draft 必须返回 drafts 数组。", status=502)

        workflow_root = Path(str(job["workflow_root"]))
        segment_id = int(job["segment_id"])
        draft_refs = list(job["draft_refs"])
        drafts_by_role = {str(item["draft_role"]): item for item in draft_refs}
        segment_dir = ensure_directory(workflow_root / "segments" / f"{segment_id:08d}")
        draft_path = segment_dir / f"{int(job['workflow_step_run_id'])}-rewrite.txt"
        created_directories = {segment_dir}
        written_paths: list[Path] = []
        rewrite_count = 0
        try:
            for item in raw_drafts:
                if not isinstance(item, dict):
                    continue
                rewrite_segment_id = self._parse_int(item.get("segment_id"))
                translated_text = str(item.get("translated_text") or "").strip()
                if rewrite_segment_id != segment_id or translated_text == "":
                    continue
                parent_draft_role = str(item.get("parent_draft_role") or "").strip()
                parent_ref = drafts_by_role.get(parent_draft_role)
                fallback_ref = draft_refs[-1] if draft_refs else None
                selected_ref = parent_ref or fallback_ref
                if selected_ref is None:
                    continue
                draft_path.write_text(translated_text, encoding="utf-8")
                if draft_path not in written_paths:
                    written_paths.append(draft_path)
                self.translation_workflows.create_draft_version(
                    workflow_run_id=int(job["workflow_run_id"]),
                    project_id=int(job["project_id"]),
                    segment_id=segment_id,
                    step_run_id=int(job["workflow_step_run_id"]),
                    parent_draft_id=None if parent_ref is None else int(parent_ref["draft_version_id"]),
                    draft_role="rewrite",
                    source_hash=str(selected_ref["source_hash"]),
                    glossary_snapshot_id=str(selected_ref["glossary_snapshot_id"]),
                    provider_name=provider_result.provider_name,
                    model_profile_id=provider_result.model_profile_id or str(job["model_profile_id"]),
                    model_name=provider_result.model_name,
                    translated_text=translated_text,
                    translated_text_path=str(draft_path),
                    status="completed",
                    evidence_payload={
                        "parent_draft_role": parent_draft_role or None,
                        "fallback_depth": int(provider_result.fallback_depth or 0),
                        "actual_model_profile_id": provider_result.model_profile_id or str(job["model_profile_id"]),
                    },
                )
                rewrite_count += 1
            return {
                "segment_id": segment_id,
                "succeeded": True,
                "rewritten_draft_count": rewrite_count,
                "model_profile_id": provider_result.model_profile_id or str(job["model_profile_id"]),
                "model_name": provider_result.model_name,
                "provider_name": provider_result.provider_name,
                "fallback_depth": int(provider_result.fallback_depth or 0),
            }
        except Exception:
            self._cleanup_workflow_outputs(
                written_paths=written_paths,
                created_directories=created_directories,
            )
            raise

    def _build_parallel_rewrite_payload(
        self,
        *,
        results: list[dict[str, object]],
        model_profile_id: str,
    ) -> dict[str, object]:
        actual_model_profiles = sorted(
            {str(item["model_profile_id"]) for item in results if item.get("model_profile_id")}
        )
        max_fallback_depth = max((int(item.get("fallback_depth") or 0) for item in results), default=0)
        rewritten_count = sum(int(item.get("rewritten_draft_count") or 0) for item in results)
        return {
            "rewritten_draft_count": rewritten_count,
            "model_profile_id": actual_model_profiles[-1] if actual_model_profiles else model_profile_id,
            "model_name": next((item.get("model_name") for item in reversed(results) if item.get("model_name")), None),
            "provider_name": next((item.get("provider_name") for item in reversed(results) if item.get("provider_name")), None),
            "fallback_depth": max_fallback_depth,
            "actual_model_profiles": actual_model_profiles,
            "max_fallback_depth": max_fallback_depth,
            "succeeded_segment_count": len(results),
            "failed_segment_count": 0,
            "failed_segments": [],
        }

    def _build_finalize_segment_job(
        self,
        *,
        project_id: int,
        workflow_step_run_id: int,
        translation_root: Path,
        segment_id: int,
        segment_map: dict[int, tuple[Chapter, ChapterSegment]],
        selected: Any,
    ) -> dict[str, object]:
        chapter, segment = segment_map[segment_id]
        return {
            "project_id": project_id,
            "workflow_step_run_id": workflow_step_run_id,
            "translation_root": str(translation_root),
            "segment_id": segment_id,
            "chapter_index": int(chapter.chapter_index),
            "source_text_path": str(segment.source_text_path),
            "selected_draft": {
                "source_hash": str(selected.source_hash),
                "glossary_snapshot_id": str(selected.glossary_snapshot_id),
                "provider_name": str(selected.provider_name),
                "model_profile_id": str(selected.model_profile_id),
                "model_name": str(selected.model_name),
                "translated_text": str(selected.translated_text),
                "fallback_depth": int(((selected.evidence_payload or {}).get("fallback_depth")) or 0),
            },
        }

    def _finalize_segment_job(self, *, job: dict[str, object]) -> dict[str, object]:
        worker_session = self._open_parallel_session()
        try:
            worker_pipeline = self.fork_for_session(worker_session)
            result = worker_pipeline._finalize_segment_job_in_session(job=job)
            worker_session.commit()
            return result
        except Exception:
            worker_session.rollback()
            raise
        finally:
            worker_session.close()

    def _finalize_segment_job_in_session(self, *, job: dict[str, object]) -> dict[str, object]:
        segment_id = int(job["segment_id"])
        selected_draft = dict(job["selected_draft"])
        translation_root = Path(str(job["translation_root"]))
        translation = self.translations.get_or_create_translation(
            project_id=int(job["project_id"]),
            segment_id=segment_id,
        )
        next_version_index = self.translations.get_next_version_index(translation.id)
        segment_output_dir = ensure_directory(translation_root / "segments" / f"{segment_id:08d}")
        version_path = segment_output_dir / f"v{next_version_index:04d}.txt"
        current_path = segment_output_dir / "current.txt"
        written_paths: list[Path] = []
        created_directories = {segment_output_dir}
        try:
            translated_text = str(selected_draft["translated_text"])
            version_path.write_text(translated_text, encoding="utf-8")
            written_paths.append(version_path)
            current_path.write_text(translated_text, encoding="utf-8")
            written_paths.append(current_path)
            version = self.translations.create_version(
                project_id=int(job["project_id"]),
                segment_translation_id=translation.id,
                version_index=next_version_index,
                source_hash=str(selected_draft["source_hash"]),
                glossary_snapshot_id=str(selected_draft["glossary_snapshot_id"]),
                provider_name=str(selected_draft["provider_name"]),
                model_profile_id=str(selected_draft["model_profile_id"]),
                model_name=str(selected_draft["model_name"]),
                source_text=Path(str(job["source_text_path"])).read_text(encoding="utf-8"),
                translated_text=translated_text,
                translated_text_path=str(version_path),
                status="completed",
            )
            translation.active_version_id = version.id
            segment = self.session.get(ChapterSegment, segment_id)
            if segment is None:
                raise ToolError(code="not_found", message=f"找不到段落 {segment_id}。", status=404)
            segment.translation_status = "translated"
            segment.review_status = "pending"
            return {
                "segment_id": segment_id,
                "chapter_index": int(job["chapter_index"]),
                "succeeded": True,
                "active_version_id": int(version.id),
                "model_profile_id": str(selected_draft["model_profile_id"]),
                "model_name": str(selected_draft["model_name"]),
                "fallback_depth": int(selected_draft["fallback_depth"]),
            }
        except Exception:
            self._cleanup_workflow_outputs(
                written_paths=written_paths,
                created_directories=created_directories,
            )
            raise

    def _build_parallel_finalize_payload(
        self,
        *,
        results: list[dict[str, object]],
        model_profile_id: str,
    ) -> dict[str, object]:
        actual_model_profiles = sorted(
            {str(item["model_profile_id"]) for item in results if item.get("model_profile_id")}
        )
        max_fallback_depth = max((int(item.get("fallback_depth") or 0) for item in results), default=0)
        return {
            "translated_segments": len(results),
            "active_version_ids": [int(item["active_version_id"]) for item in results if item.get("active_version_id")],
            "model_profile_id": actual_model_profiles[-1] if actual_model_profiles else model_profile_id,
            "model_name": next((item.get("model_name") for item in reversed(results) if item.get("model_name")), None),
            "fallback_depth": max_fallback_depth,
            "actual_model_profiles": actual_model_profiles,
            "max_fallback_depth": max_fallback_depth,
            "succeeded_segment_count": len(results),
            "failed_segment_count": 0,
            "failed_segments": [],
        }

    def _open_parallel_session(self) -> Session:
        if self.parallel_session_factory is not None:
            return self.parallel_session_factory()
        bind = self.session.get_bind()
        return Session(bind=bind, autoflush=False, expire_on_commit=False)

    def _parallel_worker_count(self, *, job_count: int) -> int:
        return max(1, min(job_count, self.max_parallel_workers))

    def _run_parallel_jobs(self, *, jobs: list[dict[str, object]], worker):
        if not jobs:
            return []
        if len(jobs) == 1:
            return [worker(jobs[0])]
        with ThreadPoolExecutor(max_workers=self._parallel_worker_count(job_count=len(jobs))) as executor:
            futures = [executor.submit(worker, job) for job in jobs]
            return [future.result() for future in futures]

    def _build_generate_segment_job(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        workflow_root: Path,
        source_language: str,
        target_language: str,
        chapter_index: int,
        segment_index: int,
        segment_id: int,
        source_text_path: str,
        model_profile_id: str,
        provider_model_name: str,
        draft_role: str,
        glossary_entries: list[GlossaryEntry],
        glossary_snapshot_id: str,
    ) -> dict[str, object]:
        source_text = Path(source_text_path).read_text(encoding="utf-8")
        prompt = self._build_translation_prompt(
            source_language=source_language,
            target_language=target_language,
            chapter_index=chapter_index,
            segment_index=segment_index,
            source_text=source_text,
            glossary_entries=glossary_entries,
        )
        return {
            "workflow_run_id": workflow_run_id,
            "workflow_step_run_id": workflow_step_run_id,
            "project_id": project_id,
            "workflow_root": str(workflow_root),
            "chapter_index": chapter_index,
            "segment_index": segment_index,
            "segment_id": segment_id,
            "source_text_path": source_text_path,
            "source_hash": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
            "prompt": prompt,
            "model_profile_id": model_profile_id,
            "provider_model_name": provider_model_name,
            "draft_role": draft_role,
            "glossary_snapshot_id": glossary_snapshot_id,
        }

    def _generate_draft_for_segment(self, *, job: dict[str, object]) -> dict[str, object]:
        worker_session = self._open_parallel_session()
        try:
            worker_pipeline = self.fork_for_session(worker_session)
            result = worker_pipeline._generate_draft_for_segment_in_session(job=job)
            worker_session.commit()
            return result
        except Exception:
            worker_session.rollback()
            raise
        finally:
            worker_session.close()

    def _generate_draft_for_segment_in_session(self, *, job: dict[str, object]) -> dict[str, object]:
        if self.provider is None:
            raise ToolError(code="invalid_arguments", message="缺少翻译 provider。", status=400)
        workflow_root = Path(str(job["workflow_root"]))
        segment_id = int(job["segment_id"])
        segment_dir = ensure_directory(workflow_root / "segments" / f"{segment_id:08d}")
        draft_path = segment_dir / f"{int(job['workflow_step_run_id'])}-{str(job['draft_role'])}.txt"
        created_directories = {segment_dir}
        written_paths: list[Path] = []
        try:
            provider_result = self.provider.generate_text(
                prompt=str(job["prompt"]),
                model_name=str(job["provider_model_name"]),
                timeout_seconds=60,
            )
            draft_path.write_text(provider_result.content, encoding="utf-8")
            written_paths.append(draft_path)
            self.translation_workflows.create_draft_version(
                workflow_run_id=int(job["workflow_run_id"]),
                project_id=int(job["project_id"]),
                segment_id=segment_id,
                step_run_id=int(job["workflow_step_run_id"]),
                parent_draft_id=None,
                draft_role=str(job["draft_role"]),
                source_hash=str(job["source_hash"]),
                glossary_snapshot_id=str(job["glossary_snapshot_id"]),
                provider_name=provider_result.provider_name,
                model_profile_id=provider_result.model_profile_id or str(job["model_profile_id"]),
                model_name=provider_result.model_name,
                translated_text=provider_result.content,
                translated_text_path=str(draft_path),
                status="completed",
                evidence_payload={
                    "chapter_index": int(job["chapter_index"]),
                    "segment_index": int(job["segment_index"]),
                    "fallback_depth": int(provider_result.fallback_depth or 0),
                    "actual_model_profile_id": provider_result.model_profile_id or str(job["model_profile_id"]),
                },
            )
            return {
                "segment_id": segment_id,
                "succeeded": True,
                "model_profile_id": provider_result.model_profile_id or str(job["model_profile_id"]),
                "model_name": provider_result.model_name,
                "provider_name": provider_result.provider_name,
                "fallback_depth": int(provider_result.fallback_depth or 0),
            }
        except Exception:
            self._cleanup_workflow_outputs(
                written_paths=written_paths,
                created_directories=created_directories,
            )
            raise

    def _build_parallel_generation_payload(
        self,
        *,
        results: list[dict[str, object]],
        model_profile_id: str,
    ) -> dict[str, object]:
        actual_model_profiles = sorted(
            {str(item["model_profile_id"]) for item in results if item.get("model_profile_id")}
        )
        max_fallback_depth = max((int(item.get("fallback_depth") or 0) for item in results), default=0)
        payload: dict[str, object] = {
            "segment_count": len(results),
            "draft_count": len(results),
            "model_profile_id": actual_model_profiles[-1] if actual_model_profiles else model_profile_id,
            "model_name": next((item.get("model_name") for item in reversed(results) if item.get("model_name")), None),
            "provider_name": next((item.get("provider_name") for item in reversed(results) if item.get("provider_name")), None),
            "fallback_depth": max_fallback_depth,
            "actual_model_profiles": actual_model_profiles,
            "max_fallback_depth": max_fallback_depth,
            "succeeded_segment_count": len(results),
            "failed_segment_count": 0,
            "failed_segments": [],
        }
        return payload

    def _load_segment_map(self, *, project_id: int) -> dict[int, tuple[Chapter, ChapterSegment]]:
        rows = self.session.execute(
            select(Chapter, ChapterSegment)
            .join(ChapterSegment, ChapterSegment.chapter_id == Chapter.id)
            .where(Chapter.project_id == project_id, ChapterSegment.project_id == project_id)
        ).all()
        return {segment.id: (chapter, segment) for chapter, segment in rows}

    def _resolve_segments(self, *, project_id: int, scope: dict[str, object]) -> list[tuple[Chapter, ChapterSegment]]:
        ensure_scope_supported(scope, stage="translation", allowed_types=get_stage_scope_types("translation"))
        statement = (
            select(Chapter, ChapterSegment)
            .join(ChapterSegment, ChapterSegment.chapter_id == Chapter.id)
            .outerjoin(
                SegmentTranslation,
                and_(SegmentTranslation.segment_id == ChapterSegment.id, SegmentTranslation.project_id == project_id),
            )
            .where(Chapter.project_id == project_id, ChapterSegment.project_id == project_id)
        )
        scope_type = str(scope["type"])
        if scope_type == "chapter_range":
            statement = statement.where(
                Chapter.chapter_index >= int(scope["start"]),
                Chapter.chapter_index <= int(scope["end"]),
            )
        if scope_type == "chapter_list":
            statement = statement.where(Chapter.chapter_index.in_(list(scope["chapters"])))
        if scope_type == "stale_only":
            statement = statement.where(ChapterSegment.translation_status == "stale")
        if scope_type == "failed_only":
            statement = statement.where(ChapterSegment.translation_status == "failed")
        if scope_type == "missing_only":
            statement = statement.where(SegmentTranslation.active_version_id.is_(None))
        statement = statement.order_by(Chapter.chapter_index.asc(), ChapterSegment.segment_index.asc())
        return [(chapter, segment) for chapter, segment in self.session.execute(statement).all()]

    def _build_translation_prompt(
        self,
        *,
        source_language: str,
        target_language: str,
        chapter_index: int,
        segment_index: int,
        source_text: str,
        glossary_entries: list[GlossaryEntry],
    ) -> str:
        prompt = (
            f"你是一个翻译引擎。请翻译正文，把{source_language}文本翻译成{target_language}。\n"
            f"章节: {chapter_index}\n"
            f"段落: {segment_index}\n"
            "只返回译文，不要解释。\n"
            "如果正文命中了术语表中的 source_term，译文必须优先使用该条目的 target_term。\n"
            "不要把已命中的术语改写成同组其他表面形式。\n"
            "同一术语在同一段落内不要出现多种译法。"
        )
        if glossary_entries:
            prompt += "\n术语表：\n" + "\n".join(self._format_glossary_entry(item) for item in glossary_entries)
        return f"{prompt}\n\n{source_text}"

    def _build_prompt_glossary_entries(
        self,
        *,
        glossary_entries: list[GlossaryEntry],
        source_text: str,
    ) -> list[GlossaryEntry]:
        matches: list[tuple[int, int, GlossaryEntry]] = []
        for entry in glossary_entries:
            start = 0
            while True:
                index = source_text.find(entry.source_term, start)
                if index < 0:
                    break
                matches.append((index, index + len(entry.source_term), entry))
                start = index + 1
        matches.sort(key=lambda item: (item[0], -(item[1] - item[0]), item[2].source_term))
        kept: list[tuple[int, int, GlossaryEntry]] = []
        for match in matches:
            conflict_index = next(
                (
                    index
                    for index, existing in enumerate(kept)
                    if not (match[1] <= existing[0] or match[0] >= existing[1])
                ),
                None,
            )
            if conflict_index is None:
                kept.append(match)
                continue
            existing = kept[conflict_index]
            if (match[1] - match[0]) > (existing[1] - existing[0]):
                kept[conflict_index] = match
        unique_entries: dict[str, GlossaryEntry] = {}
        for _, _, entry in kept:
            if entry.source_term not in unique_entries:
                unique_entries[entry.source_term] = entry
        return list(unique_entries.values())

    def _format_glossary_entry(self, entry: GlossaryEntry) -> str:
        note_suffix = f" | note: {entry.note}" if entry.note else ""
        category_suffix = f" | category: {entry.category}" if entry.category else ""
        return (
            f"- {entry.source_term} => {entry.target_term}"
            f" | role: {entry.relation_role}"
            f" | group: {entry.term_group_key}"
            f"{category_suffix}{note_suffix}"
        )

    def _compute_glossary_snapshot_id(self, glossary_entries: list[GlossaryEntry]) -> str:
        payload = json.dumps(
            [
                {
                    "source_term": entry.source_term,
                    "target_term": entry.target_term,
                    "category": entry.category,
                    "note": entry.note,
                    "status": entry.status,
                    "locked": entry.locked,
                    "term_group_key": entry.term_group_key,
                    "relation_role": entry.relation_role,
                }
                for entry in sorted(glossary_entries, key=lambda item: item.source_term)
            ],
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _mark_related_runs_stale(self, *, project_id: int, affected_chapter_indexes: list[int]) -> None:
        if not affected_chapter_indexes:
            return

        for review_run in self.session.execute(
            select(ReviewRun).where(ReviewRun.project_id == project_id)
        ).scalars().all():
            if self._scope_matches_chapters(self._decode_summary(review_run.scope_value), affected_chapter_indexes):
                review_run.status = "stale"

        for export_run in self.session.execute(
            select(ExportRun).where(ExportRun.project_id == project_id)
        ).scalars().all():
            if self._scope_matches_chapters(self._decode_summary(export_run.scope_value), affected_chapter_indexes):
                export_run.status = "stale"

        for stage_run in self.session.execute(
            select(StageRun).where(
                StageRun.project_id == project_id,
                StageRun.stage.in_(["review", "export"]),
            )
        ).scalars().all():
            if self._scope_matches_chapters(self._decode_summary(stage_run.scope_value), affected_chapter_indexes):
                stage_run.status = "stale"

    def _scope_matches_chapters(self, scope_value: object, chapter_indexes: list[int]) -> bool:
        return scope_matches_chapters(scope_value, chapter_indexes)

    def _decode_summary(self, value: str | None) -> object:
        if value is None or value == "":
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
