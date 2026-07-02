# 自动化优化小说流程 — 设计与操作文档

> 本文档沉淀了「网文自动化创作 + 流程自迭代优化」系统的完整设计、决策依据和操作规范。
> 所有后续实现（角色定义、Slash Command、目录结构、模型配置）均以本文档为唯一依据。
> 版本：v1.0 | 平台：CodeBuddy Code（从 opencode 迁移）

---

## 〇、一句话概述

用一套**可复用、可自我迭代优化**的 AI 流程，把 5 本原著网文各自改写成「逻辑严谨、有追读欲、达到签约水准」的新小说。质量通过**优化流程**普惠提升（改角色分工/prompt），而非手改单本小说。

---

## 一、需求理解（五个层次）

| 层次 | 诉求 | 落地含义 |
|------|------|---------|
| **L1 目标** | 把原著网文 → 写出「逻辑严密、有追读欲」的新小说 | 衡量标准 = 能否达到「高质量签约」水准 |
| **L2 手段** | 不靠手改单本，靠**优化流程**普遍提质 | 提质必须沉淀在角色定义（prompt/SOP/分工）层，绝不改某本书正文 |
| **L3 迭代闭环** | 写→AI审稿→不达标则AI优化流程→再写→再审→再优化… | 需要「评审-归因-改流程」的自动迭代循环 |
| **L4 工程化** | opencode 工作流转 CodeBuddy；版本化；流程优化有 md 沉淀 | 受 CodeBuddy 架构约束需调整落地形态（见第三节） |
| **L5 模型分配** | 审稿+优化=GLM-5.2；原著转新书=V4-Pro；写章节=V4-Flash | 贵模型做判断/创意，便宜模型做量产 |

### 关键补充约束（用户明确要求）

1. **绝不清空任何已写内容**：每轮迭代写到带版本号的新目录，旧版全部留存。
2. **批次同步迭代**：5 本书是一个评测集。必须 **5 本全部写完 → 汇总 5 本共性问题 → 一次性优化流程 → 再 5 本重写**。优化依据是「5 本的共性问题」，不是单本。
3. **角色可增删改**：优化流程 = 重新解耦各角色分工，不只是改 prompt 文字。
4. **量产模型是 DeepSeek-V4-Flash**：所有给 Flash 的指令必须消除歧义（固定字段、量化阈值、填空式模板、正反例、禁止开放式判断）——这是质量瓶颈所在。
5. **每本先写 20 章**，20 章全部逻辑严谨、有追读欲才算过关。
6. **终结性设计**：每本要规划「如何收尾 / 能否长线连载」。
7. **达标后扩写到 50 章**，由用户人工验收。
8. **流程优化全自动**：GLM-5.2 直接改角色定义，无人工确认环节，但强制写 changelog。

---

## 二、原始工程现状（迁移起点）

工作根目录：`/data/workspace/mine/novel-editor`

### 原 opencode 角色清单（共 18 个）

**全局层**（`.opencode/agents/`，mode: primary/subagent）：
- `global_manager`（primary，总调度：训练基准 + 创建新书）
- `original_analyst`（拆原著 → 白皮书）
- `style_urban / xuanhuan / xianxia / romance / history / scifi / suspense`（7 个赛道映射）
- `facade_generator`（书名+简介）
- `salt_architect`（盐值校验去重）
- `compliance_tomato / compliance_qimao`（平台合规）

**项目层**（`project-agents-template/.opencode/agents/`）：
- `chief_editor`（primary，项目主编，调度写作流水线）
- `plot_planner`（章纲）
- `content_writer`（正文）
- `quality_reviewer`（单章质检，105±5→120±5 分制）
- `data_operator`（数据复盘）

### 核心数据流（原流程）

```
source.txt → [original_analyst] → base_whitepaper.md（六大模块白皮书）
白皮书 + 平台 + 赛道 → [style_*] 映射 + [facade_generator] 门面 + [salt_architect] 校验
                     → project_salt.json + 项目目录
project_salt.json → [chief_editor 初始化] → 仿写衍生总纲领.md
每章循环：[plot_planner]章纲 → [content_writer]初稿 → [quality_reviewer]质检(≥80) → 终稿
```

