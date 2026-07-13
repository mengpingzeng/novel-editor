# automation_manager / master_outline_generator 对齐 global_manager 分析

> 分析范围：仅限脚本路径（`run_pipeline.sh` → `automation_manager` → `@master_outline_generator`），不涉及 global_manager 的交互式路径。

---

## 一、背景

| Agent | 定位 | 当前状态 |
|-------|------|---------|
| **global_manager** | 交互式全局管理：手动创建衍生项目、训练基准小说 | 流水线中**零调用**，仅手动交互时使用 |
| **automation_manager** | 批量 Phase 1 编排器：逐书生成框架产物 | 流水线实际入口，被 `run_pipeline.sh` 调用 |
| **master_outline_generator** | 子 agent：基于白皮书+平台规则生成《仿写衍生总纲领》 | 从 global_manager 第 7d 节内联逻辑拆出，由 automation_manager 调用 |

`master_outline_generator` 的设计意图是：将 global_manager 内联的总纲生成逻辑提取为独立 subagent，供自动化路径复用。但拆分时遗留了输入缺失和 SOP 降级问题。

---

## 二、当前脚本链数据流

```
automation_manager 步骤:
  b. @compliance_{平台}（模式一）→ 返回 JSON（上下文传递，不落盘）
  c. @style_mapper           → 赛道映射.json → 00-素材/
  d. @facade_generator       → 门面候选.json → 00-素材/
  e. @salt_architect         → project_salt.json → versions/{ver}/
  f. @master_outline_generator → 仿写衍生总纲领.md
       ↑ 输入1: whitepaper_path           ✅ 存在
       ↑ 输入2: platform_rules            ❓ 步骤b 返回了 JSON 但未落盘，无法从文件读取
       ↑ 输入3: master_outline_path       ✅ 已知
       ↑ 输入4: source_name/platform/track ✅ 已知
       ↑ 缺失: 门面候选.json 路径           — 无人传入
       ↑ 缺失: project_salt.json 路径       — 无人传入
```

步骤 f 调用时，步骤 b/c/d/e 的产出都已落盘，但只传了 4 个参数，漏了 2 个关键文件路径。

---

## 三、三处缺失

### ③ 缺 1：上游未落盘平台规则

`automation_manager.md` 步骤 b 调用 `@compliance_{平台}`（模式一）获取平台规则集 JSON，但规则仅在上下文传递，**未写入任何文件**。master_outline_generator 读取的是文件而非上下文，因此拿不到 `platform_rules`。

### ① 缺 2：master_outline_generator 输入定义不完整

`master_outline_generator.md` 第 12-17 行定义的 4 个输入，遗漏了：

| 缺失输入 | 用途 | 来源 |
|---------|------|------|
| `facade_path` | 读取书名(book_title)、简介(book_blurb)、一句话梗概(tagline) | 步骤 d 产出的 `00-素材/门面候选.json` |
| `salt_path` | 读取 classification.tags、tag_constraints、pleasure_rotation、prohibited_changes 等 | 步骤 e 产出的 `project_salt.json` |

这导致总纲第一节"书名与简介"只能写"占位"，第三节"分类标识"无法填充标签约束。

### ② 缺 3：SOP 指令过于简略

对 global_manager 7d 内联模板（10 节），master_outline_generator 的 SOP（59 行）丢失了以下执行细节：

| 总纲章节 | global_manager 内联有的 | master_outline_generator 当前没有 |
|---------|------------------------|----------------------------------|
| 二、平台适配 | 字数融合计算公式 `(optimal_min+optimal_max)/2` + 浮动范围 `(max-min)/2` + 融合理由记录 | 只有均值计算，无浮动范围、无理由记录 |
| 二、平台适配 | 合规专员来源 `"{专员名称}规则集v{版本}"` | 无此概念 |
| 二、平台适配 | 内容红线**逐条列出** | 只写"content_red_lines：内容红线" |
| 二、平台适配 | 排版要求、钩子要求逐条提取 | 无 |
| 三、分类标识 | tags 及 tag_constraints **逐条展开** | 有提及但无填充模板 |
| 四~九 | 明确"继承白皮书某章节 + 叠加盐值某字段"的映射关系 | 只有"继承+叠加"模糊指令，无章节级映射指引 |
| 末尾 | 版本号 `v1.0` + 生成日期标注 | 无 |

