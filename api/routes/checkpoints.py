"""
v5 Checkpoint API — 确定性落盘与断点续跑

每个流水线步骤完成后，agent 调用对应端点落盘 checkpoint。
Phase 转换只在全部子步骤 done 后执行。
"""

import json
import os
import re
import shutil
import unicodedata
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query

from api.models import (
    CheckpointSetRequest, CheckpointResponse, CheckpointGetResponse,
    NextActionResponse, PhaseVerifyRequest, PhaseVerifyResponse,
    NovelMetadataCreateRequest, NovelMetadataResponse,
    ErrorResponse, ChapterNameValidateResponse,
)
from services.book_state import (
    load_book_state, save_book_state, ensure_book_state,
    set_checkpoint, get_checkpoint, is_checkpoint_done,
    find_next_action, try_set_phase, can_set_phase,
    PHASE1_STEP_ORDER, BOOKS_DIR,
    load_novel_metadata, save_novel_metadata,
)
from services.log_service import get_logger, print_book_progress

router = APIRouter(prefix="/api/v1/books", tags=["checkpoints"])


# ── 通用 checkpoint 设置 ──────────────────────────────────

@router.post("/{book_id}/checkpoints/set", response_model=CheckpointResponse,
             responses={404: {"model": ErrorResponse}, 400: {"model": ErrorResponse}})
def checkpoint_set(book_id: str, req: CheckpointSetRequest):
    path = req.path
    if not path:
        return CheckpointResponse(status="error", book_id=book_id,
                                  checkpoint_path=[], checkpoint_status="no_path")

    extra = {}
    if req.path_suffix:
        extra["path"] = req.path_suffix
    if req.score is not None:
        extra["score"] = req.score
    if req.word_count is not None:
        extra["word_count"] = req.word_count
    if req.title is not None:
        extra["title"] = req.title

    node = set_checkpoint(book_id, path, req.status, **extra)
    logger = get_logger(book_id)
    logger.done(".".join(path), f"checkpoint set: {req.status}")
    return CheckpointResponse(
        status="ok", book_id=book_id,
        checkpoint_path=path, checkpoint_status=node.get("status", req.status),
    )


@router.get("/{book_id}/checkpoints/get", response_model=CheckpointGetResponse,
            responses={404: {"model": ErrorResponse}})
def checkpoint_get(book_id: str, path: str = Query(..., description="逗号分隔的 checkpoint 路径，如 phase1,whitepaper")):
    parsed = path.split(",")
    node = get_checkpoint(book_id, parsed)
    return CheckpointGetResponse(book_id=book_id, checkpoint=node)


# ── Phase 1 专用 checkpoint 端点 ──────────────────────────

def _artifact_check(book_id: str, rel_path: str = "") -> bool:
    """检查产物文件是否存在"""
    if not rel_path:
        return True
    state = load_book_state(book_id)
    if not state:
        return False
    version = state.get("version", "v1")
    full_path = os.path.join(BOOKS_DIR, book_id, "versions", version, rel_path)
    return os.path.exists(full_path)


def _normalize_artifact(book_id, expected_rel_path, fallback_rel_path):
    # type: (str, str, str) -> Tuple[bool, Optional[str]]
    """检查产物文件存在，若文件在 fallback 目录则自动迁移到预期位置。

    返回 (found, normalized_rel_path)：
    - found=True 时，normalized_rel_path 始终返回 expected_rel_path
    - found=False 时，normalized_rel_path 为 None
    """
    state = load_book_state(book_id)
    if not state:
        return False, None
    version = state.get("version", "v1")
    ver_dir = os.path.join(BOOKS_DIR, book_id, "versions", version)

    expected = os.path.join(ver_dir, expected_rel_path)
    if os.path.exists(expected):
        return True, expected_rel_path

    fallback = os.path.join(ver_dir, fallback_rel_path)
    if os.path.exists(fallback):
        shutil.move(fallback, expected)
        get_logger(book_id).warn(book_id,
            f"文件从 {fallback_rel_path} 自动迁移到 {expected_rel_path}")
        return True, expected_rel_path

    return False, None


