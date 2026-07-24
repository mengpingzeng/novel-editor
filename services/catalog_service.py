import json
import os
from typing import Any, Dict, List, Optional, Tuple

from services.book_state import load_book_state, list_all_books, phase_ge, BOOKS_DIR
from services.db import catalog_list_ids, catalog_contains


def _phase1_artifacts_ok(book_id, version):
    # type: (str, str) -> Tuple[bool, List[str]]
    vdir = os.path.join(BOOKS_DIR, book_id, "versions", version)
    missing = []  # type: List[str]

    checks = [
        (os.path.join(vdir, "发布", "cover.png"), "封面图 cover.png"),
        (os.path.join(vdir, "发布", "novel_metadata.json"), "novel_metadata.json"),
        (os.path.join(vdir, "00-素材", "base_whitepaper.md"), "白皮书 base_whitepaper.md"),
        (os.path.join(vdir, "仿写衍生总纲领.md"), "仿写衍生总纲领.md"),
    ]
    for path, label in checks:
        if not os.path.exists(path):
            missing.append(label)

    return len(missing) == 0, missing


def validate_book_for_catalog(book_id):
    # type: (str) -> Tuple[bool, str]
    state = load_book_state(book_id)
    if state is None:
        return False, "book_state.json 不存在，尚未注册"

    phase = state.get("phase", "pending")
    if not phase_ge(phase, "phase1_done"):
        return False, "phase 为 {}，未完成 Phase 1 注册".format(phase)

    version = state.get("version", "v1")
    ok, missing = _phase1_artifacts_ok(book_id, version)
    if not ok:
        return False, "缺失关键文件: {}".format(", ".join(missing))

    return True, ""


def _enrich_book(book_id):
    # type: (str) -> Optional[Dict[str, Any]]
    state = load_book_state(book_id)
    if state is None:
        return None

    version = state.get("version", "v1")
    chapters = state.get("chapters", {})
    completed = sum(1 for v in chapters.values() if v.get("status") == "completed")

    meta = {}  # type: Dict[str, Any]
    meta_path = os.path.join(BOOKS_DIR, book_id, "versions", version, "发布", "novel_metadata.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            pass

    titles = meta.get("title", [])
    name = titles[0] if titles else None

    return {
        "book_id": book_id,
        "name": name,
        "description": meta.get("description"),
        "genre": meta.get("genre"),
        "cover_url": "/v1/books/cover?book_id={}".format(book_id),
        "phase": state.get("phase"),
        "version": version,
        "total_chapters": state.get("total_chapters"),
        "chapters_completed": completed,
    }


def get_catalog_books():
    # type: () -> List[Dict[str, Any]]
    results = []  # type: List[Dict[str, Any]]
    for book_id in catalog_list_ids():
        ready, _ = validate_book_for_catalog(book_id)
        if ready:
            enriched = _enrich_book(book_id)
            if enriched:
                results.append(enriched)
    return results


def get_catalog_all(book_id_filter=None):
    # type: (Optional[str]) -> List[Dict[str, Any]]
    results = []  # type: List[Dict[str, Any]]
    in_catalog_set = set(catalog_list_ids())

    for book_id in list_all_books():
        if book_id_filter and book_id_filter not in book_id:
            continue

        state = load_book_state(book_id)
        if state is None:
            continue

        version = state.get("version", "v1")
        meta = {}  # type: Dict[str, Any]
        meta_path = os.path.join(BOOKS_DIR, book_id, "versions", version, "发布", "novel_metadata.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                pass

        titles = meta.get("title", [])
        name = titles[0] if titles else None

        chapters = state.get("chapters", {})
        completed = sum(1 for v in chapters.values() if v.get("status") == "completed")

        results.append({
            "book_id": book_id,
            "name": name,
            "genre": meta.get("genre"),
            "cover_url": "/v1/books/cover?book_id={}".format(book_id),
            "phase": state.get("phase"),
            "version": version,
            "total_chapters": state.get("total_chapters"),
            "chapters_completed": completed,
            "in_catalog": book_id in in_catalog_set,
        })

    return results
