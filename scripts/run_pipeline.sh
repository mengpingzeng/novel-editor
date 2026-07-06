#!/bin/bash
# ============================================================
#  V2 写作流水线串联脚本
#
#  核心机制:
#   -    opencode run 是同步阻塞的: agent 完成全部子任务后才返回
#   - 返回后轮询 .phase(N)_done 标记文件 (最多等 5min, 防异步落盘延迟)
#   - 每个 Phase 无总时间限制, 可跑数十小时
#
#  执行流 (step 模式):
#   书A: Phase1(框架) → Phase2(写书) → Phase3(审稿)
#   书B: Phase1(框架) → Phase2(写书) → Phase3(审稿)
#   ...
#   跨书总结
#
#  用法:
#    bash scripts/run_pipeline.sh dryrun           # 甄嬛传 ×3章 Phase1→2→3
#    bash scripts/run_pipeline.sh step             # 全部 active_books Phase1→2→3
#
#  环境变量:
#    PIPELINE_TIMEOUT  单阶段超时(秒), 0=不限(默认)
# ============================================================
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MODE="${1:-dryrun}"
TIMEOUT_PER_PHASE="${PIPELINE_TIMEOUT:-0}"
POLL_INTERVAL=15
POLL_TIMEOUT=300

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

log()    { echo -e "[$(date '+%H:%M:%S')] ${CYAN}$1${NC}"; }
success(){ echo -e "${GREEN}[$(date '+%H:%M:%S')] ✅ $1${NC}"; }
warn()   { echo -e "${YELLOW}[$(date '+%H:%M:%S')] ⚠️  $1${NC}"; }
fail()   { echo -e "${RED}[$(date '+%H:%M:%S')] ❌ $1${NC}"; }

# ── 执行 opencode run，同步阻塞等待完成 ──
run_phase() {
    local label="$1"
    shift
    log "启动: $label"
    log "命令: opencode run --dangerously-skip-permissions $*"
    echo ""

    local rc
    if [ "$TIMEOUT_PER_PHASE" -gt 0 ]; then
        timeout "$TIMEOUT_PER_PHASE" opencode run --dangerously-skip-permissions "$@"
        rc=$?
    else
        opencode run --dangerously-skip-permissions "$@"
        rc=$?
    fi

    echo ""
    if [ $rc -eq 0 ]; then
        success "$label — 完成"
        return 0
    elif [ "$TIMEOUT_PER_PHASE" -gt 0 ] && [ $rc -eq 124 ]; then
        fail "$label — 超时 (${TIMEOUT_PER_PHASE}s)"
        return 1
    else
        fail "$label — 失败 (exit=$rc)"
        return 1
    fi
}

# ── 轮询等待标记文件 ──
wait_for_marker() {
    local marker="$1"
    local label="$2"
    local elapsed=0

    if [ -f "$marker" ]; then
        success "标记已存在: $label"
        return 0
    fi

    log "等待标记: $label ..."
    while [ ! -f "$marker" ]; do
        sleep $POLL_INTERVAL
        elapsed=$((elapsed + POLL_INTERVAL))
        if [ $elapsed -ge $POLL_TIMEOUT ]; then
            fail "等待标记超时 (${POLL_TIMEOUT}s): $marker"
            return 1
        fi
    done
    success "标记已生成: $label"
}

# ── 获取版本目录中的最新版本号 ──
get_book_version() {
    local book_dir="$1"
    local ver="v1"
    local versions_dir="$book_dir/versions"
    if [ -d "$versions_dir" ]; then
        local max_ver
        max_ver=$(ls -1 "$versions_dir" 2>/dev/null | grep -E '^v[0-9]+$' | sed 's/v//' | sort -n | tail -1)
        if [ -n "$max_ver" ]; then
            # Phase 2 之后 version 可能已经递增了，用最大版本号
            echo "v$max_ver"
            return
        fi
    fi
    # 回退：从 .phase1_done 读取
    if [ -f "$book_dir/.phase1_done" ]; then
        python3 -c "import json; d=json.load(open('$book_dir/.phase1_done')); print(d.get('version','$ver'))" 2>/dev/null || echo "$ver"
    else
        echo "$ver"
    fi
}

