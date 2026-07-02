# OpenCode 自动化评分系统 — 设计与架构文档

> 版本：V1 | 日期：2026-07-02 | 平台：OpenCode
> 基于 codebuddy_自动化评分优化系统设计.md 迁移改造

---

## 一、系统概述

用 AI 流水线将原著网文改写为「逻辑严谨、有追读欲」的新小说，通过独立的评分系统对产出进行严格审核。写作流水线与评分系统完全解耦，可独立使用。

### 核心原则

1. **写作与评分解耦**：book_factory 写书，signing_reviewer 审稿，互不依赖
2. **三层严格串行**：调度 → 写作 → 审稿，前一层完成才开始下一层
3. **永不自动迭代**：每轮 step 结束后停止，由用户判断是否进入下一轮
4. **绝不自动优化**：审稿报告只输出不行动，用户手动指导优化方向
5. **版本不覆盖**：每轮写在新版本目录（v1/v2/v3...），旧版永久保留

---

## 二、架构总览

```
┌──────────────────────────────────────────────────────┐
│  批量编排层 automation_manager (V4 Pro, primary)       │
│  /iterate dryrun | /iterate step                     │
│  职责：读状态 → 调 book_factory 写书 → 调 signing_reviewer 审稿 → 汇总 → 停 │
└──────────┬───────────────────────────────┬───────────┘
           │ 等待完成                       │ 等待完成
           ▼                               ▼
┌─────────────────┐              ┌─────────────────┐
│ 独立写作流水线    │              │ 独立评分系统     │
│ book_factory     │              │ signing_reviewer │
│ (V4 Flash)       │              │ (GLM 5.2)        │
│                  │              │                  │
│ 可独立提取，      │              │ 可独立调用，      │
│ 不依赖其他层      │              │ 不关心谁写的      │
└─────────────────┘              └─────────────────┘
```

---

## 三、三层严格串行

```
automation_manager (V4 Pro) — 顶层唯一调度者
  │ 逐个等待完成
  ▼
book_factory × N (V4 Flash)
  → 第1本完成 → 第2本开始 → ... → 第N本完成
  │ 全部写完
  ▼
signing_reviewer × N (GLM 5.2)
  → 第1本完成 → 第2本开始 → ... → 第N本完成
  │ 全部审完
  ▼
汇总报告 → 停止（永不自动迭代，永不自动优化）
```

---

## 四、Agent 角色与模型分配

### 调度层

| Agent | 模式 | 模型 | 职责 |
|-------|------|------|------|
| automation_manager | primary | `team-deepseek/deepseek-v4-pro` | 读状态文件，串联写作→审稿→汇总 |

### 独立写作流水线

| Agent | 模式 | 模型 | 职责 |
|-------|------|------|------|
| **book_factory** | subagent | `team-deepseek/deepseek-v4-flash` | 编排完整写作流水线，source.txt → 章节 |
| original_analyst | subagent | `team-deepseek/deepseek-v4-pro` | 拆解原著 → 白皮书 |
| style_mapper | subagent | `team-deepseek/deepseek-v4-pro` | 赛道映射 + 分类标签 |
| facade_generator | subagent | `team-deepseek/deepseek-v4-pro` | 书名 + 简介 |
| salt_architect | subagent | `team-deepseek/deepseek-v4-pro` | 盐值校验去重 |
| plot_planner | subagent | `team-deepseek/deepseek-v4-flash` | 章纲 |
| content_writer | subagent | `team-deepseek/deepseek-v4-flash` | 正文 |
| quality_reviewer | subagent | `team-deepseek/deepseek-v4-flash` | 单章质检（≥80 分） |
| compliance_tomato | subagent | `team-deepseek/deepseek-v4-flash` | 番茄小说合规 |
| compliance_qimao | subagent | `team-deepseek/deepseek-v4-flash` | 七猫小说合规 |

### 独立评分系统

| Agent | 模式 | 模型 | 职责 |
|-------|------|------|------|
| **signing_reviewer** | subagent | `tokenhub/glm-5.2` | 签约级整本审稿（rubric v2.0 严格版） |

---

## 五、book_factory — 独立写作流水线

### 输入

