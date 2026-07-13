# P0/P1 Subagent → Skill 转换实施记录

> 日期：2026-07-10
> 范围：data_operator / compliance Mode 1 / input_monitor
> 目标：消除不必要的 subagent 生成开销，降低 token 消耗

---

## 一、转换清单

| 优先级 | 子代理 | → Skill | 编排者 | 节省效果 |
|--------|--------|---------|--------|----------|
| P0 | `data_operator` (25行, flash) | `data-operator` | `chief_editor` (flash) | 每 10 章省 1 次 subagent 生成 |
| P1 | `compliance_*` 模式一 (205行, flash) | `compliance-rule-query` | `automation_manager` (pro) | 每书 Phase 1 省 1 次 subagent 生成 |
| P1 | `input_monitor` (128行, flash) | `input-monitor` | `reviewer_orchestrator` (pro) | 每书 Phase 3 省 1 次 subagent 生成 |

---

## 二、新建文件

### 2.1 `.opencode/skills/data-operator/SKILL.md`

将原 `data_operator` subagent 的 25 行逻辑转换为可加载的 skill，包含：
- 输入输出约束（`04-数据/` + `03-纪要/` → 复盘报告）
- 调整指令规范（禁止模糊评价，必须直接对应创作动作）
- 复盘报告模板（数据总览 + 质量关联分析 + 创作调整指令 + 总纲更新条目）

### 2.2 `.opencode/skills/compliance-rule-query/SKILL.md`

将原 `compliance_tomato.md` 和 `compliance_qimao.md` 的模式一（规则查询）合并为一个 skill，内含：
- 番茄小说完整规则集 JSON（约 150 行，200+ 字段）
- 七猫小说完整规则集 JSON（约 150 行，200+ 字段）
- 由编排者按 `target_platform` 参数选择对应平台

> 注意：模式二（章节终审）仍使用原 `@compliance_*` subagent，未受影响。

### 2.3 `.opencode/skills/input-monitor/SKILL.md`

将原 `input_monitor` subagent 的 128 行检测逻辑转换为可加载的 skill，包含：
- `input_monitor.json` 数据格式说明
- 增长趋势检测逻辑（连续 3 章 > 10% 告警）
- 扣分规则（100 分起扣，含豁免条件）
- 评分档位和输出模板

---

## 三、修改文件

### 3.1 `automation_manager.md`

| 位置 | 修改前 | 修改后 |
|------|--------|--------|
| 权限(frontmatter) | 无 `skill` 声明 | `skill: "*": allow` |
| 串行保证(行29) | `compliance` | `[compliance-rule-query skill]` |
| Phase 1 步骤 b(行92-94) | `调用 @compliance_{平台}（模式一：规则查询）` | `加载 compliance-rule-query skill，根据 target_platform 输出` |

### 3.2 `chief_editor.md`

| 位置 | 修改前 | 修改后 |
|------|--------|--------|
| 权限(frontmatter) | 无 `skill` 声明 | `skill: "*": allow` |
| 章节循环末尾 | 无数据复盘步骤 | 新增 `3g. 数据复盘（每 10 章触发一次）`，加载 `data-operator` skill |

新增的 3g 步骤流程：
```
N 为 10 的倍数时触发
→ 加载 data-operator skill
→ 读取 04-数据/ + 03-纪要/
→ 生成 04-数据/第M-N章复盘报告.md
→ 根据调整指令更新 仿写衍生总纲领.md
```

### 3.3 `reviewer_orchestrator.md`

| 位置 | 修改前 | 修改后 |
|------|--------|--------|
| 权限(frontmatter) | 无 `skill` 声明 | `skill: "*": allow` |
| Step 1 表格(行44) | `@input_monitor` | `加载 input-monitor skill` |
| 评分汇总表(行83) | `input_monitor \| V4 Flash` | `input-monitor skill \| —` |

---

## 四、未删除的旧文件

以下 subagent 定义保留不动，原因：

| 文件 | 保留原因 |
|------|----------|
| `data_operator.md` | 后续确认无直接引用后可清理 |
| `compliance_tomato.md` | 模式二（章节终审）仍在使用 |
| `compliance_qimao.md` | 模式二（章节终审）仍在使用 |
| `input_monitor.md` | 后续确认无直接引用后可清理 |

---

## 五、验证方法

启动 OpenCode 后检查可用 skill 列表中是否包含新增的三个 skill：

```
compliance-rule-query / data-operator / input-monitor
```

分别在三层 workspace 中运行对应编排者，确认 skill 加载正常且输出结果与原有 subagent 一致。