# ── 为单本书创建临时 state 文件并触发 Phase 1 ──
run_phase1_for_book() {
    local name="$1"
    local platform="$2"
    local track="$3"
    local chapters="$4"

    local state_file="$ROOT_DIR/workspace/iteration-state.json"
    local state_backup="$ROOT_DIR/workspace/.iteration-state.json.bak"

    if [ ! -f "$state_file" ]; then
        fail "状态文件不存在: $state_file"
        return 1
    fi

    # 备份原始 state，创建只含当前书的临时 state
    cp "$state_file" "$state_backup"

    python3 -c "
import json
with open('$state_file') as f:
    s = json.load(f)
s['active_books'] = [{'name': '$name', 'platform': '$platform', 'track': '$track'}]
s['target_chapters'] = $chapters
s['phase'] = 'phase1'
with open('$state_file', 'w') as f:
    json.dump(s, f, ensure_ascii=False, indent=2)
"
    log "Phase 1 临时 state 已创建: 仅含 $name"

    # 确保中断时恢复 state
    trap "cp '$state_backup' '$state_file' 2>/dev/null; rm -f '$state_backup'" EXIT

    run_phase "Phase 1 - $name" "/iterate step" || { cp "$state_backup" "$state_file"; rm -f "$state_backup"; trap - EXIT; return 1; }

    # 恢复原始 state
    cp "$state_backup" "$state_file"
    rm -f "$state_backup"
    trap - EXIT

    wait_for_marker "$ROOT_DIR/workspace/books/$name/.phase1_done" "$name.phase1_done" || return 1
}

# ── 运行一本书的完整 Pipeline (Phase 1→2→3) ──
run_book_pipeline() {
    local name="$1"
    local platform="$2"
    local track="$3"
    local chapters="$4"
    local book_dir="$ROOT_DIR/workspace/books/$name"
    local reviewer_dir="$ROOT_DIR/workspace/reviewer"

    echo ""
    echo "┌──────────────────────────────────────────────┐"
    echo "│  处理: $name  ($platform / $track)            │"
    echo "└──────────────────────────────────────────────┘"

    # ── Phase 1: 框架生成 ──
    if [ -f "$book_dir/.phase1_done" ]; then
        warn "跳过 Phase 1: $name（已有 .phase1_done）"
    else
        log "═══ Phase 1: 框架生成 ═══"
        run_phase1_for_book "$name" "$platform" "$track" "$chapters" || {
            fail "$name Phase 1 失败"
            return 1
        }
    fi

    # ── Phase 2: 写书 ──
    if [ -f "$book_dir/.phase2_done" ]; then
        warn "跳过 Phase 2: $name（已有 .phase2_done）"
    else
        if [ ! -d "$book_dir/.opencode/agents" ]; then
            fail "项目 agent 目录不存在: $book_dir/.opencode/agents — Phase 1 可能未正确复制"
            return 1
        fi

        log "═══ Phase 2: 写书 ($chapters 章) ═══"

        # Phase 2.0: 初始化 + 卷纲（独立 session）
        run_phase "Phase 2.0 - $name" \
            --dir "$book_dir" \
            --agent chief_editor \
            "初始化项目并生成第1卷卷纲" || {
            fail "$name Phase 2.0 初始化/卷纲失败"
            return 1
        }

        # Phase 2.1+: 每章独立 session（支持断点续跑）
        ver=$(get_book_version "$book_dir")
        for ((ch=1; ch<=chapters; ch++)); do
            if [ -f "$book_dir/versions/$ver/02-正文/第${ch}章-终稿.md" ]; then
                warn "跳过第${ch}章（终稿已存在，断点续跑）"
                continue
            fi
            run_phase "Phase 2.$ch - $name 第${ch}章" \
                --dir "$book_dir" \
                --agent chief_editor \
                "执行第${ch}章生产" || {
                fail "$name 第${ch}章 失败"
                return 1
            }
        done

        # 写完成标记
        python3 -c "
import json, datetime
marker = {
    'phase': 'phase2_done',
    'chapters_completed': $chapters,
    'timestamp': datetime.datetime.now().isoformat()
}
with open('$book_dir/.phase2_done', 'w') as f:
    json.dump(marker, f, ensure_ascii=False, indent=2)
"
        success "$name Phase 2 完成"
        wait_for_marker "$book_dir/.phase2_done" "$name.phase2_done" || return 1
    fi

    # ── Phase 3: 审稿 ──
    local ver
    ver=$(get_book_version "$book_dir")
    local phase3_marker="$book_dir/versions/$ver/.phase3_done"

    if [ -f "$phase3_marker" ]; then
        warn "跳过 Phase 3: $name（已有 .phase3_done）"
    else
        if [ ! -d "$reviewer_dir/.opencode/agents" ]; then
            fail "评价层 agent 目录不存在: $reviewer_dir/.opencode/agents"
            return 1
        fi

        log "═══ Phase 3: 审稿 ($ver) ═══"
        run_phase "Phase 3 - $name" \
            --dir "$reviewer_dir" \
            --agent reviewer_orchestrator \
            "审核 $book_dir/versions/$ver/" || {
            fail "$name Phase 3 失败"
            return 1
        }
        wait_for_marker "$phase3_marker" "$name.phase3_done" || return 1
    fi

    success "$name — 全流程完成"
    echo "$name"
}