@router.post("/{book_id}/checkpoints/version-decided", response_model=CheckpointResponse)
def cp_version_decided(book_id: str, version: str = Query(..., regex=r"^v\d+$"),
                        platform: str = Query(default=""),
                        track: str = Query(default="")):
    state = ensure_book_state(book_id)
    state["version"] = version
    if platform:
        state["platform"] = platform
    if track:
        state["track"] = track
    save_book_state(book_id, state)
    set_checkpoint(book_id, ["phase1", "version_decided"], status="done")
    get_logger(book_id).done("[P1:ver]", f"版本号决策: {version}")
    return CheckpointResponse(status="ok", book_id=book_id, checkpoint_path=["phase1", "version_decided"], checkpoint_status="done")


@router.post("/{book_id}/checkpoints/whitepaper", response_model=CheckpointResponse)
def cp_whitepaper(book_id: str, path: str = Query(default="00-素材/base_whitepaper.md")):
    if not _artifact_check(book_id, path):
        raise HTTPException(400, f"Whitepaper not found: {path}")
    set_checkpoint(book_id, ["phase1", "whitepaper"], status="done", path=path)
    get_logger(book_id).done("[P1:a]", f"白皮书: {path}")
    return CheckpointResponse(status="ok", book_id=book_id, checkpoint_path=["phase1", "whitepaper"], checkpoint_status="done")


@router.post("/{book_id}/checkpoints/platform-rules", response_model=CheckpointResponse)
def cp_platform_rules(book_id: str, path: str = Query(default="00-素材/platform_rules.json")):
    if not _artifact_check(book_id, path):
        raise HTTPException(400, f"Platform rules not found: {path}")
    set_checkpoint(book_id, ["phase1", "platform_rules"], status="done", path=path)
    get_logger(book_id).done("[P1:b]", f"平台规则: {path}")
    return CheckpointResponse(status="ok", book_id=book_id, checkpoint_path=["phase1", "platform_rules"], checkpoint_status="done")


@router.post("/{book_id}/checkpoints/style-mapped", response_model=CheckpointResponse)
def cp_style_mapped(book_id: str, path: str = Query(default="00-素材/赛道映射.json")):
    if not _artifact_check(book_id, path):
        raise HTTPException(400, f"Style mapping not found: {path}")
    set_checkpoint(book_id, ["phase1", "style_mapped"], status="done", path=path)
    get_logger(book_id).done("[P1:c]", f"赛道映射: {path}")
    return CheckpointResponse(status="ok", book_id=book_id, checkpoint_path=["phase1", "style_mapped"], checkpoint_status="done")


@router.post("/{book_id}/checkpoints/facade", response_model=CheckpointResponse)
def cp_facade(book_id: str, path: str = Query(default="00-素材/门面候选.json")):
    if not _artifact_check(book_id, path):
        raise HTTPException(400, f"Facade not found: {path}")
    set_checkpoint(book_id, ["phase1", "facade"], status="done", path=path)
    get_logger(book_id).done("[P1:d]", f"门面候选: {path}")
    return CheckpointResponse(status="ok", book_id=book_id, checkpoint_path=["phase1", "facade"], checkpoint_status="done")


@router.post("/{book_id}/checkpoints/salt", response_model=CheckpointResponse)
def cp_salt(book_id: str, path: str = Query(default="project_salt.json")):
    found, normalized = _normalize_artifact(book_id, path, "00-素材/project_salt.json")
    if not found:
        raise HTTPException(400, f"Salt not found: {path}")
    set_checkpoint(book_id, ["phase1", "salt"], status="done", path=normalized)
    get_logger(book_id).done("[P1:e]", f"盐值: {normalized}")
    return CheckpointResponse(status="ok", book_id=book_id, checkpoint_path=["phase1", "salt"], checkpoint_status="done")


