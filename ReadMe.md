# 网文编辑工作台 — 完整使用指南

---

## 一、系统架构概览

本系统分两层：

```
工作根目录（D:\novel-editor）              ← 全局任务在此启动
├── .opencode/agents/      ← 全局 agent（处理训练基准、创建新书）
│   ├── global_manager      ← 总调度器（Primary，你直接对话的入口）
│   ├── original_analyst    ← 原作拆解分析师
│   ├── style_* (x7)        ← 赛道映射设计师
│   ├── facade_generator    ← 书名+简介生成器
│   ├── salt_architect      ← 盐值校验/去重
│   └── compliance_* (x2)   ← 平台合规专员
│
└── workspace/
    ├── repo/{原作名}/       ← 原作原文 + 基准白皮书
    └── books/{原作名}_salt_{编号}_{书名}/  ← 衍生项目目录（创建后进入这里）
        └── .opencode/agents/  ← 项目级 agent（写作流水线）
            ├── chief_editor     ← 项目主编（Primary，进入项目后对话的入口）
            ├── plot_planner     ← 剧情规划师
            ├── content_writer   ← 正文撰稿师
            ├── quality_reviewer ← 质检编审
            └── data_operator    ← 数据运营师
```

关键规则：
- **全局任务**（训练基准、创建新书）→ 在 **根目录** 启动 opencode，对话 `global_manager`
- **项目任务**（写作小说）→ 在 **衍生项目目录** 启动 opencode，对话 `chief_editor`
- 两个 Primary agent 独立工作，不存在交叉调用

---

## 二、任务 1：增量训练基准小说

> 启动目录：`D:\novel-editor`（工作根目录）
> 对话 agent：`global_manager`（Primary）
> 支持两种模式：批量扫描 / 指定训练

### 作用

将原始小说文本 `source.txt` 拆解为结构化的 `base_whitepaper.md`（包含世界观框架、人物模型、爽点公式、节奏规律、文风特征、剧情范式六大模块），供后续衍生创作使用。

### 前置准备

在 `workspace/repo/{原作名}/` 中放置 `source.txt`（原作全文），每部小说一个子目录。

---

### 模式 A：批量扫描（全量自动训练）

自动扫描所有未训练的小说，逐一生成白皮书。

#### 触发指令

```
执行基准小说增量训练
```

#### 自动执行流程

```
global_manager 扫描 workspace/repo/
    ↓ 识别存在 source.txt 但无 base_whitepaper.md 的目录
    ↓
逐个调用 @original_analyst
    ↓ 读取 source.txt → 输出 base_whitepaper.md
    ↓
输出训练汇总（成功/失败/对应目录）
```

#### 示例

```
> 执行基准小说增量训练
✓ 训练完成：成功 1 / 失败 0
  - 成功：娘娘本纪 → workspace/repo/娘娘本纪/base_whitepaper.md
```

---

### 模式 B：指定训练（训练指定小说，支持覆盖）

指定一部小说进行训练。即使该小说已有白皮书也会**覆盖重写**。

#### 触发指令

```
训练基准小说：娘娘本纪
```

或（语义等同）：

```
重新训练基准小说：娘娘本纪
```

#### 自动执行流程

```
global_manager 接收 {原作名}
    ↓ 验证 workspace/repo/{原作名}/source.txt 是否存在
    ↓ 存在 → 调用 @original_analyst（覆盖已存在的白皮书）
    ↓ 不存在 → 报错中止
    ↓
输出训练结果
```

#### 示例

```
> 训练基准小说：娘娘本纪
✓ 训练完成：娘娘本纪 → workspace/repo/娘娘本纪/base_whitepaper.md

> 训练基准小说：不存在的小说
✗ 错误：workspace/repo/不存在的小说/source.txt 不存在
```

---

### 输出（两种模式一致）

```
workspace/repo/{原作名}/base_whitepaper.md
```

---

## 三、任务 2：创建新衍生小说

> 启动目录：`D:\novel-editor`（工作根目录）
> 对话 agent：`global_manager`（Primary）
> 执行模式：全自动，用户仅需输入参数

### 作用

