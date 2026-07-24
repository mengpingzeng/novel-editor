import os
import sqlite3
import threading
from typing import List

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT_DIR, "workspace", "novel_editor.db")

_local = threading.local()


def _get_conn():
    # type: () -> sqlite3.Connection
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
    return _local.conn


def init_db():
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS catalog_books (
            book_id   TEXT PRIMARY KEY,
            added_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()


def catalog_add(book_ids):
    # type: (List[str]) -> List[str]
    conn = _get_conn()
    inserted = []
    for bid in book_ids:
        try:
            conn.execute("INSERT OR IGNORE INTO catalog_books (book_id) VALUES (?)", (bid,))
            if conn.total_changes > 0:
                inserted.append(bid)
        except Exception:
            pass
    conn.commit()
    return inserted


def catalog_remove(book_ids):
    # type: (List[str]) -> List[str]
    conn = _get_conn()
    removed = []
    for bid in book_ids:
        cur = conn.execute("DELETE FROM catalog_books WHERE book_id = ?", (bid,))
        if cur.rowcount > 0:
            removed.append(bid)
    conn.commit()
    return removed


def catalog_list_ids():
    # type: () -> List[str]
    conn = _get_conn()
    rows = conn.execute("SELECT book_id FROM catalog_books ORDER BY added_at").fetchall()
    return [r["book_id"] for r in rows]


def catalog_contains(book_id):
    # type: (str) -> bool
    conn = _get_conn()
    row = conn.execute("SELECT 1 FROM catalog_books WHERE book_id = ?", (book_id,)).fetchone()
    return row is not None
