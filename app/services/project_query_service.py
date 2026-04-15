from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import Chapter, ExportRun, GlossaryEntry, ReviewRun, SegmentTranslation, StageRun
from ..errors import ToolError
from ..repositories.projects import ProjectRepository
from .idempotency_service import IdempotencyService


class ProjectQueryService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.projects = ProjectRepository(session)
        self.idempotency = IdempotencyService(session)

    def list_projects(self) -> dict[str, object]:
        records = self.projects.list_all()
        return {
            "projects": [
                {
                    "id": item.id,
                    "request_id": item.request_id,
                    "project_key": item.project_key,
                    "source_language": item.source_language,
                    "target_language": item.target_language,
                    "status": item.status,
                    "counts": self._build_project_counts(item.id),
                }
                for item in records
            ]
        }

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
        self.session.commit()
        return {
            "project_id": project.id,
            "project_key": project.project_key,
            "status": project.status,
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
            "runs": [
                {
                    "id": item.id,
                    "stage": item.stage,
                    "scope_type": item.scope_type,
                    "status": item.status,
                    "summary": item.summary,
                }
                for item in runs
            ],
        }

    def _build_project_counts(self, project_id: int) -> dict[str, int]:
        return {
            "chapters": self._count(select(func.count()).select_from(Chapter).where(Chapter.project_id == project_id)),
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
