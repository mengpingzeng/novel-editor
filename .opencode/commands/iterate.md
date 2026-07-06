---
description: 批量自动化编排：dryrun（快速自测）/ step（框架生成）/ status（查看状态）
---

## `/iterate` — 批量自动化编排（V2）

V2 架构采用三层解耦，每层独立上下文、独立启动。`/iterate` 仅触发 Phase 1（框架层），Phase 2 和 Phase 3 需手动分步执行。

### 三层架构

```
Phase 1 框架层 → automation_manager（仅生成框架，完成后停止）
  ↓ 输出 Phase 2 命令提示
Phase 2 内容层 → chief_editor（每本书独立启动，独立上下文）
  ↓ 写入 .phase2_done
Phase 3 评价层 → reviewer_orchestrator（逐本审稿 + 跨书总结）
```

### 用法

```
/iterate dryrun [书数] [章数]     快速自测 Phase 1 框架生成，默认 1 本 × 3 章框架
/iterate step                     运行 Phase 1：对所有 active_books 逐本生成框架 → 停止
/iterate status                   查看当前 iteration-state.json 状态
```

### dryrun 说明

- **目的**：验证 Phase 1 框架生成流程正常
- **规模**：默认 1 本（甄嬛传）× 3 章配置，framework-only
- **隔离**：产物在 workspace/_dryrun/，与正式目录完全隔离
- **验收**：完成后输出验收清单

**dryrun 完整三阶段自测命令**：

```bash
# Phase 1：框架生成
opencode run --auto "/iterate dryrun"

# Phase 2：写书（需要 Phase 1 完成后手动执行）
opencode run --dir workspace/_dryrun/books/甄嬛传/ \
  --agent chief_editor --auto "全自动执行第1~3章生产"

# Phase 3：审稿（需要 Phase 2 完成后手动执行）
opencode run --dir workspace/reviewer/ \
  --agent reviewer_orchestrator --auto "审核 workspace/_dryrun/books/甄嬛传/versions/v1/"
```

### step 说明（正式执行）

**Phase 1**：生成框架
```
/iterate step
```
或直接：
```bash
opencode run --auto "/iterate step"
```
automation_manager 对 active_books 逐本生成框架产物，完成后输出 Phase 2 启动命令并停止。

**Phase 2**：逐书写书（每本书单独执行）
```bash
opencode run --dir workspace/books/{书名}/ \
  --agent chief_editor --auto "全自动执行第1~{N}章生产"
```
每本书独立上下文，完成自动写入 `.phase2_done`。

**Phase 3**：审稿（逐本 + 跨书总结）
```bash
# 逐本审稿
opencode run --dir workspace/reviewer/ \
  --agent reviewer_orchestrator --auto "审核 workspace/books/{书名}/versions/{version}/"

# 跨书总结
opencode run --dir workspace/reviewer/ --auto \
  "生成跨书总结报告 version=v1 books=书A,书B,书C"
```
完成自动写入 `.phase3_done`。

### 核心变化（V1 → V2）

| 项目 | V1 | V2 |
|------|----|----|
| 一键执行 | `/iterate step` 完成全过程 | 需分三步手动执行 |
| 写书调度 | book_factory（V4 Flash） | chief_editor（V4 Flash） |
| 审稿调度 | automation_manager 直接调 signing_reviewer | reviewer_orchestrator 编排全层级 |
| 上下文 | 单体 ~225K | Phase 2 独立 ~60K |
| 日志文件 | execution-log.md | 自动化处理日志.md |
