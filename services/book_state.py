"""
book_state.json — per-book state file CRUD.

Each book under workspace/books/{book_id}/ has exactly one book_state.json.
This replaces the global workspace/iteration-state.json for production use.
"""

import json
import os
import re
from datetime import datetime, timezone
from glob import glob
from typing import Any, Dict, List, Optional

from config import config

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS_DIR = os.path.join(ROOT_DIR, "workspace", "books")

DEFAULT_RETRY_POLICY = {
    "chapter_max_retries": config.chapter_max_retries,
}


def _state_path(book_id: str) -> str:
    return os.path.join(BOOKS_DIR, book_id, "book_state.json")


def _book_version_dir(book_id: str) -> Optional[str]:
    book_dir = os.path.join(BOOKS_DIR, book_id)
    versions_dir = os.path.join(book_dir, "versions")
    if not os.path.isdir(versions_dir):
        return None
    versions = sorted(
        [d for d in os.listdir(versions_dir) if re.match(r"^v\d+$", d)],
        key=lambda v: int(v[1:]),
    )
    return os.path.join(versions_dir, versions[-1]) if versions else None


def load_book_state(book_id: str) -> Optional[Dict[str, Any]]:
    path = _state_path(book_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_book_state(book_id: str, data: Dict[str, Any]):
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    path = _state_path(book_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def ensure_book_state(book_id: str) -> Dict[str, Any]:
    """Load existing book_state.json or create from file-system scan (migration)."""
    state = load_book_state(book_id)
    if state is not None:
        _populate_volumes_from_god_eye(state, book_id)
        save_book_state(book_id, state)
        return state

    book_dir = os.path.join(BOOKS_DIR, book_id)
    if not os.path.isdir(book_dir):
        raise FileNotFoundError(f"Book directory not found: {book_dir}")

    version = None
    ver_dir = _book_version_dir(book_id)
    if ver_dir:
        version = os.path.basename(ver_dir)

    phase = "pending"
    phase1_marker = os.path.join(ver_dir, ".phase1_done") if ver_dir else ""
    phase2_marker = os.path.join(ver_dir, ".phase2_done") if ver_dir else ""
    phase3_marker = os.path.join(ver_dir, ".phase3_done") if ver_dir else ""

    if os.path.exists(phase3_marker):
        phase = "phase3_done"
    elif os.path.exists(phase2_marker):
        phase = "phase2_done"
    elif os.path.exists(phase1_marker):
        phase = "phase1_done"

    chapters = _scan_chapters(book_id, version)

    state = {
        "book_id": book_id,
        "platform": "",
        "track": "",
        "phase": phase,
        "version": version or "v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_volumes": None,
        "total_chapters": None,
        "volumes": [],
        "chapters": chapters,
        "retry_policy": DEFAULT_RETRY_POLICY.copy(),
        "quality_avg": 0.0,
        "last_error": None,
    }

    _populate_volumes_from_god_eye(state, book_id)
    save_book_state(book_id, state)
    return state


def _scan_chapters(book_id: str, version: str) -> Dict[str, Dict[str, Any]]:
    """Scan 02-正文/ for completed chapters and build chapters dict."""
    chapters: Dict[str, Dict[str, Any]] = {}
    if not version:
        return chapters

    draft_dir = os.path.join(BOOKS_DIR, book_id, "versions", version, "02-正文")
    if not os.path.isdir(draft_dir):
        return chapters

    for fname in os.listdir(draft_dir):
        m = re.match(r"第(\d+)章-终稿\.md", fname)
        if m:
            ch_num = m.group(1)
            path = os.path.join(draft_dir, fname)
            word_count = _count_words(path)
            chapters[ch_num] = {
                "global_chapter": int(ch_num),
                "volume": 1,
                "status": "completed",
                "retries": 0,
                "score": 0.0,
                "word_count": word_count,
                "title": fname.replace(".md", ""),
                "completed_at": datetime.fromtimestamp(
                    os.path.getmtime(path), tz=timezone.utc
                ).isoformat(),
            }
    return chapters


def _count_words(path: str) -> int:
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        return len(re.sub(r"\s+", "", text))
    except Exception:
        return 0


def _populate_volumes_from_god_eye(state: dict, book_id: str):
    """Parse 上帝之眼/00-全书命运总谱.md volume table and populate volumes."""
    ver_dir = _book_version_dir(book_id)
    if not ver_dir:
        return
    fate_path = os.path.join(ver_dir, "上帝之眼", "00-全书命运总谱.md")
    if not os.path.exists(fate_path):
        return

    try:
        with open(fate_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return

    volumes_raw = []
    for line in content.split("\n"):
        line = line.strip()
        if not line.startswith("|") or "---" in line:
            continue
        cols = line.split("|")
        if len(cols) < 4:
            continue
        try:
            vol_str = cols[1].strip()
            vol_match = re.match(r"[Vv]?(\d+)", vol_str)
            if not vol_match:
                continue
            vol_id = int(vol_match.group(1))
            ch_str = cols[4].strip() if len(cols) > 4 else ""
            if not re.match(r"^\d+$", ch_str):
                ch_str = cols[3].strip()
            ch_match = re.match(r"\d+", ch_str)
            if not ch_match:
                continue
            ch_count = int(ch_match.group())
        except (ValueError, IndexError):
            continue
        if vol_id < 1 or ch_count < 1:
            continue
        volumes_raw.append((vol_id, ch_count))

    seen = set()
    deduped = []
    for vid, cnt in volumes_raw:
        if vid not in seen:
            seen.add(vid)
            deduped.append((vid, cnt))

    if not deduped:
        return

    deduped.sort(key=lambda x: x[0])
    volumes = []
    cumulative = 0
    for vid, cnt in deduped:
        ch_start = cumulative + 1
        ch_end = cumulative + cnt
        volumes.append({"volume": vid, "ch_start": ch_start, "ch_end": ch_end})
        cumulative = ch_end

    state["total_volumes"] = len(volumes)
    state["total_chapters"] = cumulative
    state["volumes"] = volumes

    for ch_key, ch_data in state.get("chapters", {}).items():
        gch = int(ch_key)
        for vol in volumes:
            if vol["ch_start"] <= gch <= vol["ch_end"]:
                ch_data["volume"] = vol["volume"]
                break


def get_next_chapter(book_id: str) -> Optional[Dict[str, int]]:
    """Find the next chapter to write. Returns {global_chapter, volume} or None if all done."""
    state = load_book_state(book_id)
    if state is None:
        return None

    version = state.get("version", "v1")
    chapters = state.get("chapters", {})
    total = state.get("total_chapters")

    if not chapters:
        start_ch = 1
    else:
        completed = {
            int(k)
            for k, v in chapters.items()
            if v.get("status") == "completed"
        }
        if not completed:
            start_ch = 1
        else:
            max_completed = max(completed)
            if total and max_completed >= total:
                return None
            start_ch = max_completed + 1

    ch_final = os.path.join(
        BOOKS_DIR, book_id, "versions", version,
        "02-正文", f"第{start_ch}章-终稿.md"
    )
    if os.path.exists(ch_final):
        from datetime import datetime as _dt
        ch_key = str(start_ch)
        chapters[ch_key] = {
            "global_chapter": start_ch,
            "volume": 1,
            "status": "completed",
            "retries": 0,
            "score": 0.0,
            "word_count": _count_words(ch_final),
            "title": ch_final.rsplit("/", 1)[-1].replace(".md", ""),
            "completed_at": _dt.fromtimestamp(
                os.path.getmtime(ch_final), tz=timezone.utc
            ).isoformat(),
        }
        state["chapters"] = chapters
        _populate_volumes_from_god_eye(state, book_id)
        for vol in state.get("volumes", []):
            if vol["ch_start"] <= start_ch <= vol["ch_end"]:
                chapters[ch_key]["volume"] = vol["volume"]
                break
        save_book_state(book_id, state)
        return get_next_chapter(book_id)

    volume = 1
    for vol in state.get("volumes", []):
        if vol["ch_start"] <= start_ch <= vol["ch_end"]:
            volume = vol["volume"]
            break

    return {"global_chapter": start_ch, "volume": volume}


def update_chapter(book_id: str, global_chapter: int, **kwargs):
    """Update a single chapter's fields in book_state.json."""
    state = load_book_state(book_id)
    if state is None:
        return
    ch_key = str(global_chapter)
    chapters = state.setdefault("chapters", {})
    if ch_key not in chapters:
        chapters[ch_key] = {
            "global_chapter": global_chapter,
            "volume": kwargs.get("volume", 1),
            "status": "pending",
            "retries": 0,
            "score": 0.0,
            "word_count": 0,
            "title": "",
            "completed_at": None,
        }
    chapters[ch_key].update(kwargs)
    chapters[ch_key]["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_book_state(book_id, state)


def get_book_phase(book_id: str) -> str:
    state = load_book_state(book_id)
    return state.get("phase", "pending") if state else "pending"


def set_book_phase(book_id: str, phase: str):
    state = load_book_state(book_id)
    if state is None:
        state = {
            "book_id": book_id,
            "platform": "",
            "track": "",
            "phase": phase,
            "version": "v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "volumes": [],
            "chapters": {},
            "retry_policy": DEFAULT_RETRY_POLICY.copy(),
            "quality_avg": 0.0,
            "last_error": None,
        }
    state["phase"] = phase
    save_book_state(book_id, state)


def list_all_books() -> List[str]:
    """List all registered books by scanning workspace/books/ for book_state.json."""
    books = []
    books_root = BOOKS_DIR
    if not os.path.isdir(books_root):
        return books
    for entry in sorted(os.listdir(books_root)):
        entry_path = os.path.join(books_root, entry)
        if os.path.isdir(entry_path) and not entry.startswith("_") and not entry.startswith("."):
            if os.path.exists(os.path.join(entry_path, "book_state.json")):
                books.append(entry)
    return books


def phase_ge(current: str, required: str) -> bool:
    """Check if current phase is >= required phase.
    Supports intermediate phases (e.g. phase2_volume1_outline) written by agents.
    """
    return _phase_level(current) >= _phase_level(required)


_PHASE_ORDER = {"pending": 0, "phase1_done": 1, "phase2_done": 2, "phase3_done": 3, "done": 4}


def _phase_level(phase: str) -> int:
    if phase in _PHASE_ORDER:
        return _PHASE_ORDER[phase]
    for prefix, level in [("phase3", 3), ("phase2", 2), ("phase1", 1)]:
        if phase.startswith(prefix):
            return level
    return -1
