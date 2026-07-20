"""Chapter routes — content and listing."""

from fastapi import APIRouter, HTTPException, Query

from api.models import (
    WriteRequest,
    TaskResponse,
    ChapterListResponse,
    ChapterContentResponse,
    ErrorResponse,
)
from services.write_service import write_chapters
from services.status_service import (
    get_chapter_content,
    get_chapter_list,
)

router = APIRouter(prefix="/api/v1/books/{book_id}", tags=["chapters"])


@router.post("/write", response_model=TaskResponse, status_code=202)
def write(book_id: str, req: WriteRequest):
    task_id = write_chapters(book_id, chapters=req.chapters)
    return TaskResponse(
        task_id=task_id,
        status="queued",
        message=f"Writing {req.chapters} chapter(s) for '{book_id}'",
    )


@router.get("/chapters", response_model=ChapterListResponse,
            responses={404: {"model": ErrorResponse}})
def list_chapters(book_id: str):
    data = get_chapter_list(book_id)
    if data is None:
        raise HTTPException(404, f"Book '{book_id}' not found")
    return ChapterListResponse(**data)


@router.get("/chapters/{global_chapter}", response_model=ChapterContentResponse,
            responses={404: {"model": ErrorResponse}})
def get_chapter(book_id: str, global_chapter: int):
    data = get_chapter_content(book_id, global_chapter)
    if data is None:
        raise HTTPException(404, f"Chapter {global_chapter} not found for book '{book_id}'")
    return ChapterContentResponse(**data)
