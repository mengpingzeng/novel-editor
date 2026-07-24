"""
Status service — read book and chapter information from file system and book_state.json.
"""

import json
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


def normalize_chapter_names(raw, completed_count=0):
    # type: (Any, int) -> List[str]
    """Normalize chapter_names to a plain list[str], regardless of input format.

    Supported formats:
      - dict  {'1': '宫门初入', '2': '深宫晚棠'}
      - list  ['测灵仪式', '残图之争']
      - list[dict]  [{'chapter':1,'title':'灰色石印'}]
      - None / empty / invalid → empty slots
    """
    result = []

    if isinstance(raw, dict):
        for idx in range(completed_count):
            key = str(idx + 1)
            val = raw.get(key, "")
            if val and not isinstance(val, str):
                val = str(val)
            result.append(val or "")
    elif isinstance(raw, list):
        for idx in range(max(completed_count, len(raw))):
            entry = raw[idx] if idx < len(raw) else None
            if isinstance(entry, dict):
                title = entry.get("title", "")
                if title and not isinstance(title, str):
                    title = str(title)
                result.append(title)
            elif isinstance(entry, str):
                result.append(entry)
            else:
                result.append("")
    else:
        result = [""] * completed_count

    while len(result) < completed_count:
        result.append("")

    return result


_DEFAULT_TITLE_RE = re.compile(r"^第\d+章[-_]?(初稿|终稿)(-v\d+)?$")


def _is_default_title(title):
    # type: (str) -> bool
    if not title:
        return True
    return bool(_DEFAULT_TITLE_RE.match(title.strip()))


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
        "book_id": book_id,
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
        "book_id": book_id,
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

    title = ch_data.get("title") or _extract_title(content)
    return {
        "global_chapter": global_chapter,
        "volume": ch_data.get("volume"),
        "title": title,
        "content": content,
        "word_count": ch_data.get("word_count", len(re.sub(r"\s+", "", content))),
        "score": ch_data.get("score"),
        "status": ch_data.get("status"),
        "draft": content,
        "chapter_title": title,
    }


def get_chapter_list(book_id: str) -> Optional[Dict[str, Any]]:
    state = load_book_state(book_id)
    if state is None:
        return None

    version = state.get("version", "v1")
    draft_dir = os.path.join(BOOKS_DIR, book_id, "versions", version, "02-正文")

    chapters = state.get("chapters", {})
    completed = sum(1 for v in chapters.values() if v.get("status") == "completed")

    chapter_names = []  # type: List[str]
    meta_path = os.path.join(BOOKS_DIR, book_id, "versions", version, "发布", "novel_metadata.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            chapter_names = normalize_chapter_names(meta.get("chapter_names", []), completed)
        except Exception:
            pass

    volumes = {}
    for key, ch_data in chapters.items():
        ch_num = int(key)
        vol_num = ch_data.get("volume", 1)
        raw_title = ch_data.get("title", "")
        if _is_default_title(raw_title):
            idx = ch_num - 1
            if idx < len(chapter_names) and chapter_names[idx]:
                raw_title = chapter_names[idx]
            else:
                raw_title = "第{}章".format(ch_num)
        elif not raw_title:
            idx = ch_num - 1
            if idx < len(chapter_names) and chapter_names[idx]:
                raw_title = chapter_names[idx]
            else:
                raw_title = "第{}章".format(ch_num)

        if vol_num not in volumes:
            volumes[vol_num] = []
        volumes[vol_num].append({
            "global_chapter": ch_num,
            "title": raw_title,
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


def get_book_metadata(book_id: str) -> Optional[Dict[str, Any]]:
    state = load_book_state(book_id)
    if state is None:
        return None

    version = state.get("version", "v1")
    meta_path = os.path.join(BOOKS_DIR, book_id, "versions", version, "发布", "novel_metadata.json")
    meta: Dict[str, Any] = {}
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            pass

    chapters = state.get("chapters", {})
    completed = sum(1 for v in chapters.values() if v.get("status") == "completed")

    titles = meta.get("title", [])
    name = titles[0] if titles else None

    raw_names = meta.get("chapter_names", [])
    chapter_names = normalize_chapter_names(raw_names, completed)

    return {
        "book_id": book_id,
        "name": name,
        "titles": titles,
        "description": meta.get("description"),
        "genre": meta.get("genre"),
        "protagonist": meta.get("protagonist"),
        "chapter_names": chapter_names,
        "chapters_completed": completed,
        "total_chapters": state.get("total_chapters"),
        "cover_image": meta.get("cover_image"),
    }


def _extract_title(content: str) -> str:
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return ""
