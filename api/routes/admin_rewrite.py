"""
Admin route: 正文重写 —— 清除章节正文与纪要，保留 Phase1 + 上帝视角（Phase2 规划）
"""

import os
import glob as glob_mod
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter

from api.models import (
    AdminRewriteRequest,
    AdminRewriteResponse,
    AdminRewriteResult,
)
from services.book_state import (
    load_book_state,
    save_book_state,
    phase_ge,
    BOOKS_DIR,
    load_novel_metadata,
    save_novel_metadata,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin-rewrite"])

_CLEAR_GLOBS = [
    "02-正文/*.md",
    "03-纪要/*.md",
    "04-数据/伏笔状态滚动摘要.md",
]

_RESET_FILES = [
    "伏笔状态滚动摘要.md",
    "自动化处理日志.md",
]


def _version_dir(book_id):
    # type: (str) -> Optional[str]
    import re as _re
    ver_root = os.path.join(BOOKS_DIR, book_id, "versions")
    if not os.path.isdir(ver_root):
        return None
    versions = sorted(
        [d for d in os.listdir(ver_root) if _re.match(r"^v\d+$", d)],
        key=lambda v: int(v[1:]),
    )
    return os.path.join(ver_root, versions[-1]) if versions else None


def _default_foreshadow_text():
    # type: () -> str
    return """# 伏笔状态滚动摘要

> 自动追踪各伏笔的埋设/强化/回收状态，供 content_writer 和 quality_reviewer 使用。
> 重置日期：{date}（正文重写，伏笔状态清零）

## 更新日志

| 日期 | 操作章节 | 操作类型 |
|------|:------:|---------|
| {date} | — | 重置（正文重写） |

---

## A 级伏笔（贯穿全书）

| ID | 内容 | 最新状态 | 最后操作章节 | 说明 |
|:--:|------|:-------:|:----------:|------|
| F-A01 | 苏见微穿越前世的完整身份与创伤 | 待埋设 | — | 计划Ch1轻触埋设 |

## B 级伏笔（跨多卷）

| ID | 内容 | 最新状态 | 最后操作章节 | 说明 |
|:--:|------|:-------:|:----------:|------|
| F-B01 | 苏见微的草药知识来源暗藏玄机 | 待埋设 | — | 计划Ch3埋设 |
| F-B02 | 崔嬷嬷驱逐锦书的背后推手 | 待埋设 | — | 计划Ch6/Ch8埋设 |

## C 级伏笔（卷级/章节级）

| ID | 内容 | 最新状态 | 最后操作章节 | 说明 |
|:--:|------|:-------:|:----------:|------|
| F-C01 | 崔嬷嬷贪墨家财的具体证据 | 待埋设 | — | 计划Ch4埋设 |
| F-C02 | 楚临渊暗中出手的痕迹 | 待埋设 | — | 计划Ch10→Ch18→Ch23 |
| F-C03 | 萧知远商队与苏记的首批合作 | 待埋设 | — | 计划Ch11→Ch13 |
| F-C04 | 沈明堂宗族质疑的原始动机 | 待埋设 | — | 计划Ch14→Ch17 |
| F-C05 | 苏见微药材价格预判布局 | 待埋设 | — | 计划Ch16→Ch21 |
| F-C06 | 姐妹联手的初次配合 | 待埋设 | — | 计划Ch19→Ch22 |
| F-C07 | 第二卷危机暗线 | 待埋设 | — | 计划Ch25轻触埋设 |

---

## 状态图例

| 符号 | 含义 |
|:---:|------|
| 已埋设 | 已完成首次埋设 |
| 已强化 | 已进行过二次或更多次触达 |
| 已回收 | 伏笔已回收/揭晓 |
| 待埋设 | 尚未开始 |
| 已过期 | 超过预定回收周期未回收 |
"""


def _reset_log_text():
    # type: () -> str
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return u"""# 自动化处理日志

## 项目：（已重写初始化）

---

### {now} 正文重写初始化

**操作**：清空全部正文产物，保留上帝视角+章纲+Phase1 产物

下一可执行操作：`执行第1卷第1章生产`
""".format(now=now)


@router.post("/rewrite", response_model=AdminRewriteResponse)
def rewrite_chapters(req: AdminRewriteRequest):
    """清除指定小说的正文 + 纪要，重置 book_state.json chapters，
    保留 Phase1 全部产物和上帝视角（Phase2 规划层）。
    """
    results = []  # type: List[AdminRewriteResult]
    for book_id in req.book_ids:
        try:
            res = _rewrite_one(book_id)
        except Exception as e:
            res = AdminRewriteResult(book_id=book_id, status="error", error=str(e))
        results.append(res)

    ok = sum(1 for r in results if r.status == "ok")
    skipped = sum(1 for r in results if r.status == "skipped")
    errors = sum(1 for r in results if r.status == "error")
    return AdminRewriteResponse(
        results=results,
        summary={"total": len(req.book_ids), "ok": ok, "skipped": skipped, "errors": errors},
    )


def _rewrite_one(book_id):
    # type: (str) -> AdminRewriteResult
    state = load_book_state(book_id)
    if state is None:
        return AdminRewriteResult(book_id=book_id, status="skipped",
                                  error=u"小说未注册或 book_state.json 不存在")

    phase = state.get("phase", "pending")
    if not phase_ge(phase, "phase1_done"):
        return AdminRewriteResult(
            book_id=book_id, status="skipped",
            error=u"当前阶段为 {}，须先完成 Phase1 注册".format(phase),
        )

    ver_dir = _version_dir(book_id)
    if not ver_dir:
        return AdminRewriteResult(book_id=book_id, status="error",
                                  error=u"找不到版本目录")

    chapters_del = 0
    minutes_del = 0
    for pattern in _CLEAR_GLOBS:
        for fp in glob_mod.glob(os.path.join(ver_dir, pattern)):
            try:
                os.remove(fp)
                if "02-正文" in fp:
                    chapters_del += 1
                elif "03-纪要" in fp:
                    minutes_del += 1
            except OSError:
                pass

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ftext = _default_foreshadow_text().replace("{date}", today)
    for rel in _RESET_FILES:
        fp = os.path.join(ver_dir, rel)
        text = None  # type: Optional[str]
        if u"伏笔" in rel:
            text = ftext
        elif u"自动化" in rel or u"日志" in rel:
            text = _reset_log_text()
        if text is not None:
            parent_dir = os.path.dirname(fp)
            if not os.path.isdir(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)
            with open(fp, "w", encoding="utf-8") as f:
                f.write(text)

    data_fp = os.path.join(ver_dir, "04-数据", "伏笔状态滚动摘要.md")
    parent_dir = os.path.dirname(data_fp)
    if not os.path.isdir(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)
    with open(data_fp, "w", encoding="utf-8") as f:
        f.write(ftext)

    meta = load_novel_metadata(book_id, state.get("version", "v1"))
    if meta:
        meta["chapters_completed"] = 0
        meta["chapter_names"] = []
        meta["rewritten_at"] = today
        save_novel_metadata(book_id, state.get("version", "v1"), meta)

    volumes_reset = _reset_book_state(state, book_id)

    return AdminRewriteResult(
        book_id=book_id,
        status="ok",
        chapters_deleted=chapters_del,
        minutes_deleted=minutes_del,
        volumes_reset=volumes_reset,
    )


def _reset_book_state(state, book_id):
    # type: (dict, str) -> List[int]
    ck = state.get("checkpoints", {})
    p2 = ck.get("phase2", {})
    volumes = state.get("volumes", [])
    reset_vols = []  # type: List[int]

    for vol in volumes:
        vol_key = "volume_{}".format(vol["volume"])
        vol_data = p2.get(vol_key, {})
        if isinstance(vol_data, dict):
            if vol_data.get("chapters"):
                vol_data["chapters"] = {}
                reset_vols.append(vol["volume"])

    ck.pop("phase2_done", None)

    state["phase"] = "phase1_done"
    state["quality_avg"] = 0.0
    state["last_error"] = None

    save_book_state(book_id, state)
    return reset_vols
