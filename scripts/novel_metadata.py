#!/usr/bin/env python3
"""novel_metadata.json 管理工具

功能：
  1. create  — 创建初始 JSON（含书名验证：无特殊符号、5个不重名）
  2. add-chapter — 追加章节名（含重名检测 + 特殊符号检测）
  3. check-name — 检查名称是否符合规范（无特殊符号、无重名）

所有操作仅通过 argparse CLI 调用，不做任何 AI 交互。
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List


# ── 名称验证 ──────────────────────────────────────────────

def has_special_chars(name: str) -> bool:
    """检测是否包含特殊符号（中英文标点、空格以外的一切特殊字符）。
    允许：中文、英文、数字、中文标点、英文标点（.,!?;:等）、空格
    不允许：制表符、换行、emoji、不可见字符等
    """
    allowed = re.compile(
        r'^[\u4e00-\u9fff\u3400-\u4dbf'  # 中文
        r'a-zA-Z0-9'                      # 英文数字
        r'\u3000-\u303f'                  # CJK 标点
        r'\uff00-\uffef'                  # 全角符号
        r'\.,!?;:\-—…、。，！？；：《》「」『』【】""''（）…～·'  # 常用标点
        r'\s'                             # 空格
        r']+$'
    )
    if not allowed.match(name):
        return True
    # 额外检查：书名不允许纯空格/纯标点
    stripped = re.sub(r'[\s\.,!?;:\-—…、。，！？；：《》「」『』【】""''（）…～·]', '', name)
    if len(stripped) == 0:
        return True
    return False


def validate_names(names, label="名称"):
    # type: (List[str], str) -> List[str]
    """验证名称列表，返回错误列表。"""
    errors = []
    seen = set()
    for name in names:
        name = name.strip()
        if not name:
            errors.append(f"{label}不能为空")
            continue
        if has_special_chars(name):
            errors.append(f"{label}「{name}」包含不允许的特殊符号")
            continue
        if name in seen:
            errors.append(f"{label}「{name}」重复，每条{label}必须唯一")
            continue
        seen.add(name)
    return errors


# ── 文件操作 ──────────────────────────────────────────────

def load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path: str, data: dict):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[OK] 已写入 {path}")


# ── CLI 命令 ──────────────────────────────────────────────

def cmd_create(args):
    """创建 novel_metadata.json"""
    path = args.path
    titles = args.title

    if len(titles) < 5:
        print(f"[FAIL] 书名数量不足：需要至少 5 个，实际 {len(titles)} 个", file=sys.stderr)
        sys.exit(1)

    errors = validate_names(titles, "书名")
    if errors:
        for e in errors:
            print(f"[FAIL] {e}", file=sys.stderr)
        sys.exit(1)

    if os.path.exists(path):
        print(f"[FAIL] 文件已存在：{path}，如需覆盖请先删除", file=sys.stderr)
        sys.exit(1)

    data = {
        "title": titles,
        "title_en": args.title_en or "",
        "source": {
            "title": args.source_title or "",
            "author": args.source_author or "",
            "year": args.source_year or 2020,
            "public_domain": args.public_domain if args.public_domain is not None else True
        },
        "description": args.description or "",
        "description_en": args.description_en or "",
        "cover_image": args.cover_image or "./cover.png",
        "cover_prompt": args.cover_prompt or "",
        "genre": args.genre or "",
        "genre_en": args.genre_en or "",
        "word_count_target": args.word_count_target or 150000,
        "total_chapters": args.total_chapters or 60,
        "chapters_completed": 0,
        "shadow_intensity": args.shadow_intensity if args.shadow_intensity is not None else 0.5,
        "protagonist": args.protagonist or "",
        "setting": args.setting or "",
        "chapter_names": [],
        "cover_generated_by": args.cover_generated_by or "gemini-3.1-flash-image-preview",
        "cover_resolution": args.cover_resolution or "3:4 (1K)",
        "created_at": datetime.now().strftime("%Y-%m-%d")
    }
    save_json(path, data)
    print(f"[OK] novel_metadata.json 创建成功，包含 {len(titles)} 个书名")


def cmd_add_chapter(args):
    """追加章节名到 novel_metadata.json"""
    path = args.path
    chapter_name = args.name.strip()

    if not os.path.exists(path):
        print(f"[FAIL] 文件不存在：{path}", file=sys.stderr)
        sys.exit(1)

    data = load_json(path)

    # 特殊符号检查
    errors = validate_names([chapter_name], "章节名")
    if errors:
        for e in errors:
            print(f"[FAIL] {e}", file=sys.stderr)
        sys.exit(1)

    # 重名检查
    existing = data.get("chapter_names", [])
    if chapter_name in existing:
        print(f"[FAIL] 章节名「{chapter_name}」已存在（第 {existing.index(chapter_name) + 1} 章），请重新生成", file=sys.stderr)
        sys.exit(2)  # 返回码 2 = 重名，调用方需重新生成章名

    existing.append(chapter_name)
    data["chapter_names"] = existing
    data["chapters_completed"] = len(existing)
    save_json(path, data)
    print(f"[OK] 章节名「{chapter_name}」已添加（第 {len(existing)} 章）")


def cmd_check_name(args):
    """检查名称是否可用（不修改文件）"""
    path = args.path
    name = args.name.strip()

    # 特殊符号检查
    if has_special_chars(name):
        print(f"[FAIL] 名称包含不允许的特殊符号", file=sys.stderr)
        sys.exit(1)

    # 书名重名检查
    if args.check_type == "title":
        data = load_json(path)
        titles = data.get("title", [])
        if name in titles:
            print(f"[FAIL] 书名「{name}」与已有书名重复", file=sys.stderr)
            sys.exit(2)
        print(f"[OK] 书名「{name}」可用")

    # 章节名重名检查
    elif args.check_type == "chapter":
        data = load_json(path)
        chapter_names = data.get("chapter_names", [])
        if name in chapter_names:
            idx = chapter_names.index(name) + 1
            print(f"[FAIL] 章节名「{name}」已存在（第 {idx} 章）", file=sys.stderr)
            sys.exit(2)
        print(f"[OK] 章节名「{name}」可用")

    else:
        print(f"[FAIL] 未知检查类型：{args.check_type}", file=sys.stderr)
        sys.exit(1)


# ── CLI 入口 ──────────────────────────────────────────────

def cmd_record_input(args):
    """记录某个环节的输入文件大小到 input_monitor.json"""
    path = args.path
    stage = args.stage
    chapter = args.chapter
    total_bytes = args.bytes

    data = load_json(path)
    if not data:
        data = {"stages": {}}

    stages = data.setdefault("stages", {})
    if stage not in stages:
        stages[stage] = {"input_files": args.input_files.split(",") if args.input_files else [], "records": []}

    stages[stage]["records"].append({
        "timestamp": datetime.now().isoformat(),
        "chapter": chapter,
        "total_bytes": total_bytes
    })

    save_json(path, data)
    print(f"[OK] 记录 {stage} 第{chapter}章输入大小: {total_bytes} bytes")


def main():
    parser = argparse.ArgumentParser(description="novel_metadata.json 管理工具")
    subparsers = parser.add_subparsers(dest="command")

    # create
    p_create = subparsers.add_parser("create", help="创建 novel_metadata.json")
    p_create.add_argument("--path", required=True, help="JSON 文件路径")
    p_create.add_argument("--title", nargs="+", required=True, help="书名列表（至少 5 个）")
    p_create.add_argument("--title-en", default=None)
    p_create.add_argument("--source-title", default=None)
    p_create.add_argument("--source-author", default=None)
    p_create.add_argument("--source-year", type=int, default=None)
    p_create.add_argument("--public-domain", type=bool, default=None)
    p_create.add_argument("--description", default=None)
    p_create.add_argument("--description-en", default=None)
    p_create.add_argument("--cover-image", default=None)
    p_create.add_argument("--cover-prompt", default=None)
    p_create.add_argument("--genre", default=None)
    p_create.add_argument("--genre-en", default=None)
    p_create.add_argument("--word-count-target", type=int, default=None)
    p_create.add_argument("--total-chapters", type=int, default=None)
    p_create.add_argument("--shadow-intensity", type=float, default=None)
    p_create.add_argument("--protagonist", default=None)
    p_create.add_argument("--setting", default=None)
    p_create.add_argument("--cover-generated-by", default=None)
    p_create.add_argument("--cover-resolution", default=None)

    # add-chapter
    p_add = subparsers.add_parser("add-chapter", help="追加章节名")
    p_add.add_argument("--path", required=True, help="JSON 文件路径")
    p_add.add_argument("--name", required=True, help="章节名")

    # check-name
    p_check = subparsers.add_parser("check-name", help="检查名称是否可用")
    p_check.add_argument("--path", required=True, help="JSON 文件路径")
    p_check.add_argument("--name", required=True, help="要检查的名称")
    p_check.add_argument("--check-type", required=True, choices=["title", "chapter"], help="检查类型")

    # record-input
    p_record = subparsers.add_parser("record-input", help="记录输入文件大小")
    p_record.add_argument("--path", required=True, help="input_monitor.json 路径")
    p_record.add_argument("--stage", required=True, help="环节名称（如 plot_planner / content_writer）")
    p_record.add_argument("--chapter", required=True, type=int, help="章节号")
    p_record.add_argument("--bytes", required=True, type=int, help="输入文件总字节数")
    p_record.add_argument("--input-files", default=None, help="输入文件列表，逗号分隔")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "create":
        cmd_create(args)
    elif args.command == "add-chapter":
        cmd_add_chapter(args)
    elif args.command == "check-name":
        cmd_check_name(args)
    elif args.command == "record-input":
        cmd_record_input(args)


if __name__ == "__main__":
    main()
