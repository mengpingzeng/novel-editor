"""
Status service — v5 纯净版

从 checkpoints 读取章节和书籍信息。无向后兼容，无读时兜底。
"""

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from services.book_state import (
    load_book_state,
    list_all_books,
    get_next_chapter,
    BOOKS_DIR,
    load_novel_metadata,
)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_DEFAULT_TITLE_RE = re.compile(r"^第\d+章[-_]?(初稿|终稿)(-v\d+)?$")


def _is_default_title(title: str) -> bool:
    """判断是否为默认占位标题（第N章-终稿 / 第N章-初稿）"""
    if not title:
        return True
    return bool(_DEFAULT_TITLE_RE.match(title.strip()))


def _load_metadata_verified(book_id: str, version: str) -> Optional[Dict[str, Any]]:
    """加载 novel_metadata.json，验 HMAC 签名。无效时尝试从 .bak 恢复。"""
    return load_novel_metadata(book_id, version)


def _load_tags_from_salt(book_id: str, version: str) -> Tuple[List[str], Optional[str], Optional[str]]:
    """从 project_salt.json 读取 classification.tags、style_track、classification.primary_category。
    用于 novel_metadata.json 缺少对应字段时的回退（兼容历史书）。
    """
    salt_path = os.path.join(BOOKS_DIR, book_id, "versions", version, "project_salt.json")
    if not os.path.exists(salt_path):
        return [], None, None
    try:
        with open(salt_path, "r", encoding="utf-8") as f:
            salt = json.load(f)
    except Exception:
        return [], None, None
    cls = salt.get("classification") or {}
    tags = cls.get("tags") or []
    tags = [t for t in tags if isinstance(t, str) and t.strip()]
    track = salt.get("style_track") or salt.get("track")
    primary = cls.get("primary_category") or cls.get("primary")
    return tags, track, primary


def get_book_status(book_id: str) -> Optional[Dict[str, Any]]:
    state = load_book_state(book_id)
    if state is None:
        return None

    finalized = _count_finalized(state)
    next_ch = get_next_chapter(book_id)

    return {
        "book_id": book_id,
        "phase": state.get("phase"),
        "version": state.get("version"),
        "total_volumes": state.get("total_volumes"),
        "total_chapters": state.get("total_chapters"),
        "chapters_completed": finalized,
        "is_completed": state.get("total_chapters") is not None
                        and finalized >= state.get("total_chapters", 0),
        "next_chapter": next_ch,
        "quality_avg": state.get("quality_avg", 0.0),
        "created_at": state.get("created_at"),
        "updated_at": state.get("updated_at"),
    }


def _count_finalized(state: dict) -> int:
    ck = state.get("checkpoints", {}).get("phase2", {})
    count = 0
    if isinstance(ck, dict):
        for vol_data in ck.values():
            if not isinstance(vol_data, dict):
                continue
            chapters = vol_data.get("chapters", {})
            if isinstance(chapters, dict):
                for ch_data in chapters.values():
                    if isinstance(ch_data, dict) and ch_data.get("finalized", {}).get("status") == "done":
                        count += 1
    return count


