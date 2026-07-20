#!/usr/bin/env bash
# ============================================================
# batch_generate_covers.sh — 批量封面生成脚本
#
# 扫描所有 workspace/books/*/versions/v*/00-素材/cover_prompt.json，
# 调用 generate_cover.py 生成封面并更新 novel_metadata.json。
#
# 用法:
#   bash scripts/batch_generate_covers.sh                    # 全部书
#   bash scripts/batch_generate_covers.sh --book 春夜困渡     # 仅指定书
#   bash scripts/batch_generate_covers.sh --retry-failed      # 仅重试失败
#
# 依赖: python3, generate_cover.py (混元 TextToImageLite)
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_DIR="$ROOT_DIR/workspace/books"

COVER_SCRIPT="${COVER_SCRIPT:-/home/main-repo/L1_novel_skill/scripts/generate_cover.py}"
BOOK_FILTER=""
RETRY_FAILED=false

# ── 颜色 ──
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
skip() { echo -e "${YELLOW}[SKIP]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }
info() { echo -e "${CYAN}[ ..]${NC} $*"; }

show_help() {
    cat << 'EOF'
使用方法:
  bash scripts/batch_generate_covers.sh [选项]

选项:
  --book NAME           仅处理指定书（如 "春夜困渡"）
  --retry-failed        仅重试不存在的 cover.png（跳过已成功生成的）
  --cover-script PATH   指定 generate_cover.py 路径（默认: /home/main-repo/L1_novel_skill/scripts/generate_cover.py）
  --help                显示帮助

示例:
  bash scripts/batch_generate_covers.sh
  bash scripts/batch_generate_covers.sh --book 春夜困渡
  bash scripts/batch_generate_covers.sh --retry-failed
EOF
}

# ── 解析参数 ──
while [ $# -gt 0 ]; do
    case "$1" in
        --book)          BOOK_FILTER="$2"; shift 2 ;;
        --retry-failed)  RETRY_FAILED=true; shift ;;
        --cover-script)  COVER_SCRIPT="$2"; shift 2 ;;
        --help)          show_help; exit 0 ;;
        *) fail "未知参数: $1（用 --help 查看帮助）"; exit 1 ;;
    esac
done

# ── 检查依赖 ──
if [ ! -f "$COVER_SCRIPT" ]; then
    fail "封面生成脚本不存在: $COVER_SCRIPT"
    fail "请用 --cover-script 指定正确路径，或将脚本放在默认位置"
    exit 1
fi

command -v python3 &>/dev/null || { fail "缺少 python3"; exit 1; }

# ── 主逻辑 ──
cd "$ROOT_DIR"

info "扫描 workspace/books/*/versions/v*/00-素材/cover_prompt.json ..."
echo ""

total=0
success=0
skipped=0
failed=0

find_args=("$WORKSPACE_DIR" -path "*/00-素材/cover_prompt.json")
if [ -n "$BOOK_FILTER" ]; then
    find_args=("$WORKSPACE_DIR/$BOOK_FILTER" -path "*/00-素材/cover_prompt.json")
fi

while IFS= read -r prompt_file; do
    [ -z "$prompt_file" ] && continue
    total=$((total + 1))

    version_dir=$(dirname "$(dirname "$prompt_file")")
    publish_dir="$version_dir/发布"
    cover_file="$publish_dir/cover.png"
    metadata_file="$publish_dir/novel_metadata.json"
    book_name=$(echo "$prompt_file" | sed 's|.*/workspace/books/||; s|/versions/.*||')

    echo "──────────────────────────────────────────────"
    info "书　名: $book_name"
    info "版　本: $(basename "$version_dir")"

    # ── skip 检查 ──
    if [ "$RETRY_FAILED" = true ]; then
        if [ -f "$cover_file" ] && [ "$(stat -c%s "$cover_file" 2>/dev/null || echo 0)" -gt 10240 ]; then
            skip "封面已存在且正常，跳过"
            skipped=$((skipped + 1))
            continue
        fi
    fi

    if [ -f "$cover_file" ] && [ "$(stat -c%s "$cover_file" 2>/dev/null || echo 0)" -gt 10240 ]; then
        skip "封面已存在且正常，跳过（用 --retry-failed 可强制重试失败项）"
        skipped=$((skipped + 1))
        continue
    fi

    # ── 读取 prompt ──
    if [ ! -f "$prompt_file" ]; then
        fail "cover_prompt.json 不存在"
        failed=$((failed + 1))
        continue
    fi

    prompt=$(python3 -c "import json; d=json.load(open('$prompt_file')); print(d.get('prompt',''))" 2>/dev/null)
    if [ -z "$prompt" ]; then
        fail "cover_prompt.json 中 prompt 为空"
        failed=$((failed + 1))
        continue
    fi

    negative_prompt=$(python3 -c "import json; d=json.load(open('$prompt_file')); print(d.get('negative_prompt',''))" 2>/dev/null || true)

    info "Prompt: ${prompt:0:80}..."

    # ── 调用生成 ──
    mkdir -p "$publish_dir"

    local neg_arg=()
    if [ -n "$negative_prompt" ]; then
        neg_arg=(--negative-prompt "$negative_prompt")
    fi

    if python3 "$COVER_SCRIPT" --prompt "$prompt" "${neg_arg[@]}" --output "$cover_file" 2>&1 | while IFS= read -r line; do
        echo "        $line"
    done; then
        # ── 更新 novel_metadata.json ──
        if [ -f "$metadata_file" ]; then
            python3 -c "
import json, os
f='$metadata_file'
if os.path.exists(f):
    d=json.load(open(f))
    d['cover_image']='./cover.png'
    d['cover_generated_by']='混元 TextToImageLite'
    d['cover_resolution']='768x1024 (3:4)'
    json.dump(d, open(f,'w'), ensure_ascii=False, indent=2)
    open(f,'a').write('\n')
"
        fi
        ok "封面已生成: $cover_file"
        success=$((success + 1))
    else
        fail "封面生成失败"
        failed=$((failed + 1))
    fi

done < <(find "${find_args[@]}" 2>/dev/null)

echo ""
echo "══════════════════════════════════════"
echo "  批量封面生成完成"
echo "══════════════════════════════════════"
echo "  总数:   $total"
echo "  成功:   ${GREEN}${success}${NC}"
echo "  跳过:   ${YELLOW}${skipped}${NC}"
[ "$failed" -gt 0 ] && echo "  失败:   ${RED}${failed}${NC}"
echo "══════════════════════════════════════"

if [ "$failed" -gt 0 ]; then
    echo ""
    fail "有 $failed 个封面生成失败，可修改 cover_prompt.json 中的 prompt 后重试"
    exit 1
fi

if [ "$success" -eq 0 ] && [ "$skipped" -gt 0 ]; then
    ok "所有封面已就绪，无需生成"
fi
