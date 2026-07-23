#!/usr/bin/env python3
"""封面生成脚本：调用 ToAPIs Gemini 3.1 Flash Image 生成小说封面"""
import argparse
import json
import random
import sys
import time
from pathlib import Path

import requests


class CoverError(Exception):
    """封面生成异常"""
    pass


API_KEY = "sk-T0PSDm03ivBdFZxhxEXah7Huvg63ckNojgd8g91384BhwN8d"
API_BASE = "https://toapis.com"
MODEL = "gemini-3.1-flash-image-preview"
SIZE = "3:4"
RESOLUTION = "1K"
POLL_INTERVAL = 5
POLL_INTERVAL_MAX = 10
MAX_WAIT = 180

SESSION = requests.Session()
SESSION.headers.update({
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
    "User-Agent": "novel-editor/1.0",
})


def submit_task(prompt):
    body = {
        "model": MODEL,
        "prompt": prompt,
        "size": SIZE,
        "n": 1,
        "metadata": {
            "resolution": RESOLUTION,
            "personGeneration": "ALLOW_ADULT",
        },
    }
    resp = SESSION.post(f"{API_BASE}/v1/images/generations", json=body)
    if resp.status_code != 200:
        raise CoverError(f"提交任务失败 ({resp.status_code}): {resp.text}")
    result = resp.json()
    task_id = result.get("id")
    if not task_id:
        raise CoverError(f"提交任务失败，未获取到 task_id: {json.dumps(result, ensure_ascii=False)}")
    return task_id


def poll_task(task_id):
    start = time.time()
    while time.time() - start < MAX_WAIT:
        resp = SESSION.get(f"{API_BASE}/v1/images/generations/{task_id}")
        if resp.status_code != 200:
            raise CoverError(f"查询任务失败 ({resp.status_code}): {resp.text}")
        result = resp.json()
        status = result.get("status")
        progress = result.get("progress", 0)
        print(f"  [状态] {status} (进度 {progress}%)", file=sys.stderr)

        if status == "completed":
            try:
                return result["result"]["data"][0]["url"]
            except (KeyError, IndexError, TypeError):
                raise CoverError(f"任务完成但未获取到图片URL: {json.dumps(result, ensure_ascii=False)}")
        elif status == "failed":
            error = result.get("error", {})
            raise CoverError(f"生成失败: {error.get('message', '未知错误')}")

        if status in ("cancelled", "canceled"):
            raise CoverError("任务已取消")

        sleep_time = POLL_INTERVAL + random.uniform(0, POLL_INTERVAL_MAX - POLL_INTERVAL)
        time.sleep(sleep_time)

    raise CoverError(f"任务超时（{MAX_WAIT}秒），task_id: {task_id}")


def generate_cover(prompt: str, output: str) -> str:
    """生成封面（可导入调用）。返回输出文件路径。"""
    print(f"提交生成任务...", file=sys.stderr)
    task_id = submit_task(prompt)
    print(f"任务 ID: {task_id}", file=sys.stderr)

    image_url = poll_task(task_id)
    print(f"下载图片: {image_url}", file=sys.stderr)

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img_resp = requests.get(image_url, timeout=30)
    img_resp.raise_for_status()
    output_path.write_bytes(img_resp.content)

    size_kb = output_path.stat().st_size / 1024
    print(f"封面已生成: {output_path} ({size_kb:.1f} KB)")

    return str(output_path)


def main():
    parser = argparse.ArgumentParser(description="封面生成 (ToAPIs Gemini 3.1 Flash)")
    parser.add_argument("--prompt", required=True, help="中文封面描述")
    parser.add_argument("--output", required=True, help="输出图片路径，如 ./cover.png")
    parser.add_argument("--negative-prompt", default=None, help="（已忽略，新模型不支持反向提示词）")
    parser.add_argument("--style", default=None, help="（已忽略，新模型通过 prompt 控制风格）")
    args = parser.parse_args()

    try:
        generate_cover(args.prompt, args.output)
    except CoverError as e:
        raise SystemExit(str(e))


if __name__ == "__main__":
    main()
