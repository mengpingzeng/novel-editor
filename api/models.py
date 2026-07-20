"""Pydantic request/response models for novel-editor API."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    source_name: str = Field(..., description="原著名称，source.txt 需放在 workspace/repo/{source_name}/ 下")
    platform: str = Field(..., description="目标平台: 番茄小说 / 七猫小说")
    track: str = Field(default="auto", description="风格赛道，不填则自动判定")
    word_count_multiplier: float = Field(default=1.0, ge=0.5, le=5.0, description="字数缩放系数")


class WriteRequest(BaseModel):
    chapters: int = Field(default=1, ge=1, description="写多少章（从下一章开始）")


class TaskResponse(BaseModel):
    task_id: str
    status: str
    message: Optional[str] = None


class TaskStatus(BaseModel):
    task_id: str
    type: str
    book_id: str
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    queue_position: int = -1
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class BookSummary(BaseModel):
    book_id: str
    phase: str
    version: Optional[str]
    total_chapters: Optional[int]
    chapters_completed: int


class BookListResponse(BaseModel):
    books: List[BookSummary]


class BookStatusResponse(BaseModel):
    book_id: str
    phase: str
    version: Optional[str]
    total_volumes: Optional[int]
    total_chapters: Optional[int]
    chapters_completed: int
    is_completed: bool
    next_chapter: Optional[Dict[str, int]]
    quality_avg: float
    created_at: Optional[str]
    updated_at: Optional[str]


class ChapterInfo(BaseModel):
    global_chapter: int
    title: str
    status: Optional[str]
    word_count: Optional[int]
    score: Optional[float]


class VolumeInfo(BaseModel):
    volume: int
    chapters: List[ChapterInfo]


class ChapterListResponse(BaseModel):
    book_id: str
    version: Optional[str]
    total_volumes: Optional[int]
    total_chapters: Optional[int]
    volumes: List[VolumeInfo]


class ChapterContentResponse(BaseModel):
    global_chapter: int
    volume: Optional[int]
    title: Optional[str]
    content: str
    word_count: Optional[int]
    score: Optional[float]
    status: Optional[str]


class HealthResponse(BaseModel):
    status: str
    version: str = "1.0.0"


class ErrorResponse(BaseModel):
    error: str
    details: Optional[str] = None
