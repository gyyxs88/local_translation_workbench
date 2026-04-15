from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import ReviewIssue, ReviewRun


class ReviewRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_run(
        self,
        *,
        project_id: int,
        scope_type: str,
        scope_value: str,
        status: str = "completed",
        summary: str | None = None,
    ) -> ReviewRun:
        review_run = ReviewRun(
            project_id=project_id,
            scope_type=scope_type,
            scope_value=scope_value,
            status=status,
            summary=summary,
        )
        self.session.add(review_run)
        self.session.flush()
        return review_run

    def create_issue(
        self,
        *,
        project_id: int,
        review_run_id: int,
        chapter_id: int,
        issue_type: str,
        severity: str = "medium",
        message: str,
        status: str = "open",
    ) -> ReviewIssue:
        issue = ReviewIssue(
            project_id=project_id,
            review_run_id=review_run_id,
            chapter_id=chapter_id,
            issue_type=issue_type,
            severity=severity,
            message=message,
            status=status,
        )
        self.session.add(issue)
        self.session.flush()
        return issue

    def list_runs(self, project_id: int) -> list[ReviewRun]:
        statement = (
            select(ReviewRun)
            .where(ReviewRun.project_id == project_id)
            .order_by(ReviewRun.id.desc())
        )
        return list(self.session.execute(statement).scalars().all())

    def list_issues(self, project_id: int) -> list[ReviewIssue]:
        statement = (
            select(ReviewIssue)
            .where(ReviewIssue.project_id == project_id)
            .order_by(ReviewIssue.review_run_id.desc(), ReviewIssue.chapter_id.asc(), ReviewIssue.id.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def list_issues_for_run(self, review_run_id: int) -> list[ReviewIssue]:
        statement = (
            select(ReviewIssue)
            .where(ReviewIssue.review_run_id == review_run_id)
            .order_by(ReviewIssue.chapter_id.asc(), ReviewIssue.id.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def get_latest_run(self, project_id: int) -> ReviewRun | None:
        statement = (
            select(ReviewRun)
            .where(ReviewRun.project_id == project_id)
            .order_by(ReviewRun.id.desc())
        )
        return self.session.execute(statement).scalar_one_or_none()