def get_book_summary(book_id: str) -> Optional[Dict[str, Any]]:
    state = load_book_state(book_id)
    if state is None:
        return None
    return {
        "book_id": book_id,
        "phase": state.get("phase"),
        "version": state.get("version"),
        "total_chapters": state.get("total_chapters"),
        "chapters_completed": _count_finalized(state),
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
    draft_path = os.path.join(BOOKS_DIR, book_id, "versions", version,
                               "02-正文", f"第{global_chapter}章-终稿.md")
    if not os.path.exists(draft_path):
        return None

    try:
        with open(draft_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return None

    title = _find_chapter_title_from_checkpoints(state, global_chapter)
    if not title:
        title = _find_chapter_title_from_metadata(book_id, version, global_chapter)
    if not title:
        title = f"第{global_chapter}章"

    score = _find_chapter_score(state, global_chapter)
    word_count = len(re.sub(r"\s+", "", content))
    volume = _find_chapter_volume(state, global_chapter)

    return {
        "global_chapter": global_chapter,
        "volume": volume,
        "title": title,
        "content": content,
        "word_count": word_count,
        "score": score,
        "status": "completed",
        "draft": content,
        "chapter_title": title,
    }


def _find_chapter_volume(state: dict, chapter: int) -> Optional[int]:
    for vol in state.get("volumes", []):
        if vol.get("ch_start", 0) <= chapter <= vol.get("ch_end", 0):
            return vol.get("volume")
    return None


def _find_chapter_title_from_checkpoints(state: dict, chapter: int) -> Optional[str]:
    ck = state.get("checkpoints", {}).get("phase2", {})
    if isinstance(ck, dict):
        for vol_data in ck.values():
            if not isinstance(vol_data, dict):
                continue
            ch_data = vol_data.get("chapters", {}).get(str(chapter), {})
            if isinstance(ch_data, dict):
                fin = ch_data.get("finalized", {})
                if isinstance(fin, dict) and fin.get("title"):
                    return fin["title"]
    return None


def _find_chapter_score(state: dict, chapter: int) -> Optional[float]:
    ck = state.get("checkpoints", {}).get("phase2", {})
    if isinstance(ck, dict):
        for vol_data in ck.values():
            if not isinstance(vol_data, dict):
                continue
            ch_data = vol_data.get("chapters", {}).get(str(chapter), {})
            if isinstance(ch_data, dict):
                fin = ch_data.get("finalized", {})
                if isinstance(fin, dict):
                    return fin.get("score")
    return None


def _find_chapter_title_from_metadata(book_id: str, version: str, chapter: int) -> Optional[str]:
    meta = _load_metadata_verified(book_id, version)
    if meta is None:
        return None
    names = meta.get("chapter_names", [])
    if isinstance(names, list) and chapter - 1 < len(names):
        return names[chapter - 1]
    return None


def get_chapter_list(book_id: str) -> Optional[Dict[str, Any]]:
    state = load_book_state(book_id)
    if state is None:
        return None

    version = state.get("version", "v1")
    chapter_names = _load_chapter_names(book_id, version)
    volumes = _build_volumes_from_checkpoints(state, chapter_names)

    return {
        "book_id": book_id,
        "version": version,
        "total_volumes": state.get("total_volumes"),
        "total_chapters": state.get("total_chapters"),
        "volumes": volumes,
    }


def _build_volumes_from_checkpoints(state: dict, chapter_names: list) -> List[Dict]:
    ck = state.get("checkpoints", {}).get("phase2", {})
    state_volumes = state.get("volumes", [])
    version = state.get("version", "v1")
    book_id = state.get("book_id", "")

    volumes = {}
    for vol in state_volumes:
        vol_num = vol["volume"]
        vol_key = f"volume_{vol_num}"
        vol_data = ck.get(vol_key, {}) if isinstance(ck, dict) else {}
        ch_dict = vol_data.get("chapters", {}) if isinstance(vol_data, dict) else {}

        for ch_num in range(vol.get("ch_start", 1), vol.get("ch_end", 0) + 1):
            ch_key = str(ch_num)
            ch_entry = ch_dict.get(ch_key, {}) if isinstance(ch_dict, dict) else {}
            fin = ch_entry.get("finalized", {}) if isinstance(ch_entry, dict) else {}
            is_done = isinstance(fin, dict) and fin.get("status") == "done"

            if not is_done:
                draft_path = os.path.join(BOOKS_DIR, book_id, "versions", version,
                                          "02-正文", f"第{ch_num}章-终稿.md")
                if not os.path.exists(draft_path):
                    continue
                is_done = True

            title = (fin.get("title") if isinstance(fin, dict) else None) or ""
            if not title or _is_default_title(title):
                idx = ch_num - 1
                if idx < len(chapter_names) and chapter_names[idx]:
                    title = chapter_names[idx]
                else:
                    title = f"第{ch_num}章"

            if vol_num not in volumes:
                volumes[vol_num] = []
            volumes[vol_num].append({
                "global_chapter": ch_num,
                "title": title,
                "status": "completed",
                "word_count": (fin.get("word_count") if isinstance(fin, dict) else None),
                "score": (fin.get("score") if isinstance(fin, dict) else None),
            })

    vol_list = []
    for vol_num in sorted(volumes.keys()):
        volumes[vol_num].sort(key=lambda c: c["global_chapter"])
        vol_list.append({"volume": vol_num, "chapters": volumes[vol_num]})
    return vol_list


def _load_chapter_names(book_id: str, version: str) -> List[str]:
    meta = _load_metadata_verified(book_id, version)
    if meta is None:
        return []
    names = meta.get("chapter_names", [])
    return names if isinstance(names, list) else []


def get_book_metadata(book_id: str) -> Optional[Dict[str, Any]]:
    state = load_book_state(book_id)
    if state is None:
        return None

    version = state.get("version", "v1")
    meta = _load_metadata_verified(book_id, version) or {}
    titles = meta.get("title", [])
    name = titles[0] if titles else None
    chapter_names = _load_chapter_names(book_id, version)

    tags = meta.get("tags") or []
    track = meta.get("track")
    primary = meta.get("primary_category")
    if (not tags) and (track is None) and (primary is None):
        salt_tags, salt_track, salt_primary = _load_tags_from_salt(book_id, version)
        if not tags:
            tags = salt_tags
        if track is None:
            track = salt_track
        if primary is None:
            primary = salt_primary
    if not isinstance(tags, list):
        tags = []

    return {
        "book_id": book_id,
        "name": name,
        "titles": titles,
        "source_title": meta.get("source", {}).get("title", book_id),
        "description": meta.get("description"),
        "genre": meta.get("genre"),
        "protagonist": meta.get("protagonist"),
        "chapter_names": chapter_names,
        "chapters_completed": _count_finalized(state),
        "total_chapters": state.get("total_chapters"),
        "cover_image": meta.get("cover_image"),
        "tags": tags,
        "track": track,
        "primary_category": primary,
    }