基于已有的基准白皮书，生成一部面向指定平台的衍生小说完整配置（世界观映射、人物映射、分类标签、书名、简介），并创建项目目录。

### 输入参数

| 参数 | 必选/可选 | 说明 | 示例 |
|------|----------|------|------|
| `基准原作名` | **必选** | 对应 workspace/repo/ 下已有白皮书的原作名称 | `娘娘本纪` |
| `目标平台` | **必选** | 发布平台，决定合规规则和标签体系 | `番茄` / `七猫` |
| `风格赛道` | **可选** | 不提供则按平台引流风格自动推断 | `都市` / `玄幻` / `仙侠` / `言情` / `历史` / `科幻` / `悬疑` |

### 触发指令

**最短用法（自动推断风格赛道）：**

```
创建新衍生小说：
基准原作：娘娘本纪
目标平台：番茄
```

**完整用法（指定风格赛道）：**

```
创建新衍生小说：
基准原作：娘娘本纪
目标平台：番茄
风格赛道：都市
```

### 自动执行流程

```
1. 接收用户输入
   │
2. 自动分配盐值编号
   │ 扫描已有目录，取最大编号+1
   │
3. 若风格赛道未提供，自动推断
   │ 调用 compliance_* 获取平台热门分类
   │
4. 第一阶段：创意映射
   ├─ @style_urban/...  → 映射层 JSON（世界观/人物/爽点映射）
   └─ 替换 salt_id 为自动编号
   │
5. 第二阶段：门面生成
   ├─ @facade_generator → 门面层 JSON（书名+简介）
   └─ 合并为完整盐值初稿
   │
6. @salt_architect 校验（去重+格式+红线）
   │
7. 创建项目目录 + 保存 project_salt.json
   │ 目录名：{原作名}_salt_{编号}_{书名}/
   │
8. 输出创建结果
```

### 输出

```
workspace/books/{原作名}_salt_{编号}_{书名}/
├── project_salt.json      ← 最终盐值（映射配置）
├── .opencode/agents/      ← 写作流水线 agent（从 project-agents-template 复制）
│   ├── chief_editor.md
│   ├── plot_planner.md
│   ├── content_writer.md
│   ├── quality_reviewer.md
│   └── data_operator.md
├── 仿写衍生总纲领.md       ←（下一章 chief_editor 初始化时生成）
├── 01-大纲/                ←（空，待写入）
├── 02-正文/                ←（空，待写入）
├── 03-纪要/                ←（空，待写入）
└── 04-数据/                ←（空，待写入）
```

### 示例

```
> 创建新衍生小说：
> 基准原作：娘娘本纪
> 目标平台：番茄
> 风格赛道：都市
✓ 项目创建完成
  原作：娘娘本纪 | 风格：都市
  编号：001 | 书名：赘婿神医之都市风云
  路径：workspace/books/娘娘本纪_salt_001_赘婿神医之都市风云/
  标签：扮猪吃虎、隐藏大佬、医道传承、赘婿逆袭
```

### 可用风格赛道一览

| 风格关键词 | 调用的 agent | 适用场景 |
|-----------|-------------|---------|
| `都市` | @style_urban | 赘婿神医、神豪、职业打脸、都市脑洞 |
| `玄幻` | @style_xuanhuan | 系统升级、废柴逆袭、高武都市 |
| `仙侠` / `修真` / `修仙` | @style_xianxia | 传统仙侠、修真飞升、仙魔大战 |
| `言情` / `女频` | @style_romance | 重生虐渣、先婚后爱、大女主、追妻火葬场 |
| `历史` / `穿越` | @style_history | 历史穿越、争霸、权谋、科技兴国 |
| `科幻` / `末世` / `废土` | @style_scifi | 末世求生、基地建设、异能觉醒 |
| `悬疑` / `灵异` / `推理` | @style_suspense | 灵异探案、恐怖解密、都市怪谈 |

---

## 四、任务 3：全自动写作小说

> 启动目录：`workspace/books/{原作名}_salt_{编号}_{书名}/`（衍生项目目录）
> 对话 agent：`chief_editor`（Primary，项目主编）
> 执行模式：全自动流水线，指定章节范围即可

### 前置条件

