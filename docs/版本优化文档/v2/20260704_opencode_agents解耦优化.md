# OpenCode Agents 三层解耦优化方案

> 日期：2026-07-04
> 状态：设计冻结，待实施

---

## 一、背景与动机

### 当前问题

1. **Agents 全部混在 `novel-editor/.opencode/agents/`**：框架层（白皮书/仿写大纲）、内容层（写章/质检）、评分层（签约审稿/内联评分）共 30+ agent 全部在一个目录，上下文互相污染。

2. **book_factory 是一个单体**：从白皮书到正文到审核报告全部在一个 subagent 调用链内完成。每本书的全文 + 评分报告全部回流到 book_factory 上下文，20 章即超过 128K token 上限。

3. **多本书之间上下文串扰**：一本书的写作上下文可能残留在 automation_manager 中，影响下一本书的调度。

4. **评分系统的 agent 与写作 agent 无物理隔离**：虽然 signing_reviewer 声明了"与写作流程完全解耦"，但 agent 定义文件处于同一目录，上下文隔离只能靠约定而非强制。

### 设计目标

1. **三层 agent 完全物理隔离**：每个 layer 的 agent 只存在于自己目录的 `.opencode/agents/`，通过 `opencode run --dir` 启动时只加载本目录 agent。
2. **每本书独立上下文**：每本书的 Phase 2 通过独立的 `opencode run` 调用启动，上下文从零开始。
3. **文件通信替代上下文回流**：层与层之间仅通过文件系统交换信息（完成标记、报告文件），不依赖上下文传递。
4. **永不交叉**：框架层 agent 感知不到内容层 agent 的定义；内容层 agent 感知不到评分层 agent 的定义。

---

## 二、架构总览

```
┌─────────────────────────────────────────────────────────────┐
│ Phase 1：框架层（novel-editor/）                              │
│ opencode run --auto "/iterate step"                         │
│                                                             │
│ Agents: novel-editor/.opencode/agents/                      │
│ ┌──────────────┐ ┌───────────┐ ┌───────────────┐           │
│ │ original_    │ │ style_*   │ │ facade_       │           │
│ │ analyst      │ │ ×7+1      │ │ generator     │           │
│ └──────────────┘ └───────────┘ └───────────────┘           │
│ ┌──────────────┐ ┌───────────┐ ┌───────────────┐           │
│ │ salt_        │ │ master_   │ │ compliance_*  │           │
│ │ architect    │ │ outline   │ │ ×2            │           │
│ └──────────────┘ └───────────┘ └───────────────┘           │
│                                                             │
│ 产出：白皮书 + 赛道映射 + 门面 + 盐值 + 仿写总纲领            │
│       复制 project-agents-template/ → 项目 .opencode/       │
│       写入 .phase1_done 标记                                │
└──────────────────────┬──────────────────────────────────────┘
                       │ (用户手动触发 或 外部脚本)
          ┌────────────┼────────────┐
          ▼            ▼            ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ Phase 2：书A  │ │ Phase 2：书B  │ │ Phase 2：书C  │
│ 独立上下文     │ │ 独立上下文     │ │ 独立上下文     │
│              │ │              │ │              │
│ Agents:      │ │ Agents:      │ │ Agents:      │
│ workspace/   │ │ workspace/   │ │ workspace/   │
│ books/A/     │ │ books/B/     │ │ books/C/     │
│ .opencode/   │ │ .opencode/   │ │ .opencode/   │
│ agents/      │ │ agents/      │ │ agents/      │
│              │ │              │ │              │
│ chief_editor │ │ chief_editor │ │ chief_editor │
│ plot_planner │ │ plot_planner │ │ plot_planner │
│ content_     │ │ content_     │ │ content_     │
│ writer       │ │ writer       │ │ writer       │
│ quality_     │ │ quality_     │ │ quality_     │
│ reviewer     │ │ reviewer     │ │ reviewer     │
│              │ │              │ │              │
│ 产出：卷纲 +  │ │ 产出：卷纲 +  │ │ 产出：卷纲 +  │
│ 章节正文 +    │ │ 章节正文 +    │ │ 章节正文 +    │
│ 章级质检      │ │ 章级质检      │ │ 章级质检      │
│ .phase2_done │ │ .phase2_done │ │ .phase2_done │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘
       │                │                │
       └────────────┬───┴───┬────────────┘
                    │       │
                    ▼       ▼
┌─────────────────────────────────────────────────────────────┐
│ Phase 3：评价层（workspace/reviewer/）                        │
│ opencode run --dir workspace/reviewer/ --auto "..."         │
│                                                             │
│ Agents: workspace/reviewer/.opencode/agents/                │
│ ┌──────────────┐ ┌───────────────┐ ┌───────────────┐       │
│ │ signing_     │ │ whitepaper_   │ │ master_       │       │
│ │ reviewer     │ │ reviewer      │ │ outline_      │       │
│ │ (GLM 5.2)    │ │ (GLM 5.2)     │ │ reviewer      │       │
│ └──────────────┘ └───────────────┘ └───────────────┘       │
│ ┌──────────────┐ ┌───────────────┐ ┌───────────────┐       │
│ │ volume_      │ │ chapter_      │ │ input_        │       │
│ │ outline_     │ │ outline_      │ │ monitor       │       │
│ │ reviewer     │ │ reviewer      │ │               │       │
│ └──────────────┘ └───────────────┘ └───────────────┘       │
│                                                             │
│ 产出：全层级评分报告 + 签约审稿报告 + 跨书总结报告            │
└─────────────────────────────────────────────────────────────┘
```

