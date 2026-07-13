# Subagent → Skill 转换分析（Token 优化）

> 分析日期：2026-07-10
> 范围：全项目 30+ agent 定义
> 目标：降低 token 消耗，同时保持三层隔离架构的核心优势

---

## 一、架构总览

当前系统采用三层 30+ 代理体系，每层由一个 `primary` 编排者调用多个 `subagent`。每次 subagent 调用 = **系统提示词 + 工具定义开销 (~2000-3000 tokens) + 任务指令 + 响应**。

| 层级 | 编排者 | 模型 | 子代理数 | 调用频率 |
|------|--------|------|----------|----------|
| Phase 1 (全局) | `automation_manager` | pro | 8 个 | 每书 1 次 |
| Phase 2 (分书) | `chief_editor` | flash | 5 个 | **每章 × (3~5 次)** |
| Phase 3 (审稿) | `reviewer_orchestrator` | pro | 7 个 | 每书 1 次 |

### 完整 Agent 清单（按层级）

#### Layer 1：Global (`.opencode/agents/` — 17 个)

| Agent | 模式 | 模型 | 行数 | 功能 |
|-------|------|------|------|------|
| `global_manager` | Primary | pro | — | 用户入口 |
| `automation_manager` | Primary | pro | 218 | Phase 1 编排者 |
| `original_analyst` | Subagent | pro | — | 四阶段原作拆解 |
| `compliance_tomato` | Subagent | flash | 205 | 番茄平台合规（双模式） |
| `compliance_qimao` | Subagent | flash | — | 七猫平台合规（双模式） |
| `style_mapper` | Subagent | pro | 727 | 多赛道映射（7 赛道分支表） |
| `style_urban` | Subagent | flash | 205 | 都市赛道盐值 |
| `style_xuanhuan` | Subagent | flash | — | 玄幻赛道盐值 |
| `style_xianxia` | Subagent | flash | — | 仙侠赛道盐值 |
| `style_romance` | Subagent | flash | — | 言情赛道盐值 |
| `style_history` | Subagent | flash | — | 历史赛道盐值 |
| `style_scifi` | Subagent | flash | — | 科幻赛道盐值 |
| `style_suspense` | Subagent | flash | — | 悬疑赛道盐值 |
| `facade_generator` | Subagent | pro | 154 | 门面生成（双模式） |
| `salt_architect` | Subagent | pro | 173 | 18 条规则校验 |
| `master_outline_generator` | Subagent | pro | 418 | 仿写衍生总纲生成 |
| `workflow_optimizer` | Primary | flash | — | Agent 定义修改器 |

#### Layer 2：Project (Per-book, `project-agents-template/.opencode/agents/` — 7 个)

| Agent | 模式 | 模型 | 行数 | 功能 |
|-------|------|------|------|------|
| `chief_editor` | Primary | flash | 333 | Phase 2 编排者 |
| `destiny_designer` | Subagent | pro | 579+ | 上帝之眼命运设计书 |
| `plot_planner` | Subagent | flash | 681 | 章纲/卷纲生成 |
| `content_writer` | Subagent | flash | 480 | 正文写作 |
| `quality_reviewer` | Subagent | glm-5.2 | 363 | 100 分制质检 |
| `data_operator` | Subagent | flash | 25 | 每 10 章数据复盘 |
| `quality_reviewer_bk` | Subagent | flash | — | 旧版质检（备份） |

#### Layer 3：Reviewer (`workspace/reviewer/.opencode/agents/` — 8 个)

| Agent | 模式 | 模型 | 行数 | 功能 |
|-------|------|------|------|------|
| `reviewer_orchestrator` | Primary | pro | 171 | Phase 3 编排者 |
| `whitepaper_reviewer` | Subagent | glm-5.2 | — | 白皮书审核 |
| `master_outline_reviewer` | Subagent | glm-5.2 | — | 总纲审核 |
| `volume_outline_reviewer` | Subagent | glm-5.2 | — | 卷纲审核 |
| `chapter_outline_reviewer` | Subagent | glm-5.2 | — | 章纲审核 |
| `signing_reviewer` | Subagent | glm-5.2 | — | 签约级审稿 |
| `pipeline_auditor` | Subagent | glm-5.2 | — | 流程审计 |
| `input_monitor` | Subagent | flash | 128 | 输入长度监控 |

---

## 二、Token 消耗根因分析

### 2.1 核心问题：Phase 2 的高频 Subagent 生成

Phase 2 是 token 消耗重灾区。以 30 章书为例：

```
每章调用链路：
  plot_planner (681行系统提示词)
  → content_writer (480行)
  → quality_reviewer (363行) × (1~3 轮重试)
  → 可选 compliance Mode 2

30 章 × (3~5 次生成) = 90~180 次 subagent 生成
```

每次子代理生成都是一个全新的上下文窗口，需要重新加载全部系统提示词和工具定义。这意味着：

- `plot_planner` 的 681 行定义被加载 30 次（~20,000 行）
- `content_writer` 的 480 行定义被加载 30~60 次（~14,000~28,000 行）
- `quality_reviewer` 的 363 行定义被加载 30~90 次（~10,000~32,000 行）