项目目录已通过任务 2 创建，且 `project_salt.json` 存在。

### 触发指令

```
全自动执行第1~10章生产
```

支持范围写法：
- `全自动执行第1~10章生产` — 单段范围
- `全自动执行第1~5章、第8章生产` — 不连续范围
- `全自动执行全部章节生产` — 按总纲领预估章节数

### 自动执行流程

#### 初始化 SOP（首次运行时自动执行一次）

```
chief_editor 读取 project_salt.json
    ↓
读取基准白皮书 → 提取节奏模型
    ↓
调用 compliance_*（模式一）→ 获取平台规则集
    ↓
规则融合计算：平台字数 × 节奏模型 → 精确字数标准
    ↓
生成《仿写衍生总纲领.md》
  ├── 首位：书名+简介
  ├── 平台适配（融合后字数）
  ├── 分类标识（标签约束）
  └── 其余章节（世界观/人物/爽点等）
    ↓
创建 01-大纲/ 02-正文/ 03-纪要/ 04-数据/ 目录
```

#### 单章生产 SOP（循环执行指定范围内的每章）

```
① @plot_planner → 章纲          → 01-大纲/第N章章纲.md
② @content_writer → 初稿        → 02-正文/第N章-初稿.md
③ @quality_reviewer → 质检
   ├── 通过（评分≥80）→ 03-纪要/第N章纪要.md
   └── 不通过 → 退回修改（最多3次）
④ @compliance_*（模式二）→ 合规终审
⑤ 合格 → 重命名 第N章-终稿.md
⑥ 自动进入下一章
```

#### 周期复盘 SOP（每10章自动执行一次）

```
扫描 04-数据/ 目录
    ↓
@data_operator → 复盘报告 → 04-数据/第M-N章复盘报告.md
    ↓
更新《仿写衍生总纲领.md》（版本号+日期）
```

### 输出产物

```
workspace/books/{原作名}_salt_{编号}_{书名}/
├── project_salt.json          ← 盐值配置
├── 仿写衍生总纲领.md           ← 创作总纲领（持续更新）
├── 01-大纲/
│   ├── 第1章章纲.md           ← 含核心事件、爽点位置、出场人物、钩子、标签覆盖
│   ├── 第2章章纲.md
│   └── ...
├── 02-正文/
│   ├── 第1章-初稿.md
│   ├── 第1章-终稿.md          ← 通过质检+合规后的最终版
│   └── ...
├── 03-纪要/
│   ├── 第1章纪要.md           ← 质检通过时生成，记录核心事件+人物状态
│   └── ...
└── 04-数据/
    ├── 流量数据.csv            ← 外部投放后手动放置
    └── 第1-10章复盘报告.md     ← 周期复盘自动生成
```

### 示例

```
> 全自动执行第1~10章生产
✓ 初始化完成（总纲领已生成）
→ [第1章] 章纲完成 → 初稿完成 → 质检通过(85分) → 合规通过 → 终稿
→ [第2章] 章纲完成 → 初稿完成 → 质检通过(82分) → 合规通过 → 终稿
→ [第3章] 章纲完成 → 初稿完成 → 质检不通过(72分) → 第2版(78分) → 第3版(88分) → 合规通过 → 终稿
...
→ [第10章] ... → 终稿
✓ 第1~10章全部完成 | 质检平均分: 84.5 | 合规通过率: 100%
```

---

## 五、辅助操作（手动执行）

以下操作通常由流水线自动触发，但也支持手动执行。

### 5.1 手动质检某一章

在项目目录中发送：

```
质检第3章
```

调用 `@quality_reviewer`，传入 `第3章-初稿.md`，返回结构化评分和修改意见。

### 5.2 手动合规终审某一章

在项目目录中发送：

```
终审第3章
```

调用 `@compliance_*`（模式二），传入 `第3章-初稿.md`，返回平台合规检查结果。

### 5.3 手动生成章纲

在项目目录中发送：

```
生成第11章章纲
```

调用 `@plot_planner`，基于总纲领和已有章节节奏生成。

### 5.4 手动复盘

在项目目录中发送：

```
执行周期复盘
```

调用 `@data_operator`，分析 `04-数据/` 目录中的流量数据，生成复盘报告并更新总纲领。