### 关键隔离保证

- **Phase 1 的 agent 无法感知 Phase 2/3 的 agent 定义**：因为 `opencode run --dir novel-editor/` 只加载 `novel-editor/.opencode/agents/`。
- **Phase 2 每本书完全独立**：`opencode run --dir workspace/books/A/` 和 `--dir workspace/books/B/` 是两个独立进程，各自的 agent 和上下文零交集。
- **Phase 3 的 agent 无法感知 Phase 1/2 的 agent 定义**：因为 `opencode run --dir workspace/reviewer/` 只加载 `workspace/reviewer/.opencode/agents/`。

---

## 三、Agent 资产划分

### 3.1 Phase 1 — 框架层（保留在 `novel-editor/.opencode/agents/`）

| Agent | 角色 | 模型 | 说明 |
|-------|------|------|------|
| `automation_manager` | primary 调度器 | V4 Pro | **精简版**：只编排框架生成 |
| `original_analyst` | 原作拆解 | V4 Pro | source.txt → base_whitepaper.md |
| `style_urban` | 都市赛道映射 | V4 Pro | |
| `style_xuanhuan` | 玄幻赛道映射 | V4 Pro | |
| `style_xianxia` | 仙侠赛道映射 | V4 Pro | |
| `style_romance` | 女频赛道映射 | V4 Pro | |
| `style_history` | 历史赛道映射 | V4 Pro | |
| `style_scifi` | 科幻赛道映射 | V4 Pro | |
| `style_suspense` | 悬疑赛道映射 | V4 Pro | |
| `style_mapper` | 通用赛道映射 | V4 Pro | 参数化版本 |
| `facade_generator` | 门面生成 | V4 Pro | 书名 + 简介 |
| `salt_architect` | 盐值校验 | V4 Pro | 去重 + 标准化 |
| `master_outline_generator` | 总纲生成 | V4 Pro | 包含卷纲规划逻辑 |
| `compliance_tomato` | 番茄合规 | V4 Flash | |
| `compliance_qimao` | 七猫合规 | V4 Flash | |
| `global_manager` | 旧版调度器 | V4 Pro | 保留，向后兼容 |
| `workflow_optimizer` | Agent 优化师 | V4 Pro | 保留 |

