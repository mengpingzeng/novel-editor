"""
Phase 1 registration service — orchestrates book registration via automation_manager agent.

Uses scope isolation to ensure only one book is processed per invocation.
"""

import json
import os
import shutil
import subprocess
import time
from typing import Any, Dict

from config import config
from services.book_state import ensure_book_state, set_book_phase

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(ROOT_DIR, "workspace", "iteration-state.json")
SCOPE_FILE = os.path.join(ROOT_DIR, "workspace", ".pipeline_scope.json")
REPO_DIR = os.path.join(ROOT_DIR, "workspace", "repo")


def register_book(source_name: str, platform: str, track: str = "auto",
                  word_count_multiplier: float = 1.0) -> str:
    """Submit a book registration task. Returns task_id."""
    from worker.task_queue import task_queue as tq
    return tq.submit("register", source_name, {
        "platform": platform,
        "track": track,
        "word_count_multiplier": word_count_multiplier,
    })


def execute_register(book_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Execute Phase 1 registration for a single book. Called by worker."""
    platform = params.get("platform", "")
    track = params.get("track", "auto")
    word_count_multiplier = params.get("word_count_multiplier", 1.0)

    source_path = os.path.join(REPO_DIR, book_id, "source.txt")
    if not os.path.exists(source_path):
        return {"success": False, "error": f"source.txt not found: {source_path}"}

    book_dir = os.path.join(ROOT_DIR, "workspace", "books", book_id)
    os.makedirs(book_dir, exist_ok=True)

    scope, backup_state = _prepare_scope(book_id, platform, track, word_count_multiplier)
    if scope is None:
        set_book_phase(book_id, "phase1_done")
        return {"success": True, "book_id": book_id, "phase": "phase1_done",
                "message": "Already registered (book_state.json exists and phase1_done)"}

    backup_path = STATE_FILE + ".register_bak"
    shutil.copy(STATE_FILE, backup_path)
    json.dump(scope, open(SCOPE_FILE, "w"), ensure_ascii=False, indent=2)
    shutil.copy(SCOPE_FILE, STATE_FILE)

    try:
        result = subprocess.run(
            ["opencode", "run", "--dangerously-skip-permissions",
             "/iterate", "step"],
            cwd=ROOT_DIR,
            timeout=config.phase1_timeout,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            last_lines = result.stderr.strip().split("\n")[-5:] if result.stderr else []
            return {
                "success": False,
                "error": f"opencode exited with code {result.returncode}",
                "details": "\n".join(last_lines),
            }

        _finalize_register(book_id)

        return {"success": True, "book_id": book_id, "phase": "phase1_done"}

    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Phase 1 timeout after {config.phase1_timeout}s"}
    except FileNotFoundError:
        return {"success": False, "error": "opencode command not found on PATH"}
    finally:
        if os.path.exists(backup_path):
            shutil.copy(backup_path, STATE_FILE)
            os.remove(backup_path)
        if os.path.exists(SCOPE_FILE):
            os.remove(SCOPE_FILE)


def _prepare_scope(book_id: str, platform: str, track: str,
                   word_count_multiplier: float) -> tuple:
    """Build a scope file containing only this one book.
    Returns (scope_dict, backup_state) or (None, None) if already registered."""
    if not os.path.exists(STATE_FILE):
        scope = {
            "mode": "step",
            "phase": "phase1",
            "current_round": 1,
            "passing_score": 10,
            "target_chapters": 0,
            "active_books": [{
                "name": book_id,
                "platform": platform,
                "track": track,
                "word_count_multiplier": word_count_multiplier,
            }],
            "books": {
                book_id: {"version": "v1", "phase": "pending"}
            }
        }
        return scope, None

    with open(STATE_FILE) as f:
        main_state = json.load(f)

    existing_book = main_state.get("books", {}).get(book_id, {})
    existing_phase = existing_book.get("phase", "pending")
    if _phase_ge(existing_phase, "phase1_done"):
        return None, None

    orig_active_entry = {"name": book_id, "platform": platform,
                         "track": track, "word_count_multiplier": word_count_multiplier}
    for b in main_state.get("active_books", []):
        if b.get("name") == book_id:
            orig_active_entry = dict(b)
            break

    scope = {
        "mode": "step",
        "phase": "phase1",
        "current_round": main_state.get("current_round", 1),
        "passing_score": main_state.get("passing_score", 10),
        "target_chapters": 0,
        "active_books": [orig_active_entry],
        "books": {
            book_id: existing_book if existing_book else {"version": "v1", "phase": "pending"}
        }
    }
    return scope, main_state


def _phase_ge(current: str, required: str) -> bool:
    order = {"pending": 0, "phase1_done": 1, "phase2_done": 2, "phase3_done": 3, "done": 4}
    return order.get(current, -1) >= order.get(required, 999)


def _finalize_register(book_id: str):
    ensure_book_state(book_id)
