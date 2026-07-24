"""
Phase 2 write service — orchestrates chapter writing via chief_editor agent.

Mirrors shell's run_phase2_full / validation-mode chapter loop:
- Chapter failure causes immediate exit (chapters are strictly serial; Ch N depends on Ch N-1).
- On success, writes .phase2_done marker and advances phase in book_state.json.
- _ensure_volume_resources returns a boolean; errors are not silently swallowed.
- Before writing a chapter, checks if the final draft already exists on disk (safety net).
"""

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import config
from services.status_service import normalize_chapter_names, _is_default_title
from services.book_state import (
    load_book_state,
    ensure_book_state,
    get_next_chapter,
    update_chapter,
    save_book_state,
    phase_ge,
)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS_DIR = os.path.join(ROOT_DIR, "workspace", "books")


def write_chapters(book_id: str, chapters: int = 1) -> str:
    from worker.task_queue import task_queue as tq
    return tq.submit("write", book_id, {
        "chapters": chapters,
    })


def _repair_metadata_chapter_names(book_id, version, state):
    chapters = state.get("chapters", {})
    completed = sum(1 for v in chapters.values() if v.get("status") == "completed")
    if completed == 0:
        return

    meta_path = os.path.join(BOOKS_DIR, book_id, "versions", version, "发布", "novel_metadata.json")
    if not os.path.exists(meta_path):
        return

    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        return

    raw_names = meta.get("chapter_names", [])
    normalized = normalize_chapter_names(raw_names, completed)

    for k in sorted(chapters.keys(), key=int):
        idx = int(k) - 1
        if idx < len(normalized) and normalized[idx]:
            continue
        ch = chapters.get(k, {})
        title = ch.get("title", "")
        if title and not _is_default_title(title):
            while len(normalized) <= idx:
                normalized.append("")
            normalized[idx] = title

    meta["chapter_names"] = normalized
    meta["chapters_completed"] = completed
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def execute_write(book_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
    chapters_to_write = params.get("chapters", 1)
    task_id = params.get("task_id")

    state = ensure_book_state(book_id)
    if state is None:
        return {"success": False, "error": f"Book not found: {book_id}"}

    book_phase = state.get("phase", "pending")
    if not phase_ge(book_phase, "phase1_done"):
        return {"success": False,
                "error": f"Book not registered yet (phase={book_phase}). Register first."}

    book_dir = os.path.join(BOOKS_DIR, book_id)
    version = state.get("version", "v1")

    _repair_metadata_chapter_names(book_id, version, state)

    written = 0
    written_chapters = []

    for _ in range(chapters_to_write):
        next_ch = get_next_chapter(book_id)
        if next_ch is None:
            break

        global_chapter = next_ch["global_chapter"]
        volume = next_ch["volume"]

        ch_final = os.path.join(
            book_dir, "versions", version,
            "02-正文", f"第{global_chapter}章-终稿.md"
        )

        if os.path.exists(ch_final):
            word_count = _count_words(ch_final)
            title = _extract_title(ch_final)
            update_chapter(book_id, global_chapter,
                           status="completed", retries=0,
                           word_count=word_count, title=title,
                           volume=volume)
            written += 1
            written_chapters.append({"global_chapter": global_chapter, "volume": volume})
            continue

        if not _ensure_volume_resources(book_id, volume, version):
            return {"success": False, "chapters_written": written,
                    "written_chapters": written_chapters,
                    "error": f"Failed to generate volume {volume} resources for chapter {global_chapter}"}

        command = f"执行第{volume}卷第{global_chapter}章生产"

        max_retries = state.get("retry_policy", {}).get(
            "chapter_max_retries", config.chapter_max_retries)
        retries = 0
        last_error_type = None
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

                if result.returncode == 0 and os.path.exists(ch_final):
                    word_count = _count_words(ch_final)
                    title = _extract_title(ch_final)
                    update_chapter(book_id, global_chapter,
                                   status="completed", retries=retries,
                                   word_count=word_count, title=title,
                                   volume=volume)
                    written += 1
                    written_chapters.append({"global_chapter": global_chapter, "volume": volume})
                    chapter_ok = True
                    break
                elif result.returncode == 124:
                    retries += 1
                    last_error_type = "timeout"
                    update_chapter(book_id, global_chapter, retries=retries)
                else:
                    retries += 1
                    last_error_type = "exec"
                    update_chapter(book_id, global_chapter, retries=retries)

            except FileNotFoundError:
                return {"success": False, "error": "timeout or opencode command not found on PATH"}

        if not chapter_ok:
            update_chapter(book_id, global_chapter,
                           status="failed", retries=retries,
                           last_error=f"Failed after {max_retries} retries (last: {last_error_type})")
            return {"success": False, "chapters_written": written,
                    "written_chapters": written_chapters,
                    "error": f"Chapter {global_chapter} failed after {max_retries} retries"}

    if written == 0:
        return {"success": True, "chapters_written": 0,
                "written_chapters": [],
                "message": "All chapters already completed"}

    _mark_phase2_done(book_id)

    return {"success": True, "chapters_written": written,
            "written_chapters": written_chapters}


def _mark_phase2_done(book_id: str):
    state = load_book_state(book_id)
    if state is None:
        return

    book_dir = os.path.join(BOOKS_DIR, book_id)
    version = state.get("version", "v1")
    ver_dir = os.path.join(book_dir, "versions", version)

    chapters = state.get("chapters", {})
    completed_count = sum(
        1 for c in chapters.values() if c.get("status") == "completed"
    )

    marker_path = os.path.join(ver_dir, ".phase2_done")
    marker = {
        "phase": "phase2_done",
        "chapters_completed": completed_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    os.makedirs(ver_dir, exist_ok=True)
    with open(marker_path, "w", encoding="utf-8") as f:
        json.dump(marker, f, ensure_ascii=False, indent=2)

    state["phase"] = "phase2_done"
    save_book_state(book_id, state)


def _ensure_volume_resources(book_id: str, volume: int, version: str) -> bool:
    book_dir = os.path.join(BOOKS_DIR, book_id)
    ver_dir = os.path.join(book_dir, "versions", version)

    inject_dir = os.path.join(ver_dir, "上帝之眼", "05-卷级注入")
    vol_padded = f"{volume:02d}"
    inject_file = os.path.join(inject_dir, f"卷{vol_padded}-注入包.md")
    vol_outline = os.path.join(ver_dir, "01-大纲", "01-卷纲", f"卷纲-第{volume}卷.md")

    if os.path.exists(vol_outline):
        if volume == 1 or os.path.exists(inject_file):
            return True

    if volume > 1:
        prompt = f"初始化第{volume}卷卷纲"
    else:
        prompt = "初始化项目并生成第1卷卷纲"

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
            if volume == 1 or os.path.exists(inject_file):
                return True

    return False


def _count_words(path: str) -> int:
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        return len(re.sub(r"\s+", "", text))
    except Exception:
        return 0


def _extract_title(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("# "):
                    return line[2:].strip()
        return os.path.basename(path).replace(".md", "")
    except Exception:
        return ""
