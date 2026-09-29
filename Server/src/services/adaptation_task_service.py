"""In-memory task manager for game code adaptation jobs."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


@dataclass
class AdaptTask:
    task_id: str
    request: dict[str, Any]
    task_type: str = "adapt_game_code"
    status: str = "queued"
    phase: str = "prepare"
    progress: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    runner: asyncio.Task | None = field(default=None, repr=False)

    def update(self, *, status: str | None = None, phase: str | None = None, progress: float | None = None) -> None:
        if status:
            self.status = status
        if phase:
            self.phase = phase
        if progress is not None:
            self.progress = max(0.0, min(1.0, progress))
        self.updated_at = time.time()

    def finish(self, *, status: str, result: dict[str, Any] | None = None, error: str | None = None) -> None:
        self.status = status
        self.result = result
        self.error = error
        self.progress = 1.0
        self.completed_at = time.time()
        self.updated_at = self.completed_at

    def to_dict(self, *, include_generated_code: bool = True) -> dict[str, Any]:
        result = self.result
        if result is not None and not include_generated_code:
            result = dict(result)
            if "generated_code" in result:
                result["generated_code"] = ""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status,
            "phase": self.phase,
            "progress": self.progress,
            "request": self.request,
            "result": result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }


class AdaptTaskManager:
    def __init__(self, max_tasks: int = 20, max_completed_age_seconds: float = 3600.0) -> None:
        self.max_tasks = max_tasks
        self.max_completed_age_seconds = max_completed_age_seconds
        self._tasks: dict[str, AdaptTask] = {}

    def start(
        self,
        request: dict[str, Any],
        runner_factory: Callable[[AdaptTask], Awaitable[dict[str, Any]]],
        task_type: str = "adapt_game_code",
    ) -> AdaptTask:
        self.cleanup()
        task = AdaptTask(task_id=str(uuid.uuid4()), request=request, task_type=task_type)
        self._tasks[task.task_id] = task
        self._attach_runner(task, runner_factory)
        return task

    def _attach_runner(
        self,
        task: AdaptTask,
        runner_factory: Callable[[AdaptTask], Awaitable[dict[str, Any]]],
    ) -> None:
        task.error = None
        task.completed_at = None
        task.updated_at = time.time()

        async def _runner() -> None:
            try:
                task.update(status="running", phase="prepare", progress=0.02)
                result = await runner_factory(task)
                if task.status == "cancelled":
                    return
                result_status = result.get("status") if isinstance(result, dict) else ""
                if result_status in {"error", "unavailable"}:
                    task.finish(status="failed", result=result, error=str(result.get("error") or result_status))
                else:
                    task.update(phase="ready", progress=1.0)
                    task.finish(status="completed", result=result)
            except asyncio.CancelledError:
                task.finish(status="cancelled", error="Task was cancelled.")
                raise
            except Exception as exc:
                task.finish(status="failed", error=str(exc))

        task.runner = asyncio.create_task(_runner())

    def run_existing(
        self,
        task: AdaptTask,
        runner_factory: Callable[[AdaptTask], Awaitable[dict[str, Any]]],
    ) -> AdaptTask:
        self.cleanup()
        self._attach_runner(task, runner_factory)
        return task

    def get(self, task_id: str) -> AdaptTask | None:
        return self._tasks.get(task_id)

    def cancel(self, task_id: str) -> AdaptTask | None:
        task = self._tasks.get(task_id)
        if not task:
            return None
        if task.status in TERMINAL_STATUSES:
            return task
        task.update(status="cancelled", phase="cancelled", progress=task.progress)
        task.completed_at = time.time()
        task.error = "Task was cancelled."
        if task.runner and not task.runner.done():
            task.runner.cancel()
        return task

    def cleanup(self) -> int:
        now = time.time()
        removed: list[str] = []
        for task_id, task in self._tasks.items():
            if task.status in TERMINAL_STATUSES and task.completed_at:
                if now - task.completed_at > self.max_completed_age_seconds:
                    removed.append(task_id)

        if len(self._tasks) - len(removed) > self.max_tasks:
            candidates = sorted(
                (
                    task
                    for task_id, task in self._tasks.items()
                    if task_id not in removed and task.status in TERMINAL_STATUSES
                ),
                key=lambda item: item.completed_at or item.updated_at,
            )
            overflow = len(self._tasks) - len(removed) - self.max_tasks
            removed.extend(task.task_id for task in candidates[:overflow])

        for task_id in removed:
            self._tasks.pop(task_id, None)
        return len(removed)


_adapt_task_manager = AdaptTaskManager()


def get_adapt_task_manager() -> AdaptTaskManager:
    return _adapt_task_manager
