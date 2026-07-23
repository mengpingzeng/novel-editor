"""Book routes — register, list, status, config, write."""

from fastapi import APIRouter, HTTPException, Query

from config import config
from api.models import (
    RegisterRequest,
    WriteRequest,
    CoverGenerateRequest,
    UpdateWriterModelRequest,
    TaskResponse,
    BookListResponse,
    BookStatusResponse,
    BookMetadataResponse,
    ErrorResponse,
)
from services.register_service import register_book
from services.write_service import write_chapters
from services.status_service import (
    get_book_status,
    get_book_summary,
    get_book_metadata,
    list_all_summaries,
)

router = APIRouter(prefix="/api/v1/books", tags=["books"])


@router.get("/config")
def get_config():
    return config.as_dict()


@router.post("/register", response_model=TaskResponse, status_code=202)
def register(req: RegisterRequest):
    task_id = register_book(
        source_name=req.source_name,
        platform=req.platform,
        track=req.track,
        word_count_multiplier=req.word_count_multiplier,
        writer_model=req.writer_model,
    )
    return TaskResponse(
        task_id=task_id,
        status="queued",
        message=f"Registration for '{req.source_name}' submitted",
    )


@router.post("/write", response_model=TaskResponse, status_code=202)
def write(req: WriteRequest):
    task_id = write_chapters(req.book_id, chapters=req.chapters)
    return TaskResponse(
        task_id=task_id,
        status="queued",
        message=f"Writing {req.chapters} chapter(s) for '{req.book_id}'",
    )


@router.get("", response_model=BookListResponse)
def list_books():
    summaries = list_all_summaries()
    return BookListResponse(books=summaries)


@router.get("/status", response_model=BookStatusResponse,
            responses={404: {"model": ErrorResponse}})
def book_status(book_id: str = Query(..., description="书名")):
    status = get_book_status(book_id)
    if status is None:
        raise HTTPException(404, f"Book '{book_id}' not found")
    return BookStatusResponse(**status)


@router.get("/metadata", response_model=BookMetadataResponse,
            responses={404: {"model": ErrorResponse}})
def book_metadata(book_id: str = Query(..., description="书名")):
    meta = get_book_metadata(book_id)
    if meta is None:
        raise HTTPException(404, f"Book '{book_id}' not found")
    return BookMetadataResponse(**meta)


@router.post("/cover/generate", response_model=TaskResponse, status_code=202)
def generate_cover(req: CoverGenerateRequest):
    from services.cover_service import submit_cover_task
    task_id = submit_cover_task(req.book_id, version=req.version, force=req.force)
    return TaskResponse(
        task_id=task_id,
        status="queued",
        message=f"Cover generation for '{req.book_id}' submitted",
    )


@router.put("/writer-model")
def update_writer_model(req: UpdateWriterModelRequest):
    from services.status_service import get_book_status
    from services.register_service import _write_writer_model
    if get_book_status(req.book_id) is None:
        raise HTTPException(404, f"Book '{req.book_id}' not found")
    _write_writer_model(req.book_id, req.writer_model)
    return {"book_id": req.book_id, "writer_model": req.writer_model, "updated": True}
