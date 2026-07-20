"""Book routes — register, list, status, config."""

from fastapi import APIRouter, HTTPException

from config import config
from api.models import (
    RegisterRequest,
    TaskResponse,
    BookListResponse,
    BookStatusResponse,
    ErrorResponse,
)
from services.register_service import register_book
from services.status_service import (
    get_book_status,
    get_book_summary,
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
    )
    return TaskResponse(
        task_id=task_id,
        status="queued",
        message=f"Registration for '{req.source_name}' submitted",
    )


@router.get("", response_model=BookListResponse)
def list_books():
    summaries = list_all_summaries()
    return BookListResponse(books=summaries)


@router.get("/{book_id}/status", response_model=BookStatusResponse,
            responses={404: {"model": ErrorResponse}})
def book_status(book_id: str):
    status = get_book_status(book_id)
    if status is None:
        raise HTTPException(404, f"Book '{book_id}' not found")
    return BookStatusResponse(**status)
