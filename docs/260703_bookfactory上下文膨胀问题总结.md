# book_factory 上下文膨胀问题总结

> 日期：2026-07-03
> 讨论范围：book_factory 编排 agent 的上下文膨胀原因、影响、可行方案

---

## 背景

book_factory 是写小说的核心编排 agent，负责 12 步完整流水线：白皮书 → 赛道映射 → 门面 → 盐值 → 总纲 → 卷纲 → 章纲 → 正文 → 质检 → 审核报告。每步通过调用子 agent（`@original_analyst`、`@whitepaper_reviewer`、`@plot_planner`、`@content_writer` 等）完成。

设计初衷是三步互相隔离：白皮书生产 → 仿写规划 → 正文生成，各自不应感知其他阶段的上下文。

---

## 已识别问题

### P0：book_factory 上下文爆炸（致命）

V4 Flash 上下文窗口约 **128K tokens**。20 章场景下 book_factory 上下文累积估算：

| 来源 | 20 章累积 | 性质 |
|------|:--:|------|
| book_factory 自身 SOP 指令 | 5,000 | 固定开销 |
| Step 6 亲自读白皮书文件 | 20K~50K | book_factory 自己读，不是子 agent |
| 4 类 reviewer 完整报告回流 | 25,000 | 不写文件，纯靠上下文传递 |
| content_writer 正文返回 | 60,000 | 写文件的同时也返回全文 |
| quality_reviewer 质检报告返回 | 60,000 | 写纪要的同时也返回全文 |
| 其他子 agent 返回值 + 工具输出 | 25,000 | 累积开销 |
| **20 章总计** | **~200K+** | **超过 128K 上限 56%** |

**估算 10 章以内就濒临溢出，20 章必然炸。**

### P1：4 类评分子 Agent 无文件沉淀

| Agent | 输出位置 |
|-------|---------|
| whitepaper_reviewer | 仅返回给 book_factory，不写文件 |
| master_outline_reviewer | 仅返回给 book_factory，不写文件 |
| volume_outline_reviewer | 仅返回给 book_factory，不写文件 |
| chapter_outline_reviewer | 仅返回给 book_factory，不写文件 |

四个 reviewer 的输出格式全部写的是「评分结果直接返回给调用方」。维度明细、致命问题、修正建议全部不落盘，只在 book_factory 上下文中短暂存在。上下文溢出即永久丢失。

### P2：三步隔离只防了下游，没防回流

```
Layer 1 (白皮书)        Layer 2 (总纲/卷纲/章纲)       Layer 3 (正文/质检)
     │                        │                            │
     └── 完整报告 ───────────→│                            │
                              └── 完整报告 ───────────────→│
     ←──────────────── 回流到 book_factory 上下文 ─────────┘
```

- 子 agent 之间隔离是好的（content_writer 拿不到白皮书、赛道映射等上下文）✓
- 但每个 agent 的完整输出全部回流到 book_factory ✗
- book_factory 成了所有阶段产物的垃圾场

### P3：Step 6 总纲生成没有委托给子 agent

book_factory 在 Step 6 自己读 50K 白皮书、自己生成仿写总纲。这一步不是子 agent 调用，白皮书全文直接灌进 book_factory 上下文。

### P4：Step 10 依赖上下文检索而非文件读取

最终的 `审核报告.md` 需要从每个 reviewer 的输出中提取「核心问题和建议」填充各层详细总结。但 reviewer 没写文件，book_factory 只能从拥挤的上下文中回溯检索——越到后期检索越不可靠，报告质量越差。

### P5：崩溃后不可恢复

book_factory 是一个长会话。如果跑到第 18 章崩溃：
- 前 17 章的 reviewer 完整报告全部丢失
- execution-log 里只有分数摘要还在
- 正文和章纲文件虽然落盘了，但评分分析全没了
- 无法续跑，只能重来

### P6：input_monitor 盲区

input_monitor 只追踪子 agent 的输入文件大小增长（如 plot_planner 读纪要从头累积），不追踪 book_factory 自身的上下文膨胀。而后者才是真正的定时炸弹。

