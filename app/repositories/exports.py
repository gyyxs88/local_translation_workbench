from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import ExportArtifact, ExportRun


class ExportRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_run(
        self,
        *,
        project_id: int,
        scope_type: str,
        scope_value: str,
        manifest_path: str,
        status: str = "completed",
        summary: str | None = None,
    ) -> ExportRun:
        export_run = ExportRun(
            project_id=project_id,
            scope_type=scope_type,
            scope_value=scope_value,
            status=status,
            manifest_path=manifest_path,
            summary=summary,
        )
        self.session.add(export_run)
        self.session.flush()
        return export_run

    def create_artifact(
        self,
        *,
        export_run_id: int,
        artifact_type: str,
        file_path: str,
    ) -> ExportArtifact:
        artifact = ExportArtifact(
            export_run_id=export_run_id,
            artifact_type=artifact_type,
            file_path=file_path,
        )
        self.session.add(artifact)
        self.session.flush()
        return artifact

    def list_runs(self, project_id: int) -> list[ExportRun]:
        statement = (
            select(ExportRun)
            .where(ExportRun.project_id == project_id)
            .order_by(ExportRun.id.desc())
        )
        return list(self.session.execute(statement).scalars().all())

    def get_latest_run(self, project_id: int) -> ExportRun | None:
        statement = (
            select(ExportRun)
            .where(ExportRun.project_id == project_id)
            .order_by(ExportRun.id.desc())
        )
        return self.session.execute(statement).scalar_one_or_none()

    def list_artifacts(self, project_id: int) -> list[ExportArtifact]:
        statement = (
            select(ExportArtifact)
            .join(ExportRun, ExportRun.id == ExportArtifact.export_run_id)
            .where(ExportRun.project_id == project_id)
            .order_by(ExportArtifact.export_run_id.desc(), ExportArtifact.id.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def list_artifacts_for_run(self, export_run_id: int) -> list[ExportArtifact]:
        statement = (
            select(ExportArtifact)
            .where(ExportArtifact.export_run_id == export_run_id)
            .order_by(ExportArtifact.id.asc())
        )
        return list(self.session.execute(statement).scalars().all())
