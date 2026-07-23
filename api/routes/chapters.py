"""Chapter routes — content, listing and covers."""

import os

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from api.models import (
    ChapterListResponse,
    ChapterContentResponse,
    ErrorResponse,
)
from services.status_service import (
    get_chapter_content,
    get_chapter_list,
    BOOKS_DIR,
)

router = APIRouter(prefix="/api/v1/books", tags=["chapters"])


@router.get("/chapters", response_model=ChapterListResponse,
            responses={404: {"model": ErrorResponse}})
def list_chapters(book_id: str = Query(..., description="书名")):
    data = get_chapter_list(book_id)
    if data is None:
        raise HTTPException(404, f"Book '{book_id}' not found")
    return ChapterListResponse(**data)


@router.get("/chapters/{global_chapter}", response_model=ChapterContentResponse,
            responses={404: {"model": ErrorResponse}})
def get_chapter(global_chapter: int,
                book_id: str = Query(..., description="书名")):
    data = get_chapter_content(book_id, global_chapter)
    if data is None:
        raise HTTPException(404, f"Chapter {global_chapter} not found for book '{book_id}'")
    return ChapterContentResponse(**data)


@router.get("/cover")
def get_cover(book_id: str = Query(..., description="书名")):
    state = __import__("services.book_state", fromlist=["load_book_state"]).load_book_state(book_id)
    if state is None:
        raise HTTPException(404, f"Book '{book_id}' not found")
    version = state.get("version", "v1")
    cover_path = os.path.join(BOOKS_DIR, book_id, "versions", version, "发布", "cover.png")
    if not os.path.exists(cover_path):
        raise HTTPException(404, f"Cover not found for book '{book_id}'")
    return FileResponse(cover_path, media_type="image/png")
