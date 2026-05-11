from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db.models import OperationRequest
from ..errors import ToolError
from ..repositories.operations import OperationRequestRepository


@dataclass(frozen=True)
class IdempotencyRecord:
    request_id: str
    operation_name: str
    project_id: int
    created: bool


class IdempotencyService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.requests = OperationRequestRepository(session)

    def get(self, *, request_id: str, operation_name: str) -> OperationRequest | None:
        return self.requests.get_by_request(request_id, operation_name)

    def record(self, *, request_id: str, operation_name: str, project_id: int) -> IdempotencyRecord:
        existing = self.get(request_id=request_id, operation_name=operation_name)
        if existing is not None:
            if existing.project_id != project_id:
                raise ToolError(
                    code="conflict_error",
                    message=f"请求 {request_id} 已绑定到其他项目。",
                    status=409,
                )
            return IdempotencyRecord(
                request_id=request_id,
                operation_name=operation_name,
                project_id=project_id,
                created=False,
            )

        try:
            self.requests.create(request_id=request_id, operation_name=operation_name, project_id=project_id)
        except IntegrityError:
            self.session.rollback()
            existing = self.get(request_id=request_id, operation_name=operation_name)
            if existing is None:
                raise
            if existing.project_id != project_id:
                raise ToolError(
                    code="conflict_error",
                    message=f"请求 {request_id} 已绑定到其他项目。",
                    status=409,
                )
            return IdempotencyRecord(
                request_id=request_id,
                operation_name=operation_name,
                project_id=project_id,
                created=False,
            )

        return IdempotencyRecord(
            request_id=request_id,
            operation_name=operation_name,
            project_id=project_id,
            created=True,
        )