### P7：chapter_outline_reviewer 缺少卷级上下文

volume_outline_reviewer 传了 3 个参数（卷纲 + 总纲 + 盐值），但 chapter_outline_reviewer 只传 2 个（章纲 + 总纲），`volume_outline_path` 是选填的但 book_factory Step 8a 根本没传。章纲评分缺少卷级节奏弧线上下文。

---

## 可行解决方案

### 方案 1：改 reviewer 输出口径（性价比最高）

修改 4 个 reviewer agent 定义：

```
改为：
1. 先 Write 完整审核报告到约定路径（如 "01-大纲/第N章章纲-审核报告.md"）
2. 再返回给调用方仅一行：评分：98/100，评级：极佳
```

- **收益**：每条 reviewer 从 ~1000 tokens 降到 ~20 tokens，20 章省 ~20K
- **改动范围**：4 个 agent 定义文件 + book_factory Step 10 改为读文件

### 方案 2：改 content_writer / quality_reviewer 输出口径（收益最大）

- content_writer：写正文到文件后，只返回 `✅ 第N章完成，{字数}字`，不返回正文
- quality_reviewer：写纪要后，只返回 `✅ {分数}分 — 通过/未通过`，不返回完整报告

- **收益**：这两类是上下文头号杀手，20 章省 ~120K tokens，直接解决爆炸问题
- **改动范围**：2 个 agent 定义文件

### 方案 3：Step 6 委托给子 agent

把仿写总纲生成交给新子 agent（或复用 plot_planner 的总纲模式），book_factory 只传参数、验文件存在。

- **收益**：省 ~30K tokens（白皮书不再进 book_factory 上下文）
- **改动范围**：book_factory Step 6 逻辑 + 新建/复用 agent

### 方案 4：Step 10 独立为 report_compiler

新建子 agent 专门做报告汇总：接收版本目录路径，读取所有层的审核报告文件，拼出最终的 `审核报告.md`。book_factory 只调用它，上下文与此无关。

- **收益**：Step 10 不再需要在拥挤上下文中检索，报告质量提升
- **前提依赖**：方案 1 先落地（reviewer 须先写文件）

### 方案 5：拆 book_factory 为多阶段 agent

将当前 12 步拆成 3 个独立 agent，每个有全新上下文：

| 新 agent | 覆盖步骤 | 职责 |
|----------|---------|------|
| `phase1_setup` | Steps 0~5 | 白皮书 → 赛道映射 → 门面 → 盐值 |
| `phase2_planning` | Steps 6~7 | 总纲生成 → 卷纲规划 |
| `phase3_writing` | Steps 8~10 | 章节循环 → 审核报告 |

它们之间只通过文件通信。

- **收益**：最彻底的隔离，每个 agent 上下文干净
- **改动范围**：最大，需要拆分 book_factory + 修改 automation_manager 调用逻辑

---

## 推荐实施顺序

| 优先级 | 方案 | 原因 |
|:--:|------|------|
| 1 | 方案 2 | 收益最大（省 120K），改动最小（2 个 agent 定义） |
| 2 | 方案 1 | 为方案 4 铺路，同时省 20K |
| 3 | 方案 3 | 进一步减负 book_factory |
| 4 | 方案 4 | 提升 Step 10 报告质量 |
| 5 | 方案 5 | 治本但改动大，长期考虑 |

---

## 其他讨论要点

1. **execution-log 是唯一持久化的评分记录**——但只有分数，没有分析细节。如果未来想做「问题趋势分析」或「修复建议追踪」，现在没有数据基础。

2. **dryrun 路径多一层 `_dryrun`**——production 路径 `workspace/books/`，dryrun 是 `workspace/_dryrun/books/`。检查文件时需注意这层差异。

3. **quality_reviewer 返回全文给 book_factory 但内容已落盘**——写完纪要又返回全文进上下文，纯属重复，属于最明显的浪费。
