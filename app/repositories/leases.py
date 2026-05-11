from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import ProjectLease


class ProjectLeaseRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_active_lease(self, project_id: int, now: datetime) -> ProjectLease | None:
        statement = select(ProjectLease).where(
            ProjectLease.project_id == project_id,
            ProjectLease.lease_expires_at > now,
        )
        return self.session.execute(statement).scalar_one_or_none()

    def create(self, project_id: int, lease_owner: str, lease_token: str, lease_expires_at: datetime) -> ProjectLease:
        lease = ProjectLease(
            project_id=project_id,
            lease_owner=lease_owner,
            lease_token=lease_token,
            lease_expires_at=lease_expires_at,
        )
        self.session.add(lease)
        self.session.flush()
        return lease