### 5 本原著评测集（`novels/` 目录）

| 文件 | 体量 | 备注 |
|------|------|------|
| `凡人修仙传.txt` | ~15MB | 仙侠/修真 |
| `斗破苍穹.txt` | ~18MB | 玄幻 |
| `娘娘本纪.txt` | ~0.9MB | 宫斗/女频（已有白皮书） |
| `白夜行.txt` | ~0.9MB | 悬疑 |
| `赘婿.txt` | ~11MB | 历史/都市 |

赛道由 `style-mapper` 根据原著自动推断，覆盖仙侠/玄幻/女频/悬疑/历史多赛道，保证评测集多样性。

---

## 三、CodeBuddy 平台关键约束（决定落地形态）

> 来自 CodeBuddy 官方文档 `sub-agents.md` / `models.md`。

1. **子代理无法嵌套**（硬约束）：文档明确「子代理不能生成其他子代理」。
   → **否定了「写一个 subagent 包住整条工作流、由它再调写作/审稿/优化 subagent」的设想。**
   → 编排逻辑必须放在**顶层主对话**（通过 Slash Command 驱动）。

2. **子代理支持 per-agent 模型**：frontmatter 的 `model` 字段，可填模型别名或 `inherit`。
   → 模型差异化分配可行。

3. **子代理文件格式**：`.codebuddy/agents/*.md`，YAML frontmatter：
   ```yaml
   ---
   name: 小写连字符唯一标识
   description: 自然语言描述（含「use PROACTIVELY」可提升自动委派）
   tools: Read, Write, Edit, Bash   # 省略则继承全部
   model: glm-5.2-ioa / deepseek-v4-pro-ioa / deepseek-v4-flash-ioa / inherit
   permissionMode: default / acceptEdits / bypassPermissions / plan / ignore
   ---
   系统提示正文
   ```

4. **Slash Command**：`.codebuddy/commands/*.md`，跑在顶层主对话，可调用所有 subagent，逻辑透明可控。

5. **模型 ID 说明**：`deepseek-v4-pro-ioa` / `deepseek-v4-flash-ioa` 为 IOA 内置模型（重装 CodeBuddy 后无需 `models.json`）。若 Flash 模型不可用，系统**禁止回退**到主模型——所有 agent 的输出首行强制输出「模型自检」行，指挥者逐次校验，不匹配则立即终止。

---

## 四、目标架构

### 编排者形态决策：Slash Command（非 Agent Teams）

理由：本闭环是**严格串行 + 批次同步**（5 本全写完才优化），Teams 的并行优势用不上，反而增加协调复杂度和失控风险；Slash Command 跑在顶层、能调所有 subagent、逻辑透明，最贴近原 opencode primary agent 的心智。

### 角色与模型分配

```
CodeBuddy 顶层主对话（你）
│
├── Slash Commands（.codebuddy/commands/，顶层编排）
│   ├── /train      编排「原著→白皮书」
│   ├── /create     编排「白皮书→新书配置」（V4-Pro 角色）
│   ├── /write      编排「章纲→初稿→单章质检→终稿」（V4-Flash 角色）
│   └── /iterate    ★核心闭环：批次写→签约审→流程优化→重写（见第六节）
│
└── Subagents（.codebuddy/agents/，扁平、单职责）
    ├── original-analyst      model: deepseek-v4-pro-ioa    拆原著→白皮书
    ├── style-mapper          model: deepseek-v4-pro-ioa    赛道映射（7→1，参数化）
    ├── facade-generator      model: deepseek-v4-pro-ioa    书名+简介
    ├── salt-architect        model: deepseek-v4-pro-ioa    盐值校验去重
    ├── plot-planner          model: deepseek-v4-flash-ioa  章纲（量产）
    ├── content-writer        model: deepseek-v4-flash-ioa  正文（量产）
    ├── quality-reviewer      model: deepseek-v4-flash-ioa  单章质检（量产，快速拦截）
    ├── compliance-tomato     model: deepseek-v4-flash-ioa  平台合规
    ├── compliance-qimao      model: deepseek-v4-flash-ioa  平台合规
    ├── signing-reviewer  ★新 model: glm-5.2-ioa            签约级整本审稿（打分+归因）
    └── flow-optimizer    ★新 model: glm-5.2-ioa            读共性问题→改角色定义+写changelog
```

