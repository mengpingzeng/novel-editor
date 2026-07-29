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
    tags: List[str] = Field(default_factory=list)
    track: Optional[str] = None
    primary_category: Optional[str] = None


class ErrorResponse(BaseModel):
    error: str
    details: Optional[str] = None


# --- Catalog models ---


class CatalogBook(BaseModel):
    book_id: str
    name: Optional[str] = None
    source_title: Optional[str] = None
    description: Optional[str] = None
    genre: Optional[str] = None
    cover_url: Optional[str] = None
    phase: Optional[str] = None
    version: Optional[str] = None
    total_chapters: Optional[int] = None
    chapters_completed: int = 0
    tags: List[str] = Field(default_factory=list)
    track: Optional[str] = None
    primary_category: Optional[str] = None


class CatalogListResponse(BaseModel):
    books: List[CatalogBook]


class CatalogAllItem(CatalogBook):
    in_catalog: bool = False


class CatalogAllResponse(BaseModel):
    books: List[CatalogAllItem]


class CatalogModifyRequest(BaseModel):
    book_ids: List[str] = Field(..., min_length=1)


class CatalogModifyResult(BaseModel):
    book_id: str
    status: str
    error: Optional[str] = None


class CatalogModifyResponse(BaseModel):
    results: List[CatalogModifyResult]
    summary: dict


# --- Admin registration models ---


class RegisterAvailableItem(BaseModel):
    book_id: str
    repo_exists: bool = True


class RegisterAvailableResponse(BaseModel):
    books: List[RegisterAvailableItem]


class RegisterSubmitRequest(BaseModel):
    book_ids: List[str] = Field(..., min_length=1)
    platform: str = Field(default="番茄小说", description="目标平台")
    track: str = Field(default="auto", description="赛道")
    word_count_multiplier: float = Field(default=1.0, ge=0.5, le=5.0)
    writer_model: str = Field(default="tokenhub/glm-5.2")


class RegisterSubmitResult(BaseModel):
    book_id: str
    task_id: Optional[str] = None
    status: str
    error: Optional[str] = None


class RegisterSubmitResponse(BaseModel):
    results: List[RegisterSubmitResult]
    summary: dict


class RegisterQueueItem(BaseModel):
    task_id: str
    book_id: str
    status: str
    queue_position: int
    error: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    platform: Optional[str] = None
    track: Optional[str] = None


class RegisterQueueResponse(BaseModel):
    tasks: List[RegisterQueueItem]
    is_paused: bool = False


class RegisterActionRequest(BaseModel):
    task_id: str = Field(..., description="任务ID")


class RegisterActionResponse(BaseModel):
    task_id: str
    status: str
    message: Optional[str] = None


class RegisterUploadResponse(BaseModel):
    book_id: str
    path: str
    bytes: int
    overwritten: bool


class RegisterRemoveSourceRequest(BaseModel):
    book_id: str = Field(..., description="书名，对应 workspace/repo 下的目录")


class RegisterRemoveSourceResponse(BaseModel):
    book_id: str
    removed: bool


class ChapterSyncRequest(BaseModel):
    book_id: str = Field(..., description="书名")
    chapter: int = Field(..., ge=1, description="章节号")
    volume: int = Field(default=1, ge=1, description="卷号")
    status: str = Field(default="completed", description="章节状态")
    score: float = Field(default=0.0, ge=0.0, le=100.0, description="质量评分")
    title: str = Field(default="", description="章节标题")


class ChapterSyncResponse(BaseModel):
    status: str
    book_id: str
    chapter: int


class BookStateInitRequest(BaseModel):
    book_id: str = Field(..., description="书名")
    platform: str = Field(default="", description="目标平台")
    track: str = Field(default="", description="风格赛道")
    version: str = Field(default="v1", description="版本号")
    phase: str = Field(default="phase1_done", description="当前阶段")


class BookStateInitResponse(BaseModel):
    status: str
    book_id: str
    phase: str


# ── v5 Checkpoint 模型 ─────────────────────────────────────

class CheckpointSetRequest(BaseModel):
    book_id: str = Field(..., description="书名")
    path: Optional[List[str]] = Field(default=None, description="checkpoint 路径数组")
    status: str = Field(default="done", description="done | failed | pending")
    path_suffix: Optional[str] = Field(default=None, description="产物文件相对路径")
    score: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    word_count: Optional[int] = Field(default=None, ge=0)
    title: Optional[str] = Field(default=None)
    volume: Optional[int] = Field(default=None, ge=1)
    chapter: Optional[int] = Field(default=None, ge=1)


class CheckpointResponse(BaseModel):
    status: str
    book_id: str
    checkpoint_path: List[str]
    checkpoint_status: str


class CheckpointGetResponse(BaseModel):
    book_id: str
    checkpoint: Optional[Dict[str, Any]]


class NextActionResponse(BaseModel):
    book_id: str
    phase: str
    step: Optional[str]
    volume: Optional[int] = None
    chapter: Optional[int] = None
    status: Optional[str] = None
    version: Optional[str] = None
    artifact_path: Optional[str] = None


class PhaseVerifyRequest(BaseModel):
    book_id: str = Field(..., description="书名")
    target_phase: str = Field(..., description="目标 phase 值")


class PhaseVerifyResponse(BaseModel):
    book_id: str
    can_set: bool
    reason: str


class NovelMetadataCreateRequest(BaseModel):
    book_id: str = Field(..., description="书名")
    title: List[str] = Field(..., min_length=5, description="候选书名，至少 5 个")
    genre: str = Field(..., min_length=1, description="主分类（如 玄幻/仙侠/都市/言情）")
    protagonist: str = Field(..., min_length=1, description="主角名")
    description: str = Field(..., min_length=1, description="简介（必填）")
    cover_prompt: str = Field(..., min_length=1, description="封面生图 prompt（必填）")
    word_count_target: int = Field(..., ge=1, description="目标字数（必填）")
    total_chapters: int = Field(..., ge=1, description="目标章数（必填）")
    shadow_intensity: float = Field(default=0.5, ge=0.0, le=1.0)
    setting: str = Field(default="")
    source_title: str = Field(default="")
    source_author: str = Field(default="")
    tags: List[str] = Field(default_factory=list, description="细粒度标签数组，来自 project_salt.json 的 classification.tags")
    track: str = Field(default="", description="赛道，来自 project_salt.json 的 style_track")
    primary_category: str = Field(default="", description="主分类，来自 project_salt.json 的 classification.primary_category")


class NovelMetadataResponse(BaseModel):
    book_id: str
    path: str


class PipelineTemplateResponse(BaseModel):
    pipeline_name: str
    version: str
    phases: Dict[str, Any]


class BookProgressResponse(BaseModel):
    book_id: str
    phase: str
    checkpoints: Dict[str, Any]
    next_action: Optional[NextActionResponse]


# ── Admin: 正文重写（清除正文，保留上帝视角 + Phase1）──

class AdminRewriteRequest(BaseModel):
    book_ids: List[str] = Field(..., min_length=1, description="要重写的书名列表")


class AdminRewriteResult(BaseModel):
    book_id: str
    status: str
    chapters_deleted: int = 0
    minutes_deleted: int = 0
    volumes_reset: List[int] = Field(default_factory=list, description="已重置的卷号")
    error: Optional[str] = None


class AdminRewriteResponse(BaseModel):
    results: List[AdminRewriteResult]
    summary: dict


class ChapterNameValidateResponse(BaseModel):
    valid: bool
    name: str
    errors: List[str] = Field(default_factory=list, description="too_long | has_symbols | duplicate")
