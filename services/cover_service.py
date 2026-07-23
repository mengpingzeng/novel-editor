"""
封面生成服务 — 与 batch_generate_covers.sh 逻辑一致。

流程:
1. 定位 cover_prompt.json
2. 读取 prompt
3. 检查是否已有封面（> 10KB），force=False 时跳过
4. 调用 generate_cover.py 生成图片
5. 更新 novel_metadata.json
"""

import json
import os
import re
import sys
from typing import Any, Dict, Optional

from config import config

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS_DIR = os.path.join(ROOT_DIR, "workspace", "books")
SCRIPTS_DIR = os.path.join(ROOT_DIR, "scripts")

COVER_PROMPT_REL = os.path.join("00-素材", "cover_prompt.json")
PUBLISH_DIR_REL = "发布"
COVER_FILENAME = "cover.png"
METADATA_FILENAME = "novel_metadata.json"
MIN_COVER_SIZE = 10240


def submit_cover_task(book_id: str, version: Optional[str] = None,
                      force: bool = False) -> str:
    from worker.task_queue import task_queue as tq
    return tq.submit("generate_cover", book_id, {
        "version": version,
        "force": force,
    })


def execute_generate_cover(book_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
    version = params.get("version")
    force = params.get("force", False)

    ver_dir = _resolve_version_dir(book_id, version)
    if not ver_dir:
        return {"success": False, "error": f"Book '{book_id}' not found or has no versions"}

    prompt_path = os.path.join(ver_dir, COVER_PROMPT_REL)
    if not os.path.exists(prompt_path):
        return {
            "success": False,
            "error": f"cover_prompt.json not found: {prompt_path}. "
                     "Run cover_prompt_generator agent first."
        }

    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt_data = json.load(f)
    prompt = prompt_data.get("prompt", "")
    if not prompt:
        return {"success": False, "error": "cover_prompt.json has empty 'prompt' field"}

    publish_dir = os.path.join(ver_dir, PUBLISH_DIR_REL)
    cover_path = os.path.join(publish_dir, COVER_FILENAME)

    if not force and os.path.exists(cover_path) and os.path.getsize(cover_path) > MIN_COVER_SIZE:
        return {"success": True, "skipped": True,
                "message": "Cover already exists", "cover_path": cover_path}

    os.makedirs(publish_dir, exist_ok=True)

    sys.path.insert(0, SCRIPTS_DIR)
    import generate_cover as cover_gen

    try:
        cover_gen.generate_cover(prompt, cover_path)
    except cover_gen.CoverError as e:
        return {"success": False, "error": str(e)}

    _update_metadata(publish_dir)

    return {"success": True, "cover_path": cover_path}


def _resolve_version_dir(book_id: str, version: Optional[str]) -> Optional[str]:
    book_dir = os.path.join(BOOKS_DIR, book_id)
    versions_dir = os.path.join(book_dir, "versions")
    if not os.path.isdir(versions_dir):
        return None

    all_versions = sorted(
        [d for d in os.listdir(versions_dir) if re.match(r"^v\d+$", d)],
        key=lambda v: int(v[1:]),
    )
    if not all_versions:
        return None

    if version:
        if version in all_versions:
            return os.path.join(versions_dir, version)
        return None

    return os.path.join(versions_dir, all_versions[-1])


def _update_metadata(publish_dir: str):
    metadata_path = os.path.join(publish_dir, METADATA_FILENAME)
    if not os.path.exists(metadata_path):
        return

    with open(metadata_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    data["cover_image"] = "./cover.png"
    data["cover_generated_by"] = "gemini-3.1-flash-image-preview"
    data["cover_resolution"] = "3:4 (1K)"

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
