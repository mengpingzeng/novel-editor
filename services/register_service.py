"""
Phase 1 registration service — orchestrates book registration via automation_manager agent.

Uses scope isolation to ensure only one book is processed per invocation.
Mirrors shell's run_phase1_for_book logic: scope swap → run agent → read agent output
from swapped-in state → persist to book_state.json.

iteration-state.json is only used as a temporary agent vehicle (scope swap); all
persistent state is written to book_state.json.
"""

import json
import os
import shutil
import subprocess
import time
from typing import Any, Dict

from config import config
from services.book_state import (
    ensure_book_state,
    load_book_state,
    set_book_phase,
    phase_ge,
)
from utils.pipeline_logger import log_step

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(ROOT_DIR, "workspace", "iteration-state.json")
SCOPE_FILE = os.path.join(ROOT_DIR, "workspace", ".pipeline_scope.json")
REPO_DIR = os.path.join(ROOT_DIR, "workspace", "repo")


def register_book(source_name: str, platform: str, track: str = "auto",
                  word_count_multiplier: float = 1.0,
                  writer_model: str = "tokenhub/glm-5.2") -> str:
    from worker.task_queue import task_queue as tq
    return tq.submit("register", source_name, {
        "platform": platform,
        "track": track,
        "word_count_multiplier": word_count_multiplier,
        "writer_model": writer_model,
    })


