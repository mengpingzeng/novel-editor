"""
Phase 2 write service — orchestrates chapter writing via chief_editor agent.

- Determines next chapter to write from book_state.json
- Resolves volume from god's eye data
- Runs chief_editor in the book's working directory
"""

import json
import os
import re
import subprocess
from typing import Any, Dict, Optional

from config import config
from services.book_state import (
    load_book_state,
    ensure_book_state,
    get_next_chapter,
    update_chapter,
    phase_ge,
)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS_DIR = os.path.join(ROOT_DIR, "workspace", "books")


def write_chapters(book_id: str, chapters: int = 1) -> str:
    """Submit a chapter writing task. Returns task_id."""
    from worker.task_queue import task_queue as tq
    return tq.submit("write", book_id, {
        "chapters": chapters,
    })


def execute_write(book_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Execute chapter writing for a book. Called by worker."""
    chapters_to_write = params.get("chapters", 1)

    state = ensure_book_state(book_id)
    if state is None:
        return {"success": False, "error": f"Book not found: {book_id}"}

    phase = state.get("phase", "pending")
    if not phase_ge(phase, "phase1_done"):
        return {"success": False, "error": f"Book not registered yet (phase={phase}). Register first."}

    book_dir = os.path.join(BOOKS_DIR, book_id)
    version = state.get("version", "v1")

    written = 0
    errors = []

    for _ in range(chapters_to_write):
        next_ch = get_next_chapter(book_id)
        if next_ch is None:
            break

        global_chapter = next_ch["global_chapter"]
        volume = next_ch["volume"]

        _ensure_volume_resources(book_id, volume, version)

        command = f"执行第{volume}卷第{global_chapter}章生产"

        retries = 0
        max_retries = state.get("retry_policy", {}).get("chapter_max_retries", 3)

        while retries < max_retries:
            try:
                result = subprocess.run(
                    ["opencode", "run", "--dangerously-skip-permissions",
                     "--dir", book_dir,
                     "--agent", "chief_editor",
                     command],
                    timeout=config.chapter_timeout,
                    capture_output=True,
                    text=True,
                )

                ch_final = os.path.join(
                    book_dir, "versions", version,
                    "02-正文", f"第{global_chapter}章-终稿.md"
                )

                if result.returncode == 0 and os.path.exists(ch_final):
                    word_count = _count_words(ch_final)
                    title = _extract_title(ch_final)
                    update_chapter(book_id, global_chapter,
                                   status="completed", retries=retries,
                                   word_count=word_count, title=title,
                                   volume=volume)
                    written += 1
                    break
                else:
                    retries += 1
                    update_chapter(book_id, global_chapter, retries=retries)
                    if retries >= max_retries:
                        update_chapter(book_id, global_chapter,
                                       status="failed", retries=retries,
                                       last_error=f"Exhausted {max_retries} retries")
                        errors.append(f"Ch{global_chapter}: failed after {max_retries} retries")

            except subprocess.TimeoutExpired:
                retries += 1
                update_chapter(book_id, global_chapter, retries=retries)
                if retries >= max_retries:
                    update_chapter(book_id, global_chapter,
                                   status="failed", retries=retries,
                                    last_error=f"Timeout after {config.chapter_timeout}s × {max_retries}")
                    errors.append(f"Ch{global_chapter}: timeout")
            except FileNotFoundError:
                return {"success": False, "error": "opencode command not found on PATH"}

        consecutive_fails = _count_consecutive_fails(book_id)
        max_consecutive = state.get("retry_policy", {}).get("max_consecutive_fails", 3)
        if consecutive_fails >= max_consecutive:
            errors.append(f"Book {book_id}: {consecutive_fails} consecutive failures, pausing")
            break

    if errors:
        return {"success": False, "chapters_written": written,
                "error": "; ".join(errors)}
    if written == 0:
        return {"success": True, "chapters_written": 0,
                "message": "All chapters already completed"}
    return {"success": True, "chapters_written": written}


def _ensure_volume_resources(book_id: str, volume: int, version: str):
    """Ensure god's eye injection package and volume outline exist for target volume."""
    book_dir = os.path.join(BOOKS_DIR, book_id)
    ver_dir = os.path.join(book_dir, "versions", version)

    inject_dir = os.path.join(ver_dir, "上帝之眼", "05-卷级注入")
    vol_padded = f"{volume:02d}"
    inject_file = os.path.join(inject_dir, f"卷{vol_padded}-注入包.md")
    vol_outline = os.path.join(ver_dir, "01-大纲", "01-卷纲", f"卷纲-第{volume}卷.md")

    if not os.path.exists(inject_file) and volume > 1:
        try:
            subprocess.run(
                ["opencode", "run", "--dangerously-skip-permissions",
                 "--dir", book_dir,
                 "--agent", "chief_editor",
                 f"初始化第{volume}卷卷纲"],
                timeout=config.chapter_timeout,
                capture_output=True,
            )
        except Exception:
            pass
    elif volume == 1 and not os.path.exists(vol_outline):
        try:
            subprocess.run(
                ["opencode", "run", "--dangerously-skip-permissions",
                 "--dir", book_dir,
                 "--agent", "chief_editor",
                 "初始化项目并生成第1卷卷纲"],
                timeout=config.chapter_timeout,
                capture_output=True,
            )
        except Exception:
            pass


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


def _count_consecutive_fails(book_id: str) -> int:
    state = load_book_state(book_id)
    if state is None:
        return 0
    chapters = state.get("chapters", {})
    count = 0
    for key in sorted(chapters.keys(), key=int, reverse=True):
        if chapters[key].get("status") == "failed":
            count += 1
        else:
            break
    return count
