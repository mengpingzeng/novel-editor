#!/bin/bash
# ============================================================
#  V3 写作流水线串联脚本
#
#  核心机制:
#   - opencode run 是同步阻塞的: agent 完成全部子任务后才返回
#   - 断点续跑通过 iteration-state.json 中 books.{name}.phase 控制
#   - 标记文件 (.phase1_done / .phase2_done / .phase3_done) 作为兜底兼容
#   - 每个 Phase 默认 1h 超时, 单章默认 30min 超时
#   - 超时后脚本自动退出, 入口层自动重启 (最多 PIPELINE_MAX_ATTEMPTS 次)
#   - 重启时已完成的步骤自动跳过 (依赖 state JSON 的 phase 字段)
#
#  执行流 (step 模式):
#   书A: Phase1(框架) → Phase2(写书) → Phase3(审稿)
#   书B: Phase1(框架) → Phase2(写书) → Phase3(审稿)
#   ...
#   跨书总结
#
#  用法:
#    bash scripts/run_pipeline.sh dryrun                   # 甄嬛传 ×3章 Phase1→2→3
#    bash scripts/run_pipeline.sh step                     # 全部 active_books Phase1→2→3
#    bash scripts/run_pipeline.sh step --skip-phase3      # 跳过 Phase 3 审稿（线上生产模 式）
#    bash scripts/run_pipeline.sh dryrun --skip-phase3    # dryrun 也支持
#
#  手动控制版本（修改 workspace/iteration-state.json）:
#   - 改 books.{书名}.version = "v3" → 从 v3 开始
#   - 改 books.{书名}.phase   = "pending" → 强制重跑 Phase 1
#   - 改 books.{书名}.phase   = "phase2_done" → 跳过 Phase 1/2，仅审稿
#   - 改 target_chapters = 0  → 全书生产模式（从上帝之眼 §七 解析卷结构，写完为止）
#   - 改 target_chapters = 5（或任意 ≥1 值） → 验证模式（写 N 章即停）
#   - phase 值: pending | phase1_done | phase2_done | phase3_done | done
#
#  环境变量:
#    PIPELINE_TIMEOUT       单阶段超时(秒), 默认3600(1h), 0=不限
#    CHAPTER_TIMEOUT        单章超时(秒), 默认1800(30min), 0=不限
#    PIPELINE_MAX_ATTEMPTS  流水线整体最大重启次数, 默认3
# ============================================================
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MODE="${1:-dryrun}"
SKIP_PHASE3="false"
for arg in "$@"; do
    case "$arg" in
        --skip-phase3) SKIP_PHASE3="true" ;;
    esac
done
TIMEOUT_PER_PHASE="${PIPELINE_TIMEOUT:-3600}"
CHAPTER_TIMEOUT="${CHAPTER_TIMEOUT:-1800}"
PIPELINE_MAX_ATTEMPTS="${PIPELINE_MAX_ATTEMPTS:-3}"
CHAPTER_MAX_RETRIES=$(python3 -c "import json; print(json.load(open('$ROOT_DIR/config.json')).get('retry',{}).get('chapter_max_retries',3))" 2>/dev/null || echo 3)
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

# ── 每书互斥锁（与 HTTP API 共享同一 lock 文件） ──
BOOK_LOCK_FD=""
acquire_book_lock() {
    local book_dir="$1"
    local lock_file="$book_dir/.write_lock"
    mkdir -p "$(dirname "$lock_file")" 2>/dev/null
    exec 200>"$lock_file"
    if ! flock -n 200; then
        fail "书 $book_dir 正在被另一个进程（HTTP API 或其他 pipeline）操作，退出"
        exec 200>&-
        return 1
    fi
    BOOK_LOCK_FD="200"
    return 0
}
release_book_lock() {
    if [ -n "$BOOK_LOCK_FD" ]; then
        flock -u 200 2>/dev/null
        exec 200>&-
        BOOK_LOCK_FD=""
    fi
}

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
        return 124
    else
        fail "$label — 失败 (exit=$rc)"
        return 1
    fi
}

# ── 执行章节生产（使用章节级超时） ──
run_chapter() {
    local label="$1"
    local chapter_timeout="${2:-$CHAPTER_TIMEOUT}"
    shift 2

    log "启动: $label (超时=${chapter_timeout}s)"
    log "命令: opencode run --dangerously-skip-permissions $*"
    echo ""

    local rc
    if [ "$chapter_timeout" -gt 0 ]; then
        timeout "$chapter_timeout" opencode run --dangerously-skip-permissions "$@"
        rc=$?
    else
        opencode run --dangerously-skip-permissions "$@"
        rc=$?
    fi

    echo ""
    if [ $rc -eq 0 ]; then
        success "$label — 完成"
        return 0
    elif [ "$chapter_timeout" -gt 0 ] && [ $rc -eq 124 ]; then
        fail "$label — 超时 (${chapter_timeout}s)"
        return 124
    else
        fail "$label — 失败 (exit=$rc)"
        return 1
    fi
}

# ── 轮询等待标记文件（兜底兼容） ──
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

# ═══════════════════════════════════════════════════════
#  V3: iteration-state.json 驱动的状态管理
# ═══════════════════════════════════════════════════════

