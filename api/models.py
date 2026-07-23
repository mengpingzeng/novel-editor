"""Pydantic request/response models for novel-editor API."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    source_name: str = Field(..., description="原著名称，source.txt 需放在 workspace/repo/{source_name}/ 下")
    platform: str = Field(..., description="目标平台: 番茄小说 / 七猫小说")
    track: str = Field(default="auto", description="风格赛道，不填则自动判定")
    word_count_multiplier: float = Field(default=1.0, ge=0.5, le=5.0, description="字数缩放系数")
    writer_model: str = Field(default="tokenhub/glm-5.2", description="写作模型")


class WriteRequest(BaseModel):
    book_id: str = Field(..., description="书名，与注册时 source_name 一致")
    chapters: int = Field(default=1, ge=1, description="写多少章（从下一章开始）")


class CoverGenerateRequest(BaseModel):
    book_id: str = Field(..., description="书名")
    version: Optional[str] = Field(default=None, description="版本号，不填则取最新版本")
    force: bool = Field(default=False, description="是否覆盖已有封面（默认跳过）")


class UpdateWriterModelRequest(BaseModel):
    book_id: str = Field(..., description="书名")
    writer_model: str = Field(..., description="写作模型，如 tokenhub/glm-5.2 或 team-deepseek/deepseek-v4-pro")


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
    draft: Optional[str] = None
    chapter_title: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    version: str = "1.0.0"


class BookMetadataResponse(BaseModel):
    book_id: str
    name: Optional[str] = None
    titles: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    genre: Optional[str] = None
    protagonist: Optional[str] = None
    chapter_names: List[str] = Field(default_factory=list)
    chapters_completed: int = 0
    total_chapters: Optional[int] = None
    cover_image: Optional[str] = None


class ErrorResponse(BaseModel):
    error: str
    details: Optional[str] = None
