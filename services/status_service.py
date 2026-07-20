"""
Status service — read book and chapter information from file system and book_state.json.
"""

import os
import re
from typing import Any, Dict, List, Optional

from services.book_state import (
    load_book_state,
    ensure_book_state,
    list_all_books,
    BOOKS_DIR,
)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_book_status(book_id: str) -> Optional[Dict[str, Any]]:
    state = load_book_state(book_id)
    if state is None:
        return None

    chapters = state.get("chapters", {})
    completed = sum(1 for v in chapters.values() if v.get("status") == "completed")
    scores = [v.get("score", 0) for v in chapters.values()
              if v.get("status") == "completed" and v.get("score")]

    from services.book_state import get_next_chapter
    next_ch = get_next_chapter(book_id)

    return {
        "book_id": state.get("book_id"),
        "phase": state.get("phase"),
        "version": state.get("version"),
        "total_volumes": state.get("total_volumes"),
        "total_chapters": state.get("total_chapters"),
        "chapters_completed": completed,
        "is_completed": state.get("total_chapters") is not None and completed >= state.get("total_chapters", 0),
        "next_chapter": next_ch,
        "quality_avg": round(sum(scores) / len(scores), 1) if scores else 0.0,
        "created_at": state.get("created_at"),
        "updated_at": state.get("updated_at"),
    }


def get_book_summary(book_id: str) -> Optional[Dict[str, Any]]:
    state = load_book_state(book_id)
    if state is None:
        return None
    chapters = state.get("chapters", {})
    completed = sum(1 for v in chapters.values() if v.get("status") == "completed")
    return {
        "book_id": state.get("book_id"),
        "phase": state.get("phase"),
        "version": state.get("version"),
        "total_chapters": state.get("total_chapters"),
        "chapters_completed": completed,
    }


def list_all_summaries() -> List[Dict[str, Any]]:
    summaries = []
    for book_id in list_all_books():
        s = get_book_summary(book_id)
        if s:
            summaries.append(s)
    return summaries


def get_chapter_content(book_id: str, global_chapter: int) -> Optional[Dict[str, Any]]:
    state = load_book_state(book_id)
    if state is None:
        return None

    version = state.get("version", "v1")
    draft_dir = os.path.join(BOOKS_DIR, book_id, "versions", version, "02-正文")
    fname = f"第{global_chapter}章-终稿.md"
    path = os.path.join(draft_dir, fname)

    if not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return None

    ch_data = state.get("chapters", {}).get(str(global_chapter), {})

    return {
        "global_chapter": global_chapter,
        "volume": ch_data.get("volume"),
        "title": ch_data.get("title", _extract_title(content)),
        "content": content,
        "word_count": ch_data.get("word_count", len(re.sub(r"\s+", "", content))),
        "score": ch_data.get("score"),
        "status": ch_data.get("status"),
    }


def get_chapter_list(book_id: str) -> Optional[Dict[str, Any]]:
    state = load_book_state(book_id)
    if state is None:
        return None

    version = state.get("version", "v1")
    draft_dir = os.path.join(BOOKS_DIR, book_id, "versions", version, "02-正文")

    volumes = {}
    chapters = state.get("chapters", {})

    for key, ch_data in chapters.items():
        ch_num = int(key)
        vol_num = ch_data.get("volume", 1)
        if vol_num not in volumes:
            volumes[vol_num] = []
        volumes[vol_num].append({
            "global_chapter": ch_num,
            "title": ch_data.get("title", f"第{ch_num}章"),
            "status": ch_data.get("status"),
            "word_count": ch_data.get("word_count"),
            "score": ch_data.get("score"),
        })

    vol_list = []
    for vol_num in sorted(volumes.keys()):
        volumes[vol_num].sort(key=lambda c: c["global_chapter"])
        vol_list.append({
            "volume": vol_num,
            "chapters": volumes[vol_num],
        })

    return {
        "book_id": book_id,
        "version": version,
        "total_volumes": state.get("total_volumes"),
        "total_chapters": state.get("total_chapters"),
        "volumes": vol_list,
    }


def _extract_title(content: str) -> str:
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return ""
