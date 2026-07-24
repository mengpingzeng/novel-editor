import os

from fastapi import APIRouter, HTTPException

from api.models import (
    RegisterAvailableItem,
    RegisterAvailableResponse,
    RegisterSubmitRequest,
    RegisterSubmitResponse,
    RegisterSubmitResult,
    RegisterQueueItem,
    RegisterQueueResponse,
    RegisterActionRequest,
    RegisterActionResponse,
)
from services.book_state import load_book_state, phase_ge
from services.register_service import register_book
from worker.task_queue import task_queue

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO_DIR = os.path.join(ROOT_DIR, "workspace", "repo")

router = APIRouter(prefix="/api/v1/admin/register", tags=["admin-register"])


def _is_available(book_id: str) -> bool:
    source_path = os.path.join(REPO_DIR, book_id, "source.txt")
    if not os.path.isfile(source_path):
        return False

    state = load_book_state(book_id)
    if state and phase_ge(state.get("phase", "pending"), "phase1_done"):
        return False

    for t in task_queue.list_register_tasks():
        if t["book_id"] == book_id and t["status"] in ("queued", "running"):
            return False

    return True


@router.get("/available", response_model=RegisterAvailableResponse)
def list_available():
    items = []
    if os.path.isdir(REPO_DIR):
        for entry in sorted(os.listdir(REPO_DIR)):
            entry_path = os.path.join(REPO_DIR, entry)
            if os.path.isdir(entry_path) and not entry.startswith("_") and not entry.startswith("."):
                if _is_available(entry):
                    items.append(RegisterAvailableItem(book_id=entry))
    return RegisterAvailableResponse(books=items)


@router.post("/submit", response_model=RegisterSubmitResponse)
def submit(req: RegisterSubmitRequest):
    results = []
    for book_id in req.book_ids:
        if not _is_available(book_id):
            results.append(RegisterSubmitResult(
                book_id=book_id,
                status="rejected",
                error="不可注册（已注册/无源文件/已在队列中）",
            ))
            continue
        try:
            task_id = register_book(
                source_name=book_id,
                platform=req.platform,
                track=req.track,
                word_count_multiplier=req.word_count_multiplier,
                writer_model=req.writer_model,
            )
            results.append(RegisterSubmitResult(
                book_id=book_id,
                task_id=task_id,
                status="queued",
            ))
        except Exception as e:
            results.append(RegisterSubmitResult(
                book_id=book_id,
                status="failed",
                error=str(e),
            ))

    accepted = sum(1 for r in results if r.status == "queued")
    rejected = sum(1 for r in results if r.status == "rejected")
    failed = sum(1 for r in results if r.status == "failed")
    return RegisterSubmitResponse(
        results=results,
        summary={"total": len(req.book_ids), "accepted": accepted, "rejected": rejected, "failed": failed},
    )


@router.get("/queue", response_model=RegisterQueueResponse)
def get_register_queue():
    tasks = task_queue.list_register_tasks()
    items = [RegisterQueueItem(**t) for t in tasks]
    return RegisterQueueResponse(tasks=items, is_paused=task_queue.is_register_paused())


@router.post("/retry", response_model=RegisterActionResponse)
def retry_task(req: RegisterActionRequest):
    result = task_queue.retry_register_task(req.task_id)
    if result is None:
        raise HTTPException(404, f"Task '{req.task_id}' not found")
    return RegisterActionResponse(**result)


@router.post("/remove", response_model=RegisterActionResponse)
def remove_task(req: RegisterActionRequest):
    result = task_queue.remove_register_task(req.task_id)
    if result is None:
        raise HTTPException(404, f"Task '{req.task_id}' not found")
    return RegisterActionResponse(**result)


@router.post("/resume", response_model=RegisterActionResponse)
def resume_queue():
    task_queue.resume_register_queue()
    return RegisterActionResponse(task_id="_queue_", status="resumed", message="Register queue resumed")