### 3.2 Phase 2 — 内容层（位于 `project-agents-template/.opencode/agents/`，Phase 1 复制到 `workspace/books/<项目>/.opencode/agents/`）

| Agent | 角色 | 模型 | 说明 |
|-------|------|------|------|
| `chief_editor` | primary 主编 | V4 Flash | 项目内全自动写作入口 |
| `plot_planner` | 剧情规划 | V4 Flash | 卷纲 + 章纲 |
| `content_writer` | 正文撰稿 | V4 Flash | 按章纲写正文 |
| `quality_reviewer` | 章级质检 | V4 Flash | ≥60 分放行 |
| `data_operator` | 数据运营 | V4 Flash | 复盘分析 |

### 3.3 Phase 3 — 评价层（新建于 `workspace/reviewer/.opencode/agents/`）

| Agent | 角色 | 模型 | 来源 | 说明 |
|-------|------|------|------|------|
| `reviewer_orchestrator` | primary 调度器 | V4 Pro | **新建** | 编排评分流程 |
| `signing_reviewer` | 签约审稿 | **GLM 5.2** | 从根目录迁移 | rubric v2.0 严格版 |
| `whitepaper_reviewer` | 白皮书评分 | **GLM 5.2** | 从根目录迁移 | |
| `master_outline_reviewer` | 总纲评分 | **GLM 5.2** | 从根目录迁移 | |
| `volume_outline_reviewer` | 卷纲评分 | **GLM 5.2** | 从根目录迁移 | |
| `chapter_outline_reviewer` | 章纲评分 | **GLM 5.2** | 从根目录迁移 | |
| `input_monitor` | 输入监控评分 | V4 Flash | 从根目录迁移 | |

### 3.4 从根目录删除的 Agent

| Agent | 原位置 | 去向/原因 |
|-------|--------|----------|
| `book_factory` | 根目录 | **废弃**，拆分为三阶段 |
| `signing_reviewer` | 根目录 | → `workspace/reviewer/.opencode/agents/` |
| `whitepaper_reviewer` | 根目录 | → `workspace/reviewer/.opencode/agents/` |
| `master_outline_reviewer` | 根目录 | → `workspace/reviewer/.opencode/agents/` |
| `volume_outline_reviewer` | 根目录 | → `workspace/reviewer/.opencode/agents/` |
| `chapter_outline_reviewer` | 根目录 | → `workspace/reviewer/.opencode/agents/` |
| `input_monitor` | 根目录 | → `workspace/reviewer/.opencode/agents/` |
| `plot_planner` | 根目录 | 从根目录删除；`project-agents-template/` 中已有专用版本 |
| `content_writer` | 根目录 | 从根目录删除；`project-agents-template/` 中已有专用版本 |
| `quality_reviewer` | 根目录 | 从根目录删除；`project-agents-template/` 中已有专用版本 |

> **注意**：根目录版 `plot_planner` / `content_writer` / `quality_reviewer` 可能与 `project-agents-template/` 版本存在差异，迁移前需要比对，以 template 版本为准。

---

## 四、各 Phase 执行流程

### 4.1 Phase 1：框架层

**启动方式**：`opencode run --auto "/iterate step"`（从 `novel-editor/` 根目录）

**automation_manager（精简版）流程**：