@router.post("/{book_id}/checkpoints/cover-prompt", response_model=CheckpointResponse)
def cp_cover_prompt(book_id: str, path: str = Query(default="00-素材/cover_prompt.json")):
    if not _artifact_check(book_id, path):
        raise HTTPException(400, f"Cover prompt not found: {path}")
    set_checkpoint(book_id, ["phase1", "cover_prompt"], status="done", path=path)
    get_logger(book_id).done("[P1:e2]", f"封面Prompt: {path}")
    return CheckpointResponse(status="ok", book_id=book_id, checkpoint_path=["phase1", "cover_prompt"], checkpoint_status="done")


@router.post("/{book_id}/checkpoints/cover-generated", response_model=CheckpointResponse)
def cp_cover_generated(book_id: str):
    state = load_book_state(book_id)
    if state is None:
        raise HTTPException(404, f"Book '{book_id}' not found")
    version = state.get("version", "v1")

    prompt_path = os.path.join(BOOKS_DIR, book_id, "versions", version, "00-素材", "cover_prompt.json")
    if not os.path.exists(prompt_path):
        raise HTTPException(400, f"cover_prompt.json not found at {prompt_path}")

    from services.cover_service import execute_generate_cover
    logger = get_logger(book_id)
    logger.info("[P1:e3]", "开始生成封面图")

    result = execute_generate_cover(book_id, {"version": version, "force": False})
    if result.get("success"):
        if result.get("skipped"):
            logger.done("[P1:e3]", "封面图已存在，跳过")
        else:
            logger.done("[P1:e3]", f"封面图生成成功: {result.get('cover_path', '')}")
        set_checkpoint(book_id, ["phase1", "cover_generated"], status="done", path="发布/cover.png")
        return CheckpointResponse(status="ok", book_id=book_id,
                                  checkpoint_path=["phase1", "cover_generated"], checkpoint_status="done")
    else:
        error = result.get("error", "unknown")
        logger.fail("[P1:e3]", "封面图生成", error)
        set_checkpoint(book_id, ["phase1", "cover_generated"], status="failed")
        raise HTTPException(500, f"Cover generation failed: {error}")


@router.post("/{book_id}/checkpoints/master-outline", response_model=CheckpointResponse)
def cp_master_outline(book_id: str, path: str = Query(default="仿写衍生总纲领.md")):
    found, normalized = _normalize_artifact(book_id, path, "00-素材/仿写衍生总纲领.md")
    if not found:
        raise HTTPException(400, f"Master outline not found: {path}")
    set_checkpoint(book_id, ["phase1", "master_outline"], status="done", path=normalized)
    get_logger(book_id).done("[P1:f]", f"仿写总纲: {normalized}")
    return CheckpointResponse(status="ok", book_id=book_id, checkpoint_path=["phase1", "master_outline"], checkpoint_status="done")


