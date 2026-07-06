# OpenCode 自动化评分系统 — 设计与架构文档

> 当前版本：V2 | 更新日期：2026-07-04 | 平台：OpenCode

---

## 一、V2 三层解耦架构（当前版本）

V2 废弃了 `book_factory` 单体流水线，改为三层独立 agent、独立上下文。

```
Phase 1 框架层（novel-editor/.opencode/agents/ — 17 个 agent）
  automation_manager → original_analyst / style_* / facade_generator / salt_architect / master_outline_generator / compliance_*
  输入: source.txt
  产出: 白皮书 + 赛道映射 + 门面 + 盐值 + 仿写总纲领
  标记: .phase1_done
  命令: opencode run --auto "/iterate step" (automation_manager 处理全部 active_books 后停止)

Phase 2 内容层（workspace/books/<书名>/.opencode/agents/ — 5 个 agent）
  chief_editor → plot_planner / content_writer / quality_reviewer / data_operator
  上下文: 每本书独立启动 (opencode run --dir workspace/books/<书名>/)
  产出: 卷纲 + 章纲 + 章节正文 + 章级质检纪要
  标记: .phase2_done

Phase 3 评价层（workspace/reviewer/.opencode/agents/ — 8 个 agent）
  reviewer_orchestrator → 7 个评分 agent
  上下文: 独立启动 (opencode run --dir workspace/reviewer/)
  产出: 全层级评分报告 + 签约审稿 + 流程审计 + 跨书总结
  标记: .phase3_done
```

### 一键执行

```bash
bash scripts/run_pipeline.sh dryrun    # 自测
bash scripts/run_pipeline.sh step      # 正式执行
```

### Agent 分布

| 层 | 位置 | 数量 | 核心 agent |
|----|------|:--:|-----------|
| Phase 1 | `novel-editor/.opencode/agents/` | 17 | automation_manager, original_analyst, style_*(×8), facade_generator, salt_architect, master_outline_generator, compliance_*(×2), global_manager, workflow_optimizer |
| Phase 2 | `project-agents-template/.opencode/agents/` → 复制到 `workspace/books/<项目>/.opencode/agents/` | 5 | chief_editor, plot_planner, content_writer, quality_reviewer, data_operator |
| Phase 3 | `workspace/reviewer/.opencode/agents/` | 8 | reviewer_orchestrator(NEW), pipeline_auditor(NEW), signing_reviewer, whitepaper_reviewer, master_outline_reviewer, volume_outline_reviewer, chapter_outline_reviewer, input_monitor |

### 评分体系（Phase 3）

| 层 | Agent | 模型 | V1 | V2 |
|----|-------|------|:--:|:--:|
| L1 白皮书 | whitepaper_reviewer | GLM 5.2 | ✅ | ✅ |
| L2 仿写总纲 | master_outline_reviewer | GLM 5.2 | ✅ | ✅ |
| L3 卷纲 | volume_outline_reviewer | GLM 5.2 | ✅ | ✅ |
| L4 章纲 | chapter_outline_reviewer | GLM 5.2 | ✅ | ✅ |
| L5 章内容 | quality_reviewer | V4 Flash | ✅ | ✅ |
| L6 输入监控 | input_monitor | V4 Flash | ✅ | ✅ |
| L7 签约审稿 | signing_reviewer | GLM 5.2 | ✅ | ✅ |
| **L8 流程审计** | **pipeline_auditor** | **GLM 5.2** | — | **★新增** |

综合加权：白皮书×10% + 总纲×15% + 卷纲×10% + 章纲×10% + 章内容×20% + 输入监控×5% + 签约审稿×20% + 流程审计×10%

### pipeline_auditor 流程架构审计

从章内容逆向追溯上游信息的完备性：

| 维度 | 权重 | 核心问题 |
|------|:--:|---------|
| A 开篇能力 | 25 | 白皮书→总纲→章纲是否为前 N 章提供了足够的钩子策略和冲突信息？ |
| B 中间丰富度 | 35 | 卷纲是否有明确的中间危机？章纲间伏笔延续率是否 ≥ 70%？ |
| C 结尾防烂尾 | 20 | 总纲是否定义了结局高潮类型？终卷有无 ≥ 3 章铺垫？ |
| D 信息可执行率 | 20 | 章纲中模糊指令占比是否 < 10%？content_writer 五要素覆盖率？ |

### quality_reviewer V2 增强

**字数约束**：<1000 或 >3000 字 → 整篇 0 分（一票否决），满分区间 [1500, 2500]。

**重写循环**：评分 <60 → 最多 3 轮重写（1 初写 + 2 重写），content_writer 读入质检纪要作反馈，取最高分版本为终稿。

### 完成标记协议

| 标记文件 | 写入者 | 位置 |
|---------|--------|------|
| `.phase1_done` | automation_manager | `workspace/books/{书名}/` |
| `.phase2_done` | chief_editor | `workspace/books/{书名}/` |
| `.phase3_done` | reviewer_orchestrator | `workspace/books/{书名}/versions/{v}/` |

### 上下文膨胀控制