```
1. 读取 workspace/iteration-state.json

2. 对 active_books 中的每本书逐本执行：
   a. 版本递增（扫描 versions/ 取 max+1，首次 v1）
   b. 验证 workspace/repo/{书名}/source.txt 存在
   c. @original_analyst → base_whitepaper.md（若已存在则跳过）
   d. 白皮书备份到版本目录：00-素材/base_whitepaper.md
   e. @compliance_{平台} → 平台规则集
   f. @style_mapper / @style_{track} → 赛道映射.json
   g. @facade_generator → 门面候选.json
   h. @salt_architect → project_salt.json（校验通过则继续，不通过则终止）
   i. @master_outline_generator → 仿写衍生总纲领.md
   j. bash cp -r project-agents-template/.opencode/agents/ workspace/books/{书名}/.opencode/agents/
   k. 创建 versions/{version}/ 目录结构（01-大纲/01-卷纲/, 02-正文/, 03-纪要/）
   l. 创建 novel_metadata.json（通过 novel_metadata.py）
   m. 写入完成标记：workspace/books/{书名}/.phase1_done
      内容：{"phase": "phase1_done", "version": "v1", "timestamp": "..."}

3. 全部书完成 → 输出汇总表：
   ═══════════════════════════════════
     Phase 1 完成
   ═══════════════════════════════════
   | 书名        | 版本 | 白皮书 | 盐值 | 总纲 | 状态   |
   |------------|------|--------|------|------|--------|
   | 凡人修仙传   | v1   | ✅     | ✅   | ✅   | 完成   |
   | 斗破苍穹    | v1   | ✅     | ✅   | ✅   | 完成   |
   ═══════════════════════════════════

   下一步：对每本书执行 Phase 2
     opencode run --dir workspace/books/{书名}/ --agent chief_editor --auto "全自动执行第1~N章生产"

4. 停止。不自动触发 Phase 2。
```

**状态文件更新**：`workspace/iteration-state.json` 中标记 `phase = "phase1_done"`。

---

### 4.2 Phase 2：内容层

**启动方式**（每本书分别执行）：
```bash
opencode run --dir workspace/books/<书名>/ --agent chief_editor --auto "全自动执行第1~N章生产"
```

**chief_editor（项目主编）流程**：

```
1. 初始化 SOP（首次运行）：
   a. 读取 project_salt.json → 推导基准白皮书路径
   b. 读取基准白皮书 → 提取节奏模型 + v2.0 模块（社会语言层次/角色语言指纹/句式模式/全局变量）
   c. 读取仿写衍生总纲领.md → 获取分类标识、平台规则、字数标准
   d. 创建 01-大纲/01-卷纲/, 02-正文/, 03-纪要/, 04-数据/ 目录
   e. 创建 .opencode/progress.json

2. 卷纲规划：
   a. 根据当前进度确定卷位
   b. @plot_planner（卷规划模式）→ 01-大纲/01-卷纲/卷纲-第X卷.md
   c. 卷纲输出包含该卷各阶段的节奏弧线、里程碑、章规划

3. 章节循环（对当前卷内每章 N）：
   a. @plot_planner → 01-大纲/第N章章纲.md
   b. 记录 plot_planner 输入大小到 input_monitor.json
   c. @content_writer → 02-正文/第N章-初稿.md
   d. 记录 content_writer 输入大小到 input_monitor.json
   e. @quality_reviewer → 章级质检
      - ≥60 分 → 初稿重命名为 第N章-终稿.md
      - <60 分 → 记录告警，继续下一章
   f. 生成 03-纪要/第N章纪要.md
   g. 记录章节名到 novel_metadata.json

4. 当前卷全部章节完成 → 评估是否继续下一卷：
   - 若 chapter_count 未完成 → 回到步骤 2
   - 若完成 → 进入步骤 5

5. 完成：
   a. 写入完成标记：./.phase2_done
      内容：{"phase": "phase2_done", "chapters_completed": N, "timestamp": "..."}
   b. 输出完成摘要
```

**注意**：`quality_reviewer` 是在 Phase 2 内联执行的，属于内容生产流程的一部分。评分 <60 不阻断流水线，只记录。

---

### 4.3 Phase 3：评价层