**仅 Phase 2 的系统提示词重复加载量就达到约 45,000~80,000 行/书**。

### 2.2 Subagent vs Skill 的 Token 差异

| 维度 | Subagent | Skill（合并到编排者） |
|------|----------|----------------------|
| 系统提示词 | 每次重新加载全部定义 | 一次性加载到编排者上下文 |
| 工具定义 | 每次附带完整工具集 | 复用编排者工具集 |
| 上下文隔离 | ✅ 完全隔离，无污染 | ⚠️ 共享编排者上下文 |
| 模型灵活性 | 可按任务选不同模型 | 受限于编排者模型 |
| 维护成本 | 独立文件，职责清晰 | 与编排者耦合 |

---

## 三、转换候选分析

### 3.1 强烈建议转为 Skill

#### ① `data_operator` → `chief_editor` Skill

| 指标 | 值 |
|------|-----|
| 行数 | 25 行 |
| 模型匹配 | ✅ flash → flash |
| 调用频率 | 每 10 章 1 次 |
| 任务性质 | 读取流量数据 + 章节纪要 → 输出模板化复盘报告 |

**理由**：极轻量、同模型、低频调用。转为 skill 几乎零成本，编排者直接读取数据并输出报告即可。

**预估节省**：每书省去 3~5 次 subagent 生成。

---

#### ② `compliance_*` 模式一（规则查询）→ `automation_manager` Skill

| 指标 | 值 |
|------|-----|
| 行数 | 模式一部分约 80 行（纯 JSON 输出） |
| 模型匹配 | ⚠️ flash → pro（但任务无推理，仅为知识输出） |
| 调用频率 | 每书 1 次（Phase 1） |
| 任务性质 | 输出硬编码的平台规则 JSON——本质是知识库查询 |

**理由**：模式一不涉及任何推理或文件读取，编排者只需"知道"平台规则。转为 skill 即把 JSON 知识块内嵌到 `automation_manager` 的 skill 库中，调用时直接引用。

**注意**：模式二（章节终审）涉及读取正文 + 逐项扫描，仍需保留为 subagent。

**预估节省**：每书 Phase 1 省去 1 次 subagent 生成。

---

#### ③ `input_monitor` → `reviewer_orchestrator` Skill

| 指标 | 值 |
|------|-----|
| 行数 | 128 行 |
| 模型匹配 | ⚠️ flash → pro（但任务是纯计算逻辑） |
| 调用频率 | 每书 1 次 |
| 任务性质 | 读取 JSON → 计算增长率 → 按阈值打分 |

**理由**：纯确定性计算逻辑（JSON 解析 + 百分比计算 + 阈值比较），不涉及自然语言推理。转为 skill 后编排者可直接执行这些计算步骤。

**预估节省**：每书 Phase 3 省去 1 次 subagent 生成。

---

### 3.2 可考虑转为 Skill（需权衡）

#### ④ `salt_architect` → `automation_manager` Skill

| 指标 | 值 |
|------|-----|
| 行数 | 173 行 |
| 模型匹配 | ✅ pro → pro |
| 调用频率 | 每书 1 次 |
| 任务性质 | 18 条校验规则 checklist |

**权衡点**：
- **支持转换**：18 条规则本质是结构化 checklist，无创意成分。编排者按规则逐条检查 JSON 即可。
- **反对转换**：规则仍在频繁迭代（v2→v3→v4 持续增加校验项），独立 agent 更易维护和版本管理。173 行 skill 注入编排者会增加编排者上下文负担。

**建议**：暂时保留，待规则稳定后再评估。

---

#### ⑤ `facade_generator` 模式一 → `automation_manager` Skill

| 指标 | 值 |
|------|-----|
| 行数 | 154 行 |
| 模型匹配 | ✅ pro → pro |
| 调用频率 | 每书 1 次 |
| 任务性质 | 给定平台+标签 → 生成 5 组书名/简介候选 |

**权衡点**：
- **支持转换**：模式一的"快速灵感"输入简单（platform + tags），输出结构固定（5 组 JSON），同模型。
- **反对转换**：书名/简介是网文的"门面"，创意质量直接影响签约和流量。独立 agent 上下文可以给创意生成更好的"专注空间"，不受编排者长上下文干扰。且 temperature 0.75 高于编排者的 0.3。

**建议**：暂时保留。创意任务在独立上下文通常表现更好。

---

### 3.3 必须保留为 Subagent

以下 agent **不适合**转为 skill，原因汇总：

| Agent | 不可转换原因 |
|-------|-------------|
| `original_analyst` | 四阶段深度分析管线，输出数万字白皮书，必须隔离上下文 |
| `style_mapper` | 727 行 7 赛道分支表 + 整本白皮书映射，计算量极大 |
| `master_outline_generator` | 生成 10 节约 100+ 行的总纲 + ~120 行 phase 级差异化约束表 |
| `destiny_designer` | 579+ 行，生成完整上帝之眼 6 个子目录（00~05），复杂度最高 |
| `plot_planner` | 681 行，核心创作环节：五段式结构/爽点预算/伏笔管理/L2 替换模式 |
| `content_writer` | 480 行，正文写作核心创意任务，temperature 0.6 ≠ 编排者 0.3 |
| `quality_reviewer` | 使用 **glm-5.2** 外部模型，强制性 Grep 扫描，不可合并 |
| `compliance_*` 模式二 | 需读取章节正文逐项扫描红线，需独立上下文 |
| Phase 3 全部审稿 agent (6 个) | 全部使用 **glm-5.2**，模型完全不同 |
| `fate_designer`（如有） | 已由 `destiny_designer` 覆盖 |

