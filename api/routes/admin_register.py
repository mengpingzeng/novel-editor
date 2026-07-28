import os
import re

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

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
    RegisterUploadResponse,
    RegisterRemoveSourceRequest,
    RegisterRemoveSourceResponse,
)
from services.book_state import load_book_state, phase_ge
from services.register_service import register_book
from worker.task_queue import task_queue

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO_DIR = os.path.join(ROOT_DIR, "workspace", "repo")

# 合法 book_id：中文/字母/数字/下划线/连字符，禁止路径穿越
_BOOK_ID_RE = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fa5]+$")
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20MB

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
        for entry in os.listdir(REPO_DIR):
            entry_path = os.path.join(REPO_DIR, entry)
            if os.path.isdir(entry_path) and not entry.startswith("_") and not entry.startswith("."):
                if _is_available(entry):
                    source_path = os.path.join(entry_path, "source.txt")
                    try:
                        uploaded_at = os.path.getmtime(source_path)
                    except OSError:
                        uploaded_at = 0.0
                    items.append((uploaded_at, entry))
        # 按上传时间升序：先上传的排前面
        items.sort(key=lambda x: (x[0], x[1]))
    return RegisterAvailableResponse(
        books=[RegisterAvailableItem(book_id=book_id) for _, book_id in items]
    )


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


@router.post("/upload", response_model=RegisterUploadResponse)
async def upload_source(
    book_id: str = Form(..., description="书名，作为 workspace/repo 下的目录名"),
    file: UploadFile = File(..., description="原著 txt 文件"),
):
    """上传原著 txt 文件，写入 workspace/repo/{book_id}/source.txt。

    纯文件写入，不触发注册流程；仅作为注册的前置数据准备。
    """
    bid = (book_id or "").strip()
    if not bid or not _BOOK_ID_RE.match(bid):
        raise HTTPException(400, "非法 book_id（仅允许中文/字母/数字/下划线/连字符）")
    if bid.startswith(".") or bid.startswith("_"):
        raise HTTPException(400, "非法 book_id")

    book_dir = os.path.join(REPO_DIR, bid)
    source_path = os.path.join(book_dir, "source.txt")
    # 二次校验，防止构造的 book_id 逃逸出 REPO_DIR
    if not os.path.abspath(book_dir).startswith(os.path.abspath(REPO_DIR) + os.sep):
        raise HTTPException(400, "非法 book_id")

    overwritten = os.path.isfile(source_path)
    os.makedirs(book_dir, exist_ok=True)

    total = 0
    with open(source_path, "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_UPLOAD_BYTES:
                out.close()
                os.remove(source_path)
                raise HTTPException(413, f"文件过大，上限 {_MAX_UPLOAD_BYTES // 1024 // 1024}MB")
            out.write(chunk)

    return RegisterUploadResponse(
        book_id=bid,
        path=source_path,
        bytes=total,
        overwritten=overwritten,
    )


@router.post("/remove-source", response_model=RegisterRemoveSourceResponse)
def remove_source(req: RegisterRemoveSourceRequest):
    """删除未注册小说的 source.txt（仅当该书尚未注册、未在目录、不在队列中时允许）。

    用于清理误上传的 txt，不影响已注册小说的任何数据。
    """
    bid = (req.book_id or "").strip()
    if not bid or not _BOOK_ID_RE.match(bid):
        raise HTTPException(400, "非法 book_id")
    if bid.startswith(".") or bid.startswith("_"):
        raise HTTPException(400, "非法 book_id")

    book_dir = os.path.join(REPO_DIR, bid)
    source_path = os.path.join(book_dir, "source.txt")
    if not os.path.abspath(book_dir).startswith(os.path.abspath(REPO_DIR) + os.sep):
        raise HTTPException(400, "非法 book_id")

    if not os.path.isfile(source_path):
        return RegisterRemoveSourceResponse(book_id=bid, removed=False)

    # 安全护栏：仅允许删除「可注册」状态的 txt（未注册、未在目录、不在队列）
    if not _is_available(bid):
        raise HTTPException(400, "该书已注册/在目录中/在队列中，不允许删除 source.txt")

    try:
        os.remove(source_path)
    except OSError as e:
        raise HTTPException(500, f"删除 source.txt 失败：{e.strerror or str(e)}")
    # 目录若已空则一并清理
    try:
        if os.path.isdir(book_dir) and not os.listdir(book_dir):
            os.rmdir(book_dir)
    except OSError:
        pass
    return RegisterRemoveSourceResponse(book_id=bid, removed=True)
