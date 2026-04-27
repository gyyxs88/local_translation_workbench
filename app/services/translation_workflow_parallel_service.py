from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable


class TranslationWorkflowParallelService:
    def __init__(self, *, parallel_session_factory=None, max_parallel_workers: int = 4) -> None:
        self.parallel_session_factory = parallel_session_factory
        self.max_parallel_workers = max_parallel_workers

    def should_run_parallel(self, *, job_count: int) -> bool:
        return self.parallel_session_factory is not None and job_count > 1

    def run_parallel_jobs(
        self,
        *,
        jobs: list[dict[str, object]],
        worker: Callable[[dict[str, object]], dict[str, object]],
    ) -> list[dict[str, object]]:
        if not jobs:
            return []
        if len(jobs) == 1:
            return [worker(jobs[0])]
        with ThreadPoolExecutor(max_workers=self._worker_count(job_count=len(jobs))) as executor:
            futures = [executor.submit(worker, job) for job in jobs]
            return [future.result() for future in futures]

    def _worker_count(self, *, job_count: int) -> int:
        return max(1, min(job_count, self.max_parallel_workers))
