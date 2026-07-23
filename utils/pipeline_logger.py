"""
流水线日志 — sh/http 共享日志模块。

写入 workspaced/books/{book_id}/pipeline.log，格式:
    [2026-07-21 20:50:14] [INFO] [register] 开始注册

Shell 脚本通过同类格式写同一文件，实现日志共写。
"""

import os
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS_DIR = os.path.join(ROOT_DIR, "workspace", "books")

LOG_FORMAT = "[{timestamp}] [{level}] [{step}] {message}\n"


def log_step(book_id: str, step: str, message: str, level: str = "INFO"):
    """写入一条流水线日志。线程安全依赖 OS 行级原子写入。"""
    log_dir = os.path.join(BOOKS_DIR, book_id)
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "pipeline.log")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = LOG_FORMAT.format(
        timestamp=timestamp,
        level=level,
        step=step,
        message=message,
    )
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)