> 注：`compliance_*` 是否合并、`style_*` 7→1 的具体拆分，由 flow-optimizer 在迭代中按需调整（角色可增删改）。初始落地按上表。

### 两个新增核心角色（L3 闭环的灵魂）

- **signing-reviewer（GLM-5.2）**：站在「签约编辑」视角审**整本前 20 章**，按第五节 rubric 打分，产出「分数 + 每个扣分点定位到第几章第几处 + 归因到哪个角色」。
- **flow-optimizer（GLM-5.2）**：读 5 本的审稿报告，提取**共性问题** → 直接修改对应角色的 `.md` 定义（含增删改角色、调分工、加约束、改 Flash 防歧义指令）→ 写 changelog md。**全自动，无人工确认。**

---

## 五、签约审核标准 rubric v1.1（已经用户认可）

> v1.1 相比 v1.0 变更：新增维度 9「原创改写度」（10分，从其他维度匀出），新增一票否决项「换皮抄袭」。
> 核心理念：我们要的是**基于原著脉络的实质再创作**，而非换名抄袭。

### 总则
- 满分 **100 分**，**签约线 = 85 分**，且**无任何一票否决项命中**。
- 审核对象：一本书的**前 20 章整体**（追读欲是跨章累积的）。
- 每维度必须输出：得分 + 扣分点定位（第几章第几处）+ 归因角色。
- signing-reviewer 审稿时**同时持有两份脉络**：①原著白皮书的抽样章脉络（人物内核/爽点序列/关键情节/对白风格）②新书 20 章脉络。维度 9 与抄袭否决项基于二者**结构性比对**（非字面查重）。

### 九大评分维度（100 分）

| # | 维度 | 分值 | 考察本质 | 量化打分锚点 |
|---|------|-----|---------|------------|
| 1 | **开篇抓力** | 13 | 前3章能否留住读者 | 第1章是否3段内进入核心矛盾；前3章是否各有1个钩子；黄金三章的爽点/悬念是否到位 |
| 2 | **追读欲/钩子链** | 20 | 是否章章想看 | 20章每章末是否有有效钩子；钩子是否形成「未解问题链」而非孤立；中段(8-15章)有无塌陷 |
| 3 | **逻辑严谨性** | 20 | 有无硬伤/降智/矛盾 | 因果链自洽；无「为爽而爽」降智配角；伏笔回收；人物信息流合理（谁该知道什么） |
| 4 | **人物可信度** | 10 | 动机行为立得住 | 主角动机一以贯之；配角非工具人；反派有合理动机非纯降智 |
| 5 | **爽感节奏** | 12 | 爽点密度与铺垫匹配 | 爽点间隔符合赛道节奏；爽点前有压抑铺垫（压制→反杀闭环）；无爽点疲劳/空窗 |
| 6 | **文笔流畅度** | 8 | 句子通顺无AI味 | 无翻译腔/重复句式/语义歧义；对话自然；无 Flash 常见的机械排比、空洞形容词堆砌 |
| 7 | **设定与世界观** | 4 | 清晰且不过载 | 设定随剧情自然释放非信息倾倒；金手指规则自洽不崩 |
| 8 | **完本延展性** | 3 | 支撑长线连载 | 主线够大撑50万字+；预留升级路径/势力梯度；20章末处在能自然延展的节点 |
| 9 | **原创改写度** ★新 | 10 | 是基于脉络改写还是换皮抄袭 | 见下方专项判定 |

#### 维度 9「原创改写度」专项判定（10 分）

