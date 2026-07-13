# Phase 1 Scope 隔离失效分析与 State 文件替换方案

## 问题现象

执行 `./scripts/run_pipeline.sh step`，第一步处理斗破苍穹的 Phase 1 时，`/iterate step` agent 同时对甄嬛传、白夜行、赘婿启动了 `original_analyst`，导致多本书的 Phase 1 被并行触发。

## 执行流程

```
step_inner():
  for 斗破苍穹:
    Phase 1 → 调 /iterate step
      agent 读 iteration-state.json → active_books(4 本) 全 pending
      → 对 4 本书并行启动 original_analyst
  for 甄嬛传:
    Phase 1 → (phase 仍是 pending，同上)
  ...
```

## 根因分析

`run_pipeline.sh` 在 `run_phase1_for_book()` 中做了 scope 隔离：

```bash
# L289-307：创建 scope 文件，仅含当前 1 本书
python3 -c "..."  → workspace/.pipeline_scope.json (1 本书)

# L310：调用 agent
opencode run "/iterate step"
```

但 agent 启动时，工作目录下同时存在两个文件：

| 文件 | 内容 |
|------|------|
| `workspace/.pipeline_scope.json` | `active_books: [斗破苍穹]` |
| `workspace/iteration-state.json` | `active_books: [斗破苍穹, 甄嬛传, 白夜行, 赘婿]` |

`automation_manager.md:38` 写的是 **"优先读取 scope 文件"**，这只是 prompt 级建议，不构成强制。agent 可以同时读两个文件，看到 `iteration-state.json` 中 4 本全部 `pending` → "热心"地全部处理。

**scope 隔离依赖 LLM agent 遵守 prompt 指令，不是文件系统级硬隔离。**

## 方案：临时替换 State 文件

不改变 agent 逻辑，不改变脚本循环结构。在 `run_phase1_for_book()` 中，调用 `/iterate step` 前后交换 state 文件。

### 原理

agent 内部逻辑不变（同一条 `/iterate step`、同一个 `automation_manager`），但启动时 `iteration-state.json` 路径下物理上只包含当前 1 本书。agent 读不到其他书的条目 → 只能处理 1 本。

### 改动位置

`scripts/run_pipeline.sh` 中 `run_phase1_for_book()` 函数（L276），在 scope 文件生成之后、agent 调用之前，对 `iteration-state.json` 做临时替换。

### 伪代码

```
run_phase1_for_book(book_name):
  1. 创建 scope 文件（已有，L289-307）

  # ── 新增 swap ──
  2. cp iteration-state.json → iteration-state.json.bak    # 备份全量（含所有书）
  3. cp .pipeline_scope.json → iteration-state.json        # 替换为单书内容

  4. opencode run "/iterate step"                           # agent 只看到 1 本书
     → agent 按 active_books（1 本）逐本执行
     → 完成后写入 phase1_done 到 scope 文件

  # ── 新增恢复 ──
  5. cp iteration-state.json.bak → iteration-state.json    # 恢复全量

  6. 从 scope 同步 phase/version 回全量 state（已有，L335-349）
     → iteration-state.json 更新为: book_name=phase1_done, 其余=原样
```

### 循环执行示例

5 本书的 `active_books`，其中凡人修仙传还不在 `active_books` 中而是在 `books` 字典中：

```
# 初始 iteration-state.json:
books: {凡人修仙传: pending, 斗破苍穹: pending, 甄嬛传: pending, 白夜行: pending, 赘婿: pending}
active_books: [斗破苍穹, 甄嬛传, 白夜行, 赘婿]

# 第 1 轮: 斗破苍穹
swap → agent 只看到 {斗破苍穹} → 处理完成 → phase=phase1_done
恢复 → iteration-state.json: {凡人修仙传: pending, 斗破苍穹: phase1_done, 甄嬛传: pending, ...}

# 第 2 轮: 甄嬛传
swap → agent 只看到 {甄嬛传} → 处理完成 → phase=phase1_done
恢复 → iteration-state.json: {斗破苍穹: phase1_done, 甄嬛传: phase1_done, ...}

# 第 3 轮: 白夜行
swap → agent 只看到 {白夜行} → ...
```

每轮 swap 是局部操作：进来把全量藏到 `.bak`，出去恢复全量并补上当前书的 phase 变更。外层 `for` 无感知。

凡人修仙传在 `books` 字典中但不在 `active_books` 中——它原样保留在 `.bak` 中，swap 后不受影响，agent 不会处理它。

### 与现有机制的兼容

| 已有代码 | 影响 |
|----------|------|
| L335-349 同步 scope → 主 state | **不变**，swap 恢复后继续执行 |
| L289-307 创建 scope 文件 | **不变**，仍创建，agent 写回 scope |
| `get_book_phase()` 对 `pending` 的判断 | **不变**，全量文件恢复后 phase 正确更新 |
| Phase 2 / Phase 3 | **不变**，不涉及 state 文件 swap |

### 待清理

- `workspace/.pipeline_scope.json` 可在每轮 Phase 1 结束后删除，或直接复用覆盖
- swap 中产生的 `.bak` 文件在函数退出后不再需要，可删除
