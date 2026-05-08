from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import (
    Chapter,
    ChapterSegment,
    ExportRun,
    GlossaryEntry,
    ProjectSynopsis,
    ReviewRun,
    SegmentTranslation,
    StageRun,
)
from ..errors import ToolError
from ..repositories.projects import ProjectRepository
from .idempotency_service import IdempotencyService
from .run_cancellation_service import RunCancellationService
from .stage_run_inspection_service import StageRunInspectionService


class ProjectQueryService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.projects = ProjectRepository(session)
        self.idempotency = IdempotencyService(session)
        self.stage_runs = StageRunInspectionService(session)

    def list_projects(self) -> dict[str, object]:
        records = self.projects.list_all()
        synopsis_by_project_id = self._load_synopsis_by_project_id([item.id for item in records])
        duplicate_groups = self._build_duplicate_groups(records)
        return {
            "projects": [
                self._build_project_list_item(
                    project=item,
                    synopsis=synopsis_by_project_id.get(item.id),
                    duplicate_project_ids=duplicate_groups[self._normalize_source_path(item.source_path)],
                )
                for item in records
            ]
        }

    def _build_project_list_item(
        self,
        *,
        project,
        synopsis: ProjectSynopsis | None,
        duplicate_project_ids: list[int],
    ) -> dict[str, object]:
        counts = self._build_project_counts(project.id)
        source_synopsis_status = "missing" if synopsis is None else synopsis.source_synopsis_status
        target_synopsis_status = "missing" if synopsis is None else synopsis.target_synopsis_status
        duplicate_group_key = self._normalize_source_path(project.source_path)
        return {
            "id": project.id,
            "request_id": project.request_id,
            "project_key": project.project_key,
            "title": self._build_source_title(project.source_path),
            "source_path": project.source_path,
            "source_language": project.source_language,
            "target_language": project.target_language,
            "status": project.status,
            "source_synopsis_status": source_synopsis_status,
            "target_synopsis_status": target_synopsis_status,
            "is_duplicate": len(duplicate_project_ids) > 1,
            "duplicate_group_key": duplicate_group_key,
            "duplicate_count": len(duplicate_project_ids),
            "duplicate_project_ids": duplicate_project_ids,
            "counts": counts,
            "next_stage_hint": self._build_next_stage_hint(project_status=project.status, counts=counts),
        }

    def _load_synopsis_by_project_id(self, project_ids: list[int]) -> dict[int, ProjectSynopsis]:
        if not project_ids:
            return {}
        statement = select(ProjectSynopsis).where(ProjectSynopsis.project_id.in_(project_ids))
        return {item.project_id: item for item in self.session.execute(statement).scalars().all()}

    def _build_duplicate_groups(self, projects) -> dict[str, list[int]]:
        groups: dict[str, list[int]] = defaultdict(list)
        for project in projects:
            groups[self._normalize_source_path(project.source_path)].append(project.id)
        return groups

    def _build_source_title(self, source_path: str) -> str:
        file_name = self._build_source_file_name(source_path)
        if "." not in file_name:
            return file_name
        return file_name.rsplit(".", 1)[0]

    def _build_source_file_name(self, source_path: str) -> str:
        normalized = str(source_path).strip().replace("\\", "/").rstrip("/")
        if not normalized:
            return ""
        return normalized.rsplit("/", 1)[-1]

    def _normalize_source_path(self, source_path: str) -> str:
        normalized = str(source_path).strip().replace("\\", "/")
        while "//" in normalized:
            normalized = normalized.replace("//", "/")
        return normalized.rstrip("/").casefold()

    def _build_next_stage_hint(self, *, project_status: str, counts: dict[str, int]) -> dict[str, object]:
        if project_status == "cancelled":
            return {"stage": None, "scope_type": None, "reason": "项目已取消"}
        if counts["chapters"] == 0 or counts["segments"] == 0:
            return {"stage": "chaptering", "scope_type": "all", "reason": "尚未拆章"}
        if counts["glossary_entries"] == 0:
            return {"stage": "glossary", "scope_type": "all", "reason": "已拆章但还没有正式术语"}
        if counts["translations"] == 0:
            return {"stage": "translation", "scope_type": "all", "reason": "已有术语但还没有译文"}
        if counts["translations"] < counts["segments"]:
            return {"stage": "translation", "scope_type": "missing_only", "reason": "仍有未翻译分片"}
        if counts["review_runs"] == 0:
            return {"stage": "review", "scope_type": "missing_only", "reason": "已有译文但尚未审校"}
        if counts["export_runs"] == 0:
            return {"stage": "export", "scope_type": "all", "reason": "已有审校记录但尚未导出"}
        return {"stage": None, "scope_type": None, "reason": "已有导出，可按需继续复核或扩展范围"}

    def cancel_project(self, *, project_id: int, request_id: str) -> dict[str, object]:
        project = self.projects.get_by_id(project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        self.idempotency.record(
            request_id=request_id,
            operation_name="project.cancel",
            project_id=project_id,
        )
        self.projects.update_status(project, status="cancelled")
        cancellation = RunCancellationService(self.session).cancel_project_runs(
            project_id=project_id,
            request_id=request_id,
            reason="project.cancel",
        )
        self.session.commit()
        return {
            "project_id": project.id,
            "project_key": project.project_key,
            "status": project.status,
            **cancellation,
        }

    def cancel_stage_run(
        self,
        *,
        project_id: int,
        request_id: str,
        stage_run_id: int | None = None,
        stage: str | None = None,
    ) -> dict[str, object]:
        project = self.projects.get_by_id(project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        self.idempotency.record(
            request_id=request_id,
            operation_name="stage.cancel",
            project_id=project_id,
        )
        cancellation = RunCancellationService(self.session).cancel_stage_run(
            project_id=project_id,
            request_id=request_id,
            stage_run_id=stage_run_id,
            stage=stage,
            reason="stage.cancel",
        )
        self.session.commit()
        return {
            "project_id": project.id,
            "project_key": project.project_key,
            "project_status": project.status,
            **cancellation,
        }

    def inspect_stage_runs(
        self,
        *,
        project_id: int,
        stage: str | None = None,
        limit: int = 20,
    ) -> dict[str, object]:
        project = self.projects.get_by_id(project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        normalized_limit = max(1, min(limit, 200))
        statement = select(StageRun).where(StageRun.project_id == project_id)
        if stage:
            statement = statement.where(StageRun.stage == stage.strip().lower())
        statement = statement.order_by(StageRun.id.desc()).limit(normalized_limit)

        runs = list(self.session.execute(statement).scalars().all())
        return {
            "project_id": project_id,
            "runs": [self.stage_runs.build_stage_run_payload(stage_run=item) for item in runs],
        }

    def _build_project_counts(self, project_id: int) -> dict[str, int]:
        return {
            "chapters": self._count(select(func.count()).select_from(Chapter).where(Chapter.project_id == project_id)),
            "segments": self._count(
                select(func.count()).select_from(ChapterSegment).where(ChapterSegment.project_id == project_id)
            ),
            "glossary_entries": self._count(
                select(func.count()).select_from(GlossaryEntry).where(GlossaryEntry.project_id == project_id)
            ),
            "translations": self._count(
                select(func.count()).select_from(SegmentTranslation).where(SegmentTranslation.project_id == project_id)
            ),
            "review_runs": self._count(
                select(func.count()).select_from(ReviewRun).where(ReviewRun.project_id == project_id)
            ),
            "export_runs": self._count(
                select(func.count()).select_from(ExportRun).where(ExportRun.project_id == project_id)
            ),
            "stage_runs": self._count(
                select(func.count()).select_from(StageRun).where(StageRun.project_id == project_id)
            ),
        }

    def _count(self, statement) -> int:
        return int(self.session.execute(statement).scalar_one())
