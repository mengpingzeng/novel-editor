"""
Task queue with global concurrency control and per-book lock enforcement.

- FIFO queue for pending tasks
- Worker pool with configurable max concurrent books
- Per-book flock lock (BookLock) ensures no two workers write the same book
- Task status tracking: queued → running → completed/failed
- Register tasks are serialized (max 1 at a time) and pause queue on failure
"""

import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from queue import Queue, Empty
from typing import Any, Callable, Dict, List, Optional

from config import config
from utils.lock import BookLock


@dataclass
class Task:
    task_id: str
    type: str
    book_id: str
    params: Dict[str, Any] = field(default_factory=dict)
    status: str = "queued"
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    queue_position: int = -1
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TaskQueue:
    def __init__(self, max_concurrent: int = None):
        if max_concurrent is None:
            max_concurrent = config.max_concurrent_books
        self._queue: Queue = Queue()
        self._tasks: Dict[str, Task] = {}
        self._tasks_lock = threading.Lock()
        self._semaphore = threading.BoundedSemaphore(max_concurrent)
        self._register_semaphore = threading.BoundedSemaphore(1)
        self._register_paused = threading.Event()
        self._register_paused.clear()
        self._workers: List[threading.Thread] = []
        self._running = False
        self._shutdown_event = threading.Event()

    def start(self, num_workers: int = 2):
        self._running = True
        self._shutdown_event.clear()
        for _ in range(num_workers):
            t = threading.Thread(target=self._worker_loop, daemon=True)
            t.start()
            self._workers.append(t)

    def shutdown(self, wait: bool = True):
        self._running = False
        self._shutdown_event.set()
        if wait:
            for t in self._workers:
                t.join(timeout=5)

    def submit(self, task_type: str, book_id: str, params: Dict[str, Any] = None) -> str:
        task_id = f"{task_type[:4]}_{uuid.uuid4().hex[:8]}"
        task = Task(
            task_id=task_id,
            type=task_type,
            book_id=book_id,
            params=params or {},
            queue_position=self._queue.qsize() + 1,
        )
        with self._tasks_lock:
            self._tasks[task_id] = task
        self._queue.put(task)
        return task_id

    def get_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._tasks_lock:
            task = self._tasks.get(task_id)
        if task is None:
            return None
        return {
            "task_id": task.task_id,
            "type": task.type,
            "book_id": task.book_id,
            "status": task.status,
            "result": task.result,
            "error": task.error,
            "queue_position": self._get_position(task.task_id),
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        }

    def get_queue_length(self) -> int:
        return self._queue.qsize()

    def _get_position(self, task_id: str) -> int:
        count = 0
        with self._tasks_lock:
            task = self._tasks.get(task_id)
            if task is None or task.status not in ("queued",):
                return -1
        for item in list(self._queue.queue):
            if item.task_id == task_id:
                return count + 1
            count += 1
        return -1

    def _update_task(self, task_id: str, **kwargs):
        with self._tasks_lock:
            task = self._tasks.get(task_id)
            if task:
                for k, v in kwargs.items():
                    setattr(task, k, v)
                task.updated_at = datetime.now(timezone.utc).isoformat()

    def _execute_task(self, task: Task) -> bool:
        from services.register_service import execute_register
        from services.write_service import execute_write

        try:
            if task.type == "register":
                result = execute_register(task.book_id, task.params)
            elif task.type == "write":
                task.params["task_id"] = task.task_id
                result = execute_write(task.book_id, task.params)
            elif task.type == "generate_cover":
                from services.cover_service import execute_generate_cover
                result = execute_generate_cover(task.book_id, task.params)
            else:
                self._update_task(task.task_id, status="failed", error=f"Unknown task type: {task.type}")
                return True

            if result.get("success"):
                self._update_task(task.task_id, status="completed", result=result)
            else:
                self._update_task(task.task_id, status="failed", error=result.get("error"), result=result)
        except Exception as e:
            self._update_task(task.task_id, status="failed", error=str(e))
        return True

    def _try_execute_with_lock(self, task: Task) -> bool:
        lock = BookLock(task.book_id)

        if not lock.acquire(nonblocking=True):
            self._update_task(task.task_id, error=f"Book {task.book_id} is currently being written by another task")
            return False

        try:
            self._update_task(task.task_id, status="running")
            return self._execute_task(task)
        finally:
            lock.release()

    def _worker_loop(self):
        while self._running:
            try:
                task = self._queue.get(timeout=2)
            except Empty:
                continue

            if self._shutdown_event.is_set():
                self._queue.task_done()
                continue

            if task.type == "register":
                self._process_register_task(task)
            else:
                self._process_general_task(task)

    def _process_register_task(self, task: Task):
        acquired = self._register_semaphore.acquire(blocking=False)
        if not acquired:
            self._queue.put(task)
            self._queue.task_done()
            return

        try:
            if self._register_paused.is_set():
                self._queue.put(task)
                return

            success = self._try_execute_with_lock(task)
            if not success:
                time.sleep(2)
                self._queue.put(task)
            else:
                with self._tasks_lock:
                    t = self._tasks.get(task.task_id)
                if t and t.status == "failed":
                    self._register_paused.set()
        finally:
            self._register_semaphore.release()
            self._queue.task_done()

    def _process_general_task(self, task: Task):
        acquired = self._semaphore.acquire(blocking=True, timeout=600)
        if not acquired:
            self._queue.put(task)
            self._queue.task_done()
            return

        try:
            success = self._try_execute_with_lock(task)
            if not success:
                time.sleep(2)
                self._queue.put(task)
        finally:
            self._semaphore.release()
            self._queue.task_done()

    def pause_register_queue(self):
        self._register_paused.set()

    def resume_register_queue(self):
        self._register_paused.clear()

    def is_register_paused(self) -> bool:
        return self._register_paused.is_set()

    def list_register_tasks(self) -> List[Dict[str, Any]]:
        with self._tasks_lock:
            register_tasks = [t for t in self._tasks.values() if t.type == "register"]
        result = []
        for t in register_tasks:
            result.append({
                "task_id": t.task_id,
                "book_id": t.book_id,
                "status": t.status,
                "queue_position": self._get_position(t.task_id),
                "error": t.error,
                "created_at": t.created_at,
                "updated_at": t.updated_at,
                "platform": t.params.get("platform", ""),
                "track": t.params.get("track", ""),
            })
        return result

    def retry_register_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._tasks_lock:
            task = self._tasks.get(task_id)
            if task is None or task.type != "register":
                return None
            if task.status not in ("failed",):
                return {
                    "task_id": task_id,
                    "status": task.status,
                    "message": "Task is not in failed state, cannot retry",
                }
            task.status = "queued"
            task.error = None
            task.result = None
            task.updated_at = datetime.now(timezone.utc).isoformat()
        self._queue.put(task)
        if self._register_paused.is_set():
            self._register_paused.clear()
        return {
            "task_id": task_id,
            "status": "queued",
            "message": "Task re-queued for retry",
        }

    def remove_register_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._tasks_lock:
            task = self._tasks.get(task_id)
            if task is None or task.type != "register":
                return None
            if task.status == "running":
                return {
                    "task_id": task_id,
                    "status": "running",
                    "message": "Task is currently running, cannot remove",
                }
            del self._tasks[task_id]
        return {
            "task_id": task_id,
            "status": "removed",
            "message": "Task removed from queue",
        }


# Module-level singleton for the API server
task_queue = TaskQueue()