STATE_FILE="$ROOT_DIR/workspace/iteration-state.json"

# ── 从 iteration-state.json 读取某本书的 version ──
# 用法: get_book_version <书名> [fallback_dir]
# Primary: state JSON books.{name}.version
# Fallback: 扫描文件系统 versions/ 目录取最大号
get_book_version() {
    local book_name="$1"
    local fallback_dir="${2:-$ROOT_DIR/workspace/books/$book_name}"

    if [ -f "$STATE_FILE" ]; then
        local ver
        ver=$(python3 -c "
import json
with open('$STATE_FILE') as f:
    s = json.load(f)
print(s.get('books', {}).get('$book_name', {}).get('version', ''))
" 2>/dev/null)
        if [ -n "$ver" ]; then
            echo "$ver"
            return 0
        fi
    fi

    local versions_dir="$fallback_dir/versions"
    if [ -d "$versions_dir" ]; then
        local max_ver
        max_ver=$(ls -1 "$versions_dir" 2>/dev/null | grep -E '^v[0-9]+$' | sed 's/v//' | sort -n | tail -1)
        if [ -n "$max_ver" ]; then
            echo "v$max_ver"
            return 0
        fi
    fi
    echo "v1"
}

# ── 从 book_state.json（优先）或 iteration-state.json 读取某本书的 phase ──
# Primary: workspace/books/{name}/book_state.json
# Fallback: iteration-state.json → marker files
get_book_phase() {
    local book_name="$1"
    local fallback_dir="${2:-$ROOT_DIR/workspace/books/$book_name}"
    local bstate="$fallback_dir/book_state.json"

    if [ -f "$bstate" ]; then
        local phase
        phase=$(python3 -c "
import json
with open('$bstate') as f:
    s = json.load(f)
print(s.get('phase', ''))
" 2>/dev/null)
        if [ -n "$phase" ]; then
            echo "$phase"
            return 0
        fi
    fi

    # Fallback: iteration-state.json
    if [ -f "$STATE_FILE" ]; then
        local phase2
        phase2=$(python3 -c "
import json
with open('$STATE_FILE') as f:
    s = json.load(f)
p = s.get('books', {}).get('$book_name', {}).get('phase')
if p is not None:
    print(p)
" 2>/dev/null)
        if [ -n "$phase2" ]; then
            echo "$phase2"
            return 0
        fi
    fi

    # Fallback: 通过版本级标记文件推断
    local ver
    ver=$(get_book_version "$book_name" "$fallback_dir")
    if [ -f "$fallback_dir/versions/$ver/.phase3_done" ]; then
        echo "phase3_done"
    elif [ -f "$fallback_dir/versions/$ver/.phase2_done" ]; then
        echo "phase2_done"
    elif [ -f "$fallback_dir/versions/$ver/.phase1_done" ]; then
        echo "phase1_done"
    else
        echo "pending"
    fi
}

# ── 更新 book_state.json（优先）或 iteration-state.json 中某本书的 phase ──
update_book_phase() {
    local book_name="$1"
    local new_phase="$2"
    local bstate="$ROOT_DIR/workspace/books/$book_name/book_state.json"

    if [ -f "$bstate" ]; then
        python3 -c "
import json
with open('$bstate') as f:
    s = json.load(f)
s['phase'] = '$new_phase'
with open('$bstate', 'w') as f:
    json.dump(s, f, ensure_ascii=False, indent=2)
" 2>/dev/null && return 0 || return 1
    fi

    # Fallback: iteration-state.json
    python3 -c "
import json
with open('$STATE_FILE') as f:
    s = json.load(f)
if '$book_name' in s.get('books', {}):
    s['books']['$book_name']['phase'] = '$new_phase'
else:
    s.setdefault('books', {})['$book_name'] = {'phase': '$new_phase'}
with open('$STATE_FILE', 'w') as f:
    json.dump(s, f, ensure_ascii=False, indent=2)
" 2>/dev/null && return 0 || return 1
}

# ── 更新 book_state.json（优先）或 iteration-state.json 中某本书的 score / passed ──
update_book_score() {
    local book_name="$1"
    local score="$2"
    local passed="$3"
    local bstate="$ROOT_DIR/workspace/books/$book_name/book_state.json"

    if [ -f "$bstate" ]; then
        python3 -c "
import json
with open('$bstate') as f:
    s = json.load(f)
s['score'] = $score
s['passed'] = $passed
with open('$bstate', 'w') as f:
    json.dump(s, f, ensure_ascii=False, indent=2)
" 2>/dev/null && return 0 || return 1
    fi

    # Fallback: iteration-state.json
    python3 -c "
import json
with open('$STATE_FILE') as f:
    s = json.load(f)
if '$book_name' in s.get('books', {}):
    s['books']['$book_name']['score'] = $score
    s['books']['$book_name']['passed'] = $passed
with open('$STATE_FILE', 'w') as f:
    json.dump(s, f, ensure_ascii=False, indent=2)
" 2>/dev/null && return 0 || return 1
}

# ── 判断 phase 是否已达到或超过某个里程碑 ──
# phase 阶序: pending < phase1_done < phase2_done < phase3_done < done
phase_ge() {
    local current="$1"
    local required="$2"

    case "$required" in
        pending)     return 0 ;;
        phase1_done) [ "$current" = "phase1_done" ] || [ "$current" = "phase2_done" ] || [ "$current" = "phase3_done" ] || [ "$current" = "done" ] && return 0 || return 1 ;;
        phase2_done) [ "$current" = "phase2_done" ] || [ "$current" = "phase3_done" ] || [ "$current" = "done" ] && return 0 || return 1 ;;
        phase3_done) [ "$current" = "phase3_done" ] || [ "$current" = "done" ] && return 0 || return 1 ;;
        done)        [ "$current" = "done" ] && return 0 || return 1 ;;
        *)           return 1 ;;
    esac
}

