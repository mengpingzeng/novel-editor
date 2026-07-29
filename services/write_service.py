"""
Phase 2 write service — v5 纯净版

使用 checkpoints 驱动写章流程。不自动设 checkpoint（由 agent 完成后 pipeline 调用 API 落盘）。
"""

import os
import re
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import config
from services.book_state import (
    load_book_state,
    ensure_book_state,
    get_next_chapter,
    set_checkpoint,
    is_checkpoint_done,
    try_set_phase,
    phase_ge,
    populate_volumes_from_god_eye,
    save_book_state,
    BOOKS_DIR,
    load_novel_metadata,
    save_novel_metadata,
)
from services.log_service import get_logger

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_DEFAULT_TITLE_RE = re.compile(r"^第\d+章[-_]?(初稿|终稿)(-v\d+)?$")
_CHAPTER_PREFIX_RE = re.compile(r"^第\d+章\s*")


def write_chapters(book_id: str, chapters: int = 1) -> str:
    from worker.task_queue import task_queue as tq
    existing = tq.find_active_task("write", book_id)
    if existing:
        return existing
    return tq.submit("write", book_id, {"chapters": chapters})


def execute_write(book_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
    chapters_to_write = params.get("chapters", 1)
    task_id = params.get("task_id")
    logger = get_logger(book_id)

    state = ensure_book_state(book_id)
    if state is None:
        return {"success": False, "error": f"Book not found: {book_id}"}

    book_phase = state.get("phase", "pending")
    if not phase_ge(book_phase, "phase1_done"):
        return {"success": False,
                "error": f"Book not registered yet (phase={book_phase}). Register first."}

    book_dir = os.path.join(BOOKS_DIR, book_id)
    version = state.get("version", "v1")

    # Phase 2 初始化：volumes 为空表示命运设计/卷纲从未生成
    if not state.get("volumes"):
        logger.info("[P2:init]", "volumes 为空，触发 Phase 2 初始化")
        init_result = _init_phase2(book_id, version, book_dir, logger)
        if not init_result.get("success"):
            return init_result
        for chk_path_tuple, chk_data in init_result.get("checkpoints", {}).items():
            set_checkpoint(book_id, list(chk_path_tuple), status="done", **chk_data)
        state = load_book_state(book_id)

    written = 0
    written_chapters = []

    for _ in range(chapters_to_write):
        next_ch = get_next_chapter(book_id)
        if next_ch is None:
            break

        global_chapter = next_ch["global_chapter"]
        volume = next_ch["volume"]
        resume_step = next_ch.get("resume_step", "outline")
        vol_key = f"volume_{volume}"
        ch_key = str(global_chapter)

        if is_checkpoint_done(book_id, ["phase2", vol_key, "chapters", ch_key, "finalized"]) \
                and is_checkpoint_done(book_id, ["phase2", vol_key, "chapters", ch_key, "chapter_name"]):
            logger.skip(f"[P2:v{volume}:ch{global_chapter}]", "已终稿")
            continue

        logger.info(f"[P2:v{volume}:ch{global_chapter}]",
                     f"从 {resume_step} 步骤恢复" if resume_step != "outline" else "开始生产")

        if not _ensure_volume_resources(book_id, volume, version, logger):
            return {"success": False, "chapters_written": written,
                    "written_chapters": written_chapters,
                    "error": f"Volume {volume} resources failed for chapter {global_chapter}"}

        command = f"执行第{volume}卷第{global_chapter}章生产"
        max_retries = state.get("retry_policy", {}).get(
            "chapter_max_retries", config.chapter_max_retries)
        retries = 0
        chapter_ok = False

        while retries < max_retries:
            if task_id:
                from worker.task_queue import task_queue
                task_queue._update_task(task_id, result={
                    "chapter": global_chapter,
                    "attempt": retries + 1,
                    "max_attempts": max_retries,
                    "phase": "writing",
                })
            try:
                logger.info(f"[P2:v{volume}:ch{global_chapter}]",
                           f"第{retries + 1}次尝试")
                result = subprocess.run(
                    ["timeout", str(config.chapter_timeout),
                     "opencode", "run", "--dangerously-skip-permissions",
                     "--dir", book_dir,
                     "--agent", "chief_editor",
                     command],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                )

                ver_dir = os.path.join(book_dir, "versions", version)
                ch_final = os.path.join(ver_dir, "02-正文", f"第{global_chapter}章-终稿.md")

                if result.returncode == 0:
                    ckp = ["phase2", vol_key, "chapters", ch_key]

                    # agent 执行完毕后，由 pipeline 自行检查产物文件并落盘所有 checkpoint
                    ch_outline = os.path.join(ver_dir, "01-大纲", f"第{global_chapter}章章纲.md")
                    if os.path.exists(ch_outline):
                        set_checkpoint(book_id, ckp + ["outline"], status="done")

                    ch_draft = os.path.join(ver_dir, "02-正文", f"第{global_chapter}章-初稿-v1.md")
                    if os.path.exists(ch_draft):
                        set_checkpoint(book_id, ckp + ["draft"], status="done")

                    compliance_dir = os.path.join(ver_dir, "03-纪要")
                    if os.path.isdir(compliance_dir):
                        for fname in os.listdir(compliance_dir):
                            if fname.startswith(f"第{global_chapter}章合规审查-"):
                                set_checkpoint(book_id, ckp + ["compliance"], status="done")
                                break

                    review_path = os.path.join(ver_dir, "03-纪要", f"第{global_chapter}章纪要.md")
                    if os.path.exists(review_path):
                        set_checkpoint(book_id, ckp + ["quality"], status="done")

                    if os.path.exists(ch_final):
                        word_count = _count_words(ch_final)
                        title = _resolve_chapter_title(ch_final, book_dir, version, global_chapter)
                        gen_title = _get_fallback_title(book_dir, version, global_chapter)
                        if gen_title:
                            _sync_title_to_draft(ch_final, book_dir, version, global_chapter, gen_title)
                        set_checkpoint(book_id, ckp + ["finalized"],
                                       status="done", word_count=word_count, title=title)
                        set_checkpoint(book_id, ckp + ["chapter_name"],
                                       status="done", title=title)
                        _sync_chapter_name_to_metadata(book_id, version, global_chapter, title)
                        logger.done(f"[P2:v{volume}:ch{global_chapter}:fin]",
                                    f"终稿确认 ({word_count}字, {title})")
                        written += 1
                        written_chapters.append({"global_chapter": global_chapter, "volume": volume})
                        chapter_ok = True
                        break
                    else:
                        retries += 1
                        logger.warn(f"[P2:v{volume}:ch{global_chapter}]",
                                    f"agent exited 0 but 终稿 not found (retry {retries}/{max_retries})")
                elif result.returncode == 124:
                    retries += 1
                    logger.warn(f"[P2:v{volume}:ch{global_chapter}]",
                                f"超时 (retry {retries}/{max_retries})")
                else:
                    retries += 1
                    logger.warn(f"[P2:v{volume}:ch{global_chapter}]",
                                f"执行失败 exit={result.returncode} (retry {retries}/{max_retries})")

            except FileNotFoundError:
                return {"success": False, "error": "timeout or opencode command not found on PATH"}

        if not chapter_ok:
            logger.fail(f"[P2:v{volume}:ch{global_chapter}]",
                        f"第{global_chapter}章",
                        f"Failed after {max_retries} retries")
            return {"success": False, "chapters_written": written,
                    "written_chapters": written_chapters,
                    "error": f"Chapter {global_chapter} failed after {max_retries} retries"}

    if written == 0:
        return {"success": True, "chapters_written": 0,
                "written_chapters": [],
                "message": "All chapters already completed"}

    ok, reason = try_set_phase(book_id, "phase2_done")
    if ok:
        logger.done("[P2:done]", "Phase 2 完成")
    else:
        logger.info("[P2:done]", f"Phase 2 未全部完成: {reason}")

    return {"success": True, "chapters_written": written,
            "written_chapters": written_chapters}


def _ensure_volume_resources(book_id: str, volume: int, version: str, logger) -> bool:
    vol_key = f"volume_{volume}"

    if is_checkpoint_done(book_id, ["phase2", vol_key, "volume_outline"]):
        return True

    book_dir = os.path.join(BOOKS_DIR, book_id)
    ver_dir = os.path.join(book_dir, "versions", version)
    vol_outline = os.path.join(ver_dir, "01-大纲", "01-卷纲", f"卷纲-第{volume}卷.md")

    if os.path.exists(vol_outline):
        return True

    prompt = f"初始化第{volume}卷卷纲" if volume > 1 else "初始化项目并生成第1卷卷纲"
    timeout = config.phase1_timeout if volume == 1 else config.chapter_timeout
    max_retries = config.chapter_max_retries

    for attempt in range(max_retries):
        try:
            subprocess.run(
                ["timeout", str(timeout),
                 "opencode", "run", "--dangerously-skip-permissions",
                 "--dir", book_dir,
                 "--agent", "chief_editor",
                 prompt],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            )
        except FileNotFoundError:
            return False

        if os.path.exists(vol_outline):
            return True

    return False


def _count_words(path: str) -> int:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return len(re.sub(r"\s+", "", f.read()))
    except Exception:
        return 0


def _is_default_title(title: str) -> bool:
    """判断是否为默认占位标题（第N章-终稿 / 第N章-初稿）"""
    if not title:
        return True
    return bool(_DEFAULT_TITLE_RE.match(title.strip()))


def _extract_title(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("# "):
                    title = line[2:].strip()
                    title = _CHAPTER_PREFIX_RE.sub("", title)
                    return title
        return os.path.basename(path).replace(".md", "")
    except Exception:
        return ""


def _get_fallback_title(book_dir: str, version: str, chapter: int) -> Optional[str]:
    """从 gen 文件读取章节名生成器产出的标题。"""
    gen_path = os.path.join(book_dir, "versions", version,
                            "02-正文", f"第{chapter}章-章节名-gen.txt")
    if not os.path.exists(gen_path):
        return None
    try:
        with open(gen_path, "r", encoding="utf-8") as f:
            title = f.read().strip()
        if title and not _is_default_title(title):
            return title
    except Exception:
        pass
    return None


def _resolve_chapter_title(ch_final: str, book_dir: str, version: str, chapter: int) -> str:
    """解析章节标题：gen 文件第一优先级 → # 首行兜底 → 文件名 fallback。"""
    gen_title = _get_fallback_title(book_dir, version, chapter)
    if gen_title:
        return gen_title
    return _extract_title(ch_final)


def _sync_title_to_draft(ch_final: str, book_dir: str, version: str, chapter: int, gen_title: str):
    """用 gen 文件内容更新终稿 # 首行：有则替换，无则插入。"""
    if not os.path.exists(ch_final) or not gen_title:
        return
    try:
        with open(ch_final, "r", encoding="utf-8") as f:
            lines = f.readlines()

        title_line = f"# 第{chapter}章 {gen_title}\n"
        if lines and lines[0].startswith("# "):
            lines[0] = title_line
        else:
            lines.insert(0, title_line)

        with open(ch_final, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception:
        pass


def _init_phase2(book_id: str, version: str, book_dir: str, logger) -> Dict[str, Any]:
    """Phase 2 初始化：生成命运设计 + 卷纲，解析 volumes 写入 book_state.json。
    返回 {"success": bool, "checkpoints": {...}} 或 {"success": False, "error": "..."}
    """
    ver_dir = os.path.join(book_dir, "versions", version)
    god_eye_dir = os.path.join(ver_dir, "上帝之眼")
    fate_path = os.path.join(god_eye_dir, "00-全书命运总谱.md")
    vol_outline = os.path.join(ver_dir, "01-大纲", "01-卷纲", "卷纲-第1卷.md")
    inject_file = os.path.join(god_eye_dir, "05-卷级注入", "卷01-注入包.md")

    # 检查产物是否已存在（可能之前初始化中断）
    if os.path.exists(fate_path) and os.path.exists(vol_outline):
        logger.info("[P2:init]", "God's Eye + 卷纲已存在，解析 volumes")
        state = load_book_state(book_id)
        result = populate_volumes_from_god_eye(state, book_id)
        if result:
            save_book_state(book_id, state)
            _sync_metadata_total_chapters(book_id, version, result["total_chapters"])
            logger.done("[P2:init]", f"volumes 已填充: {result['total_volumes']}卷/{result['total_chapters']}章")
            return {
                "success": True,
                "checkpoints": {
                    ("phase2", "volume_1", "destiny_global"): {},
                    ("phase2", "volume_1", "destiny_volume"): {"injection_path": "上帝之眼/05-卷级注入/卷01-注入包.md"},
                    ("phase2", "volume_1", "volume_outline"): {"path": "01-大纲/01-卷纲/卷纲-第1卷.md"},
                }
            }
        else:
            logger.fail("[P2:init]", "God's Eye 解析", "表格解析失败，请检查 00-全书命运总谱.md �七 格式")
            return {"success": False, "error": "God's Eye table parsing failed"}

    # 启动 chief_editor 生成命运设计 + 卷纲
    logger.info("[P2:init]", "启动 chief_editor 生成命运设计 + 卷纲")
    prompt = "初始化项目并生成第1卷卷纲"
    timeout = config.phase1_timeout
    max_retries = config.chapter_max_retries

    for attempt in range(max_retries):
        try:
            subprocess.run(
                ["timeout", str(timeout),
                 "opencode", "run", "--dangerously-skip-permissions",
                 "--dir", book_dir,
                 "--agent", "chief_editor",
                 prompt],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            )
        except FileNotFoundError:
            return {"success": False, "error": "opencode command not found on PATH"}

        # 验证产物
        if os.path.exists(fate_path) and os.path.exists(vol_outline):
            state = load_book_state(book_id)
            result = populate_volumes_from_god_eye(state, book_id)
            if result:
                save_book_state(book_id, state)
                _sync_metadata_total_chapters(book_id, version, result["total_chapters"])
                logger.done("[P2:init]", f"Phase 2 初始化完成: {result['total_volumes']}卷/{result['total_chapters']}章")
                return {
                    "success": True,
                    "checkpoints": {
                        ("phase2", "volume_1", "destiny_global"): {},
                        ("phase2", "volume_1", "destiny_volume"): {"injection_path": "上帝之眼/05-卷级注入/卷01-注入包.md"},
                        ("phase2", "volume_1", "volume_outline"): {"path": "01-大纲/01-卷纲/卷纲-第1卷.md"},
                    }
                }
            else:
                logger.fail("[P2:init]", "God's Eye 解析", "表格解析失败")
                return {"success": False,
                        "error": "God's Eye generated but volume table parsing failed"}

        logger.warn("[P2:init]", f"初始化尝试 {attempt + 1}/{max_retries} 失败")

    missing = []
    if not os.path.exists(fate_path):
        missing.append("00-全书命运总谱.md")
    if not os.path.exists(vol_outline):
        missing.append("卷纲-第1卷.md")
    return {"success": False,
            "error": f"Phase 2 init failed after {max_retries} retries. Missing: {', '.join(missing)}"}


def _sync_metadata_total_chapters(book_id: str, version: str, total_chapters: int):
    """将 God's Eye 解析出的 total_chapters 同步到 novel_metadata.json"""
    meta = load_novel_metadata(book_id, version)
    if meta is None:
        return
    meta["total_chapters"] = total_chapters
    save_novel_metadata(book_id, version, meta)


def _sync_chapter_name_to_metadata(book_id: str, version: str, chapter: int, title: str):
    """每章完成后同步章节名到 novel_metadata.json（HMAC 签名保护）。

    v8: 同时维护 chapters 字典（扩展格式），记录 title_source 标识。
        title_source 取值：
        - "agent"：     content_writer 直接产出正确的 # 标题
        - "generated"： chapter_name_generator 兜底生成
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
    chapters = meta.get("chapters", {})
    ch_key = str(chapter)
    if ch_key not in chapters:
        chapters[ch_key] = {}
    chapters[ch_key]["title"] = title

    # 判断 title_source：检查 gen 文件是否存在
    book_dir = os.path.join(BOOKS_DIR, book_id)
    gen_path = os.path.join(book_dir, "versions", version,
                            "02-正文", f"第{chapter}章-章节名-gen.txt")
    if _is_default_title(title) or os.path.exists(gen_path):
        chapters[ch_key]["title_source"] = "generated"
    else:
        chapters[ch_key]["title_source"] = "agent"
    meta["chapters"] = chapters

    save_novel_metadata(book_id, version, meta)
