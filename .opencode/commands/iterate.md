---
description: 批量自动化编排：dryrun（快速自测）/ step（单轮执行）/ status（查看状态）
---

## `/iterate` — 批量自动化编排

### 三层严格串行

```
automation_manager（顶层调度，V4 Pro）
  ↓ 等待完成
book_factory × N（独立写作流水线，V4 Flash）
  ↓ 等待完成
signing_reviewer × N（独立评分系统，GLM 5.2）
  ↓ 等待完成
汇总报告 → 停止（永不自动迭代）
```

### 用法

```
/iterate dryrun [书数] [章数]     快速自测，默认 1 本 × 3 章，产物落在 workspace/_dryrun/
/iterate step                     运行一轮：写书 → 审稿 → 汇总 → 停止
/iterate status                   查看当前 iteration-state.json 状态
```

### dryrun 说明

- **目的**：验证全流程能跑通——模型分配正确、日志正确、内容可正常生产
- **规模**：默认 1 本（娘娘本纪）× 3 章
- **隔离**：产物在 workspace/_dryrun/，与正式目录完全隔离
- **验收**：dryrun 完成后会输出验收清单，逐项确认后即可正式 step

### step 说明

- **每轮三阶段严格串行**：writing → reviewing → done
- **writing**：逐本调 book_factory（一本写完才开始下一本）
- **reviewing**：逐本调 signing_reviewer（一本审完才开始下一本）
- **done**：输出汇总表，停止

**永不自动迭代，永不自动优化 agent 定义。**