---

## 六、完整操作流程示例

```powershell
# 第一步：进入工作根目录
cd D:\novel-editor
opencode

# 第二步：训练基准小说（如果 source.txt 已放置）
> 执行基准小说增量训练

# 第三步：创建衍生项目
> 创建新衍生小说：
> 基准原作：娘娘本纪
> 目标平台：番茄
> 风格赛道：都市

# 第四步：进入项目目录，启动写作
cd D:\novel-editor\workspace\books\娘娘本纪_salt_001_赘婿神医之都市风云
opencode

# 第五步：启动全自动写作流水线
> 全自动执行第1~10章生产
```

---

## 七、agent 速查表

### 全局 agent（根目录 `.opencode/agents/`）

| agent | 角色 | 模式 | 谁调用它 |
|-------|------|------|---------|
| `global_manager` | 总调度器 | Primary | 你（用户对话入口） |
| `original_analyst` | 原作拆解师 | Subagent | global_manager |
| `style_urban` | 都市赛道映射 | Subagent | global_manager |
| `style_xuanhuan` | 玄幻赛道映射 | Subagent | global_manager |
| `style_xianxia` | 仙侠赛道映射 | Subagent | global_manager |
| `style_romance` | 女频赛道映射 | Subagent | global_manager |
| `style_history` | 历史赛道映射 | Subagent | global_manager |
| `style_scifi` | 科幻赛道映射 | Subagent | global_manager |
| `style_suspense` | 悬疑赛道映射 | Subagent | global_manager |
| `facade_generator` | 门面信息生成器 | Subagent | global_manager |
| `salt_architect` | 盐值校验/去重 | Subagent | global_manager |
| `compliance_tomato` | 番茄合规专员 | Subagent | chief_editor |
| `compliance_qimao` | 七猫合规专员 | Subagent | chief_editor |

### 项目 agent（项目目录 `.opencode/agents/`，从模板复制）

| agent | 角色 | 模式 | 谁调用它 |
|-------|------|------|---------|
| `chief_editor` | 项目主编 | Primary | 你（项目内对话入口） |
| `plot_planner` | 剧情规划师 | Subagent | chief_editor |
| `content_writer` | 正文撰稿师 | Subagent | chief_editor |
| `quality_reviewer` | 质检编审 | Subagent | chief_editor |
| `data_operator` | 数据运营师 | Subagent | chief_editor |

---

## 八、目录结构总览

```
D:\novel-editor/                       # 工作根目录（全局任务启动点）
├── .opencode/
│   └── agents/                    # 全局 agent（13个）
│       ├── global_manager.md
│       ├── original_analyst.md
│       ├── style_*.md (x7)
│       ├── facade_generator.md
│       ├── salt_architect.md
│       └── compliance_*.md (x2)
│
├── project-agents-template/
│   └── .opencode/agents/          # 项目 agent 模板（创建新书时复制）
│       ├── chief_editor.md
│       ├── plot_planner.md
│       ├── content_writer.md
│       ├── quality_reviewer.md
│       └── data_operator.md
│
├── workspace/
│   ├── repo/                      # 原作基准库
│   │   ├── {原作名}/
│   │   │   ├── source.txt         # ← 手动放置
│   │   │   └── base_whitepaper.md # → 任务1自动生成
│   │   └── ...
│   │
│   └── books/                     # 衍生项目库
│       ├── {原作名}_salt_{编号}_{书名}/  # → 任务2自动创建
│       │   ├── project_salt.json  # → 任务2自动生成
│       │   ├── 仿写衍生总纲领.md   # → 任务3初始化时生成
│       │   ├── 01-大纲/
│       │   ├── 02-正文/
│       │   ├── 03-纪要/
│       │   ├── 04-数据/
│       │   └── .opencode/agents/  # ← 从 project-agents-template 复制
│       └── ...
│
└── ReadMe.md                      # ← 本文件
```

---

> 原则：全局任务（训练基准、创建新书）在根目录对话 `global_manager`；
> 项目任务（写作小说）在项目目录对话 `chief_editor`。
> 两个 Primary agent 各管各的，互不依赖。