---

## 四、对齐方案

### 步骤 A：automation_manager 步骤 b 增加平台规则落盘

步骤 b 调用 compliance agent 返回 JSON 后，写入 `00-素材/platform_rules.json`，使 downstream agent 可通过文件路径读取。

### 步骤 B：master_outline_generator 增加两个输入参数

```diff
- 输入2：platform_rules — 平台规则集全文（必填，由调用方传入）
+ 输入2：platform_rules_path — 平台规则 JSON 文件路径（从文件读取）

+ 输入5：facade_path — 门面候选 JSON 文件路径
+ 输入6：salt_path — project_salt.json 文件路径
```

### 步骤 C：master_outline_generator SOP 补充模板填充指引

将 global_manager 内联第 7a/7b/7c 三步（读白皮书→读规则→融合计算）的字段级操作迁移到 SOP 中，确保每节有明确的**数据来源+填充格式**指引。

### 步骤 D：automation_manager 步骤 f 调用时传入补全的参数

```bash
@master_outline_generator
  whitepaper_path=workspace/repo/{source_name}/base_whitepaper.md
  platform_rules_path=workspace/books/{source_name}/versions/{version}/00-素材/platform_rules.json
  master_outline_path=workspace/books/{source_name}/versions/{version}/仿写衍生总纲领.md
  facade_path=workspace/books/{source_name}/versions/{version}/00-素材/门面候选.json
  salt_path=workspace/books/{source_name}/versions/{version}/project_salt.json
  source_name/platform/track={元信息}
```

---

## 五、对齐后的关系图

```
run_pipeline.sh
  └── automation_manager（批量入口，仅脚本调用）
        ├── @original_analyst         → base_whitepaper.md
        ├── @compliance_{平台}        → platform_rules.json（新增落盘）
        ├── @style_mapper             → 赛道映射.json
        ├── @facade_generator         → 门面候选.json
        ├── @salt_architect           → project_salt.json
        └── @master_outline_generator → 仿写衍生总纲领.md
              ↑ 从此可读取全部上游产出，产出对齐 global_manager 7d 质量

global_manager（交互入口，保留不动）
  → 不参与脚本路径，不受本次优化影响
```

---

## 六、关键结论

### 对齐后 automation_manager 是否完全替代 global_manager？

**不完全是。** 两者各有独立入口和适用场景：

| 维度 | automation_manager（脚本路径） | global_manager（交互路径） |
|------|-------------------------------|---------------------------|
| 调用方式 | `run_pipeline.sh step` 或 `/iterate step` | 用户手动运行 `opencode` |
| 人机交互 | 无人值守，自动选 rank=1 门面 | 用户从 5 组候选中选择、手动输入参数 |
| 盐值编号 | 不产生 salt_id，用 version 管理 | 扫描已有目录，自动分配 salt_001/002/... |
| 项目目录 | `{书名}/versions/{ver}/` | `{原作}_salt_{编号}_{书名}/` |
| 赛道 agent | 统一用 @style_mapper（参数化） | 按赛道分别路由到 7 个 @style_* 专项 agent |
| 批量能力 | 遍历 active_books，串行执行 | 无，每次只处理一本 |

对齐优化后：
- **总纲输出内容对齐**，两者的《仿写衍生总纲领.md》结构一致、质量一致
- **但角色不重叠**：automation_manager 是批量的、脚本驱动的；global_manager 是交互的、用户驱动的
- **两套项目目录结构仍然不同**（scripts 路径 vs 手动路径），这是一个独立问题

### 真正的"完全替代"需要额外处理

如果要让 automation_manager **成为唯一的 Phase 1 入口**（替代 global_manager 的 Task 2），还需要：
1. automation_manager 支持交互模式（展示 facade 候选、等待用户选择）
2. 统一项目目录结构（`_salt_` 命名 vs `versions/` 结构二选一）
3. 统一赛道代理路由策略（style_mapper vs style_* 专项 agent）

但这超出了"对齐总纲质量"的范畴，属于架构统一问题。
