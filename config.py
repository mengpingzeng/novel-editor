"""
Centralized configuration — reads config.json, overridable via env vars.

Usage:
    from config import config
    print(config.max_concurrent_books)
    print(config.chapter_timeout)

Priority: env var > config.json > hardcoded default
"""

import json
import os

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT_DIR, "config.json")


def _load() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


class Config:
    def __init__(self):
        self._data = _load()

    def _int(self, env_key: str, json_path: tuple, default: int) -> int:
        env_val = os.environ.get(env_key)
        if env_val is not None:
            return int(env_val)
        node = self._data
        for key in json_path:
            node = node.get(key, {})
        val = node if isinstance(node, (int, float)) else default
        return int(val)

    def _str(self, env_key: str, json_path: tuple, default: str) -> str:
        env_val = os.environ.get(env_key)
        if env_val is not None:
            return env_val
        node = self._data
        for key in json_path:
            node = node.get(key, {})
        return str(node) if isinstance(node, str) else default

    @property
    def server_host(self) -> str:
        return self._str("NOVEL_EDITOR_HOST", ("server", "host"), "0.0.0.0")

    @property
    def server_port(self) -> int:
        return self._int("NOVEL_EDITOR_PORT", ("server", "port"), 19080)

    @property
    def max_concurrent_books(self) -> int:
        return self._int("NOVEL_EDITOR_MAX_CONCURRENT_BOOKS",
                         ("concurrency", "max_concurrent_books"), 2)

    @property
    def chapter_max_retries(self) -> int:
        return self._int("CHAPTER_MAX_RETRIES",
                         ("retry", "chapter_max_retries"), 3)

    @property
    def phase1_timeout(self) -> int:
        return self._int("PHASE1_TIMEOUT",
                         ("timeout", "phase1_seconds"), 3600)

    @property
    def chapter_timeout(self) -> int:
        return self._int("CHAPTER_TIMEOUT",
                         ("timeout", "chapter_seconds"), 1800)

    @property
    def cover_timeout(self) -> int:
        return self._int("COVER_TIMEOUT",
                         ("timeout", "cover_seconds"), 300)

    @property
    def mainrepo_url(self) -> str:
        return self._str("MAINREPO_URL",
                         ("mainrepo", "url"), "http://localhost:8088")

    def as_dict(self) -> dict:
        return {
            "server": {
                "host": self.server_host,
                "port": self.server_port,
            },
            "concurrency": {
                "max_concurrent_books": self.max_concurrent_books,
            },
            "retry": {
                "chapter_max_retries": self.chapter_max_retries,
            },
            "timeout": {
                "phase1_seconds": self.phase1_timeout,
                "chapter_seconds": self.chapter_timeout,
                "cover_seconds": self.cover_timeout,
            },
        }


config = Config()