---

## 四、额外优化建议

### 4.1 删除 7 个冗余的 style_* 赛道 Agent

```
style_urban / style_xuanhuan / style_xianxia / style_romance
style_history / style_scifi / style_suspense
```

这 7 个独立 agent 与 `style_mapper`（727 行，内含完整 7 赛道分支表）**功能高度重叠**。`automation_manager` 实际只调用 `style_mapper`，通过 `style_track` 参数切换赛道。这 7 个 agent 处于半废弃状态。

**建议**：确认无其他引用后删除，统一走 `style_mapper`。

**影响**：减 7 个配置文件，不影响功能。

---

### 4.2 `workflow_optimizer` 合并入 `global_manager`

| 当前状态 | 问题 |
|----------|------|
| `workflow_optimizer` (Primary, flash) | 功能是"诊断问题→修改 agent 定义" |
| `global_manager` (Primary, pro) | 用户入口，处理训练/创建/灵感任务 |

两者都是全局 primary agent，职责边界模糊。`workflow_optimizer` 作为"修改 agent 定义"的工具可以做成 `global_manager` 的一个 skill 或内嵌命令。

**建议**：合并，减少一个 primary agent 切换开销。

---

### 4.3 Phase 2 `quality_reviewer` 批量化（最大节省潜力）

当前模式：
```
每章写完后 → @quality_reviewer (同步) → 不通过则 @content_writer (重写) → @quality_reviewer (再检)
→ 每章 1~3 次 glm-5.2 调用
```

glm-5.2 作为外部 TokenHub 模型，每次调用有额外的网络延迟和开销。30 章书 × 2 轮平均 = **60 次外部模型调用**。

**备选方案**：改为写 5 章后批量质检。

| 方案 | 质检频率 | 外部模型调用/30章 | 质量保证 | 延迟 |
|------|----------|-------------------|----------|------|
| 当前（同步逐章） | 每章 | ~60 次 | 实时门禁 | 高 |
| **建议（批量）** | 每 5 章 | ~12 次 | 批次门禁 | 低 |
| 激进（卷末） | 每卷 | ~6 次 | 事后审查 | 最低 |

**权衡**：批量质检失去实时阻止低质量章节继续生产的能力，但可减少约 80% 的 glm-5.2 调用。建议作为可选配置项，允许用户在"速度优先"和"质量优先"间切换。

---

### 4.4 Phase 2 编排者上下文裁剪

`chief_editor` 在每章循环中承载了完整的 333 行系统提示词 + 全量注入包内容。实际上大部分规则是"常驻知识"而非"每章决策"。

可考虑将以下部分抽取为 skill（按需加载）：
- 初始化 SOP（仅首章需要）
- 卷纲规划（每卷首章需要）
- 完成处理（末章需要）

这样 `chief_editor` 的常驻提示词可缩减约 40%，每章写作时只加载"章节循环"相关的规则。

---

## 五、优先级排序

按"(节省效果 × 实施风险) / 改动成本"排序：

| 优先级 | 措施 | 类型 | 节省效果 | 风险 | 改动成本 |
|--------|------|------|----------|------|----------|
| **P0** | `data_operator` → skill | 转换 | 中 | 极低 | 极低 |
| **P0** | 删除 7 个冗余 style_* | 清理 | 低 | 极低 | 极低 |
| **P1** | `compliance_*` 模式一 → skill | 转换 | 中 | 低 | 低 |
| **P1** | `input_monitor` → skill | 转换 | 低 | 低 | 低 |
| **P2** | `workflow_optimizer` 合并入 `global_manager` | 合并 | 低 | 中 | 中 |
| **P2** | `chief_editor` 上下文裁剪 | 重构 | 高 | 中 | 中 |
| **P3** | Phase 2 `quality_reviewer` 批量化 | 流程改动 | **极高** | 高 | 高 |
| **P3** | `salt_architect` → skill | 转换 | 中 | 中 | 中 |

---

## 六、不可转换清单（速查）

以下 agent **绝不应**转为 skill：

```
❌ original_analyst        — 复杂分析管线，上下文隔离必需
❌ style_mapper             — 727 行分支表，计算量极大
❌ master_outline_generator — 生成数万字总纲 + 约束表
❌ destiny_designer         — 生成 6 个子目录命运书
❌ plot_planner             — 核心创作环节，681 行规则
❌ content_writer           — 核心创作环节，专用 temperature
❌ quality_reviewer         — glm-5.2 模型，Grep 强制扫描
❌ 全部 Phase 3 reviewer    — glm-5.2 模型，不可合并
❌ compliance_* 模式二       — 需读章节正文扫描红线
```
