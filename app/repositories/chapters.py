from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..db.models import Chapter, ChapterSegment, StageRun


class ChapterRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_chapter(self, **kwargs) -> Chapter:
        chapter = Chapter(**kwargs)
        self.session.add(chapter)
        self.session.flush()
        return chapter

    def create_segment(self, **kwargs) -> ChapterSegment:
        segment = ChapterSegment(**kwargs)
        self.session.add(segment)
        self.session.flush()
        return segment

    def create_stage_run(self, **kwargs) -> StageRun:
        stage_run = StageRun(**kwargs)
        self.session.add(stage_run)
        self.session.flush()
        return stage_run

    def delete_segments_for_project(self, project_id: int) -> None:
        self.session.execute(delete(ChapterSegment).where(ChapterSegment.project_id == project_id))

    def delete_chapters_for_project(self, project_id: int) -> None:
        self.session.execute(delete(Chapter).where(Chapter.project_id == project_id))