与原著抽样章脉络结构性比对，**扣分 = 越像原著扣越多，加分 = 实质再创作**：

| 检查项 | 判定 | 分数影响 |
|-------|------|---------|
| 人物内核是否实质再创作（非仅换名） | 主角性格/动机/成长弧与原著主角实质不同 | 满足 +基准；仅换名内核照搬 → 直接触发否决（见下） |
| 爽点序列是否重新编排 | 新书爽点类型序列与原著抽样章不构成连续雷同 | 重新编排得分高；照搬序列 -4 |
| 关键情节是否再创作 | 核心情节是改写化用而非原样平移 | 化用得分高；原样平移 -3 |
| 场景/对白是否原创 | 标志性场景、金句、对白非高度雷同 | 原创得分高；高度雷同 -3 |
| 是否保留原著「套路骨架」做正向继承 | 保留节奏模型/赛道套路但填入全新血肉 | **这是鼓励项**：骨架继承 + 血肉原创 = 满分方向 |

> **正向样例**：保留「废柴隐忍→打脸逆袭」的节奏骨架，但主角身份、金手指、核心矛盾、人物关系、具体打脸场景全部重新设计 → 高分。
> **反向样例（触发否决）**：主角改名秦风、岳母改名王淑芬，但家庭结构、入赘设定、第一次打脸的「救濒死贵客」桥段、对白几乎照搬 → 换皮抄袭，直接拒。

### 一票否决项（命中任意一条 → 直接不通过，无论总分）

1. **逻辑硬伤**：读者一眼可见的剧情矛盾/穿帮。
2. **降智推进**：核心冲突靠配角集体降智才成立。
3. **追读断裂**：连续 ≥3 章无有效钩子。
4. **平台红线**：涉政/低俗擦边/未成年恋爱等（沿用 compliance 标准）。
5. **AI 味过重**：通篇机械句式/不通顺，读者一眼看出是机器写的。
6. **换皮抄袭** ★新（尺度=严）：人物仅换名而内核照搬，且情节、场景、对白基本平移原著 → 直接拒。
   - 判定线（严）：只要满足「人物仅换名 + 情节/场景/对白基本平移」即命中，不要求逐字相同。
   - 保护条款：若保留的是赛道**套路骨架/节奏模型**（行业通用，非原著独有），而人物与具体情节是实质再创作，**不算抄袭**。

### 评分档位

| 总分 | 含义 |
|------|------|
| 90-100 | 可直接签约，质量上乘 |
| **85-89** | **达签约线（闭环退出条件）** |
| 70-84 | 有潜力但需修流程，明确不达标 |
| <70 | 流程有重大缺陷 |

### signing-reviewer 固定输出格式

```
# 《书名》v{N} 签约审核报告
总分：__/100   判定：通过/不通过   一票否决：无/命中第_条

维度明细：
1. 开篇抓力 __/13
   扣分点：第2章开篇用了300字环境描写才进入矛盾（第2章第1-4段）
   归因角色：content-writer（开场约束不够硬）
2. 追读欲 __/20
   扣分点：第9-11章连续3章钩子同质「又来一个强敌」（第9/10/11章末）
   归因角色：plot-planner（钩子类型未做轮换约束）
... （维度3~8逐条）
9. 原创改写度 __/10
   比对结论：人物内核__/爽点序列__/关键情节__/场景对白__（逐项 原创/化用/雷同）
   归因角色：style-mapper（盐值差异化不足）或 content-writer（落地时贴原文）

本书最致命问题：____，根因在____角色，属于【框架层(V4-Pro) / 执行层(V4-Flash)】。
```

> **每本书每轮都必须打分并给出打分理由**（用户明确要求）。
> 末行的「框架层/执行层」归层判断是供 flow-optimizer 做根因分析的关键输入（见第六节）。

---

## 六、L3 闭环：迭代状态机与 SOP

### 状态机文件：`workspace/iteration-state.json`

闭环的全部「记忆」落盘于此（Slash Command 是一次性执行，靠状态文件实现可中断/可重启）。