**启动方式**（逐本审稿）：
```bash
# 审稿单本书
opencode run --dir workspace/reviewer/ --agent signing_reviewer --auto "审核 workspace/books/<书名>/versions/v1/ 来源白皮书: workspace/repo/<书名>/base_whitepaper.md"

# 生成跨书总结
opencode run --dir workspace/reviewer/ --auto "生成跨书总结报告 version=v1 books=书A,书B,书C"
```

**reviewer_orchestrator 流程**：

```
模式一：单书完整评分

1. 逐一执行全层级评分（均为 GLM 5.2）：
   a. @whitepaper_reviewer → 00-素材/base_whitepaper-审核报告.md
   b. @master_outline_reviewer → 仿写衍生总纲领-审核报告.md
   c. @volume_outline_reviewer → 01-大纲/01-卷纲/卷纲-第X卷-审核报告.md（每卷）
   d. @chapter_outline_reviewer → 01-大纲/第N章章纲-审核报告.md（每章）
   e. @input_monitor → 读取 input_monitor.json，输出评分

2. 签约审稿（GLM 5.2）：
   @signing_reviewer
   - 读取全部正文（02-正文/第*-终稿.md）
   - 读取白皮书脉络（用于维度 9 原创改写度比对）
   - 按 rubric v2.0 九大维度 + 一票否决项评分
   - 产出：workspace/books/{书名}/versions/{version}/审稿报告-{version}.md

3. 生成单书审核报告：
   汇总 1 中所有评分 + 签约审稿评分
   产出：workspace/books/{书名}/versions/{version}/审核报告.md

模式二：跨书总结分析

1. 读取所有书的 审核报告.md + 审稿报告-{version}.md
2. 提取全层级评分数据
3. 分析：
   - 共性优点（≥50% 书籍共同高分维度）
   - 共性通病（≥40% 书籍共同扣分维度）
   - 根因分析（框架层 / 执行层）
   - 输入监控跨书对比
   - 优化建议（按优先级）
4. 产出：workspace/总结性审核报告-{version}.md
```

---

## 五、目录结构变更

### 变更前

```
novel-editor/
├── .opencode/agents/          # 30+ agent，全部混在一起
│   ├── automation_manager.md
│   ├── book_factory.md        ← 待删除
│   ├── signing_reviewer.md    ← 待迁移
│   ├── whitepaper_reviewer.md ← 待迁移
│   ├── ...（所有 reviewer）    ← 待迁移
│   ├── plot_planner.md        ← 待删除
│   ├── content_writer.md      ← 待删除
│   └── quality_reviewer.md    ← 待删除
├── project-agents-template/
│   └── .opencode/agents/      # 项目模板 agent
└── workspace/
    ├── books/<项目>/           # 无 .opencode/agents/
    └── reviewer/              ← 不存在
```

### 变更后

```
novel-editor/
├── .opencode/agents/          # 仅框架层 agent（17 个）
│   ├── automation_manager.md  # 精简版
│   ├── original_analyst.md
│   ├── style_urban.md
│   ├── style_xuanhuan.md
│   ├── style_xianxia.md
│   ├── style_romance.md
│   ├── style_history.md
│   ├── style_scifi.md
│   ├── style_suspense.md
│   ├── style_mapper.md
│   ├── facade_generator.md
│   ├── salt_architect.md
│   ├── master_outline_generator.md
│   ├── compliance_tomato.md
│   ├── compliance_qimao.md
│   ├── global_manager.md      # 保留（向后兼容）
│   └── workflow_optimizer.md  # 保留
│
├── project-agents-template/
│   └── .opencode/agents/      # 内容层 agent 模板
│       ├── chief_editor.md
│       ├── plot_planner.md
│       ├── content_writer.md
│       ├── quality_reviewer.md
│       └── data_operator.md
│
└── workspace/
    ├── books/
    │   ├── 凡人修仙传/
    │   │   ├── .opencode/agents/    # Phase 1 复制自 template
    │   │   │   ├── chief_editor.md
    │   │   │   ├── plot_planner.md
    │   │   │   ├── content_writer.md
    │   │   │   ├── quality_reviewer.md
    │   │   │   └── data_operator.md
    │   │   ├── .phase1_done          # 完成标记
    │   │   ├── .phase2_done          # 完成标记
    │   │   ├── project_salt.json
    │   │   ├── 仿写衍生总纲领.md
    │   │   ├── novel_metadata.json
    │   │   ├── 01-大纲/01-卷纲/
    │   │   ├── 02-正文/
    │   │   ├── 03-纪要/
    │   │   └── versions/
    │   ├── 斗破苍穹/
    │   │   └── ...（同上结构）
    │   └── ...
    │
    └── reviewer/                    # 新建
        ├── .opencode/
        │   └── agents/              # 评价层 agent
        │       ├── reviewer_orchestrator.md  # 新建 primary
        │       ├── signing_reviewer.md       # 从根目录迁移
        │       ├── whitepaper_reviewer.md     # 从根目录迁移
        │       ├── master_outline_reviewer.md # 从根目录迁移
        │       ├── volume_outline_reviewer.md # 从根目录迁移
        │       ├── chapter_outline_reviewer.md# 从根目录迁移
        │       └── input_monitor.md           # 从根目录迁移
        └── .gitignore
```