| 参数 | 必填 | 说明 |
|------|------|------|
| source_name | ✓ | 原作名，如「凡人修仙传」 |
| target_platform | ✓ | 目标平台，番茄小说/七猫小说 |
| style_track | 选填 | 赛道，自动推断 |
| chapter_count | ✓ | 章节数 |
| version | ✓ | 版本号 |

### 完整流水线

```
Step 0: 初始化 — 验证 source.txt，创建目录
Step 1: @original_analyst     → base_whitepaper.md         (V4 Pro)
Step 2: @compliance_*         → 平台规则集                 (V4 Flash)
Step 3: @style_mapper         → 赛道映射 JSON              (V4 Pro)
Step 4: @facade_generator     → 书名 + 简介                (V4 Pro)
Step 5: @salt_architect       → 盐值校验                   (V4 Pro)
Step 6: 生成仿写衍生总纲领.md  (book_factory 自身)
Step 7: 章节循环 ×N:
  7a: @plot_planner           → 章纲                       (V4 Flash)
  7b: @content_writer         → 初稿                       (V4 Flash)
  7c: @quality_reviewer       → 质检(≥80分)                (V4 Flash)
  7d: 保存纪要
Step 8: 写入 execution-log.md
```

### 输出目录

```
workspace/books/{原著名}/versions/{version}/
├── 01-大纲/            # 第1章章纲.md ...
├── 02-正文/            # 第1章-终稿.md ...
├── 03-纪要/            # 第1章纪要.md ...
├── 仿写衍生总纲领.md
├── project_salt.json
└── execution-log.md    # 每步的 Agent+模型+状态
```

---

## 六、signing_reviewer — 独立评分系统

### 签约审核标准 rubric v2.0（严格版）

**总则：** 满分 100 分，**及格线 = 60 分**，且无任何一票否决项命中

#### 九大维度

| # | 维度 | 分值 | 核心理念 |
|---|------|------|---------|
| 1 | 开篇抓力 | 12 | 前3章能否留住读者 |
| 2 | 追读欲 / 钩子链 | 18 | 是否章章想追 |
| 3 | 逻辑严谨性 | 18 | 有无硬伤/降智/矛盾 |
| 4 | 人物可信度 | 10 | 动机行为是否立得住 |
| 5 | 爽感节奏 | 10 | 爽点密度与铺垫是否匹配 |
| 6 | 文笔流畅度 | 8 | 句子是否通顺无 AI 味 |
| 7 | 设定与世界观 | 5 | 是否清晰且不过载 |
| 8 | 完结延展性 | 4 | 能否支撑长线连载 |
| 9 | 原创改写度 | 15 | 是基于脉络改写还是换皮抄袭 |

#### 六条一票否决项

1. 逻辑硬伤：主线自相矛盾
2. 降智推进：核心冲突靠配角集体降智
3. 追读断裂：连续 ≥3 章无有效钩子
4. 平台红线：涉政/低俗/未成年恋爱
5. AI 味过重：超 30% 段落一眼 AI
6. 换皮抄袭：人物仅换名 + 情节平移

#### 评分档位

| 总分 | 含义 |
|------|------|
| 90-100 | 签约级上品 |
| 75-89 | 可签约（小修即可） |
| **60-74** | **勉强及格**（骨架 OK 需改） |
| 40-59 | 不合格（需大幅调整） |
| <40 | 严重不合格 |

---

## 七、目录结构

```
workspace/
├── iteration-state.json          # 正式状态文件
├── _dryrun/                      # dryrun 隔离目录
│   ├── iteration-state.json
│   └── books/
├── repo/                         # 原著仓库
│   └── {原著名}/
│       ├── source.txt            # 原著全文
│       └── base_whitepaper.md    # 原作基准白皮书
└── books/                        # 衍生作品
    └── {原著名}/
        └── versions/
            ├── v1/               # 第1版
            │   ├── 01-大纲/
            │   ├── 02-正文/
            │   ├── 03-纪要/
            │   ├── 仿写衍生总纲领.md
            │   ├── project_salt.json
            │   ├── execution-log.md
            │   └── 审稿报告-v1.md
            ├── v2/               # 第2版（优化后重写）
            └── ...
```

---

## 八、状态文件

`workspace/iteration-state.json`：

