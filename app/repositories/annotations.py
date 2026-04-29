from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Annotation, AnnotationOccurrence, Chapter, ChapterSegment


class AnnotationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_canonical_key(self, *, project_id: int, canonical_key: str) -> Annotation | None:
        statement = select(Annotation).where(
            Annotation.project_id == project_id,
            Annotation.canonical_key == canonical_key,
        )
        return self.session.execute(statement).scalar_one_or_none()

    def get_annotation(self, annotation_id: int) -> Annotation | None:
        return self.session.get(Annotation, annotation_id)

    def create_annotation(
        self,
        *,
        project_id: int,
        source_anchor: str,
        target_anchor: str,
        annotation_type: str,
        canonical_key: str,
        explanation: str,
        status: str,
        locked: int,
        source: str,
        evidence_payload: dict[str, object] | None,
        conflict_with_annotation_id: int | None = None,
    ) -> Annotation:
        annotation = Annotation(
            project_id=project_id,
            source_anchor=source_anchor,
            target_anchor=target_anchor,
            annotation_type=annotation_type,
            canonical_key=canonical_key,
            explanation=explanation,
            status=status,
            locked=locked,
            source=source,
            evidence_payload=evidence_payload,
            conflict_with_annotation_id=conflict_with_annotation_id,
        )
        self.session.add(annotation)
        self.session.flush()
        return annotation

    def update_annotation(self, annotation: Annotation, candidate: dict[str, object]) -> Annotation:
        annotation.source_anchor = str(candidate["source_anchor"])
        annotation.target_anchor = str(candidate["target_anchor"])
        annotation.annotation_type = str(candidate["annotation_type"])
        annotation.explanation = str(candidate["explanation"])
        annotation.status = str(candidate.get("status") or annotation.status)
        annotation.source = str(candidate.get("source") or annotation.source)
        evidence_payload = candidate.get("evidence_payload")
        annotation.evidence_payload = evidence_payload if isinstance(evidence_payload, dict) else annotation.evidence_payload
        self.session.flush()
        return annotation

    def create_or_update_occurrence(
        self,
        *,
        annotation_id: int,
        project_id: int,
        chapter_id: int,
        segment_id: int,
        version_id: int,
        source_anchor: str,
        target_anchor: str,
        source_start: int | None = None,
        source_end: int | None = None,
        target_start: int | None = None,
        target_end: int | None = None,
        display_order: int = 0,
    ) -> AnnotationOccurrence:
        occurrence = self.get_occurrence(
            annotation_id=annotation_id,
            version_id=version_id,
            source_anchor=source_anchor,
            target_anchor=target_anchor,
        )
        if occurrence is None:
            occurrence = AnnotationOccurrence(
                annotation_id=annotation_id,
                project_id=project_id,
                chapter_id=chapter_id,
                segment_id=segment_id,
                version_id=version_id,
                source_anchor=source_anchor,
                target_anchor=target_anchor,
                source_start=source_start,
                source_end=source_end,
                target_start=target_start,
                target_end=target_end,
                display_order=display_order,
            )
            self.session.add(occurrence)
        else:
            occurrence.project_id = project_id
            occurrence.chapter_id = chapter_id
            occurrence.segment_id = segment_id
            occurrence.source_start = source_start
            occurrence.source_end = source_end
            occurrence.target_start = target_start
            occurrence.target_end = target_end
            occurrence.display_order = display_order
        self.session.flush()
        return occurrence

    def get_occurrence(
        self,
        *,
        annotation_id: int,
        version_id: int,
        source_anchor: str,
        target_anchor: str,
    ) -> AnnotationOccurrence | None:
        statement = select(AnnotationOccurrence).where(
            AnnotationOccurrence.annotation_id == annotation_id,
            AnnotationOccurrence.version_id == version_id,
            AnnotationOccurrence.source_anchor == source_anchor,
            AnnotationOccurrence.target_anchor == target_anchor,
        )
        return self.session.execute(statement).scalar_one_or_none()

    def list_annotations(self, *, project_id: int, status: str | None = None) -> list[dict[str, object]]:
        statement = (
            select(Annotation, AnnotationOccurrence, Chapter, ChapterSegment)
            .outerjoin(AnnotationOccurrence, AnnotationOccurrence.annotation_id == Annotation.id)
            .outerjoin(Chapter, Chapter.id == AnnotationOccurrence.chapter_id)
            .outerjoin(ChapterSegment, ChapterSegment.id == AnnotationOccurrence.segment_id)
            .where(Annotation.project_id == project_id)
            .order_by(Annotation.id.asc(), AnnotationOccurrence.display_order.asc(), AnnotationOccurrence.id.asc())
        )
        if status is not None:
            statement = statement.where(Annotation.status == status)
        return self._group_annotation_rows(self.session.execute(statement).all())

    def list_export_annotations(self, *, project_id: int, chapter_ids: list[int]) -> list[dict[str, object]]:
        if not chapter_ids:
            return []
        statement = (
            select(Annotation, AnnotationOccurrence, Chapter, ChapterSegment)
            .join(AnnotationOccurrence, AnnotationOccurrence.annotation_id == Annotation.id)
            .join(Chapter, Chapter.id == AnnotationOccurrence.chapter_id)
            .join(ChapterSegment, ChapterSegment.id == AnnotationOccurrence.segment_id)
            .where(
                Annotation.project_id == project_id,
                Annotation.status == "approved",
                AnnotationOccurrence.chapter_id.in_(chapter_ids),
            )
            .order_by(
                AnnotationOccurrence.chapter_id.asc(),
                AnnotationOccurrence.display_order.asc(),
                Annotation.id.asc(),
                AnnotationOccurrence.id.asc(),
            )
        )
        return self._group_annotation_rows(self.session.execute(statement).all())

    def approve(self, annotation_id: int, *, locked: bool = False) -> Annotation | None:
        annotation = self.get_annotation(annotation_id)
        if annotation is None:
            return None
        annotation.status = "approved"
        if locked:
            annotation.locked = 1
        self.session.flush()
        return annotation

    def reject(self, annotation_id: int) -> Annotation | None:
        annotation = self.get_annotation(annotation_id)
        if annotation is None:
            return None
        annotation.status = "rejected"
        self.session.flush()
        return annotation

    def _group_annotation_rows(self, rows: list[tuple[Annotation, AnnotationOccurrence | None, Chapter | None, ChapterSegment | None]]) -> list[dict[str, object]]:
        grouped: dict[int, dict[str, object]] = {}
        for annotation, occurrence, chapter, segment in rows:
            item = grouped.setdefault(annotation.id, self._annotation_payload(annotation))
            if occurrence is not None:
                occurrences = item["occurrences"]
                assert isinstance(occurrences, list)
                occurrences.append(self._occurrence_payload(occurrence, chapter, segment))
        return list(grouped.values())

    def _annotation_payload(self, annotation: Annotation) -> dict[str, object]:
        return {
            "id": annotation.id,
            "project_id": annotation.project_id,
            "source_anchor": annotation.source_anchor,
            "target_anchor": annotation.target_anchor,
            "annotation_type": annotation.annotation_type,
            "canonical_key": annotation.canonical_key,
            "explanation": annotation.explanation,
            "status": annotation.status,
            "locked": annotation.locked,
            "source": annotation.source,
            "conflict_with_annotation_id": annotation.conflict_with_annotation_id,
            "evidence_payload": annotation.evidence_payload,
            "occurrences": [],
        }

    def _occurrence_payload(
        self,
        occurrence: AnnotationOccurrence,
        chapter: Chapter | None,
        segment: ChapterSegment | None,
    ) -> dict[str, object]:
        return {
            "id": occurrence.id,
            "chapter_id": occurrence.chapter_id,
            "chapter_index": None if chapter is None else chapter.chapter_index,
            "segment_id": occurrence.segment_id,
            "segment_index": None if segment is None else segment.segment_index,
            "version_id": occurrence.version_id,
            "source_anchor": occurrence.source_anchor,
            "target_anchor": occurrence.target_anchor,
            "source_start": occurrence.source_start,
            "source_end": occurrence.source_end,
            "target_start": occurrence.target_start,
            "target_end": occurrence.target_end,
            "display_order": occurrence.display_order,
        }