@router.post("/{book_id}/checkpoints/novel-metadata", response_model=NovelMetadataResponse)
def cp_novel_metadata(book_id: str, req: NovelMetadataCreateRequest):
    """创建 novel_metadata.json（全量 schema 校验）"""
    state = load_book_state(book_id)
    if state is None:
        raise HTTPException(404, f"Book '{book_id}' not found")
    version = state.get("version", "v1")

    publish_dir = os.path.join(BOOKS_DIR, book_id, "versions", version, "发布")
    os.makedirs(publish_dir, exist_ok=True)
    meta_path = os.path.join(publish_dir, "novel_metadata.json")

    data = {
        "title": req.title,
        "title_en": "",
        "source": {
            "title": req.source_title or book_id,
            "author": req.source_author or "原作者",
            "year": 2020,
            "public_domain": True,
        },
        "description": req.description,
        "description_en": "",
        "cover_image": "./cover.png",
        "cover_prompt": req.cover_prompt,
        "genre": req.genre,
        "genre_en": "",
        "tags": req.tags if isinstance(req.tags, list) else [],
        "track": req.track or "",
        "primary_category": req.primary_category or "",
        "word_count_target": req.word_count_target,
        "total_chapters": req.total_chapters,
        "chapters_completed": 0,
        "shadow_intensity": req.shadow_intensity,
        "protagonist": req.protagonist,
        "setting": req.setting,
        "chapter_names": [],
        "cover_generated_by": "",
        "cover_resolution": "",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    save_novel_metadata(book_id, version, data)

    set_checkpoint(book_id, ["phase1", "novel_metadata"], status="done",
                   path=f"发布/novel_metadata.json")
    get_logger(book_id).done("[P1:g2]", f"novel_metadata.json 创建完成 ({len(req.title)} 个书名)")
    return NovelMetadataResponse(book_id=book_id, path=f"versions/{version}/发布/novel_metadata.json")


@router.post("/{book_id}/checkpoints/agents-copied", response_model=CheckpointResponse)
def cp_agents_copied(book_id: str):
    state = load_book_state(book_id)
    if state is None:
        raise HTTPException(404, f"Book '{book_id}' not found")

    book_dir = os.path.join(BOOKS_DIR, book_id)
    chief_path = os.path.join(book_dir, ".opencode", "agents", "chief_editor.md")
    if not os.path.exists(chief_path):
        raise HTTPException(400, f"chief_editor.md not found at {chief_path}")

    set_checkpoint(book_id, ["phase1", "agents_copied"], status="done")
    get_logger(book_id).done("[P1:h]", "agents 复制完成")
    return CheckpointResponse(status="ok", book_id=book_id,
                              checkpoint_path=["phase1", "agents_copied"], checkpoint_status="done")


@router.post("/{book_id}/checkpoints/phase1-done", response_model=PhaseVerifyResponse)
def cp_phase1_done(book_id: str):
    ok, reason = try_set_phase(book_id, "phase1_done")
    logger = get_logger(book_id)
    if ok:
        logger.done("[P1:done]", "Phase 1 完成")
    else:
        logger.fail("[P1:done]", "Phase 1 完成确认", reason)
    return PhaseVerifyResponse(book_id=book_id, can_set=ok, reason=reason)


# ── Phase 2 专用 checkpoint 端点 ──────────────────────────

@router.post("/{book_id}/checkpoints/destiny-global", response_model=CheckpointResponse)
def cp_destiny_global(book_id: str, volume: int = Query(..., ge=1)):
    """全局命运设计完成"""
    state = load_book_state(book_id)
    if state is None:
        raise HTTPException(404, f"Book '{book_id}' not found")
    version = state.get("version", "v1")

    god_eye = os.path.join(BOOKS_DIR, book_id, "versions", version, "上帝之眼")
    checks = [
        os.path.join(god_eye, "00-全书命运总谱.md"),
        os.path.join(god_eye, "01-人物命运谱"),
        os.path.join(god_eye, "03-伏笔命运谱", "全书伏笔网络.md"),
        os.path.join(god_eye, "04-世界观展开谱", "世界观展开节奏.md"),
    ]
    for c in checks:
        if not os.path.exists(c):
            raise HTTPException(400, f"Destiny artifact missing: {c}")

    vol_key = f"volume_{volume}"
    set_checkpoint(book_id, ["phase2", vol_key, "destiny_global"], status="done")
    get_logger(book_id).done(f"[P2:v{volume}:dg]", "全局命运设计完成")
    return CheckpointResponse(status="ok", book_id=book_id,
                              checkpoint_path=["phase2", vol_key, "destiny_global"],
                              checkpoint_status="done")


@router.post("/{book_id}/checkpoints/destiny-volume", response_model=CheckpointResponse)
def cp_destiny_volume(book_id: str, volume: int = Query(..., ge=1)):
    """本卷命运设计完成"""
    state = load_book_state(book_id)
    if state is None:
        raise HTTPException(404, f"Book '{book_id}' not found")
    version = state.get("version", "v1")

    god_eye = os.path.join(BOOKS_DIR, book_id, "versions", version, "上帝之眼")
    vol_pad = f"{volume:02d}"
    checks = [
        os.path.join(god_eye, "02-剧情命运谱", f"卷{vol_pad}-剧情.md"),
        os.path.join(god_eye, "05-卷级注入", f"卷{vol_pad}-注入包.md"),
    ]
    for c in checks:
        if not os.path.exists(c):
            raise HTTPException(400, f"Volume destiny artifact missing: {c}")

    vol_key = f"volume_{volume}"
    injection_path = f"上帝之眼/05-卷级注入/卷{vol_pad}-注入包.md"
    set_checkpoint(book_id, ["phase2", vol_key, "destiny_volume"], status="done",
                   injection_path=injection_path)
    get_logger(book_id).done(f"[P2:v{volume}:dv]", f"卷{volume}命运设计完成")
    return CheckpointResponse(status="ok", book_id=book_id,
                              checkpoint_path=["phase2", vol_key, "destiny_volume"],
                              checkpoint_status="done")


@router.post("/{book_id}/checkpoints/volume-outline", response_model=CheckpointResponse)
def cp_volume_outline(book_id: str, volume: int = Query(..., ge=1),
                      path: str = Query(default="")):
    """卷纲规划完成"""
    state = load_book_state(book_id)
    if state is None:
        raise HTTPException(404, f"Book '{book_id}' not found")
    version = state.get("version", "v1")

    expected_path = path or f"01-大纲/01-卷纲/卷纲-第{volume}卷.md"
    full_path = os.path.join(BOOKS_DIR, book_id, "versions", version, expected_path)
    if not os.path.exists(full_path):
        raise HTTPException(400, f"Volume outline not found: {expected_path}")

    vol_key = f"volume_{volume}"
    set_checkpoint(book_id, ["phase2", vol_key, "volume_outline"], status="done",
                   path=expected_path)
    get_logger(book_id).done(f"[P2:v{volume}:ol]", f"卷纲: {expected_path}")
    return CheckpointResponse(status="ok", book_id=book_id,
                              checkpoint_path=["phase2", vol_key, "volume_outline"],
                              checkpoint_status="done")


@router.post("/{book_id}/checkpoints/chapter-outline", response_model=CheckpointResponse)
def cp_chapter_outline(book_id: str, volume: int = Query(..., ge=1),
                       chapter: int = Query(..., ge=1)):
    """章纲生成完成"""
    state = load_book_state(book_id)
    if state is None:
        raise HTTPException(404)
    version = state.get("version", "v1")
    outline_path = os.path.join(BOOKS_DIR, book_id, "versions", version,
                                "01-大纲", f"第{chapter}章章纲.md")
    if not os.path.exists(outline_path):
        raise HTTPException(400, f"Chapter outline not found: 第{chapter}章章纲.md")

    vol_key = f"volume_{volume}"
    set_checkpoint(book_id, ["phase2", vol_key, "chapters", str(chapter), "outline"],
                   status="done")
    get_logger(book_id).done(f"[P2:v{volume}:ch{chapter}:ol]", "章纲完成")
    return CheckpointResponse(status="ok", book_id=book_id,
                              checkpoint_path=["phase2", vol_key, "chapters", str(chapter), "outline"],
                              checkpoint_status="done")


@router.post("/{book_id}/checkpoints/chapter-draft", response_model=CheckpointResponse)
def cp_chapter_draft(book_id: str, volume: int = Query(..., ge=1),
                     chapter: int = Query(..., ge=1)):
    """正文初稿完成"""
    state = load_book_state(book_id)
    if state is None:
        raise HTTPException(404)
    version = state.get("version", "v1")
    draft_path = os.path.join(BOOKS_DIR, book_id, "versions", version,
                              "02-正文", f"第{chapter}章-初稿-v1.md")
    if not os.path.exists(draft_path):
        raise HTTPException(400, f"Draft not found: 第{chapter}章-初稿-v1.md")

    vol_key = f"volume_{volume}"
    set_checkpoint(book_id, ["phase2", vol_key, "chapters", str(chapter), "draft"],
                   status="done")
    get_logger(book_id).done(f"[P2:v{volume}:ch{chapter}:draft]", "初稿完成")
    return CheckpointResponse(status="ok", book_id=book_id,
                              checkpoint_path=["phase2", vol_key, "chapters", str(chapter), "draft"],
                              checkpoint_status="done")


@router.post("/{book_id}/checkpoints/chapter-compliance", response_model=CheckpointResponse)
def cp_chapter_compliance(book_id: str, volume: int = Query(..., ge=1),
                          chapter: int = Query(..., ge=1)):
    """合规审查完成"""
    state = load_book_state(book_id)
    if state is None:
        raise HTTPException(404)
    version = state.get("version", "v1")
    compliance_dir = os.path.join(BOOKS_DIR, book_id, "versions", version, "03-纪要")
    if not os.path.isdir(compliance_dir):
        raise HTTPException(400, "03-纪要/ directory not found")

    found = False
    for fname in os.listdir(compliance_dir):
        if fname.startswith(f"第{chapter}章合规审查-"):
            found = True
            break
    if not found:
        raise HTTPException(400, f"Compliance report not found for chapter {chapter}")

    vol_key = f"volume_{volume}"
    set_checkpoint(book_id, ["phase2", vol_key, "chapters", str(chapter), "compliance"],
                   status="done")
    get_logger(book_id).done(f"[P2:v{volume}:ch{chapter}:cmp]", "合规审查完成")
    return CheckpointResponse(status="ok", book_id=book_id,
                              checkpoint_path=["phase2", vol_key, "chapters", str(chapter), "compliance"],
                              checkpoint_status="done")


@router.post("/{book_id}/checkpoints/chapter-quality", response_model=CheckpointResponse)
def cp_chapter_quality(book_id: str, volume: int = Query(..., ge=1),
                       chapter: int = Query(..., ge=1),
                       score: float = Query(..., ge=0.0, le=100.0)):
    """质检评分完成"""
    state = load_book_state(book_id)
    if state is None:
        raise HTTPException(404)
    version = state.get("version", "v1")
    review_path = os.path.join(BOOKS_DIR, book_id, "versions", version,
                               "03-纪要", f"第{chapter}章纪要.md")
    if not os.path.exists(review_path):
        raise HTTPException(400, f"Quality review not found: 第{chapter}章纪要.md")

    vol_key = f"volume_{volume}"
    set_checkpoint(book_id, ["phase2", vol_key, "chapters", str(chapter), "quality"],
                   status="done", score=score)
    get_logger(book_id).done(f"[P2:v{volume}:ch{chapter}:qa]", f"质检完成 ({score}分)")
    return CheckpointResponse(status="ok", book_id=book_id,
                              checkpoint_path=["phase2", vol_key, "chapters", str(chapter), "quality"],
                              checkpoint_status="done")


@router.post("/{book_id}/checkpoints/chapter-finalized", response_model=CheckpointResponse)
def cp_chapter_finalized(book_id: str, volume: int = Query(..., ge=1),
                         chapter: int = Query(..., ge=1),
                         word_count: int = Query(..., ge=0),
                         title: str = Query(..., min_length=1),
                         score: float = Query(default=0.0, ge=0.0, le=100.0)):
    """章节终稿确认 — 验证所有前置步骤 + 同步 novel_metadata.json"""
    state = load_book_state(book_id)
    if state is None:
        raise HTTPException(404, f"Book '{book_id}' not found")
    version = state.get("version", "v1")

    vol_key = f"volume_{volume}"
    ch_key = str(chapter)

    prerequisites = [
        (["phase2", vol_key, "chapters", ch_key, "outline"], "outline"),
        (["phase2", vol_key, "chapters", ch_key, "draft"], "draft"),
        (["phase2", vol_key, "chapters", ch_key, "compliance"], "compliance"),
        (["phase2", vol_key, "chapters", ch_key, "quality"], "quality"),
    ]
    for ck_path, label in prerequisites:
        if not is_checkpoint_done(book_id, ck_path):
            raise HTTPException(400, f"Cannot finalize: '{label}' checkpoint not done")

    final_path = os.path.join(BOOKS_DIR, book_id, "versions", version,
                              "02-正文", f"第{chapter}章-终稿.md")
    if not os.path.exists(final_path):
        raise HTTPException(400, f"Final draft file not found: 第{chapter}章-终稿.md")

    set_checkpoint(book_id, ["phase2", vol_key, "chapters", ch_key, "finalized"],
                   status="done", word_count=word_count, title=title, score=score)

    _sync_chapter_name_to_metadata(book_id, version, chapter, title)

    logger = get_logger(book_id)
    logger.done(f"[P2:v{volume}:ch{chapter}:fin]",
                f"终稿确认 ({word_count}字, {score}分, 标题={title})")
    return CheckpointResponse(status="ok", book_id=book_id,
                              checkpoint_path=["phase2", vol_key, "chapters", ch_key, "finalized"],
                              checkpoint_status="done")


# ── 章节名校验 ────────────────────────────────────────────

_CN_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")


def _has_punctuation(name: str) -> bool:
    """检查是否含标点符号（Unicode P* 类别 + ASCII 标点）。"""
    for ch in name:
        cat = unicodedata.category(ch)
        if cat.startswith("P"):
            return True
        if ord(ch) < 128 and not ch.isalnum() and ch != " ":
            return True
    return False


def _validate_chapter_name(name: str, book_id: str, version: str, current_chapter: int) -> tuple:
    """校验章节名。返回 (valid: bool, errors: list)。"""
    errors = []
    cjk_chars = _CN_CHAR_RE.findall(name)
    if len(cjk_chars) > 10:
        errors.append("too_long")
    if _has_punctuation(name):
        errors.append("has_symbols")

    # 重名检测：仅比较 novel_metadata.json 的 chapter_names（忽略空字符串和当前章位置）
    meta = load_novel_metadata(book_id, version)
    if meta:
        chapter_names = meta.get("chapter_names", [])
        for i, existing in enumerate(chapter_names):
            if not existing or not existing.strip():
                continue
            if i == current_chapter - 1:
                continue
            if existing.strip() == name.strip():
                errors.append("duplicate")
                break

    return (len(errors) == 0, errors)


@router.get("/{book_id}/checkpoints/validate-chapter-name", response_model=ChapterNameValidateResponse)
def validate_chapter_name(book_id: str,
                          chapter: int = Query(..., ge=1, description="章节号"),
                          name: str = Query(..., min_length=1, description="待校验章节名")):
    """校验章节名：字符数 ≤10 中文字符、无标点、不重名。"""
    state = load_book_state(book_id)
    if state is None:
        raise HTTPException(404, f"Book '{book_id}' not found")
    version = state.get("version", "v1")

    valid, errors = _validate_chapter_name(name, book_id, version, chapter)
    return ChapterNameValidateResponse(valid=valid, name=name, errors=errors)


def _sync_chapter_name_to_metadata(book_id: str, version: str, chapter: int, title: str):
    """同步章节名到 novel_metadata.json（HMAC 签名保护）。

    v8: 同时维护 chapters 字典（扩展格式），记录 title_source 标识。
    """
    meta = load_novel_metadata(book_id, version)
    if meta is None:
        return

    # chapter_names 数组（兼容旧格式）
    names = meta.get("chapter_names", [])
    while len(names) < chapter:
        names.append("")
    names[chapter - 1] = title
    meta["chapter_names"] = names
    meta["chapters_completed"] = chapter

    # chapters 字典（v8 扩展格式，含 title_source）
    _DEFAULT_TITLE_RE = re.compile(r"^第\d+章[-_]?(初稿|终稿)(-v\d+)?$")
    chapters = meta.get("chapters", {})
    ch_key = str(chapter)
    if ch_key not in chapters:
        chapters[ch_key] = {}
    chapters[ch_key]["title"] = title
    if _DEFAULT_TITLE_RE.match(title.strip()):
        chapters[ch_key]["title_source"] = "generated"
    else:
        chapters[ch_key]["title_source"] = "agent"
    meta["chapters"] = chapters

    save_novel_metadata(book_id, version, meta)


@router.post("/{book_id}/checkpoints/volume-archived", response_model=CheckpointResponse)
def cp_volume_archived(book_id: str, volume: int = Query(..., ge=1)):
    """卷归档 — 验证本卷所有章 finalized"""
    state = load_book_state(book_id)
    if state is None:
        raise HTTPException(404)
    vol_key = f"volume_{volume}"
    vol_data = state.get("checkpoints", {}).get("phase2", {}).get(vol_key, {})
    chapters = vol_data.get("chapters", {})

    for ch_key, ch_data in chapters.items():
        if ch_data.get("finalized", {}).get("status") != "done":
            raise HTTPException(400, f"Cannot archive: chapter {ch_key} not finalized")

    set_checkpoint(book_id, ["phase2", vol_key, "volume_archived"], status="done")
    get_logger(book_id).done(f"[P2:v{volume}:arc]", f"卷{volume}归档完成 ({len(chapters)}章)")
    return CheckpointResponse(status="ok", book_id=book_id,
                              checkpoint_path=["phase2", vol_key, "volume_archived"],
                              checkpoint_status="done")


@router.post("/{book_id}/checkpoints/phase2-done", response_model=PhaseVerifyResponse)
def cp_phase2_done(book_id: str):
    ok, reason = try_set_phase(book_id, "phase2_done")
    logger = get_logger(book_id)
    if ok:
        logger.done("[P2:done]", "Phase 2 完成")
    else:
        logger.fail("[P2:done]", "Phase 2 完成确认", reason)
    return PhaseVerifyResponse(book_id=book_id, can_set=ok, reason=reason)


# ── 断点续跑 ──────────────────────────────────────────────

@router.get("/{book_id}/next-action", response_model=NextActionResponse)
def get_next_action(book_id: str):
    action = find_next_action(book_id)
    return NextActionResponse(**action)


@router.post("/{book_id}/verify-phase", response_model=PhaseVerifyResponse)
def verify_phase(book_id: str, req: PhaseVerifyRequest):
    ok, reason = can_set_phase(book_id, req.target_phase)
    return PhaseVerifyResponse(book_id=book_id, can_set=ok, reason=reason)


@router.post("/{book_id}/try-set-phase", response_model=PhaseVerifyResponse)
def try_set_phase_endpoint(book_id: str, req: PhaseVerifyRequest):
    ok, reason = try_set_phase(book_id, req.target_phase)
    return PhaseVerifyResponse(book_id=book_id, can_set=ok, reason=reason)


# ── 进度总览 ──────────────────────────────────────────────

@router.get("/{book_id}/progress", response_model=dict)
def get_progress(book_id: str):
    state = load_book_state(book_id)
    if state is None:
        raise HTTPException(404, f"Book '{book_id}' not found")
    action = find_next_action(book_id)
    return {
        "book_id": book_id,
        "phase": state.get("phase"),
        "checkpoints": state.get("checkpoints", {}),
        "next_action": action,
    }