```json
{
  "mode": "step",
  "phase": "writing",
  "current_round": 1,
  "passing_score": 60,
  "target_chapters": 20,
  "output_root": "workspace/books",
  "active_books": [
    {"name": "凡人修仙传", "platform": "番茄小说", "track": "仙侠"}
  ],
  "books": {
    "凡人修仙传": {"version": "v1", "status": "pending", "score": null, "passed": false}
  }
}
```

字段说明：
- `target_chapters`：每本书写几章，可修改
- `active_books`：参与评测的书列表，可增减
- `passing_score`：及格线，默认 60

---

## 九、模型使用日志规范

### execution-log.md 格式（每本书独立）

```
# 执行日志 - {version}

| 时间 | 步骤 | Agent | 模型 | 状态 |
|------|------|-------|------|------|
| 2026-07-02 10:00:00 | 流水线启动 | book_factory | team-deepseek/deepseek-v4-flash | ✅ |
| 2026-07-02 10:00:05 | 原作拆解 | original_analyst | team-deepseek/deepseek-v4-pro | ✅ |
| 2026-07-02 10:05:00 | 平台规则 | compliance_tomato | team-deepseek/deepseek-v4-flash | ✅ |
| ... | ... | ... | ... | ... |
| 2026-07-02 14:00:00 | 流水线完成 | book_factory | team-deepseek/deepseek-v4-flash | ✅ |
```

### 主对话日志（automation_manager 打印）

```
[2026-07-02 10:00:00] [automation_manager → book_factory] 模型: team-deepseek/deepseek-v4-flash | 凡人修仙传 v1 | ✅
[2026-07-02 14:00:00] [automation_manager → signing_reviewer] 模型: tokenhub/glm-5.2 | 凡人修仙传 审稿 | ✅
```

---

## 十、相关文件清单

| 文件 | 说明 |
|------|------|
| `.opencode/agents/automation_manager.md` | 批量编排 primary agent |
| `.opencode/agents/book_factory.md` | 独立写作流水线 subagent |
| `.opencode/agents/signing_reviewer.md` | 独立评分系统 subagent |
| `.opencode/agents/original_analyst.md` | 原作拆解（V4 Pro） |
| `.opencode/agents/style_mapper.md` | 赛道映射（V4 Pro） |
| `.opencode/agents/facade_generator.md` | 门面生成（V4 Pro） |
| `.opencode/agents/salt_architect.md` | 盐值校验（V4 Pro） |
| `.opencode/agents/plot_planner.md` | 章纲（V4 Flash） |
| `.opencode/agents/content_writer.md` | 正文（V4 Flash） |
| `.opencode/agents/quality_reviewer.md` | 单章质检（V4 Flash） |
| `.opencode/agents/compliance_tomato.md` | 番茄合规（V4 Flash） |
| `.opencode/agents/compliance_qimao.md` | 七猫合规（V4 Flash） |
| `.opencode/commands/iterate.md` | `/iterate` slash command |
| `workspace/iteration-state.json` | 状态配置文件 |

---

## 附：关键决策记录

| 决策点 | 结论 | 原因 |
|--------|------|------|
| 编排者形态 | automation_manager (primary) 顶层调度 | 严格串行，不需要并行；一层完成才到下一层 |
| 写作模型 | book_factory = V4 Flash，框架子 agent = V4 Pro | 编排本身不费智力，Flash 足够；框架层需要 V4 Pro 的深度分析能力 |
| 评分模型 | GLM 5.2 | 审稿是「判断」任务，需要强推理模型 |
| 自动化程度 | 永不自动迭代，永不自动优化 | 用户明确要求：审稿→人看→人决策→人优化 |
| 评分策略 | 60 分及格，从严扣分 | 降低及格心理门槛，但扣分不手软，防止 AI 批量低质产出过关 |
| 版本策略 | 每轮新目录 v1/v2/v3...，旧版不删 | 版本化可追溯，绝不清空已有内容 |
| dryrun | 1本×3章，隔离到 workspace/_dryrun/ | 验证管道无 bug，不污染正式目录 |
| 解耦程度 | book_factory 和 signing_reviewer 完全独立 | 可分别提取使用，互不依赖 |