# ═══════════════════════════════════════════════════════
#  DRYRUN 模式：甄嬛传 × 3章
# ═══════════════════════════════════════════════════════
dryrun_all() {
    echo "============================================"
    echo "  dryrun — 甄嬛传 × 3章 全流程测试"
    echo "============================================"
    echo ""

    local name="甄嬛传"
    local dryrun_book_dir="$ROOT_DIR/workspace/_dryrun/books/$name"
    local reviewer_dir="$ROOT_DIR/workspace/reviewer"

    # Phase 1: 框架生成 (dryrun 模式)
    log "═══ Phase 1: 框架生成 ═══"
    run_phase "Phase 1 dryrun" "/iterate dryrun" || return 1
    wait_for_marker "$dryrun_book_dir/.phase1_done" "$name.phase1_done" || return 1

    # Phase 2: 写书
    log "═══ Phase 2: 写书 (3章) ═══"
    if [ ! -d "$dryrun_book_dir/.opencode/agents" ]; then
        fail "项目 agent 目录不存在: $dryrun_book_dir/.opencode/agents"
        return 1
    fi

    # Phase 2.0: 初始化 + 卷纲（独立 session）
    run_phase "Phase 2.0 dryrun" \
        --dir "$dryrun_book_dir" \
        --agent chief_editor \
        "初始化项目并生成第1卷卷纲" || return 1

    # Phase 2.1-2.3: 每章独立 session（支持断点续跑）
    local dryrun_ver
    dryrun_ver=$(get_book_version "$dryrun_book_dir")
    for ch in 1 2 3; do
        if [ -f "$dryrun_book_dir/versions/$dryrun_ver/02-正文/第${ch}章-终稿.md" ]; then
            warn "跳过第${ch}章（终稿已存在，断点续跑）"
            continue
        fi
        run_phase "Phase 2.$ch dryrun" \
            --dir "$dryrun_book_dir" \
            --agent chief_editor \
            "执行第${ch}章生产" || return 1
    done

    # 写完成标记
    python3 -c "
import json, datetime
marker = {
    'phase': 'phase2_done',
    'chapters_completed': 3,
    'timestamp': datetime.datetime.now().isoformat()
}
with open('$dryrun_book_dir/.phase2_done', 'w') as f:
    json.dump(marker, f, ensure_ascii=False, indent=2)
"
    success "$name Phase 2 完成"

    # Phase 3: 审稿
    log "═══ Phase 3: 审稿 ═══"
    local dryrun_version
    dryrun_version=$(get_book_version "$dryrun_book_dir")
    run_phase "Phase 3 dryrun" \
        --dir "$reviewer_dir" \
        --agent reviewer_orchestrator \
        "审核 $dryrun_book_dir/versions/$dryrun_version/" || return 1
    wait_for_marker "$dryrun_book_dir/versions/$dryrun_version/.phase3_done" "$name.phase3_done" || return 1

    echo ""
    echo "============================================"
    echo "  dryrun 全流程完成"
    echo "============================================"
}