```json
{
  "status": "running",          // running / converged / stopped
  "mode": "start",              // start（自动连跑）/ step（逐轮）/ dryrun（自测）
  "phase": "writing",           // writing / reviewing / optimizing（保证「5本全写完才优化」）
  "current_round": 3,
  "signing_line": 85,
  "target_chapters": 20,        // dryrun 时为 3
  "expand_chapters": 50,
  "active_books": ["凡人修仙传","斗破苍穹","娘娘本纪","白夜行","赘婿"],  // dryrun 时仅 ["娘娘本纪"]
  "books": {
    "凡人修仙传": { "track": "仙侠", "latest_version": "v3", "round_done": false, "score": null,  "passed": false },
    "斗破苍穹":   { "track": "玄幻", "latest_version": "v3", "round_done": true,  "score": 88,   "passed": true  },
    "娘娘本纪":   { "track": "女频", "latest_version": "v3", "round_done": true,  "score": 79,   "passed": false },
    "白夜行":     { "track": "悬疑", "latest_version": "v3", "round_done": true,  "score": 90,   "passed": true  },
    "赘婿":       { "track": "历史", "latest_version": "v3", "round_done": false, "score": null,  "passed": false }
  },
  "dimension_history": {
    // 防死循环用：记录每个维度逐版本均分 + 该维度上次从哪一层优化的 + 同方向无改善累计轮数
    "追读欲":       { "scores": [12, 15, 15], "last_layer": "执行层", "stale_rounds": 1 },
    "逻辑严谨性":   { "scores": [10, 14, 17], "last_layer": "框架层", "stale_rounds": 0 },
    "原创改写度":   { "scores": [5,  6,  6],  "last_layer": "框架层", "stale_rounds": 1 }
    // ...其余维度同构。stale_rounds 达到 2 → 触发方向切换（框架层↔执行层）
  }
}
```

> `dimension_history.scores` 是 5 本（dryrun 为 1 本）在该维度上的**逐版本均分序列**，是 flow-optimizer 判断「分数趋势」「是否正向优化」「是否回归」的数据来源。
> `stale_rounds` 记录「同一层优化但该维度无改善」的连续轮数，达 2 即强制换层。

### 单轮 SOP（一个 round 内严格按 phase 推进）

```
phase = writing：
  for 每本未 round_done 的书：
    1. （首轮）/train 生成白皮书 → /create 生成 project_salt + 总纲领
    2. /write 写 1~20 章 → 落到 versions/v{N}/{书}/ （章纲+正文+单章质检）
    3. 标记该书 round_done = true
  5 本全部 round_done → phase = reviewing

phase = reviewing：
  for 每本书：
    signing-reviewer（GLM-5.2）审 versions/v{N}/{书} 前20章 → 打分 → 写审稿报告 v{N}.md
  汇总 5 本 score/passed 写回状态机
  若 5 本全 passed → status = converged（闭环结束）
  否则 → phase = optimizing

phase = optimizing（历史感知优化，防死循环）：
  flow-optimizer（GLM-5.2）执行以下强制步骤：
    【步骤1 读全部历史】读 iteration-log.md（各版本各维度分数曲线）
                       + 所有历史 flow-changelog/*.md（历次改了什么、预期改善什么）
    【步骤2 提取共性问题】汇总本轮 5 本审稿报告，找出 5 本反复出现的共性扣分维度
                       （单本独有问题优先级低于共性问题）
    【步骤3 分数趋势判断】对每个目标维度，对比上一版分数：涨 / 跌 / 原地踏步
    【步骤4 回归检测】检查本轮是否有「之前已修好的维度又退化了」→ 若有，优先回滚或修复回归
    【步骤5 根因归层】结合审稿报告末行的「框架层/执行层」标记，判断问题根因：
                       - 框架层(V4-Pro)：白皮书脉络浅 / 盐值差异化不足 / 总纲领约束模糊
                         → 改 original-analyst / style-mapper / facade-generator / 总纲领生成逻辑
                       - 执行层(V4-Flash)：框架没问题但落地走样 / AI味 / 不按章纲写
                         → 改 plot-planner / content-writer（按第八节 Flash 防歧义规范收紧）
    【步骤6 死循环防护】对每个维度查 dimension_history：
                       若该维度【连续 2 轮】「已针对性优化但分数无改善（涨幅<阈值或仍不达标）」
                       → 判定当前优化方向无效 → 强制切换下手层（框架层↔执行层对调）
                       → 在 changelog 显式记录「方向切换：因 X 维度连续2轮 Y 层优化无效，改从 Z 层下手」
    【步骤7 落地修改】直接修改 .codebuddy/agents/ 下相关角色定义（含增删改角色）
    【步骤8 写优化日志】写 flow-changelog/v{N}-to-v{N+1}.md，强制包含：
                       · 本轮5本共性问题清单
                       · 每个维度的分数趋势（本版 vs 上版，附数字）
                       · 回归检测结果
                       · 根因归层结论（框架层/执行层 + 理由）
                       · 是否触发死循环防护与方向切换
                       · 本次具体改了哪些角色、改了什么、预期改善哪个维度多少分
  current_round += 1，所有书 round_done = false，phase = writing（用新流程重写到 v{N+1}）
```