---

## 六、执行流程总览（完整走一遍）

### 用户操作序列

```bash
# ═══ Phase 1：生成框架 ═══
cd /mnt/data/novel-editor
opencode run --auto "/iterate step"

# automation_manager 处理所有 active_books 的框架：
#   白皮书 → 赛道映射 → 门面 → 盐值 → 仿写总纲
#   复制 project-agents-template/ → workspace/books/<项目>/.opencode/agents/
#   写入 .phase1_done
# 完成后停止，输出汇总表。

# ═══ Phase 2：写书（每本书独立执行）═══
opencode run --dir workspace/books/凡人修仙传/ \
  --agent chief_editor --auto "全自动执行第1~20章生产"

opencode run --dir workspace/books/斗破苍穹/ \
  --agent chief_editor --auto "全自动执行第1~20章生产"

# ... 每本书的上下文完全隔离
# 每本完成后写入 .phase2_done

# ═══ Phase 3：审稿 ═══

# 3a. 逐本审稿
opencode run --dir workspace/reviewer/ \
  --agent reviewer_orchestrator --auto \
  "审核 workspace/books/凡人修仙传/versions/v1/"

opencode run --dir workspace/reviewer/ \
  --agent reviewer_orchestrator --auto \
  "审核 workspace/books/斗破苍穹/versions/v1/"

# 3b. 跨书总结
opencode run --dir workspace/reviewer/ --auto \
  "生成跨书总结报告 version=v1 books=凡人修仙传,斗破苍穹"
```

### dryrun 模式

```bash
# Phase 1 dryrun：1 本书 × 框架
cd /mnt/data/novel-editor
opencode run --auto "/iterate dryrun"

# Phase 2 dryrun：该书的 3 章
opencode run --dir workspace/_dryrun/books/甄嬛传/ \
  --agent chief_editor --auto "全自动执行第1~3章生产"

# Phase 3 dryrun：审稿
opencode run --dir workspace/reviewer/ --auto \
  "审核 workspace/_dryrun/books/甄嬛传/versions/v1/"
```

---

## 七、完成标记协议

### Phase 1 完成标记

**文件**：`workspace/books/<书名>/.phase1_done`

```json
{
  "phase": "phase1_done",
  "version": "v1",
  "timestamp": "2026-07-04T10:00:00",
  "files": {
    "base_whitepaper": "workspace/repo/<书名>/base_whitepaper.md",
    "project_salt": "workspace/books/<书名>/project_salt.json",
    "master_outline": "workspace/books/<书名>/versions/v1/仿写衍生总纲领.md"
  }
}
```

### Phase 2 完成标记