# ═══════════════════════════════════════════════════════
#  STEP 模式：每本书独立跑 Phase 1→2→3
# ═══════════════════════════════════════════════════════
step_all() {
    local state_file="$ROOT_DIR/workspace/iteration-state.json"

    if [ ! -f "$state_file" ]; then
        fail "状态文件不存在: $state_file"
        return 1
    fi

    # 读取所有 active_books
    local books_data
    books_data=$(python3 -c "
import json
with open('$state_file') as f:
    s = json.load(f)
chapters = s.get('target_chapters', 5)
books = s.get('active_books', [])
for b in books:
    print(f'{b[\"name\"]}|{b.get(\"platform\",\"\")}|{b.get(\"track\",\"\")}')
" 2>/dev/null)
    local chapters
    chapters=$(python3 -c "import json; s=json.load(open('$state_file')); print(s.get('target_chapters',5))")

    local book_count
    book_count=$(echo "$books_data" | grep -c '|')
    local current=0
    local completed_books=""
    local failed_books=""

    echo "============================================"
    echo "  step — $book_count 本书 × $chapters 章"
    echo "  每本书独立执行 Phase 1→2→3"
    echo "============================================"
    echo ""

    while IFS='|' read -r name platform track; do
        [ -z "$name" ] && continue
        current=$((current + 1))
        log ">>> 第 $current/$book_count 本: $name <<<"

        local result
        result=$(run_book_pipeline "$name" "$platform" "$track" "$chapters")
        local rc=$?

        if [ $rc -eq 0 ] && [ -n "$result" ]; then
            completed_books="$completed_books $name"
        else
            failed_books="$failed_books $name"
        fi
    done <<< "$books_data"

    # ── 跨书总结 ──
    if [ -n "$completed_books" ]; then
        local book_list
        book_list=$(echo "$completed_books" | sed 's/^ //; s/ /,/g')
        local first_book
        first_book=$(echo "$completed_books" | awk '{print $1}')
        local cross_ver
        cross_ver=$(get_book_version "$ROOT_DIR/workspace/books/$first_book")
        echo ""
        log "═══ 跨书总结 ═══"
        run_phase "跨书总结" \
            --dir "$ROOT_DIR/workspace/reviewer" \
            "生成跨书总结报告 version=$cross_ver books=$book_list" || {
            fail "跨书总结失败"
        }
    fi

    # ── 汇总 ──
    echo ""
    echo "============================================"
    echo "  step 执行完毕"
    echo "============================================"
    if [ -n "$completed_books" ]; then
        success "成功: $completed_books"
    fi
    if [ -n "$failed_books" ]; then
        fail "失败: $failed_books"
    fi
    echo "============================================"
}

# ═══════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════

cd "$ROOT_DIR" || exit 1

case "$MODE" in
    dryrun)
        dryrun_all
        ;;
    step)
        step_all
        ;;
    *)
        echo "用法: bash scripts/run_pipeline.sh {dryrun|step}"
        echo ""
        echo "  dryrun    甄嬛传 × 3章 全流程自测"
        echo "  step      全部 active_books 全流程 (每本书独立 Phase 1→2→3)"
        echo ""
        echo "step 模式执行流:"
        echo "  书A: Phase1(框架) → Phase2(写书) → Phase3(审稿)"
        echo "  书B: Phase1(框架) → Phase2(写书) → Phase3(审稿)"
        echo "  ..."
        echo "  跨书总结"
        echo ""
        echo "环境变量:"
        echo "  PIPELINE_TIMEOUT  单阶段超时秒数 (默认 0=不限)"
        exit 1
        ;;
esac

exit_code=$?
echo ""
if [ $exit_code -eq 0 ]; then
    success "流水线完成"
else
    fail "流水线异常终止 (exit=$exit_code)"
fi
exit $exit_code
