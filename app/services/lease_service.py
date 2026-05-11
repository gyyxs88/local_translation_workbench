from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db.models import ProjectLease
from ..errors import ToolError


@dataclass(frozen=True)
class LeaseRecord:
    project_id: int
    lease_owner: str
    lease_token: str
    lease_expires_at: datetime


class LeaseService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def acquire(self, *, project_id: int, lease_owner: str, ttl_seconds: int) -> LeaseRecord:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        lease = self.session.execute(
            select(ProjectLease)
            .where(ProjectLease.project_id == project_id)
            .with_for_update()
        ).scalar_one_or_none()
        expires_at = now + timedelta(seconds=ttl_seconds)
        lease_token = uuid4().hex

        if lease is not None and lease.lease_expires_at > now and lease.lease_owner != lease_owner:
            raise ToolError(
                code="conflict_error",
                message=f"项目 {project_id} 当前正被 {lease.lease_owner} 占用。",
                status=409,
            )

        if lease is None:
            lease = ProjectLease(
                project_id=project_id,
                lease_owner=lease_owner,
                lease_token=lease_token,
                lease_expires_at=expires_at,
            )
            self.session.add(lease)
        else:
            lease.lease_owner = lease_owner
            lease.lease_token = lease_token
            lease.lease_expires_at = expires_at

        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ToolError(
                code="conflict_error",
                message=f"项目 {project_id} 当前存在租约竞争，请稍后重试。",
                status=409,
            ) from exc
        return LeaseRecord(
            project_id=project_id,
            lease_owner=lease_owner,
            lease_token=lease_token,
            lease_expires_at=expires_at,
        )

    def release(self, *, project_id: int, lease_owner: str, lease_token: str) -> bool:
        lease = self._get_lease(project_id=project_id)
        if lease is None or lease.lease_owner != lease_owner or lease.lease_token != lease_token:
            return False

        self.session.delete(lease)
        self.session.commit()
        return True

    def refresh(self, *, project_id: int, lease_owner: str, lease_token: str, ttl_seconds: int) -> LeaseRecord:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        lease = self.session.execute(
            select(ProjectLease)
            .where(ProjectLease.project_id == project_id)
            .with_for_update()
        ).scalar_one_or_none()
        if lease is None or lease.lease_owner != lease_owner or lease.lease_token != lease_token:
            raise ToolError(
                code="conflict_error",
                message=f"项目 {project_id} 的租约已失效，无法续租。",
                status=409,
            )

        expires_at = now + timedelta(seconds=ttl_seconds)
        lease.lease_expires_at = expires_at
        self.session.commit()
        return LeaseRecord(
            project_id=project_id,
            lease_owner=lease_owner,
            lease_token=lease_token,
            lease_expires_at=expires_at,
        )

    def _get_lease(self, *, project_id: int) -> ProjectLease | None:
        statement = select(ProjectLease).where(ProjectLease.project_id == project_id)
        return self.session.execute(statement).scalar_one_or_none()
