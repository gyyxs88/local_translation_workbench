from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import OperationRequest


class OperationRequestRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_request(self, request_id: str, operation_name: str) -> OperationRequest | None:
        statement = select(OperationRequest).where(
            OperationRequest.request_id == request_id,
            OperationRequest.operation_name == operation_name,
        )
        return self.session.execute(statement).scalar_one_or_none()

    def create(self, request_id: str, operation_name: str, project_id: int) -> OperationRequest:
        operation_request = OperationRequest(
            request_id=request_id,
            operation_name=operation_name,
            project_id=project_id,
        )
        self.session.add(operation_request)
        self.session.flush()
        return operation_request