def execute_register(book_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
    platform = params.get("platform", "")
    track = params.get("track", "auto")
    word_count_multiplier = params.get("word_count_multiplier", 1.0)
    writer_model = params.get("writer_model", "tokenhub/glm-5.2")

    log_step(book_id, "register",
             f"开始注册: platform={platform}, track={track}, multiplier={word_count_multiplier}, model={writer_model}")

    source_path = os.path.join(REPO_DIR, book_id, "source.txt")
    if not os.path.exists(source_path):
        log_step(book_id, "register", f"source.txt 不存在: {source_path}", "ERROR")
        return {"success": False, "error": f"source.txt not found: {source_path}"}

    log_step(book_id, "register", "source.txt 已确认")

    book_dir = os.path.join(ROOT_DIR, "workspace", "books", book_id)
    os.makedirs(book_dir, exist_ok=True)

    scope, _main_state = _prepare_scope(book_id, platform, track, word_count_multiplier)
    if scope is None:
        log_step(book_id, "register", "已注册，跳过")
        set_book_phase(book_id, "phase1_done")
        return {"success": True, "book_id": book_id, "phase": "phase1_done",
                "message": "Already registered"}

    backup_path = STATE_FILE + ".bak"
    shutil.copy2(STATE_FILE, backup_path)

    json.dump(scope, open(SCOPE_FILE, "w"), ensure_ascii=False, indent=2)
    shutil.copy2(SCOPE_FILE, STATE_FILE)

    log_step(book_id, "register",
             f"scope 已创建，启动 agent（超时 {config.phase1_timeout}s）")

    try:
        t_start = time.time()
        result = subprocess.run(
            ["timeout", str(config.phase1_timeout),
             "opencode", "run", "--dangerously-skip-permissions",
             "/iterate", "step"],
            cwd=ROOT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        elapsed = int(time.time() - t_start)

        if result.stderr:
            _append_agent_log(book_id, result.stderr)

        if result.returncode == 124:
            log_step(book_id, "register",
                     f"agent 超时 ({config.phase1_timeout}s, elapsed={elapsed}s)", "ERROR")
            _restore_and_cleanup(backup_path)
            return {"success": False, "error": f"Phase 1 timeout after {config.phase1_timeout}s"}

        if result.returncode != 0:
            last_lines = result.stderr.strip().split("\n")[-5:] if result.stderr else []
            log_step(book_id, "register",
                     f"agent 失败 (exit={result.returncode}, elapsed={elapsed}s)", "ERROR")
            _restore_and_cleanup(backup_path)
            return {
                "success": False,
                "error": f"opencode exited with code {result.returncode}",
                "details": "\n".join(last_lines),
            }

        log_step(book_id, "register",
                 f"agent 执行完成 (exit=0, elapsed={elapsed}s)，检查 book_state.json")

        _restore_and_cleanup(backup_path)

        book_state = load_book_state(book_id)
        if not book_state or not phase_ge(book_state.get("phase", "pending"), "phase1_done"):
            current_phase = book_state.get("phase", "pending") if book_state else "no_state"
            log_step(book_id, "register",
                     f"phase 未达到 phase1_done: current={current_phase}", "ERROR")
            return {
                "success": False,
                "error": f"Agent completed but book_state.json phase not updated for '{book_id}'. "
                         f"Current phase: {current_phase}. Agent may not have processed this book.",
                "details": result.stderr.strip().split("\n")[-10:] if result.stderr else [],
            }

        log_step(book_id, "register", f"注册成功: phase={book_state['phase']}")
        _finalize_register(book_id, writer_model)

        _try_generate_cover(book_id)

        return {"success": True, "book_id": book_id, "phase": book_state["phase"]}

    except FileNotFoundError:
        _restore_and_cleanup(backup_path)
        log_step(book_id, "register", "opencode 命令未找到", "ERROR")
        return {"success": False, "error": "timeout or opencode command not found on PATH"}
    finally:
        if os.path.exists(SCOPE_FILE):
            os.remove(SCOPE_FILE)


def _append_agent_log(book_id: str, text: str):
    if not text:
        return
    for line in text.strip().split("\n"):
        stripped = line.strip()
        if stripped:
            log_step(book_id, "agent", stripped[:500], "DEBUG")


def _read_state_file() -> Dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _restore_and_cleanup(backup_path: str):
    if os.path.exists(backup_path):
        shutil.copy2(backup_path, STATE_FILE)
        os.remove(backup_path)


def _prepare_scope(book_id: str, platform: str, track: str,
                   word_count_multiplier: float):
    bstate = load_book_state(book_id)
    if bstate and phase_ge(bstate.get("phase", "pending"), "phase1_done"):
        return None, None

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

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        main_state = json.load(f)

    existing_book = main_state.get("books", {}).get(book_id, {})
    existing_phase = existing_book.get("phase", "pending")
    if phase_ge(existing_phase, "phase1_done"):
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


def _finalize_register(book_id: str, writer_model: str = "tokenhub/glm-5.2"):
    ensure_book_state(book_id)
    _write_writer_model(book_id, writer_model)
    _cleanup_iteration_state(book_id)


def _write_writer_model(book_id: str, model: str):
    book_dir = os.path.join(ROOT_DIR, "workspace", "books", book_id)
    config_path = os.path.join(book_dir, "opencode.json")
    if not os.path.exists(config_path):
        return
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("agent", {}).setdefault("content_writer", {})["model"] = model
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    log_step(book_id, "register", f"写作模型已写入 opencode.json: {model}")


def _try_generate_cover(book_id: str):
    try:
        from services.cover_service import execute_generate_cover
        log_step(book_id, "register", "开始生成封面图")
        result = execute_generate_cover(book_id, {"version": None, "force": False})
        if result.get("success"):
            if result.get("skipped"):
                log_step(book_id, "register", "封面图已存在，跳过")
            else:
                log_step(book_id, "register",
                         f"封面图生成成功: {result.get('cover_path', '')}")
        else:
            log_step(book_id, "register",
                     f"封面图生成失败: {result.get('error', 'unknown')}", "WARN")
    except Exception as e:
        log_step(book_id, "register", f"封面图生成异常: {e}", "WARN")


def _cleanup_iteration_state(book_id: str):
    if not os.path.exists(STATE_FILE):
        return
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        books = state.get("books", {})
        if book_id in books and books[book_id].get("phase") == "pending":
            del books[book_id]
        active_books = state.get("active_books", [])
        state["active_books"] = [b for b in active_books if b.get("name") != book_id]
        if state["active_books"] != active_books or book_id in books:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _notify_mainrepo(book_id: str, platform: str):
    mainrepo = config.mainrepo_url
    if not mainrepo:
        return
    try:
        import urllib.request
        import urllib.error
        data = json.dumps({
            "novel_name": book_id,
            "platform": platform,
            "is_auto_publish": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{mainrepo.rstrip('/')}/api/task/book-register",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
        log_step(book_id, "register", f"已通知 main-repo 上线: {book_id}")
    except urllib.error.HTTPError as e:
        log_step(book_id, "register",
                 f"通知 main-repo 失败 HTTP {e.code}: {book_id}", "WARN")
    except Exception as e:
        log_step(book_id, "register",
                 f"通知 main-repo 异常: {e}", "WARN")
