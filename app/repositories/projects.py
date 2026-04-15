from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import load_config
from ..db.engine import require_database_url, session_scope
from ..db.models import TranslationProject
from ..utils import ensure_directory
from .operations import OperationRequestRepository
from .synopsis import ProjectSynopsisRepository


CREATE_PROJECT_OPERATION = "project.create"


@dataclass(frozen=True)
class ProjectRecord:
    id: int
    request_id: str
    project_key: str
    source_path: str
    source_language: str
    target_language: str
    status: str


class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, project_id: int) -> TranslationProject | None:
        return self.session.get(TranslationProject, project_id)

    def list_all(self) -> list[TranslationProject]:
        statement = select(TranslationProject).order_by(TranslationProject.id.asc())
        return list(self.session.execute(statement).scalars().all())

    def get_by_request_id(self, request_id: str) -> TranslationProject | None:
        statement = select(TranslationProject).where(TranslationProject.request_id == request_id)
        return self.session.execute(statement).scalar_one_or_none()

    def create(
        self,
        request_id: str,
        source_path: str,
        source_language: str,
        target_language: str,
    ) -> TranslationProject:
        project = TranslationProject(
            request_id=request_id,
            project_key=f"prj_{uuid4().hex[:12]}",
            source_path=source_path,
            source_language=source_language,
            target_language=target_language,
            status="created",
        )
        self.session.add(project)
        self.session.flush()
        return project

    def update_status(self, project: TranslationProject, *, status: str) -> TranslationProject:
        project.status = status
        self.session.flush()
        return project


class ProjectService:
    def __init__(self, database_url: str | None = None, data_dir: Path | None = None) -> None:
        config = load_config()
        self.database_url = require_database_url(database_url or config.database_url)
        self.data_dir = data_dir or config.data_dir

    def create_project(
        self,
        request_id: str,
        source_path: str,
        source_language: str,
        target_language: str,
    ) -> ProjectRecord:
        with session_scope(self.database_url) as session:
            operations = OperationRequestRepository(session)
            project_repository = ProjectRepository(session)

            project = self._find_existing_project(project_repository, operations, request_id)
            if project is None:
                try:
                    project = project_repository.create(
                        request_id=request_id,
                        source_path=source_path,
                        source_language=source_language,
                        target_language=target_language,
                    )
                    operations.create(
                        request_id=request_id,
                        operation_name=CREATE_PROJECT_OPERATION,
                        project_id=project.id,
                    )
                except IntegrityError:
                    session.rollback()
                    project = self._find_existing_project(project_repository, operations, request_id)
                    if project is None:
                        raise

            project = self._ensure_operation_request(
                session=session,
                project_repository=project_repository,
                operations=operations,
                project=project,
                request_id=request_id,
            )

            ProjectSynopsisRepository(session).ensure(project.id)

            self._ensure_project_directories(project.project_key)
            return ProjectRecord(
                id=project.id,
                request_id=project.request_id,
                project_key=project.project_key,
                source_path=project.source_path,
                source_language=project.source_language,
                target_language=project.target_language,
                status=project.status,
            )

    def _find_existing_project(
        self,
        project_repository: ProjectRepository,
        operations: OperationRequestRepository,
        request_id: str,
    ) -> TranslationProject | None:
        existing_request = operations.get_by_request(request_id, CREATE_PROJECT_OPERATION)
        if existing_request is not None:
            project = project_repository.get_by_id(existing_request.project_id)
            if project is not None:
                return project
        return project_repository.get_by_request_id(request_id)

    def _ensure_operation_request(
        self,
        session: Session,
        project_repository: ProjectRepository,
        operations: OperationRequestRepository,
        project: TranslationProject,
        request_id: str,
    ) -> TranslationProject:
        existing_request = operations.get_by_request(request_id, CREATE_PROJECT_OPERATION)
        if existing_request is not None:
            existing_project = project_repository.get_by_id(existing_request.project_id)
            return existing_project or project

        try:
            operations.create(
                request_id=request_id,
                operation_name=CREATE_PROJECT_OPERATION,
                project_id=project.id,
            )
            return project
        except IntegrityError:
            session.rollback()
            recovered_project = self._find_existing_project(project_repository, operations, request_id)
            if recovered_project is None:
                raise
            return recovered_project

    def _ensure_project_directories(self, project_key: str) -> None:
        project_root = ensure_directory(self.data_dir / project_key)
        ensure_directory(project_root / "source")
        ensure_directory(project_root / "translation")
        ensure_directory(project_root / "artifacts")