| 场景 | V1 (book_factory 单体) | V2 (三层隔离) |
|------|----------------------|--------------|
| Phase 1 上下文 | ~50K | ~50K |
| Phase 2 上下文 | ~225K | **~60K** |
| Phase 3 上下文 | 混在 book_factory | **~20K** |
| 跨书总结上下文 | 混在 automation_manager | **~15K** |

---

## 二、目录结构（V2）

```
workspace/
├── iteration-state.json
├── repo/{原著名}/
│   ├── source.txt
│   └── base_whitepaper.md
├── books/
│   └── {书名}/
│       ├── .opencode/agents/         ← Phase 2 agent
│       ├── .phase1_done
│       ├── .phase2_done
│       ├── project_salt.json
│       ├── 仿写衍生总纲领.md
│       └── versions/{v}/
│           ├── 00-素材/
│           ├── 01-大纲/
│           │   ├── 01-卷纲/
│           │   └── 第N章章纲.md
│           ├── 02-正文/
│           ├── 03-纪要/
│           ├── 发布/                  ← novel_metadata.json
│           ├── 自动化处理日志.md       ← 原 execution-log.md
│           ├── 审核报告.md
│           ├── 审稿报告-{v}.md
│           ├── 流程审计报告-{v}.md
│           └── .phase3_done
├── reviewer/                         ← Phase 3 独立目录
│   └── .opencode/agents/
│       ├── reviewer_orchestrator.md   ← 新建
│       ├── pipeline_auditor.md        ← 新建
│       ├── signing_reviewer.md        ← 从根目录迁移
│       ├── whitepaper_reviewer.md      ← 从根目录迁移
│       ├── master_outline_reviewer.md  ← 从根目录迁移
│       ├── volume_outline_reviewer.md  ← 从根目录迁移
│       ├── chapter_outline_reviewer.md ← 从根目录迁移
│       └── input_monitor.md           ← 从根目录迁移
└── _dryrun/
```

---

## 三、V1 历史内容（仅供参考）

> 以下为 V1 版本的架构文档，V2 已废弃 `book_factory` 单体模式。

### 3.1 系统概述

用 AI 流水线将原著网文改写为「逻辑严谨、有追读欲」的新小说，通过独立的评分系统对产出进行严格审核。写作流水线与评分系统完全解耦，可独立使用。

### 3.2 V1 架构（已废弃）

```
automation_manager (V4 Pro, primary)
  → book_factory × N (V4 Flash) — 写书
  → signing_reviewer × N (GLM 5.2) — 审稿
  → 汇总报告 → 停止
```

### 3.3 V1 Agent 角色（已废弃）

| Agent | 模式 | 模型 | 职责 |
|-------|------|------|------|
| book_factory | subagent | V4 Flash | 编排完整写作流水线 |
| original_analyst | subagent | V4 Pro | 拆解原著 → 白皮书 |
| style_mapper | subagent | V4 Pro | 赛道映射 + 分类标签 |
| facade_generator | subagent | V4 Pro | 书名 + 简介 |
| salt_architect | subagent | V4 Pro | 盐值校验去重 |
| plot_planner | subagent | V4 Flash | 章纲 |
| content_writer | subagent | V4 Flash | 正文 |
| quality_reviewer | subagent | V4 Flash | 单章质检（≥80 分） |
| compliance_* | subagent | V4 Flash | 平台合规 |
| signing_reviewer | subagent | GLM 5.2 | 签约级整本审稿 |

### 3.4 V1 signing_reviewer rubric v2.0（仅供参考）

**总则：** 满分 100 分，**及格线 = 60 分**，且无任何一票否决项命中。

| # | 维度 | 分值 |
|---|------|------|
| 1 | 开篇抓力 | 12 |
| 2 | 追读欲 / 钩子链 | 18 |
| 3 | 逻辑严谨性 | 18 |
| 4 | 人物可信度 | 10 |
| 5 | 爽感节奏 | 10 |
| 6 | 文笔流畅度 | 8 |
| 7 | 设定与世界观 | 5 |
| 8 | 完结延展性 | 4 |
| 9 | 原创改写度 | 15 |

六条一票否决项：逻辑硬伤 / 降智推进 / 追读断裂 / 平台红线 / AI 味过重 / 换皮抄袭。

### 3.5 V2 key changes from V1

| 变更 | V1 | V2 |
|------|----|----|
| 写书入口 | book_factory (single agent) | chief_editor (Phase 2 primary) |
| 审稿入口 | signing_reviewer (single call) | reviewer_orchestrator (orchestrates 8 agents) |
| 执行方式 | `/iterate step` (all-in-one) | `bash scripts/run_pipeline.sh step` (per-book pipeline) |
| 上下文 | Single monolithic ~225K | Phase 2 ~60K (isolated per book) |
| 质检 | Score <60 → skip | Max 3 rewrite rounds, pick best |
| 字数 | Max -5 points | <1000 or >3000 → entire chapter 0 points |
| 流程审计 | None | pipeline_auditor (4 dimensions, 100-point scale) |
| 日志文件 | execution-log.md | 自动化处理日志.md |
| novel_metadata | books/{name}/ | versions/{v}/发布/ |
