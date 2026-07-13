# Pipeline 子 agent 卡死 → 无限消耗 token Bug 分析与修复

**日期**: 2026-07-06
**涉及文件**: `scripts/run_pipeline.sh`, `project-agents-template/.opencode/agents/chief_editor.md`

---

## 一、问题描述

执行 `./scripts/run_pipeline.sh step` 时，Phase 2 的第3章卡死。`content_writer` 子 agent (Flash) 不返回结果、不写输出文件。`chief_editor` 主 agent (Pro 主控) 永远等待，shell 脚本永远阻塞。Token 持续消耗。

## 二、根因分析

### 2.1 卡死链路

```
shell: run_pipeline.sh
  └─ run_phase()
      └─ opencode run --agent chief_editor "执行第3章生产"
          ├─ chief_editor (Pro v4 主控)
          │   ├─ @plot_planner (Flash) → 章纲 ✅
          │   └─ @content_writer (Flash) → 初稿 ███ 卡死 ███
          └─ 永远等不到 content_writer 返回
```

### 2.2 Pro token 为何持续消耗

`chief_editor` 主 agent 通过 Pro 模型做编排决策。`@content_writer` 子 agent 卡死期间，opencode 框架层的心跳/上下文维护/超时重决策等操作都触发 Pro 推理，导致 Pro token 被持续消耗。

### 2.3 全链路 19 处超时盲点

Phase 1 (`automation_manager`): @original_analyst, @compliance_*, @style_mapper/@style_*, @facade_generator, @salt_architect, @master_outline_generator

Phase 2 (`chief_editor`): @plot_planner(卷纲), @plot_planner(章纲), @content_writer(fresh), @quality_reviewer, @content_writer(rewrite)

Phase 3 (`reviewer_orchestrator`): @whitepaper_reviewer, @master_outline_reviewer, @volume_outline_reviewer, @chapter_outline_reviewer, @signing_reviewer, @pipeline_auditor, @input_monitor

跨书总结

## 三、修复方案

### 设计原则

> 卡死不等于写不出来。超时后退出重启（最多3次），利用 checkpoint 天然跳过已完成章节。不跳过任何章。全部重试耗尽才停止，人工介入排查。

### 3.1 Shell 层：`run_pipeline.sh`

#### 变更 1：新增超时默认值

```bash
# 旧
TIMEOUT_PER_PHASE="${PIPELINE_TIMEOUT:-0}"   # 不限时，默认 0

# 新
TIMEOUT_PER_PHASE="${PIPELINE_TIMEOUT:-3600}"   # 默认 1h
CHAPTER_TIMEOUT="${CHAPTER_TIMEOUT:-1800}"       # 单章 30min
PIPELINE_MAX_ATTEMPTS="${PIPELINE_MAX_ATTEMPTS:-3}"  # 最多重启3次
```

#### 变更 2：`run_phase` / `run_chapter` 区分超时信号

```bash
# 超时返回 exit code 124（不是 1），调用方可区分"超时"与"普通失败"
run_phase() {
    # ...
    elif [ "$TIMEOUT_PER_PHASE" -gt 0 ] && [ $rc -eq 124 ]; then
        return 124   # 传播超时信号
    # ...
}
```

#### 变更 3：章节超时 → exit 整个脚本

```bash
# 单章超时: exit 124 → 触发入口层重启
run_chapter "Phase 2.$ch ..." "$CHAPTER_TIMEOUT" ...
if [ $ch_rc -eq 124 ]; then
    fail "$name 第${ch}章 超时，退出流水线等待重启"
    exit 124         # ← 退出整个脚本，不跳过，不放弃
elif [ $ch_rc -ne 0 ]; then
    fail "$name 第${ch}章 失败"
    return 1         # ← 普通失败，放弃该书
fi
```

#### 变更 4：入口层重启循环

```bash
# 脚本底部: 重试包装器
while [ $current_attempt -lt $PIPELINE_MAX_ATTEMPTS ]; do
    # 执行 dryrun_inner / step_inner（原 dryrun_all / step_all）
    exit_code=$?

    if [ $exit_code -eq 0 ]; then
        success "流水线完成"
        exit 0
    elif [ $exit_code -eq 124 ]; then
        # 超时 → 等待后重启
        sleep "$CHAPTER_TIMEOUT"
        # 重启时: 终稿存在的章节自动跳过 (checkpoint 生效)
    else
        fail "异常终止"
        exit $exit_code
    fi
done
fail "全部尝试均超时，请人工排查"
```

### 3.2 Agent 层：`chief_editor.md`

#### 新增 §3f：子 agent 输出校验

每次调完子 agent 后立即检查输出文件是否存在：

| 步骤 | 检验文件 | 无输出时的处理 |
|------|---------|--------------|
| 3a @plot_planner | 章纲.md | 重试1次，仍失败则不写终稿 |
| 3b @content_writer(fresh) | 初稿-v1.md | 不写终稿（重启时重试） |
| 3c.a @quality_reviewer | 纪要.md | 视为 score=0，继续循环 |
| 3c.i @content_writer(rewrite) | 初稿-v{retry+1}.md | 退出循环，取 best_version |

**核心原则**：绝不写"假的终稿"。子 agent 没产出 = 终稿不存在 = 重启时自动重试。

---

## 四、对当前斗破苍穹 v2 第3章的影响

**当前状态**：`02-正文/第3章-终稿.md` 不存在，无终稿。

**修复后行为**：

```
阶段1: 到达第3章 → run_chapter → 30min超时 → exit 124
阶段2: 脚本自动重启 (2/3) → 第1章终稿exists → 跳过 → 第2章终稿exists → 跳过 → 第3章无终稿 → 重试 → 再次超时 → exit 124
阶段3: 脚本自动重启 (3/3) → 同阶段2 → 再次超时 → 重试耗尽
结果: 输出"全部 3 次尝试均超时，请人工排查: 子 agent 卡死点 | chapter 文件状态 | opencode 配置"
```

如果卡死是 transient（网络抖动/API 临时不可用），自动重启就能恢复。如果卡死是 systemic（content_writer 指令死循环），人工介入排查 agent 配置。

---

## 五、环境变量参考

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PIPELINE_TIMEOUT` | 3600 (1h) | 单阶段全局超时秒数，0=不限 |
| `CHAPTER_TIMEOUT` | 1800 (30min) | 单章超时秒数，0=不限 |
| `PIPELINE_MAX_ATTEMPTS` | 3 | 流水线整体最大重启次数 |

恢复旧行为（无超时）：`PIPELINE_TIMEOUT=0 CHAPTER_TIMEOUT=0 bash scripts/run_pipeline.sh step`