**文件**：`workspace/books/<书名>/.phase2_done`

```json
{
  "phase": "phase2_done",
  "version": "v1",
  "chapters_completed": 20,
  "timestamp": "2026-07-04T14:00:00",
  "quality_avg": 72.5
}
```

### Phase 3 完成标记

**文件**：`workspace/books/<书名>/versions/v1/.phase3_done`

```json
{
  "phase": "phase3_done",
  "version": "v1",
  "timestamp": "2026-07-04T15:00:00",
  "signing_score": 68,
  "signing_passed": true,
  "summary_report": "workspace/总结性审核报告-v1.md"
}
```

---

## 八、Phase 1 automation_manager 变更要点

### 删减（相对当前版本）

1. **删除所有 Phase: writing 内容**：不再调用 book_factory，不再编排章节写作。
2. **删除所有 Phase: reviewing 内容**：不再调用 signing_reviewer，不再提取分数和判定。
3. **删除所有 Phase: done 内容**：不再生成跨书总结报告（移到 Phase 3）。
4. **删除所有 `@book_factory` 调用**。
5. **删除所有 `@signing_reviewer` 调用**。

### 新增（相对当前版本）

1. **框架生成编排**：直接调用 `@original_analyst`、`@style_*`、`@facade_generator`、`@salt_architect`、`@master_outline_generator`。不再通过 book_factory 间接调用。
2. **项目 agent 复制**：bash `cp -r project-agents-template/.opencode/agents/ workspace/books/<书名>/.opencode/agents/`。
3. **完成标记写入**：每本书框架完成后写入 `.phase1_done`。
4. **Phase 2 提示输出**：输出每本书的 Phase 2 启动命令，不自动执行。

### 保留不变

1. `workspace/iteration-state.json` 管理（active_books, version, phase）。
2. 版本递增逻辑。
3. `/iterate dryrun` 模式（产物落在 `workspace/_dryrun/`）。
4. `/iterate status` 模式。
5. execution-log 日志记录。
6. 严格串行保证。

---

## 九、待实施文件清单

### 9.1 新建文件

| 文件 | 说明 |
|------|------|
| `workspace/reviewer/.opencode/agents/reviewer_orchestrator.md` | Phase 3 primary 调度器，新建 |
| `workspace/reviewer/.gitignore` | 忽略临时文件 |

### 9.2 迁移文件（从根目录 `.opencode/agents/` → `workspace/reviewer/.opencode/agents/`）

| 源 | 目标 |
|----|------|
| `.opencode/agents/signing_reviewer.md` | `workspace/reviewer/.opencode/agents/signing_reviewer.md` |
| `.opencode/agents/whitepaper_reviewer.md` | `workspace/reviewer/.opencode/agents/whitepaper_reviewer.md` |
| `.opencode/agents/master_outline_reviewer.md` | `workspace/reviewer/.opencode/agents/master_outline_reviewer.md` |
| `.opencode/agents/volume_outline_reviewer.md` | `workspace/reviewer/.opencode/agents/volume_outline_reviewer.md` |
| `.opencode/agents/chapter_outline_reviewer.md` | `workspace/reviewer/.opencode/agents/chapter_outline_reviewer.md` |
| `.opencode/agents/input_monitor.md` | `workspace/reviewer/.opencode/agents/input_monitor.md` |

### 9.3 删除文件

| 文件 | 原因 |
|------|------|
| `.opencode/agents/book_factory.md` | 废弃，拆分为三阶段各自编排 |
| `.opencode/agents/signing_reviewer.md` | 已迁移至 reviewer 目录 |
| `.opencode/agents/whitepaper_reviewer.md` | 已迁移至 reviewer 目录 |
| `.opencode/agents/master_outline_reviewer.md` | 已迁移至 reviewer 目录 |
| `.opencode/agents/volume_outline_reviewer.md` | 已迁移至 reviewer 目录 |
| `.opencode/agents/chapter_outline_reviewer.md` | 已迁移至 reviewer 目录 |
| `.opencode/agents/input_monitor.md` | 已迁移至 reviewer 目录 |
| `.opencode/agents/plot_planner.md` | 移至 project-agents-template/（内容层，已有） |
| `.opencode/agents/content_writer.md` | 移至 project-agents-template/（内容层，已有） |
| `.opencode/agents/quality_reviewer.md` | 移至 project-agents-template/（内容层，已有） |

