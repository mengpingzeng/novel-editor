"""
流水线日志系统 — 双轨制（模版 + 实例）

- 模版层: 从 config/pipeline_template.json 读取，定义每一步的预期流程
- 实例层: 每本书的 workspace/books/{book_id}/pipeline.log

服务启动时输出完整模版到日志，方便判断进度。
运行时每步日志使用相同的 step_id 对齐模版。
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = ROOT_DIR / "config" / "pipeline_template.json"


def load_template() -> Dict[str, Any]:
    if not TEMPLATE_PATH.exists():
        return {}
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def print_template_summary():
    """服务启动时打印流水线模版概览，作为'预期行为说明书'"""
    tpl = load_template()
    if not tpl:
        print("[LOG] 流水线模版未找到")
        return

    print("=" * 70)
    print(f"  流水线模版: {tpl.get('pipeline_name', 'unknown')} (v{tpl.get('version','?')})")
    print(f"  {tpl.get('description','')}")
    print("=" * 70)

    for phase_key in ["phase0", "phase1", "phase2"]:
        phase = tpl["phases"].get(phase_key, {})
        if not phase:
            continue
        print(f"\n── {phase['label']} ──")

        if phase_key == "phase2":
            _print_phase2_template(phase)
        else:
            for step_key, step in phase.get("steps", {}).items():
                _print_step(step)

    print("\n" + "=" * 70)
    print("  以上为流水线标准模版。实际执行日志将使用相同 step_id 对齐。")
    print("=" * 70)


def _print_step(step: dict):
    sid = step.get("step_id", "?")
    label = step.get("label", "?")
    produces = " → ".join(step.get("produces", []))
    agent = step.get("agent", step.get("skill", ""))
    if agent:
        print(f"  {sid} {label}\n       调用: {agent}\n       产物: {produces or '(无文件产物)'}")
    else:
        print(f"  {sid} {label}\n       产物: {produces or '(无文件产物)'}")


def _print_phase2_template(phase: dict):
    per_vol = phase.get("per_volume_steps", {})
    for step_key in ["destiny_global", "destiny_volume", "volume_outline"]:
        s = per_vol.get(step_key)
        if s:
            _print_step(s)

    ch = per_vol.get("chapters", {})
    if ch:
        print(f"  [P2:vN:chN] 章节循环 (每章重复)")
        for sub_key, sub_step in ch.get("sub_steps", {}).items():
            print(f"         └─ [{sub_key}] {sub_step['label']}")
            prod = " → ".join(sub_step.get("produces", []))
            print(f"              调用: {sub_step.get('agent','')}")
            print(f"              产物: {prod or '(无文件产物)'}")

    for step_key in ["volume_archived", "phase2_done"]:
        s = per_vol.get(step_key)
        if s:
            _print_step(s)

    done = phase.get("phase2_done")
    if done:
        _print_step(done)


# ── 实例日志 ──────────────────────────────────────────────


class PipelineLogger:
    """单本小说的流水线日志"""

    def __init__(self, book_id: str):
        self.book_id = book_id
        self._log_path = ROOT_DIR / "workspace" / "books" / book_id / "pipeline.log"

    def _write(self, level: str, step_id: str, message: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        os.makedirs(self._log_path.parent, exist_ok=True)
        line = f"[{ts}] [{level}] {step_id} {message}\n"
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(line)
        print(f"  {step_id} {message}")

    def start(self, step_id: str, label: str):
        self._write("INFO", step_id, f"开始: {label}")

    def skip(self, step_id: str, label: str, reason: str = "已完成"):
        self._write("INFO", step_id, f"跳过: {label} ({reason})")

    def done(self, step_id: str, label: str, detail: str = ""):
        msg = f"完成: {label}"
        if detail:
            msg += f" | {detail}"
        self._write("OK", step_id, msg)

    def fail(self, step_id: str, label: str, error: str):
        self._write("FAIL", step_id, f"失败: {label} — {error}")

    def warn(self, step_id: str, message: str):
        self._write("WARN", step_id, message)

    def info(self, step_id: str, message: str):
        self._write("INFO", step_id, message)


_loggers: Dict[str, PipelineLogger] = {}


def get_logger(book_id: str) -> PipelineLogger:
    if book_id not in _loggers:
        _loggers[book_id] = PipelineLogger(book_id)
    return _loggers[book_id]


def print_book_progress(book_id: str, checkpoints: dict):
    """打印单本书当前进度概览"""
    print(f"\n── 《{book_id}》当前进度 ──")
    p1 = checkpoints.get("phase1", {})
    done_1 = sum(1 for v in p1.values() if isinstance(v, dict) and v.get("status") == "done")
    total_1 = len(p1)
    print(f"  Phase 1: {done_1}/{total_1} steps done")

    p2 = checkpoints.get("phase2", {})
    if p2:
        for vol_key, vol_data in p2.items():
            ch_data = vol_data.get("chapters", {})
            done_ch = sum(1 for c in ch_data.values() if c.get("finalized", {}).get("status") == "done")
            total_ch = len(ch_data)
            if total_ch > 0:
                print(f"    {vol_key}: {done_ch}/{total_ch} chapters finalized")
    print()
