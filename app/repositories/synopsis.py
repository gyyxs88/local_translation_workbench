from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import ProjectSynopsis


class ProjectSynopsisRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_project_id(self, project_id: int) -> ProjectSynopsis | None:
        statement = select(ProjectSynopsis).where(ProjectSynopsis.project_id == project_id)
        return self.session.execute(statement).scalar_one_or_none()

    def ensure(self, project_id: int) -> ProjectSynopsis:
        synopsis = self.get_by_project_id(project_id)
        if synopsis is not None:
            return synopsis

        synopsis = ProjectSynopsis(
            project_id=project_id,
            source_synopsis_status="missing",
            target_synopsis_status="missing",
        )
        self.session.add(synopsis)
        self.session.flush()
        return synopsis