> **「5 本全写完才优化」由 phase 强制保证**：只有所有书 round_done 且 reviewing 完成，才允许进入 optimizing。resume 严格按 phase 恢复，绝不会「只写完 2 本就去改流程」。
>
> **历史感知是防死循环的核心**：flow-optimizer 绝不只看当前版本。它必须基于「分数曲线 + 历次优化记录」判断优化是否正向，并能区分「框架层(V4-Pro 写的小说框架有问题) vs 执行层(V4-Flash 基于框架写的正文有问题)」——这两层的修法完全不同。连续 2 轮同方向无效即强制换层下手。

### 目录结构（版本化，绝不清空）

```
workspace/
├── iteration-state.json              ← 闭环状态机
├── repo/{原著名}/
│   ├── source.txt                    ← 从 novels/ 拷入
│   └── base_whitepaper.md
└── books/{原著名}/
    ├── versions/
    │   ├── v1/
    │   │   ├── project_salt.json
    │   │   ├── 仿写衍生总纲领.md
    │   │   ├── 01-大纲/  02-正文/  03-纪要/  04-数据/
    │   │   └── 审稿报告-v1.md
    │   ├── v1-bk/                     ← resume 时未完成版本的备份（见操作语义）
    │   ├── v2/ ...
    │   └── v3/ ...
    ├── flow-changelog/               ← 每轮流程优化沉淀
    │   ├── v1-to-v2.md
    │   └── v2-to-v3.md
    └── iteration-log.md              ← 本书每轮得分台账

.codebuddy/
├── agents/                           ← 所有 subagent 定义（flow-optimizer 会改这里）
└── commands/                         ← /train /create /write /iterate
```

> 注意：flow-optimizer 改的是**全局角色定义**，会同时影响 5 本书——这正是 L2「提质要普惠」的诉求；因此用 GLM-5.2 判断 + 强制 changelog 来保障可追溯。

---

## 七、操作机制（dryrun / start / step / stop / resume / status / expand / reset）

### 设计要点（用户确认的语义）

- **先 `dryrun` 自测**：正式跑前用极小规模（1 本书 3 章）跑通完整闭环（写→审→优化），验证全流程无 bug。用户确认 dryrun 没问题后再正式执行。
- 同时支持 `step`（手动逐轮）和 `start`（自动连跑）。
- `stop` 用于停止；被 stop 中断的那一轮，**resume 时从该版本头部重跑**：
  - 例：迭代到 v3 执行到一半被 stop → resume 时把已有的半成品 `v3/` **复制备份为 `v3-bk/`**，然后 `v3/` 从头重新跑。
  - 备份保证「绝不清空」；从头重跑保证该版本一致性（不接半成品）。

### 命令速查表

