"""
book_state.json — 确定性状态机（v5 改造）

核心变更:
1. 增加 checkpoints 字段，精确跟踪每个子步骤的完成状态
2. phase 只由 API 在验证所有子步骤完成后设置，禁止 agent 直接写入
3. 所有写入通过 save_book_state() 统一 schema 校验 + atomic write
4. HMAC 签名防伪：只有 Pipeline 写入的文件能通过 load_book_state() 验证
5. 废弃从文件系统扫描/重建逻辑（ensure_book_state 磁盘扫描）
6. find_next_action() 替代 get_next_chapter() 的磁盘扫描
"""

import hashlib
import hmac
import json
import os
import re
import shutil
from datetime import datetime, timezone
from glob import glob
from typing import Any, Dict, List, Optional, Tuple

from config import config

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS_DIR = os.path.join(ROOT_DIR, "workspace", "books")

DEFAULT_RETRY_POLICY = {
    "chapter_max_retries": config.chapter_max_retries,
}

_PIPELINE_KEY = b"novel-editor::pipeline::v5::2026-07-27::hmac-sha256"

_SIG_FIELD = "_pipeline_sig"


def _sign(state: dict) -> str:
    """对 state dict 做 HMAC-SHA256 签名（排除签名自身）"""
    payload = json.dumps(state, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hmac.new(_PIPELINE_KEY, payload, hashlib.sha256).hexdigest()


def _verify(state: dict) -> bool:
    """验证 _pipeline_sig 是否有效"""
    sig = state.pop(_SIG_FIELD, None)
    if not sig or not isinstance(sig, str) or len(sig) != 64:
        return False
    expected = _sign(state)
    return hmac.compare_digest(expected, sig)


def sign_dict(data: dict) -> str:
    """对任意 dict 做 HMAC-SHA256 签名（排除 _pipeline_sig 自身）"""
    return _sign(data)


def verify_dict(data: dict) -> bool:
    """验证 dict 的 _pipeline_sig 是否有效，无效时删除文件"""
    return _verify(data)

PHASE1_STEP_ORDER = [
    "version_decided", "whitepaper", "platform_rules", "style_mapped",
    "facade", "salt", "cover_prompt", "master_outline",
    "diff_constraints",
    "novel_metadata", "cover_generated", "agents_copied",
]

# ── 路径工具 ──────────────────────────────────────────────

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


def _artifact_path(book_id: str, rel_path: str) -> str:
    version_dir = _book_version_dir(book_id)
    if not version_dir:
        version = "v1"
        version_dir = os.path.join(BOOKS_DIR, book_id, "versions", version)
    return os.path.join(version_dir, rel_path)


# ── 空状态模板 ────────────────────────────────────────────

def _empty_state(book_id: str, platform: str = "", track: str = "",
                 version: str = "v1", phase: str = "pending") -> Dict[str, Any]:
    return {
        "book_id": book_id,
        "platform": platform,
        "track": track,
        "phase": phase,
        "version": version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_volumes": None,
        "total_chapters": None,
        "volumes": [],
        "retry_policy": DEFAULT_RETRY_POLICY.copy(),
        "quality_avg": 0.0,
        "last_error": None,
        "checkpoints": {
            "phase1": _empty_phase1_done_checkpoint(),
        },
    }


def _empty_phase1_done_checkpoint():
    p1 = {step: {"status": "pending"} for step in PHASE1_STEP_ORDER}
    p1["phase1_done"] = {"status": "pending"}
    return p1

# ── Schema 校验 ───────────────────────────────────────────


def _validate_state(state: Dict[str, Any]) -> List[str]:
    """校验 book_state.json 顶层结构。返回错误列表。"""
    errors = []
    if not isinstance(state.get("book_id"), str) or not state["book_id"].strip():
        errors.append("book_id is required and must be a non-empty string")
    if not isinstance(state.get("phase"), str) or not state["phase"].strip():
        errors.append("phase is required and must be a non-empty string")
    if not state.get("version"):
        errors.append("version is required")

    vols = state.get("volumes", [])
    if not isinstance(vols, list):
        errors.append("volumes must be a list")
    else:
        for i, vol in enumerate(vols):
            if not isinstance(vol, dict):
                errors.append(f"volumes[{i}] must be a dict, got {type(vol).__name__}")
                continue
            if not isinstance(vol.get("volume"), int):
                errors.append(f"volumes[{i}].volume must be int")
            if not isinstance(vol.get("ch_start"), int):
                errors.append(f"volumes[{i}].ch_start must be int")
            if not isinstance(vol.get("ch_end"), int):
                errors.append(f"volumes[{i}].ch_end must be int")

    if "checkpoints" not in state:
        errors.append("checkpoints field is required")

    return errors


def _compute_quality_avg(state: Dict[str, Any]) -> float:
    """从 phase2 checkpoints 中的 quality.score 重算 quality_avg"""
    scores = []
    p2 = state.get("checkpoints", {}).get("phase2", {})
    if isinstance(p2, dict):
        for vol_key, vol_data in p2.items():
            if not isinstance(vol_data, dict):
                continue
            chapters = vol_data.get("chapters", {})
            if isinstance(chapters, dict):
                for ch_data in chapters.values():
                    if isinstance(ch_data, dict):
                        q = ch_data.get("quality", {})
                        if isinstance(q, dict):
                            try:
                                s = float(q.get("score", 0))
                                if s > 0:
                                    scores.append(s)
                            except (ValueError, TypeError):
                                pass
    return round(sum(scores) / len(scores), 1) if scores else 0.0


# ── 核心读写 ──────────────────────────────────────────────

def load_book_state(book_id: str) -> Optional[Dict[str, Any]]:
    """加载 book_state.json。无有效 HMAC 签名时尝试从 .bak 恢复。"""
    path = _state_path(book_id)
    if not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        state = None

    if state and _verify(state):
        if "checkpoints" not in state:
            state["checkpoints"] = {
                "phase1": _empty_phase1_done_checkpoint(),
            }
        return state

    bak_path = path + ".bak"
    if os.path.exists(bak_path):
        try:
            with open(bak_path, "r", encoding="utf-8") as f:
                bak_state = json.load(f)
        except (json.JSONDecodeError, OSError):
            bak_state = None

        if bak_state and _verify(bak_state):
            shutil.copy2(bak_path, path)
            if "checkpoints" not in bak_state:
                bak_state["checkpoints"] = {
                    "phase1": _empty_phase1_done_checkpoint(),
                }
            return bak_state

    if os.path.exists(path):
        os.remove(path)
    return None


def save_book_state(book_id: str, data: Dict[str, Any]):
    """原子写入 book_state.json，写入前 schema 校验 + HMAC 签名"""

    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    data.pop(_SIG_FIELD, None)

    errors = _validate_state(data)
    if errors:
        raise ValueError("book_state validation failed:\n  - " + "\n  - ".join(errors))

    data["quality_avg"] = _compute_quality_avg(data)

    data[_SIG_FIELD] = _sign(data)

    path = _state_path(book_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
    try:
        shutil.copy2(path, path + ".bak")
    except OSError:
        pass


# ── novel_metadata.json 读写 ───────────────────────────────

def _metadata_path(book_id: str, version: str) -> str:
    return os.path.join(BOOKS_DIR, book_id, "versions", version, "发布", "novel_metadata.json")


def load_novel_metadata(book_id: str, version: str = "v1") -> Optional[Dict[str, Any]]:
    """加载 novel_metadata.json，HMAC 验证失败时尝试从 .bak 恢复。"""
    meta_path = _metadata_path(book_id, version)
    if not os.path.exists(meta_path):
        return None

    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except (json.JSONDecodeError, OSError):
        meta = None

    if meta and verify_dict(meta):
        return meta

    bak_path = meta_path + ".bak"
    if os.path.exists(bak_path):
        try:
            with open(bak_path, "r", encoding="utf-8") as f:
                bak_meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            bak_meta = None

        if bak_meta and verify_dict(bak_meta):
            shutil.copy2(bak_path, meta_path)
            return bak_meta

    return None


def save_novel_metadata(book_id: str, version: str, data: Dict[str, Any]):
    """原子写入 novel_metadata.json + .bak，写入前 HMAC 签名。"""
    meta_path = _metadata_path(book_id, version)
    os.makedirs(os.path.dirname(meta_path), exist_ok=True)

    data.pop(_SIG_FIELD, None)
    data[_SIG_FIELD] = sign_dict(data)

    tmp_path = meta_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, meta_path)
    try:
        shutil.copy2(meta_path, meta_path + ".bak")
    except OSError:
        pass


def converge_novel_metadata(book_id: str) -> bool:
    """收敛 novel_metadata.json 到规范格式：补齐缺失字段 + HMAC 签名。

    三层修复策略：
    1. 已有效签名 → 零开销直接返回
    2. 无签名但文件存在 → raw 读取 → 从 project_salt.json 补齐 tags/track/primary_category
                             → 补空 source.title/source.author → save_novel_metadata() 签名
    3. 文件不存在 → 返回 False（无从修复）

    Returns True if file is valid after convergence, False otherwise.
    """
    state = load_book_state(book_id)
    if state is None:
        return False
    version = state.get("version", "v1")

    meta = load_novel_metadata(book_id, version)
    if meta is not None:
        return True

    meta_path = _metadata_path(book_id, version)
    if not os.path.exists(meta_path):
        return False

    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False

    salt_path = os.path.join(BOOKS_DIR, book_id, "versions", version, "project_salt.json")
    salt = {}
    if os.path.exists(salt_path):
        try:
            with open(salt_path, "r", encoding="utf-8") as f:
                salt = json.load(f)
        except (json.JSONDecodeError, OSError):
            salt = {}

    cls = salt.get("classification") or {}

    if "tags" not in data or not data.get("tags"):
        data["tags"] = cls.get("tags") or []
    if "track" not in data or not data.get("track"):
        data["track"] = salt.get("style_track") or ""
    if "primary_category" not in data or not data.get("primary_category"):
        data["primary_category"] = cls.get("primary_category") or ""

    src = data.setdefault("source", {})
    if not src.get("title"):
        base = salt.get("base_novel") if isinstance(salt.get("base_novel"), dict) else {}
        src["title"] = base.get("title") if base else book_id
    if not src.get("author"):
        base = salt.get("base_novel") if isinstance(salt.get("base_novel"), dict) else {}
        src["author"] = base.get("author") if base else "原作者"

    save_novel_metadata(book_id, version, data)
    return True


def ensure_book_state(book_id: str) -> Dict[str, Any]:
    """加载已有 state 或创建标准空模板。不再做文件系统扫描/重建。"""
    state = load_book_state(book_id)
    if state is not None:
        # 确保 checkpoints 字段存在（兼容旧格式）
        if "checkpoints" not in state:
            state["checkpoints"] = {}
        if "phase1" not in state["checkpoints"]:
            state["checkpoints"]["phase1"] = _empty_phase1_done_checkpoint()
        save_book_state(book_id, state)
        return state

    book_dir = os.path.join(BOOKS_DIR, book_id)
    if not os.path.isdir(book_dir):
        os.makedirs(book_dir, exist_ok=True)

    state = _empty_state(book_id)
    save_book_state(book_id, state)
    return state


# ── Checkpoint 操作 ───────────────────────────────────────

def _ensure_checkpoint_path(state: Dict[str, Any], path: List[str]) -> Dict[str, Any]:
    """确保 checkpoint 嵌套路径存在，返回叶子 dict。
    path: 要遍历的所有中间键（不含最终叶子键）"""
    ck = state.setdefault("checkpoints", {})
    for key in path:
        ck = ck.setdefault(key, {})
    return ck


def set_checkpoint(book_id: str, checkpoint_path: List[str], status: str = "done",
                   **extra) -> Dict[str, Any]:
    """设置一个 checkpoint 为 done/failed/pending。
    
    Args:
        book_id: 书名
        checkpoint_path: checkpoint 路径数组，如 ["phase1", "whitepaper"]
        status: done | failed | pending
        extra: 额外数据写入 checkpoint 节点 (如 path, score, word_count 等)
    """
    state = load_book_state(book_id)
    if state is None:
        raise ValueError(f"Book '{book_id}' not found. Call ensure_book_state() first.")

    # 获取父路径（不含最终键）
    parent = _ensure_checkpoint_path(state, checkpoint_path[:-1])
    node = parent.setdefault(checkpoint_path[-1], {})
    node["status"] = status
    node["at"] = datetime.now(timezone.utc).isoformat()
    node.update(extra)

    save_book_state(book_id, state)
    return node


def get_checkpoint(book_id: str, path: List[str]) -> Optional[Dict[str, Any]]:
    """读取一个 checkpoint 的状态"""
    state = load_book_state(book_id)
    if state is None:
        return None
    ck = state.get("checkpoints", {})
    for key in path:
        if not isinstance(ck, dict):
            return None
        ck = ck.get(key, {})
    return ck if isinstance(ck, dict) else None


def is_checkpoint_done(book_id: str, path: List[str]) -> bool:
    node = get_checkpoint(book_id, path)
    return node is not None and node.get("status") == "done"


# ── Phase 转换验证 ───────────────────────────────────────


def can_set_phase(book_id: str, target_phase: str) -> Tuple[bool, str]:
    """检查是否可以设置目标 phase。返回 (OK, 原因)"""
    state = load_book_state(book_id)
    if state is None:
        return False, f"Book '{book_id}' not found"

    if target_phase == "phase1_done":
        return _verify_phase1_complete(state)
    elif target_phase == "phase2_done":
        return _verify_phase2_complete(state)
    elif target_phase == "phase3_done":
        return True, ""
    elif target_phase == "done":
        return True, ""
    elif target_phase == "pending":
        return True, ""
    return False, f"Unknown target phase: {target_phase}"


def _verify_phase1_complete(state: Dict[str, Any]) -> Tuple[bool, str]:
    """验证 Phase 1 所有步骤是否完成（含文件存在校验 + novel_metadata HMAC/字段校验）"""
    book_id = state["book_id"]
    version = state.get("version", "v1")
    ck = state.get("checkpoints", {}).get("phase1", {})

    for step in PHASE1_STEP_ORDER:
        node = ck.get(step, {})
        if node.get("status") != "done":
            return False, f"Step '{step}' is not done (status={node.get('status','pending')})"

        path = node.get("path", "")
        if path and not os.path.exists(_artifact_path(book_id, path)):
            return False, f"Artifact for step '{step}' not found: {path}"

        if step == "novel_metadata":
            meta = load_novel_metadata(book_id, version)
            if meta is None:
                return False, "novel_metadata.json 未通过 HMAC 校验（缺少签名或签名无效）"
            if not meta.get("description"):
                return False, "novel_metadata.json 缺少 description 字段"
            if not isinstance(meta.get("tags"), list) or not meta.get("tags"):
                return False, "novel_metadata.json 缺少 tags 字段"
            if not meta.get("track"):
                return False, "novel_metadata.json 缺少 track 字段"
            if not meta.get("primary_category"):
                return False, "novel_metadata.json 缺少 primary_category 字段"

    return True, ""


def _verify_phase2_complete(state: Dict[str, Any]) -> Tuple[bool, str]:
    """验证 Phase 2 所有卷是否完成"""
    p2 = state.get("checkpoints", {}).get("phase2", {})
    if not p2:
        return False, "No phase2 checkpoints found"

    for vol_key, vol_data in p2.items():
        if not isinstance(vol_data, dict):
            continue
        chapters = vol_data.get("chapters", {})
        if isinstance(chapters, dict):
            for ch_key, ch_data in chapters.items():
                if isinstance(ch_data, dict):
                    fin = ch_data.get("finalized", {})
                    if fin.get("status") != "done":
                        return False, f"Chapter {ch_key} not finalized in {vol_key}"

    return True, ""


# ── find_next_action: 断点续跑引擎 ─────────────────────────


def find_next_action(book_id: str) -> Dict[str, Any]:
    """扫描 checkpoints，返回第一个未完成的步骤。
    
    Returns:
        {"phase": "phase1", "step": "whitepaper", "status": "pending", ...}
        或 {"phase": "all_done", "step": None}
    """
    state = load_book_state(book_id)
    if state is None:
        return {"phase": "init", "step": "need_ensure_state"}

    current_phase = state.get("phase", "pending")
    ck = state.get("checkpoints", {})

    # Phase 1
    if not phase_ge(current_phase, "phase1_done"):
        p1 = ck.get("phase1", {})
        for step in PHASE1_STEP_ORDER:
            node = p1.get(step, {})
            if node.get("status") != "done":
                path = node.get("path", "")
                return {
                    "phase": "phase1", "step": step, "status": node.get("status", "pending"),
                    "book_id": book_id, "version": state.get("version", "v1"),
                    "artifact_path": path,
                }

    # Phase 1 done 标志
    p1_done = ck.get("phase1", {}).get("phase1_done", {})
    if p1_done.get("status") != "done":
        return {"phase": "phase1", "step": "phase1_done",
                "status": "pending", "book_id": book_id,
                "version": state.get("version", "v1")}

    # Phase 2: 逐卷逐章扫描
    p2 = ck.get("phase2", {})

    # 检查 phase2_done
    p2_done = ck.get("phase2_done", {})
    if p2_done.get("status") == "done":
        return {"phase": "all_done", "step": None, "book_id": book_id}

    # 逐卷扫描
    volumes = state.get("volumes", [])
    for vol in volumes:
        vol_num = vol["volume"]
        vol_key = f"volume_{vol_num}"
        vol_data = p2.get(vol_key, {})

        # volume 级步骤
        for vol_step in ["destiny_global", "destiny_volume", "volume_outline"]:
            node = vol_data.get(vol_step, {})
            if node.get("status") != "done":
                return {
                    "phase": "phase2", "step": vol_step, "volume": vol_num,
                    "status": "pending", "book_id": book_id,
                }

        # 逐章扫描
        for ch_num in range(vol["ch_start"], vol["ch_end"] + 1):
            ch_key = str(ch_num)
            ch_data = vol_data.get("chapters", {}).get(ch_key, {})

            if not ch_data:
                ch_data = {}
                vol_data.setdefault("chapters", {})[ch_key] = ch_data
            elif isinstance(ch_data, dict) and ch_data.get("finalized", {}).get("status") == "done":
                continue

            for ch_step in ["outline", "draft", "finalized", "chapter_name"]:
                node = ch_data.get(ch_step, {})
                if node.get("status") != "done":
                    return {
                        "phase": "phase2", "step": ch_step,
                        "volume": vol_num, "chapter": ch_num,
                        "status": "pending", "book_id": book_id,
                        "version": state.get("version", "v1"),
                    }

        # volume_archived
        arc = vol_data.get("volume_archived", {})
        if arc.get("status") != "done":
            return {
                "phase": "phase2", "step": "volume_archived",
                "volume": vol_num, "status": "pending", "book_id": book_id,
            }

    # 所有卷都完成，标记 phase2_done
    return {
        "phase": "phase2", "step": "phase2_done",
        "status": "pending", "book_id": book_id,
    }


def _sync_volumes_from_master_outline(state: Dict[str, Any], book_id: str) -> bool:
    """从仿写衍生总纲领.md 解析卷结构，填充 state["volumes"]。

    仅当 volumes 为空时执行。解析 §二（平台适配）中的推导卷数行。
    返回 True 表示成功填充，False 表示解析失败或无需填充。
    """
    if state.get("volumes"):
        return False

    version = state.get("version", "v1")
    ver_dir = os.path.join(BOOKS_DIR, book_id, "versions", version)
    outline_path = os.path.join(ver_dir, "仿写衍生总纲领.md")
    if not os.path.exists(outline_path):
        fallback_path = os.path.join(ver_dir, "00-素材", "仿写衍生总纲领.md")
        if os.path.exists(fallback_path):
            outline_path = fallback_path
        else:
            return False

    try:
        with open(outline_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return False

    m = re.search(
        r'推导卷数[：:]\s*(\d+)\s*卷\s*[×xX*]\s*(\d+)\s*章/卷',
        content,
    )
    if not m:
        return False

    total_volumes = int(m.group(1))
    ch_per_vol = int(m.group(2))
    if total_volumes < 1 or ch_per_vol < 1:
        return False

    volumes = []
    for i in range(1, total_volumes + 1):
        ch_start = (i - 1) * ch_per_vol + 1
        ch_end = i * ch_per_vol
        volumes.append({"volume": i, "ch_start": ch_start, "ch_end": ch_end})

    state["total_volumes"] = total_volumes
    state["total_chapters"] = total_volumes * ch_per_vol
    state["volumes"] = volumes
    return True


def try_set_phase(book_id: str, target_phase: str) -> Tuple[bool, str]:
    """原子设置 phase，前提是所有 prerequisite checkpoints 已 done"""
    ok, reason = can_set_phase(book_id, target_phase)
    if not ok:
        return False, reason

    state = load_book_state(book_id)

    if target_phase == "phase1_done":
        synced = _sync_volumes_from_master_outline(state, book_id)
        if synced:
            from services.log_service import get_logger
            get_logger(book_id).info(
                "[P1:sync_vol]",
                f"从总纲同步卷结构: {state['total_volumes']}卷 × "
                f"{state['total_chapters'] // state['total_volumes']}章/卷",
            )

    state["phase"] = target_phase
    save_book_state(book_id, state)

    if target_phase == "phase1_done":
        set_checkpoint(book_id, ["phase1", "phase1_done"], status="done")
    elif target_phase == "phase2_done":
        set_checkpoint(book_id, ["phase2_done"], status="done")

    return True, "ok"


def get_book_phase(book_id: str) -> str:
    state = load_book_state(book_id)
    return state.get("phase", "pending") if state else "pending"


def list_all_books() -> List[str]:
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
    _ORDER = {"pending": 0, "phase1_done": 1, "phase2_done": 2, "phase3_done": 3, "done": 4}
    return _ORDER.get(current, -1) >= _ORDER.get(required, 999)


def get_next_chapter(book_id: str) -> Optional[Dict[str, Any]]:
    """返回第一个未完成的章节及其第一个未完成的子步骤。
    
    Returns:
        None 或 {"global_chapter": int, "volume": int, "resume_step": str}
        resume_step 为第一个 pending 子步骤名: outline/draft/finalized/chapter_name
    """
    state = load_book_state(book_id)
    if state is None:
        return None

    p2 = state.get("checkpoints", {}).get("phase2", {})
    volumes = state.get("volumes", [])

    CHAPTER_STEPS = ["outline", "draft", "finalized", "chapter_name"]

    for vol in volumes:
        vol_num = vol["volume"]
        vol_key = f"volume_{vol_num}"
        vol_data = p2.get(vol_key, {})

        for ch_num in range(vol["ch_start"], vol["ch_end"] + 1):
            ch_key = str(ch_num)
            ch_data = vol_data.get("chapters", {}).get(ch_key, {})
            if not ch_data:
                return {"global_chapter": ch_num, "volume": vol_num, "resume_step": "outline"}

            if ch_data.get("finalized", {}).get("status") == "done":
                continue

            for step in CHAPTER_STEPS:
                node = ch_data.get(step, {})
                if node.get("status") != "done":
                    return {"global_chapter": ch_num, "volume": vol_num, "resume_step": step}

            return {"global_chapter": ch_num, "volume": vol_num, "resume_step": "outline"}

    return None


def _count_words(path: str) -> int:
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        return len(re.sub(r"\s+", "", text))
    except Exception:
        return 0


_CN_DIGIT_MAP = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15,
    "十六": 16, "十七": 17, "十八": 18, "十九": 19, "二十": 20,
}


def _parse_volume_id(vol_str: str) -> int:
    """Parse volume number from string like '1', 'V1', 'v1', '卷一', '卷 一', '第一卷', etc.
    Returns int or 0 if unparseable.
    """
    vol_str = vol_str.strip()
    if not vol_str:
        return 0
    # ASCII digit format: '1', 'V1', 'v1'
    m = re.match(r"[Vv]?(\d+)", vol_str)
    if m:
        return int(m.group(1))
    # Chinese numeral format: '卷N' where N is Chinese digit
    m = re.match(r"卷\s*([一二三四五六七八九十百]+)", vol_str)
    if not m:
        # Also handle '第N卷' format
        m = re.match(r"第\s*([一二三四五六七八九十百]+)\s*卷", vol_str)
    if m:
        cn = m.group(1)
        if cn in _CN_DIGIT_MAP:
            return _CN_DIGIT_MAP[cn]
        # Handle multi-digit Chinese numbers like '十二' (already in map)
        # Handle '二十' and '二十X' patterns
        if cn == "二十":
            return 20
        if cn.startswith("二十"):
            suffix = cn[2:]
            if suffix in _CN_DIGIT_MAP:
                return 20 + _CN_DIGIT_MAP[suffix]
        if cn.startswith("三十"):
            suffix = cn[2:]
            if suffix in _CN_DIGIT_MAP:
                return 30 + _CN_DIGIT_MAP[suffix]
    return 0


def populate_volumes_from_god_eye(state: dict, book_id: str) -> dict:
    """从 上帝之眼/00-全书命运总谱.md 解析卷结构。
    返回 {total_volumes, total_chapters, volumes: [{volume, ch_start, ch_end}]}
    解析失败返回空 dict。
    
    这是确定性数据解析，不是补丁。God's Eye 由 @destiny_designer agent 生成，
    但 volumes 数据的提取由 Pipeline Python 代码完成，不依赖 agent。
    """
    ver_dir = _book_version_dir(book_id)
    if not ver_dir:
        return {}

    fate_path = os.path.join(ver_dir, "上帝之眼", "00-全书命运总谱.md")
    if not os.path.exists(fate_path):
        return {}

    try:
        with open(fate_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return {}

    # 解析表格行：| 卷号 | ... | 章数 | ...
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
            vol_id = _parse_volume_id(vol_str)
            if vol_id == 0:
                continue

            # 章数列在 col[3] 或 col[4]
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

    # 去重
    seen = set()
    deduped = []
    for vid, cnt in volumes_raw:
        if vid not in seen:
            seen.add(vid)
            deduped.append((vid, cnt))

    if not deduped:
        return {}

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

    # 赋回每个章节的 volume 号
    for ch_key, ch_data in state.get("chapters", {}).items():
        gch = int(ch_key)
        for vol in volumes:
            if vol["ch_start"] <= gch <= vol["ch_end"]:
                ch_data["volume"] = vol["volume"]
                break

    return {
        "total_volumes": len(volumes),
        "total_chapters": cumulative,
        "volumes": volumes,
    }
