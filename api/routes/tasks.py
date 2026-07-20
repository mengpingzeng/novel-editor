"""Task routes — status polling."""

from fastapi import APIRouter, HTTPException

from api.models import TaskStatus, ErrorResponse
from worker.task_queue import task_queue

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.get("/{task_id}", response_model=TaskStatus,
            responses={404: {"model": ErrorResponse}})
def get_task(task_id: str):
    status = task_queue.get_status(task_id)
    if status is None:
        raise HTTPException(404, f"Task '{task_id}' not found")
    return TaskStatus(**status)