| 命令 | 行为 |
|------|------|
| `/iterate dryrun` | **快速自测**：仅 1 本书（默认娘娘本纪，体量最小）× 3 章，跑完整闭环一轮（写→审→优化→重写），验证管道无 bug。产物落到独立的 `workspace/_dryrun/` 不污染正式目录 |
| `/iterate start` | 从当前状态**自动连跑**多轮，直到 5 本全达标（converged）或被 stop/中断 |
| `/iterate step` | **只跑一轮**（write→review→optimize），round+1 后停下等检查 |
| `/iterate stop` | 停止闭环，`status=stopped`，保留全部产物（含当前半成品版本） |
| `/iterate resume` | 从中断处恢复：若当前版本是被 stop 的半成品 → 先备份为 `{vN}-bk/` → `vN/` 从头重跑；否则按 phase 续跑 |
| `/iterate status` | 打印 iteration-state.json 摘要（轮次、各书分数、phase） |
| `/iterate expand 50` | 收敛后将 5 本从 20 章扩写到 50 章供人工验收 |
| `/iterate reset` | 迭代计数归 1 重新开始，**不删除任何旧 versions**，新轮从更高版本号继续编号 |

### dryrun 自测说明

- **目的**：不是为了写出好小说，而是**验证整条流水线能跑通**——所有角色被正确调用、状态机正确流转、文件正确落盘、GLM-5.2 审稿+优化能正常产出、changelog 能写出。
- **规模**：1 本书（娘娘本纪，已有白皮书最省时）× 3 章 × 1 轮闭环。
- **隔离**：产物写到 `workspace/_dryrun/`，与正式 `workspace/books/` 完全隔离，自测完可整目录删除。
- **验收点**（dryrun 跑完后人工确认这些都 OK 才算通过）：
  1. 白皮书/盐值/总纲领正确生成
  2. 3 章正文+章纲+单章质检正确产出
  3. signing-reviewer 给出了 9 维打分+归因+框架层/执行层判断
  4. flow-optimizer 正确读历史、写出含「趋势/回归/归层」的 changelog 并真实改了角色文件
  5. 状态机字段正确更新，stop/resume 能正常工作

### resume 的核心判定逻辑（实现要点）

```
读 iteration-state.json：
  若 status == stopped 且当前 round 的 vN 目录存在但 round 未完成（半成品）：
    1. 将 workspace/books/*/versions/vN/ 复制为 vN-bk/   （备份，绝不清空）
    2. 清出 vN/ 重新建空目录
    3. status = running，phase 回退到 writing，所有书 round_done = false
    4. 从头重跑本轮（vN）
  否则（正常中断/上轮干净结束）：
    按 phase 与各书 round_done 续跑（已完成的书跳过）
```

### 现实约束（需用户知晓）

1. 单次 `/iterate start` 连跑「5本 × (章纲+20章正文+单章质检) + 5本GLM-5.2审稿 + 流程优化」耗时极长，可能一次执行只能推进一轮。`start` 实现为「自动续跑直到收敛或被打断」，但随时可靠状态文件 `resume`。
2. `start` 模式中途想停：`/iterate stop` 或按 Esc 打断；下次 `resume` 按上述逻辑（半成品 → 备份 vN-bk → 从头重跑 vN）。

---

## 八、DeepSeek-V4-Flash 防歧义规范（量产角色强制遵守）

因最终写章节/章纲/单章质检的是 Flash，所有发给 Flash 的角色定义必须遵守：

1. **字段固定化**：所有输入/输出用固定字段名 + 固定结构，禁止开放式自由发挥。
2. **量化阈值**：凡「合适」「自然」「足够」等模糊词，一律替换为可计算的数值阈值（如「开场≤3段进入矛盾」「单章爽点≥1次」）。
3. **填空式模板**：章纲/正文给出带占位符的骨架模板，Flash 只填空不自创结构。
4. **正反例对照**：每条关键约束附「✅正例 / ❌反例」，消除理解歧义。
5. **禁止开放判断**：判断类任务（如「是否够爽」）拆成可勾选的 checklist，而非让 Flash 主观评价。
6. **单一职责**：每个 Flash 角色只做一件事，输入输出边界清晰，降低上下文负担。