# ── 为单本书触发 Phase 1 ──
# V4 改进: 通过 scope 文件物理隔离，agent 只看到当前一本书
# scope 文件 = workspace/.pipeline_scope.json（临时，仅含当前书）
# 主 state = workspace/iteration-state.json（持久化，断点续跑用）
# agent 完成后，从 scope 同步 phase/version 到主 state
run_phase1_for_book() {
    local name="$1"
    local platform="$2"
    local track="$3"
    local chapters="$4"
    local word_count_multiplier="${5:-1.0}"
    local scope_file="$ROOT_DIR/workspace/.pipeline_scope.json"

    if [ ! -f "$STATE_FILE" ]; then
        fail "状态文件不存在: $STATE_FILE"
        return 1
    fi

    # 从主 state 构建 scope 文件：只包含当前书，其他书物理不可见
    # V5: 从 main state 的 active_books 中继承完整条目字段（word_count_multiplier 等）
    python3 -c "
import json
with open('$STATE_FILE') as f:
    s = json.load(f)
book = s.get('books', {}).get('$name', {})
orig_active_entry = None
for b in s.get('active_books', []):
    if b.get('name') == '$name':
        orig_active_entry = dict(b)
        break
if orig_active_entry is None:
    orig_active_entry = {'name': '$name', 'platform': '$platform', 'track': '$track'}
scope = {
    'mode': 'step',
    'phase': 'phase1',
    'current_round': s.get('current_round', 1),
    'passing_score': s.get('passing_score', 10),
    'target_chapters': $chapters,
    'active_books': [orig_active_entry],
    'books': {
        '$name': book if book else {'version': 'v1', 'phase': 'pending'}
    }
}
with open('$scope_file', 'w') as f:
    json.dump(scope, f, ensure_ascii=False, indent=2)
"
    log "Phase 1 scope 已创建: 仅含 $name"

    # 保存 scope 副本（agent 可能会删除 scope 文件）
    local scope_backup="${scope_file}.copy"
    cp "$scope_file" "$scope_backup"

    cp "$STATE_FILE" "${STATE_FILE}.bak"
    cp "$scope_file" "$STATE_FILE"

    run_phase "Phase 1 - $name" "/iterate step"
    local agent_rc=$?

    # ── 无论成功失败，先恢复 state 文件（防止 swap 残留） ──
    cp "${STATE_FILE}.bak" "$STATE_FILE"
    rm -f "${STATE_FILE}.bak"

    # ── 超时：向上传播 124，触发流水线重启 ──
    if [ $agent_rc -eq 124 ]; then
        fail "$name Phase 1 agent 执行超时"
        rm -f "$scope_backup" "$scope_file"
        return 124
    fi

    if [ $agent_rc -ne 0 ]; then
        fail "$name Phase 1 agent 执行失败"
        rm -f "$scope_backup" "$scope_file"
        return 1
    fi

    # 从 scope 原文件读取 agent 写入的当前书 phase
    # 原文件已被 agent 在 Phase 1 执行期间更新（phase=pending → phase1_done）
    if [ ! -f "$scope_file" ]; then
        fail "$name Phase 1 scope 文件丢失，无法同步 phase"
        return 1
    fi
    local final_phase
    final_phase=$(python3 -c "
import json
with open('$scope_file') as f:
    s = json.load(f)
print(s.get('books', {}).get('$name', {}).get('phase', 'pending'))
" 2>/dev/null)

    if [ -z "$final_phase" ]; then
        fail "Phase 1 完成但无法读取 $name 的 phase（scope 文件可能损坏）"
        rm -f "$scope_file"
        return 1
    fi

    if ! phase_ge "$final_phase" "phase1_done"; then
        fail "Phase 1 完成但 phase 未更新: $final_phase（agent 可能未处理 $name，请检查 agent 输出日志）"
        rm -f "$scope_backup" "$scope_file"
        return 1
    fi

    # 将 scope 原文件中的 phase/version 同步回主 state（只更新当前书，不动其他书）
    python3 -c "
import json
with open('$scope_file') as f:
    scope = json.load(f)
with open('$STATE_FILE') as f:
    s = json.load(f)
scope_book = scope.get('books', {}).get('$name', {})
if '$name' not in s.setdefault('books', {}):
    s['books']['$name'] = {}
s['books']['$name']['phase'] = scope_book.get('phase', '$final_phase')
if scope_book.get('version'):
    s['books']['$name']['version'] = scope_book['version']
with open('$STATE_FILE', 'w') as f:
    json.dump(s, f, ensure_ascii=False, indent=2)
"

    rm -f "$scope_backup" "$scope_file"

    success "Phase 1 验证通过: $name phase=$final_phase"
}

# ── 从上帝之眼 00-全书命运总谱.md 解析全书卷结构 ──
# 全文件扫描匹配卷表行（| 卷号 | ... | 章数 | ...），不依赖 section 编号
resolve_book_volumes() {
    local book_dir="$1"
    local ver="$2"
    local fate_path="$book_dir/versions/$ver/上帝之眼/00-全书命运总谱.md"

    if [ ! -f "$fate_path" ]; then
        echo '{"total_volumes":0,"total_chapters":0,"volumes":[]}'
        return
    fi

    python3 -c "
import json, re, sys

with open('$fate_path') as f:
    content = f.read()

volumes_raw = []
for line in content.split('\n'):
    line = line.strip()
    if not line.startswith('|') or '---' in line:
        continue
    cols = line.split('|')
    if len(cols) < 4:
        continue
    try:
        vol_str = cols[1].strip()
        vol_match = re.match(r'[Vv]?(\\d+)', vol_str)
        if not vol_match:
            continue
        vol_id = int(vol_match.group(1))
        # 章数列可能在 col[3] 或 col[4]（取决于表格有无"章号范围"列）
        ch_str = cols[4].strip() if len(cols) > 4 else ''
        if not re.match(r'^\\d+$', ch_str):
            ch_str = cols[3].strip()
        ch_match = re.match(r'\\d+', ch_str)
        if not ch_match:
            continue
        ch_count = int(ch_match.group())
    except (ValueError, IndexError):
        continue
    if vol_id < 1 or ch_count < 1:
        continue
    volumes_raw.append((vol_id, ch_count))

seen = set()
volumes_raw_deduped = []
for vid, cnt in volumes_raw:
    if vid not in seen:
        seen.add(vid)
        volumes_raw_deduped.append((vid, cnt))

if not volumes_raw_deduped:
    print(json.dumps({'total_volumes':0,'total_chapters':0,'volumes':[]}))
    sys.exit(0)

volumes_raw_deduped.sort(key=lambda x: x[0])

volumes = []
cumulative = 0
for vid, cnt in volumes_raw_deduped:
    ch_start = cumulative + 1
    ch_end = cumulative + cnt
    volumes.append({'id': vid, 'ch_start': ch_start, 'ch_end': ch_end})
    cumulative = ch_end

total_chapters = cumulative
total_volumes = len(volumes)
print(json.dumps({
    'total_volumes': total_volumes,
    'total_chapters': total_chapters,
    'volumes': volumes
}, ensure_ascii=False))
"
}

# ── 全书生产模式下逐卷逐章写书 ──
run_phase2_full() {
    local book_dir="$1"
    local ver="$2"
    local name="$3"

    local vol_json
    vol_json=$(resolve_book_volumes "$book_dir" "$ver")

    local total_volumes total_chapters
    total_volumes=$(echo "$vol_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['total_volumes'])")
    total_chapters=$(echo "$vol_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['total_chapters'])")

    if [ "$total_volumes" -le 0 ]; then
        fail "$name 全书模式失败：无法从上帝之眼 §七 解析卷结构"
        fail "$name 请先执行 Phase 1.5 命运设计（destiny_designer），确保 00-全书命运总谱.md §七 表格存在"
        return 1
    fi

    log "全书结构：$total_volumes 卷 / 共 $total_chapters 章"

    # 获取每书互斥锁（与 HTTP API 共享同一 .write_lock 文件）
    if ! acquire_book_lock "$book_dir"; then
        fail "$name 无法获取写入锁（被 HTTP API 或其他进程占用）"
        return 1
    fi
    trap release_book_lock RETURN

    local vol_count=$total_volumes
    local vol_idx=1
    while [ "$vol_idx" -le "$vol_count" ]; do
        local v_start v_end
        v_start=$(echo "$vol_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['volumes'][$((vol_idx-1))]['ch_start'])")
        v_end=$(echo "$vol_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['volumes'][$((vol_idx-1))]['ch_end'])")

        log "--- 第${vol_idx}卷：Ch ${v_start}~${v_end} ---"

        if [ "$vol_idx" -gt 1 ]; then
            run_phase "Phase 2 - ${name} 第${vol_idx}卷卷纲" \
                --dir "$book_dir" \
                --agent chief_editor \
                "初始化第${vol_idx}卷卷纲" || {
                fail "${name} 第${vol_idx}卷卷纲失败"
                return 1
            }
        fi

        for ((ch=v_start; ch<=v_end; ch++)); do
            if [ -f "$book_dir/versions/$ver/02-正文/第${ch}章-终稿.md" ]; then
                warn "跳过第${vol_idx}卷第${ch}章（终稿已存在）"
                continue
            fi

            local retry_count=0
            local ch_done=false

            while [ "$ch_done" != "true" ] && [ "$retry_count" -lt "$CHAPTER_MAX_RETRIES" ]; do
                run_chapter "Phase 2 - ${name} 第${vol_idx}卷第${ch}章" "$CHAPTER_TIMEOUT" \
                    --dir "$book_dir" \
                    --agent chief_editor \
                    "执行第${vol_idx}卷第${ch}章生产"
                local ch_rc=$?

                local ch_final="$book_dir/versions/$ver/02-正文/第${ch}章-终稿.md"
                if [ $ch_rc -eq 0 ] && [ -f "$ch_final" ]; then
                    success "${name} 第${vol_idx}卷第${ch}章 终稿已生成"
                    ch_done=true
                else
                    retry_count=$((retry_count + 1))
                    local reason="exec"
                    [ $ch_rc -eq 124 ] && reason="timeout"
                    warn "${name} 第${vol_idx}卷第${ch}章 失败 (retry=${retry_count}/${CHAPTER_MAX_RETRIES}, reason=${reason})"
                fi
            done

            if [ "$ch_done" != "true" ]; then
                fail "${name} 第${vol_idx}卷第${ch}章 重试耗尽 (${retry_count}/${CHAPTER_MAX_RETRIES})"
                return 1
            fi
        done

        vol_idx=$((vol_idx + 1))
    done

    python3 -c "
import json, datetime
now = datetime.datetime.now().isoformat()
marker = {
    'phase': 'phase2_done',
    'mode': 'full_book',
    'total_volumes': $total_volumes,
    'total_chapters': $total_chapters,
    'timestamp': now
}
with open('$book_dir/versions/$ver/.phase2_done', 'w') as f:
    json.dump(marker, f, ensure_ascii=False, indent=2)
with open('$STATE_FILE') as f:
    s = json.load(f)
if '$name' in s.get('books', {}):
    s['books']['$name']['phase'] = 'phase2_done'
with open('$STATE_FILE', 'w') as f:
    json.dump(s, f, ensure_ascii=False, indent=2)
"
    update_book_phase "$name" "phase2_done"
    success "$name Phase 2 全书完成（$total_volumes 卷 / $total_chapters 章）"
}

# ── 运行一本书的完整 Pipeline (Phase 1→2→3) ──
run_book_pipeline() {
    local name="$1"
    local platform="$2"
    local track="$3"
    local chapters="$4"
    local word_count_multiplier="${5:-1.0}"
    local book_dir="$ROOT_DIR/workspace/books/$name"
    local reviewer_dir="$ROOT_DIR/workspace/reviewer"

    echo ""
    echo "┌──────────────────────────────────────────────┐"
    echo "│  处理: $name  ($platform / $track)            │"
    echo "└──────────────────────────────────────────────┘"

    local phase
    phase=$(get_book_phase "$name" "$book_dir")

    # ── Phase 1: 框架生成 ──
    if phase_ge "$phase" "phase1_done"; then
        warn "跳过 Phase 1: $name（phase=$phase）"
    else
        log "═══ Phase 1: 框架生成 ═══"
        run_phase1_for_book "$name" "$platform" "$track" "$chapters" "$word_count_multiplier" || {
            fail "$name Phase 1 失败"
            return 1
        }
        phase=$(get_book_phase "$name" "$book_dir")
    fi

    # ── Phase 2: 写书 ──
    if phase_ge "$phase" "phase2_done"; then
        warn "跳过 Phase 2: $name（phase=$phase）"
    else
        if [ ! -d "$book_dir/.opencode/agents" ]; then
            fail "项目 agent 目录不存在: $book_dir/.opencode/agents — Phase 1 可能未正确复制"
            return 1
        fi

        local ver
        ver=$(get_book_version "$name" "$book_dir")
        log "═══ Phase 2: 写书 ($([ "$chapters" -eq 0 ] && echo '全书模式' || echo "$chapters 章"), $ver) ═══"

        # Phase 2.0: 初始化 + 卷纲（独立 session，全书/验证模式共享）
        run_phase "Phase 2.0 - $name" \
            --dir "$book_dir" \
            --agent chief_editor \
            "初始化项目并生成第1卷卷纲" || {
            fail "$name Phase 2.0 初始化/卷纲失败"
            return 1
        }
        local vol_outline="$book_dir/versions/$ver/01-大纲/01-卷纲/卷纲-第1卷.md"
        if [ ! -f "$vol_outline" ]; then
            fail "$name Phase 2.0 agent 返回成功但卷纲文件不存在: $vol_outline"
            return 1
        fi
        success "$name Phase 2.0 卷纲已生成"

        # Phase 2.1+: 模式分支（全书生产 / 验证模式）
        if [ "$chapters" -eq 0 ]; then
            # 全书生产模式：从上帝之眼 §七 解析卷结构，逐卷逐章写完
            run_phase2_full "$book_dir" "$ver" "$name" || return $?
        else
            # 验证模式：写指定数量的章节（向后兼容，target_chapters ≥ 1）
            if ! acquire_book_lock "$book_dir"; then
                fail "$name 无法获取写入锁（被 HTTP API 或其他进程占用）"
                return 1
            fi
            trap release_book_lock RETURN
            for ((ch=1; ch<=chapters; ch++)); do
                if [ -f "$book_dir/versions/$ver/02-正文/第${ch}章-终稿.md" ]; then
                    warn "跳过第${ch}章（终稿已存在，断点续跑）"
                    continue
                fi

                local retry_count=0
                local ch_done=false

                while [ "$ch_done" != "true" ] && [ "$retry_count" -lt "$CHAPTER_MAX_RETRIES" ]; do
                    run_chapter "Phase 2.$ch - $name 第${ch}章" "$CHAPTER_TIMEOUT" \
                        --dir "$book_dir" \
                        --agent chief_editor \
                        "执行第${ch}章生产"
                    local ch_rc=$?

                    local ch_final="$book_dir/versions/$ver/02-正文/第${ch}章-终稿.md"
                    if [ $ch_rc -eq 0 ] && [ -f "$ch_final" ]; then
                        success "$name 第${ch}章 终稿已生成"
                        ch_done=true
                    else
                        retry_count=$((retry_count + 1))
                        local reason="exec"
                        [ $ch_rc -eq 124 ] && reason="timeout"
                        warn "$name 第${ch}章 失败 (retry=${retry_count}/${CHAPTER_MAX_RETRIES}, reason=${reason})"
                    fi
                done

                if [ "$ch_done" != "true" ]; then
                    fail "$name 第${ch}章 重试耗尽 (${retry_count}/${CHAPTER_MAX_RETRIES})"
                    return 1
                fi
            done

            python3 -c "
import json, datetime
now = datetime.datetime.now().isoformat()
marker = {
    'phase': 'phase2_done',
    'chapters_completed': $chapters,
    'timestamp': now
}
with open('$book_dir/versions/$ver/.phase2_done', 'w') as f:
    json.dump(marker, f, ensure_ascii=False, indent=2)
with open('$STATE_FILE') as f:
    s = json.load(f)
if '$name' in s.get('books', {}):
    s['books']['$name']['phase'] = 'phase2_done'
with open('$STATE_FILE', 'w') as f:
    json.dump(s, f, ensure_ascii=False, indent=2)
"
            update_book_phase "$name" "phase2_done"
            success "$name Phase 2 完成"
            phase="phase2_done"
        fi
    fi

    # ── Phase 3: 审稿 ──
    # 重新获取最新 phase（Phase 2 可能刚更新）
    phase=$(get_book_phase "$name" "$book_dir")
    local ver
    ver=$(get_book_version "$name" "$book_dir")
    local phase3_marker="$book_dir/versions/$ver/.phase3_done"

    if [ "$SKIP_PHASE3" = "true" ]; then
        if phase_ge "$phase" "phase3_done"; then
            warn "跳过 Phase 3: $name（已有评分结果, phase=$phase）"
        else
            warn "跳过 Phase 3: $name（--skip-phase3）"
            # V4: 跳过评分时写入跳过标记，并将 phase 置为 phase3_done
            python3 -c "
import json, datetime
marker = {
    'phase': 'phase3_done',
    'version': '$ver',
    'timestamp': datetime.datetime.now().isoformat(),
    'review_skipped': True
}
with open('$phase3_marker', 'w') as f:
    json.dump(marker, f, ensure_ascii=False, indent=2)
with open('$STATE_FILE') as f:
    s = json.load(f)
if '$name' in s.get('books', {}):
    s['books']['$name']['phase'] = 'phase3_done'
    s['books']['$name']['review_skipped'] = True
with open('$STATE_FILE', 'w') as f:
    json.dump(s, f, ensure_ascii=False, indent=2)
"
            phase="phase3_done"
        fi
    elif phase_ge "$phase" "phase3_done"; then
        warn "跳过 Phase 3: $name（phase=$phase）"
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
        # 等待 agent 写入 .phase3_done 标记
        wait_for_marker "$phase3_marker" "$name.phase3_done" || return 1

        # 从 .phase3_done 读取 score 并同步到 state JSON
        python3 -c "
import json
with open('$phase3_marker') as f:
    p3 = json.load(f)
with open('$STATE_FILE') as f:
    s = json.load(f)
if '$name' in s.get('books', {}):
    s['books']['$name']['phase'] = 'phase3_done'
    s['books']['$name']['score'] = p3.get('signing_score')
    s['books']['$name']['passed'] = p3.get('signing_passed', False)
with open('$STATE_FILE', 'w') as f:
    json.dump(s, f, ensure_ascii=False, indent=2)
" 2>/dev/null
        phase="phase3_done"
    fi

    success "$name — 全流程完成 (phase=$phase)"
    echo "$name"
}

# ═══════════════════════════════════════════════════════
#  DRYRUN 模式：甄嬛传 × 3章
# ═══════════════════════════════════════════════════════
dryrun_inner() {
    echo "============================================"
    echo "  dryrun — 甄嬛传 × 3章 全流程测试"
    echo "============================================"
    echo ""

    local name="甄嬛传"
    local dryrun_book_dir="$ROOT_DIR/workspace/_dryrun/books/$name"
    local reviewer_dir="$ROOT_DIR/workspace/reviewer"

    # Phase 1: 框架生成 (dryrun 模式)
    log "═══ Phase 1: 框架生成 ═══"
    local dryrun_ver
    dryrun_ver=$(get_book_version "$name" "$dryrun_book_dir")
    run_phase "Phase 1 dryrun" "/iterate dryrun" || return 1
    wait_for_marker "$dryrun_book_dir/versions/$dryrun_ver/.phase1_done" "$name.phase1_done" || return 1

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
    local dryrun_vol="$dryrun_book_dir/versions/$dryrun_ver/01-大纲/01-卷纲/卷纲-第1卷.md"
    if [ ! -f "$dryrun_vol" ]; then
        fail "dryrun Phase 2.0 agent 返回成功但卷纲文件不存在: $dryrun_vol"
        return 1
    fi

    # Phase 2.1-2.3: 每章独立 session（断点续跑，含 chapter_max_retries 重试）
    for ch in 1 2 3; do
        if [ -f "$dryrun_book_dir/versions/$dryrun_ver/02-正文/第${ch}章-终稿.md" ]; then
            warn "跳过第${ch}章（终稿已存在，断点续跑）"
            continue
        fi

        local retry_count=0
        local ch_done=false

        while [ "$ch_done" != "true" ] && [ "$retry_count" -lt "$CHAPTER_MAX_RETRIES" ]; do
            run_chapter "Phase 2.$ch dryrun" "$CHAPTER_TIMEOUT" \
                --dir "$dryrun_book_dir" \
                --agent chief_editor \
                "执行第${ch}章生产"
            local ch_rc=$?

            local dryrun_ch="$dryrun_book_dir/versions/$dryrun_ver/02-正文/第${ch}章-终稿.md"
            if [ $ch_rc -eq 0 ] && [ -f "$dryrun_ch" ]; then
                success "dryrun 第${ch}章 终稿已生成"
                ch_done=true
            else
                retry_count=$((retry_count + 1))
                local reason="exec"
                [ $ch_rc -eq 124 ] && reason="timeout"
                warn "dryrun 第${ch}章 失败 (retry=${retry_count}/${CHAPTER_MAX_RETRIES}, reason=${reason})"
            fi
        done

        if [ "$ch_done" != "true" ]; then
            fail "dryrun 第${ch}章 重试耗尽"
            return 1
        fi
    done

    python3 -c "
import json, datetime
marker = {
    'phase': 'phase2_done',
    'chapters_completed': 3,
    'timestamp': datetime.datetime.now().isoformat()
}
with open('$dryrun_book_dir/versions/$dryrun_ver/.phase2_done', 'w') as f:
    json.dump(marker, f, ensure_ascii=False, indent=2)
"
    success "$name Phase 2 完成"

    # Phase 3: 审稿
    log "═══ Phase 3: 审稿 ═══"
    local dryrun_version
    dryrun_version=$(get_book_version "$name" "$dryrun_book_dir")
    local dryrun_phase3_marker="$dryrun_book_dir/versions/$dryrun_version/.phase3_done"

    if [ "$SKIP_PHASE3" = "true" ]; then
        warn "跳过 Phase 3: $name（--skip-phase3）"
        python3 -c "
import json, datetime
marker = {
    'phase': 'phase3_done',
    'version': '$dryrun_version',
    'timestamp': datetime.datetime.now().isoformat(),
    'review_skipped': True
}
with open('$dryrun_phase3_marker', 'w') as f:
    json.dump(marker, f, ensure_ascii=False, indent=2)
"
    else
        run_phase "Phase 3 dryrun" \
            --dir "$reviewer_dir" \
            --agent reviewer_orchestrator \
            "审核 $dryrun_book_dir/versions/$dryrun_version/" || return 1
        wait_for_marker "$dryrun_phase3_marker" "$name.phase3_done" || return 1
    fi

    echo ""
    echo "============================================"
    echo "  dryrun 全流程完成"
    echo "============================================"
}

# ═══════════════════════════════════════════════════════
#  STEP 模式：每本书独立跑 Phase 1→2→3
# ═══════════════════════════════════════════════════════
step_inner() {
    if [ ! -f "$STATE_FILE" ]; then
        fail "状态文件不存在: $STATE_FILE"
        return 1
    fi

    # 读取所有 active_books
    local books_data
    books_data=$(python3 -c "
import json
with open('$STATE_FILE') as f:
    s = json.load(f)
chapters = s.get('target_chapters', 5)
books = s.get('active_books', [])
for b in books:
    print(f'{b[\"name\"]}|{b.get(\"platform\",\"\")}|{b.get(\"track\",\"\")}|{b.get(\"word_count_multiplier\",1.0)}')
" 2>/dev/null)
    local chapters
    chapters=$(python3 -c "import json; s=json.load(open('$STATE_FILE')); print(s.get('target_chapters',5))")

    local book_count
    book_count=$(echo "$books_data" | grep -c '|')
    local current=0
    local completed_books=""
    local failed_books=""

    echo "============================================"
    echo "  step — $book_count 本书 × $chapters 章"
    echo "  每本书独立执行 Phase 1→2→3"
    echo "  状态管理: iteration-state.json"
    echo "============================================"
    echo ""

    while IFS='|' read -r name platform track word_count_multiplier; do
        [ -z "$name" ] && continue
        current=$((current + 1))

        local phase
        phase=$(get_book_phase "$name")
        local ver
        ver=$(get_book_version "$name")
        log ">>> 第 $current/$book_count 本: $name (phase=$phase, version=$ver) <<<"

        local result
        result=$(run_book_pipeline "$name" "$platform" "$track" "$chapters" "$word_count_multiplier")
        local rc=$?

        if [ $rc -eq 124 ]; then
            fail "$name 超时退出，流水线等待重启"
            return 124
        elif [ $rc -eq 0 ] && [ -n "$result" ]; then
            completed_books="$completed_books $name"
        else
            failed_books="$failed_books $name"
        fi
    done <<< "$books_data"

    # ── 跨书总结 ──
    if [ "$SKIP_PHASE3" = "true" ]; then
        warn "跳过跨书总结（--skip-phase3）"
    elif [ -n "$completed_books" ]; then
        local book_list
        book_list=$(echo "$completed_books" | sed 's/^ //; s/ /,/g')
        local first_book
        first_book=$(echo "$completed_books" | awk '{print $1}')
        local cross_ver
        cross_ver=$(get_book_version "$first_book")
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
#  入口 — 带自动重启的重试循环
# ═══════════════════════════════════════════════════════

cd "$ROOT_DIR" || exit 1

ATTEMPT_FILE="$ROOT_DIR/workspace/.pipeline_attempt"

current_attempt=0
if [ -f "$ATTEMPT_FILE" ]; then
    current_attempt=$(cat "$ATTEMPT_FILE" 2>/dev/null || echo 0)
fi

while [ $current_attempt -lt $PIPELINE_MAX_ATTEMPTS ]; do
    current_attempt=$((current_attempt + 1))
    echo "$current_attempt" > "$ATTEMPT_FILE"

    log "══════ Pipeline 第 ${current_attempt}/${PIPELINE_MAX_ATTEMPTS} 次启动 ══════"
    echo ""

    case "$MODE" in
        dryrun) dryrun_inner ;;
        step)   step_inner ;;
        *)
            echo "用法: bash scripts/run_pipeline.sh {dryrun|step} [--skip-phase3]"
            echo ""
            echo "  dryrun    甄嬛传 × 3章 全流程自测"
            echo "  step      全部 active_books 全流程 (每本书独立 Phase 1→2→3)"
            echo ""
            echo "可选参数:"
            echo "  --skip-phase3    跳过 Phase 3 审稿 + 跨书总结（线上生产模式，零评分开销）"
            echo ""
            echo "step 模式执行流:"
            echo "  书A: Phase1(框架) → Phase2(写书) → Phase3(审稿)"
            echo "  书B: Phase1(框架) → Phase2(写书) → Phase3(审稿)"
            echo "  ..."
            echo "  跨书总结"
            echo ""
            echo "V3 状态管理 (workspace/iteration-state.json):"
            echo "  ═══ Phase 阶段控制 ═══"
            echo "  books.{书名}.phase  : pending | phase1_done | phase2_done | phase3_done | done"
            echo "  books.{书名}.version: v1 | v2 | v3 | ...  (目标版本号)"
            echo "  books.{书名}.score  : 签约审稿分数 (Phase 3 后自动填充)"
            echo "  books.{书名}.passed : true/false (Phase 3 后自动填充)"
            echo "  books.{书名}.review_skipped : true (--skip-phase3 时标记)"
            echo ""
            echo "  ═══ 使用场景 ═══"
            echo "  断点续跑          : 不做任何修改，脚本自动跳过已完成阶段"
            echo "  重头从 v3 跑      : 改 version → v3, phase → pending"
            echo "  仅重跑 Phase 2/3  : 改 phase → phase1_done"
            echo "  仅重跑 Phase 3    : 改 phase → phase2_done"
            echo "  补审已跳过的书    : 改 phase → phase2_done，不带 --skip-phase3 重跑"
            echo ""
            echo "环境变量:"
            echo "  PIPELINE_TIMEOUT       单阶段超时秒数 (默认 3600=1h, 0=不限)"
            echo "  CHAPTER_TIMEOUT        单章超时秒数 (默认 1800=30min, 0=不限)"
            echo "  PIPELINE_MAX_ATTEMPTS  流水线最大重启次数 (默认 3)"
            rm -f "$ATTEMPT_FILE"
            exit 1
            ;;
    esac

    exit_code=$?

    if [ $exit_code -eq 0 ]; then
        rm -f "$ATTEMPT_FILE"
        echo ""
        success "流水线完成 (第 ${current_attempt} 次尝试)"
        exit 0
    elif [ $exit_code -eq 124 ]; then
        if [ $current_attempt -lt $PIPELINE_MAX_ATTEMPTS ]; then
            warn "流水线超时，${CHAPTER_TIMEOUT}s 后自动重启..."
            sleep "$CHAPTER_TIMEOUT"
        else
            rm -f "$ATTEMPT_FILE"
            echo ""
            fail "流水线全部 ${PIPELINE_MAX_ATTEMPTS} 次尝试均超时"
            fail "请人工检查: 子 agent 卡死点 | chapter 文件状态 | opencode 配置"
            exit 1
        fi
    else
        rm -f "$ATTEMPT_FILE"
        echo ""
        fail "流水线异常终止 (exit=$exit_code, 第 ${current_attempt} 次尝试)"
        exit $exit_code
    fi
done
