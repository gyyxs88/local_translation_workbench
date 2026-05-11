from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import threading
import time
from typing import Any, Callable

from sqlalchemy import select

from ..db.models import Chapter, WorkflowStepRun


class GlossaryExtractionProgressTracker:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Any],
        workflow_step_run_id: int,
        chapters: list[Chapter],
        max_parallel_workers: int,
    ) -> None:
        self.session_factory = session_factory
        self.workflow_step_run_id = int(workflow_step_run_id)
        self._lock = threading.Lock()
        self._chapter_started_monotonic: dict[int, float] = {}
        now = self._now()
        self._progress: dict[str, object] = {
            "kind": "glossary.extract",
            "total_chapters": len(chapters),
            "queued_chapters": len(chapters),
            "running_chapters": 0,
            "completed_chapters": 0,
            "failed_chapters": 0,
            "skipped_chapters": 0,
            "finished_chapters": 0,
            "max_parallel_workers": max(1, int(max_parallel_workers)),
            "started_at": now,
            "updated_at": now,
            "chapters": [
                {
                    "chapter_id": int(chapter.id),
                    "chapter_index": int(chapter.chapter_index),
                    "chapter_title": str(chapter.chapter_title),
                    "status": "queued",
                    "extraction_status": None,
                    "candidate_count": 0,
                    "quality_issue_count": 0,
                    "started_at": None,
                    "finished_at": None,
                    "elapsed_ms": None,
                    "error": None,
                }
                for chapter in chapters
            ],
        }

    def initialize(self) -> None:
        self._persist(self.snapshot())

    def mark_running(self, *, chapter_id: int) -> None:
        now = self._now()
        with self._lock:
            chapter = self._find_chapter_locked(chapter_id)
            chapter["status"] = "running"
            chapter["started_at"] = now
            chapter["error"] = None
            self._chapter_started_monotonic[int(chapter_id)] = time.perf_counter()
            self._recount_locked(updated_at=now)
            snapshot = deepcopy(self._progress)
        self._persist(snapshot)

    def mark_completed(
        self,
        *,
        chapter_id: int,
        extraction_status: str,
        candidate_count: int,
        quality_issue_count: int,
    ) -> None:
        self._mark_finished(
            chapter_id=chapter_id,
            status="completed",
            extraction_status=extraction_status,
            candidate_count=candidate_count,
            quality_issue_count=quality_issue_count,
            error=None,
        )

    def mark_skipped(self, *, chapter_id: int, error: str) -> None:
        self._mark_finished(
            chapter_id=chapter_id,
            status="skipped",
            extraction_status="skipped",
            candidate_count=0,
            quality_issue_count=1,
            error=error,
        )

    def mark_failed(self, *, chapter_id: int, error: str) -> None:
        self._mark_finished(
            chapter_id=chapter_id,
            status="failed",
            extraction_status="failed",
            candidate_count=0,
            quality_issue_count=1,
            error=error,
        )

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return deepcopy(self._progress)

    def _mark_finished(
        self,
        *,
        chapter_id: int,
        status: str,
        extraction_status: str,
        candidate_count: int,
        quality_issue_count: int,
        error: str | None,
    ) -> None:
        now = self._now()
        with self._lock:
            chapter = self._find_chapter_locked(chapter_id)
            chapter["status"] = status
            chapter["extraction_status"] = extraction_status
            chapter["candidate_count"] = int(candidate_count)
            chapter["quality_issue_count"] = int(quality_issue_count)
            chapter["finished_at"] = now
            chapter["elapsed_ms"] = self._elapsed_ms(chapter_id)
            chapter["error"] = error
            self._recount_locked(updated_at=now)
            snapshot = deepcopy(self._progress)
        self._persist(snapshot)

    def _find_chapter_locked(self, chapter_id: int) -> dict[str, object]:
        chapters = self._progress.get("chapters")
        if not isinstance(chapters, list):
            raise ValueError("glossary progress chapters payload is invalid.")
        for chapter in chapters:
            if isinstance(chapter, dict) and int(chapter.get("chapter_id") or 0) == int(chapter_id):
                return chapter
        raise ValueError(f"glossary progress chapter_id={chapter_id} is not tracked.")

    def _recount_locked(self, *, updated_at: str) -> None:
        chapters = [item for item in self._progress.get("chapters", []) if isinstance(item, dict)]
        status_counts: dict[str, int] = {}
        for chapter in chapters:
            status = str(chapter.get("status") or "queued")
            status_counts[status] = status_counts.get(status, 0) + 1
        completed = status_counts.get("completed", 0)
        skipped = status_counts.get("skipped", 0)
        failed = status_counts.get("failed", 0)
        self._progress["queued_chapters"] = status_counts.get("queued", 0)
        self._progress["running_chapters"] = status_counts.get("running", 0)
        self._progress["completed_chapters"] = completed
        self._progress["skipped_chapters"] = skipped
        self._progress["failed_chapters"] = failed
        self._progress["finished_chapters"] = completed + skipped + failed
        self._progress["updated_at"] = updated_at

    def _elapsed_ms(self, chapter_id: int) -> int | None:
        started_at = self._chapter_started_monotonic.get(int(chapter_id))
        if started_at is None:
            return None
        return max(0, int((time.perf_counter() - started_at) * 1000))

    def _persist(self, progress: dict[str, object]) -> None:
        session = self.session_factory()
        try:
            step_run = session.execute(
                select(WorkflowStepRun)
                .where(WorkflowStepRun.id == self.workflow_step_run_id)
                .with_for_update()
            ).scalar_one_or_none()
            if step_run is None:
                session.rollback()
                return
            payload = dict(step_run.output_payload) if isinstance(step_run.output_payload, dict) else {}
            payload["progress"] = progress
            step_run.output_payload = payload
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