> flow-optimizer 优化时，若审稿归因到 Flash 角色「理解歧义/AI味」，应优先按本规范收紧指令。

---

## 九、终结性与扩写设计

- 每本 `仿写衍生总纲领.md` 增加「完本架构」章节：主线分卷规划、升级路径/势力梯度、可延展节点与可收束节点。
- 20 章末必须处在「能自然延展」的剧情节点（既能停也能续）。
- 收敛后 `/iterate expand 50`：基于已达标的 20 章 + 完本架构，续写到 50 章，沿用同一套已优化的流程角色。

---

## 十、实现清单（落地状态）

1. [x] ~~`models.json` 配置（旧版 self-hosted 用，重装后 IOA 内置模型无需此文件）~~
2. [x] 迁移并改造 opencode 角色 → `.codebuddy/agents/`（9 个：original-analyst / style-mapper〔7→1参数化〕/ facade-generator / salt-architect / plot-planner / content-writer / quality-reviewer / compliance-tomato / compliance-qimao；含模型分配 + 3 个 Flash 量产角色追加「Flash 执行铁律」防歧义段）。
3. [x] 新增 `signing-reviewer`（固化 rubric v1.1，含维度9原创改写度+换皮抄袭否决+框架层/执行层归层）和 `flow-optimizer`（八步法：历史感知+趋势/回归/归层+死循环防护 stale_rounds≥2 换层）。
4. [x] 编写 Slash Commands：`/train` `/create` `/write` `/iterate`（含全状态机语义）。
5. [x] 实现 `iteration-state.json` 状态机（含 9 维 dimension_history）与 dryrun/start/step/stop/resume/status/expand/reset 全部语义（落于 `/iterate` 命令逻辑）。
6. [x] 建立版本化目录结构（每本 versions/ + flow-changelog/ + iteration-log.md）与备份（vN-bk）逻辑；dryrun 隔离目录 `workspace/_dryrun/`。
7. [x] 从 `novels/` 拷贝 5 本原著到 `workspace/repo/{原著名}/source.txt`。
8. [ ] **下一步（交给用户）：先跑 `/iterate dryrun`（1本3章）验证全流程，确认无 bug 后再正式 `/iterate start` 或 `step`。**

---

## 附：关键决策记录（避免反复）

| 决策点 | 结论 | 依据 |
|--------|------|------|
| 编排者形态 | Slash Command（顶层） | 子代理不能嵌套；闭环严格串行 |
| 优化控制 | GLM-5.2 全自动改 + 强制 changelog，无人工确认 | 用户明确要求 |
| 签约线 | 85 分 + 无一票否决 | 用户认可 rubric v1.1 |
| 打分方 | GLM-5.2（signing-reviewer），每本每轮给分+理由 | 用户要求 |
| 防抄袭 | 维度9原创改写度(10分) + 换皮抄袭一票否决(尺度=严)；结构性比对非字面查重；保护「基于脉络改写」 | 用户要求1 |
| 历史感知优化 | flow-optimizer 强制读分数曲线+历次changelog；判趋势/查回归/归层(框架层V4-Pro↔执行层V4-Flash) | 用户要求2 |
| 防死循环 | 某维度连续2轮同层优化无改善 → 强制切换下手层；过程写入changelog | 用户要求2，阈值=2轮 |
| 快速自测 | `/iterate dryrun` = 1本×3章×1轮，隔离到 _dryrun/，验证管道无bug | 用户要求3 |
| 版本策略 | 每轮新目录，绝不清空；半成品 resume 备份为 vN-bk 后从头重跑 | 用户明确要求 |
| 批次粒度 | 5 本全写完才优化，依据共性问题 | 用户明确要求 |
| 章节目标 | 先 20 章过关 → 达标后扩 50 章人工验收 | 用户明确要求 |
| 评测集 | novels/ 下 5 本：凡人修仙传/斗破苍穹/娘娘本纪/白夜行/赘婿 | 用户指定 |

