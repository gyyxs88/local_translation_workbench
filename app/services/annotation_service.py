from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..db.models import (
    Chapter,
    ChapterSegment,
    SegmentTranslation,
    SegmentTranslationVersion,
    TranslationProject,
)
from ..errors import ToolError
from ..repositories.annotations import AnnotationRepository
from ..repositories.glossary import GlossaryRepository
from ..repositories.review import ReviewRepository
from .annotation_prompt_service import AnnotationPromptService


class AnnotationService:
    def __init__(self, session: Session, *, provider: Any | None = None) -> None:
        self.session = session
        self.provider = provider
        self.repository = AnnotationRepository(session)
        self.prompts = AnnotationPromptService()
        self.glossary = GlossaryRepository(session)
        self.reviews = ReviewRepository(session)

    def extract(
        self,
        *,
        request_id: str,
        project_id: int,
        scope: dict[str, object],
        model_profile_id: str,
        provider_model_name: str | None,
    ) -> dict[str, object]:
        if self.provider is None:
            raise ToolError(code="invalid_arguments", message="annotation.extract 需要可用 provider。", status=400)
        project = self.session.get(TranslationProject, project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        rows = self._resolve_active_segment_rows(project_id=project_id, scope=scope)
        if not rows:
            raise ToolError(code="invalid_arguments", message="scope 范围内没有 active translation version。", status=400)

        annotation_ids: set[int] = set()
        occurrence_count = 0
        skipped_count = 0
        model_name = provider_model_name or model_profile_id
        for chapter, segment, version in rows:
            source_text = Path(segment.source_text_path).read_text(encoding="utf-8")
            prompt = self.prompts.build_extraction_prompt(
                source_text=source_text,
                translated_text=version.translated_text,
                glossary_entries=self._build_glossary_context(project_id=project_id),
                review_issues=self._build_review_issue_context(project_id=project_id, segment_id=segment.id),
                existing_annotations=self.repository.list_annotations(project_id=project_id, status="approved"),
            )
            response = self.provider.generate_text(prompt=prompt, model_name=model_name, timeout_seconds=120)
            candidates = self.prompts.parse_extraction_response(response.content)
            display_order = 0
            for candidate in candidates:
                evidence_payload = self._build_evidence_payload(
                    candidate=candidate,
                    request_id=request_id,
                    response=response,
                    model_profile_id=model_profile_id,
                    chapter=chapter,
                    segment=segment,
                    version=version,
                )
                candidate = {**candidate, "evidence_payload": evidence_payload}
                annotation = self.merge_candidate(project_id=project_id, candidate=candidate)
                source_anchor = annotation.source_anchor
                target_anchor = annotation.target_anchor
                source_start, source_end = self._find_span(source_text, source_anchor)
                target_start, target_end = self._find_span(version.translated_text, target_anchor)
                display_order += 1
                self.repository.create_or_update_occurrence(
                    annotation_id=annotation.id,
                    project_id=project_id,
                    chapter_id=chapter.id,
                    segment_id=segment.id,
                    version_id=version.id,
                    source_anchor=source_anchor,
                    target_anchor=target_anchor,
                    source_start=source_start,
                    source_end=source_end,
                    target_start=target_start,
                    target_end=target_end,
                    display_order=display_order,
                )
                annotation_ids.add(annotation.id)
                occurrence_count += 1
            skipped_count += max(0, len(candidates) - display_order)

        return {
            "project_id": project_id,
            "scope": scope,
            "annotation_count": len(annotation_ids),
            "occurrence_count": occurrence_count,
            "skipped_count": skipped_count,
        }

    def merge_candidate(self, *, project_id: int, candidate: dict[str, object]):
        canonical_key = str(candidate["canonical_key"])
        existing = self.repository.get_by_canonical_key(project_id=project_id, canonical_key=canonical_key)
        if existing is None:
            return self._create_candidate(project_id=project_id, candidate=candidate, canonical_key=canonical_key)

        if existing.status == "approved" or int(existing.locked):
            if self._matches_existing(existing, candidate):
                return existing
            conflict_key = self._build_conflict_key(canonical_key=canonical_key, candidate=candidate)
            conflict = self.repository.get_by_canonical_key(project_id=project_id, canonical_key=conflict_key)
            if conflict is not None:
                return conflict
            return self._create_candidate(
                project_id=project_id,
                candidate={**candidate, "status": "candidate"},
                canonical_key=conflict_key,
                conflict_with_annotation_id=existing.id,
            )

        return self.repository.update_annotation(existing, candidate)

    def approve(self, *, annotation_id: int, locked: bool = False) -> dict[str, object]:
        annotation = self.repository.approve(annotation_id, locked=locked)
        if annotation is None:
            raise ToolError(code="not_found", message=f"找不到 annotation_id={annotation_id}。", status=404)
        return self._annotation_status_payload(annotation)

    def reject(self, *, annotation_id: int) -> dict[str, object]:
        annotation = self.repository.reject(annotation_id)
        if annotation is None:
            raise ToolError(code="not_found", message=f"找不到 annotation_id={annotation_id}。", status=404)
        return self._annotation_status_payload(annotation)

    def inspect(self, *, project_id: int) -> dict[str, object]:
        return {
            "project_id": project_id,
            "annotations": self.repository.list_annotations(project_id=project_id),
        }

    def _resolve_active_segment_rows(
        self,
        *,
        project_id: int,
        scope: dict[str, object],
    ) -> list[tuple[Chapter, ChapterSegment, SegmentTranslationVersion]]:
        statement = (
            select(Chapter, ChapterSegment, SegmentTranslationVersion)
            .join(ChapterSegment, ChapterSegment.chapter_id == Chapter.id)
            .join(
                SegmentTranslation,
                and_(SegmentTranslation.segment_id == ChapterSegment.id, SegmentTranslation.project_id == project_id),
            )
            .join(SegmentTranslationVersion, SegmentTranslationVersion.id == SegmentTranslation.active_version_id)
            .where(Chapter.project_id == project_id, ChapterSegment.project_id == project_id)
        )
        scope_type = str(scope.get("type", "all"))
        if scope_type == "chapter_range":
            statement = statement.where(
                Chapter.chapter_index >= int(scope["start"]),
                Chapter.chapter_index <= int(scope["end"]),
            )
        elif scope_type == "chapter_list":
            statement = statement.where(Chapter.chapter_index.in_(list(scope["chapters"])))
        elif scope_type != "all":
            raise ToolError(code="invalid_arguments", message=f"annotation.extract 不支持 scope_type={scope_type}。", status=400)
        statement = statement.order_by(Chapter.chapter_index.asc(), ChapterSegment.segment_index.asc())
        return [(chapter, segment, version) for chapter, segment, version in self.session.execute(statement).all()]

    def _build_glossary_context(self, *, project_id: int) -> list[dict[str, object]]:
        return [
            {
                "source_term": entry.source_term,
                "target_term": entry.target_term,
                "category": entry.category,
                "note": entry.note,
            }
            for entry in self.glossary.list_entries(project_id)
            if entry.status == "active"
        ]

    def _build_review_issue_context(self, *, project_id: int, segment_id: int) -> list[dict[str, object]]:
        return [
            {
                "issue_type": issue.issue_type,
                "severity": issue.severity,
                "message": issue.message,
                "structured_payload": issue.structured_payload,
            }
            for issue in self.reviews.list_issues(project_id)
            if issue.segment_id == segment_id
        ]

    def _build_evidence_payload(
        self,
        *,
        candidate: dict[str, object],
        request_id: str,
        response,
        model_profile_id: str,
        chapter: Chapter,
        segment: ChapterSegment,
        version: SegmentTranslationVersion,
    ) -> dict[str, object]:
        raw_evidence = candidate.get("evidence_payload")
        evidence = dict(raw_evidence) if isinstance(raw_evidence, dict) else {}
        evidence.update(
            {
                "request_id": request_id,
                "provider_name": response.provider_name,
                "model_profile_id": model_profile_id,
                "model_name": response.model_name,
                "chapter_id": chapter.id,
                "chapter_index": chapter.chapter_index,
                "segment_id": segment.id,
                "segment_index": segment.segment_index,
                "version_id": version.id,
            }
        )
        return evidence

    def _create_candidate(
        self,
        *,
        project_id: int,
        candidate: dict[str, object],
        canonical_key: str,
        conflict_with_annotation_id: int | None = None,
    ):
        return self.repository.create_annotation(
            project_id=project_id,
            source_anchor=str(candidate["source_anchor"]),
            target_anchor=str(candidate["target_anchor"]),
            annotation_type=str(candidate["annotation_type"]),
            canonical_key=canonical_key,
            explanation=str(candidate["explanation"]),
            status=str(candidate.get("status") or "candidate"),
            locked=0,
            source=str(candidate.get("source") or "llm_annotation"),
            evidence_payload=candidate.get("evidence_payload") if isinstance(candidate.get("evidence_payload"), dict) else None,
            conflict_with_annotation_id=conflict_with_annotation_id,
        )

    def _matches_existing(self, existing, candidate: dict[str, object]) -> bool:
        return (
            existing.target_anchor.strip() == str(candidate["target_anchor"]).strip()
            and existing.annotation_type.strip() == str(candidate["annotation_type"]).strip()
            and existing.explanation.strip() == str(candidate["explanation"]).strip()
        )

    def _build_conflict_key(self, *, canonical_key: str, candidate: dict[str, object]) -> str:
        signature = "|".join(
            [
                str(candidate.get("target_anchor") or ""),
                str(candidate.get("annotation_type") or ""),
                str(candidate.get("explanation") or ""),
            ]
        )
        digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:8]
        return f"{canonical_key}#conflict:{digest}"

    def _find_span(self, text: str, anchor: str) -> tuple[int | None, int | None]:
        start = text.find(anchor)
        if start < 0:
            return None, None
        return start, start + len(anchor)

    def _annotation_status_payload(self, annotation) -> dict[str, object]:
        return {
            "id": annotation.id,
            "project_id": annotation.project_id,
            "canonical_key": annotation.canonical_key,
            "status": annotation.status,
            "locked": annotation.locked,
        }