### 9.4 修改文件

| 文件 | 改动范围 |
|------|---------|
| `.opencode/agents/automation_manager.md` | **大量精简**：移除 writing/reviewing/done 阶段，只保留框架生成编排 |
| `.opencode/commands/iterate.md` | 更新命令说明，反映三阶段架构 |
| `project-agents-template/.opencode/agents/chief_editor.md` | 增加 `.phase2_done` 写入逻辑和 input_monitor 数据采集 |
| `project-agents-template/.opencode/agents/plot_planner.md` | 确认卷纲模式 + 章纲模式工作流（与根目录旧版对比后更新） |
| `project-agents-template/.opencode/agents/content_writer.md` | 与根目录旧版对比后更新 |
| `project-agents-template/.opencode/agents/quality_reviewer.md` | 与根目录旧版对比后更新 |

---

## 十、风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 根目录与 template 的 `plot_planner` / `content_writer` / `quality_reviewer` 存在差异 | Phase 2 行为不同 | 迁移前用 diff 比对，人工审核差异 |
| reviewer agent 迁移后路径引用可能失效 | Phase 3 评分失败 | reviewer agent 统一使用绝对路径风格（`workspace/books/{书名}/...`） |
| 三阶段手动执行增加操作步骤 | 操作繁琐 | 可选的外部 bash 脚本串联三阶段 |
| `book_factory` 废弃后，旧有依赖它的流程不再可用 | 兼容性 | 保留 `book_factory.md` 备份，Phase 1 先验证通过再删除 |
| `opencode run --dir` 的 `--auto` 权限行为 | 依赖交互式确认 | dryrun 先行验证 |

---

## 十一、实施顺序建议

```
Step 1: 比对根目录版 vs template 版的 plot_planner / content_writer / quality_reviewer
        → 确认 template 版是最新/最优版本

Step 2: 创建 workspace/reviewer/ 目录结构
        → mkdir -p workspace/reviewer/.opencode/agents/
        → 创建 reviewer_orchestrator.md

Step 3: 迁移 6 个 reviewer agent 到 workspace/reviewer/.opencode/agents/
        → cp（保留根目录原文件，先验证再删除）

Step 4: 修改 project-agents-template/ 下的 chief_editor 等（.phase2_done 逻辑等）

Step 5: 精简 automation_manager.md（仅框架生成编排）

Step 6: 删除根目录不再需要的 agent 文件

Step 7: dryrun 验证（Phase 1 + Phase 2 + Phase 3 完整走一遍）

Step 8: 更新 ReadMe.md 和 iterate.md 文档
```

---

## 十二、上下文膨胀效果预估

| 场景 | 旧架构（book_factory 单体） | 新架构（三阶段隔离） |
|------|---------------------------|---------------------|
| Phase 1 上下文 | ~50K（框架） | ~50K（框架，相同） |
| Phase 2 上下文（每本书） | ~225K（含全部 reviewer 回流 + 历史章节累积） | **~60K**（仅当前章 + 最近 2 章纪要；无 reviewer 回流） |
| Phase 3 上下文（每本书） | 混在 book_factory 中 | **~20K**（只读评分所需的报告文件，不写章节） |
| 跨书总结上下文 | 混在 automation_manager 中 | **~15K**（读取所有审核报告，独立上下文） |

每本 20 章的 Phase 2 上下文从 ~225K → ~60K，**直接压到安全线下**。
