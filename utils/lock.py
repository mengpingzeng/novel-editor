"""
Per-book flock-based mutex.

Usage:
    lock = BookLock("甄嬛传")
    if lock.acquire():
        try:
            # write chapter...
        finally:
            lock.release()

    # or as context manager:
    with BookLock("甄嬛传") as _:
        # write chapter...
"""

import fcntl
import os
from typing import Optional

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS_DIR = os.path.join(ROOT_DIR, "workspace", "books")


class BookLock:
    def __init__(self, book_id: str):
        self.lock_path = os.path.join(BOOKS_DIR, book_id, ".write_lock")
        self.fd: Optional[int] = None

    def acquire(self, nonblocking: bool = True) -> bool:
        os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
        self.fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        flags = fcntl.LOCK_EX
        if nonblocking:
            flags |= fcntl.LOCK_NB
        try:
            fcntl.flock(self.fd, flags)
            return True
        except BlockingIOError:
            os.close(self.fd)
            self.fd = None
            return False

    def release(self):
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        if not self.acquire(nonblocking=True):
            raise BlockingIOError(f"Book {self.lock_path} is locked by another process")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False
