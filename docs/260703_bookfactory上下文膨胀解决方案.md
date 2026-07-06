# book_factory 上下文膨胀解决方案

> 日期：2026-07-03
> 关联：`docs/260703_bookfactory上下文膨胀问题总结.md`、`docs/260703_同书上下文膨胀问题解决方案分析.md`
> 状态：P0 已实施

---

## 根因回顾

方案 1+2（4 reviewer 写文件 + content_writer/quality_reviewer 薄返回）已实施但 dryrun 仍卡死在第 1 章。deep-dive 发现：

1. **book_factory Step 6 自己读了 57KB 白皮书** → 25K tokens 直灌上下文
2. **plot_planner 没有返回约束** → 卷纲 32KB + 章纲 21KB 可能原样返回
3. **style_mapper / salt_architect 返回完整 JSON** → 44KB + 55KB 固定开销
4. **bash 监控 stdout 每章累积** → 7K/章

旧版 (027cf95) 能跑是因为没有卷纲规划步骤、没有 reviewer、指令也短一半，总上下文 ~105K。新版因新增卷纲 + 指令翻倍 = +23K，精确压线 128K。

---

## 解决方案

### P0 — 堵死两个最大入口（已实施）

| # | 文件 | 改动 | 省 |
|:--:|------|------|:--:|
| 1 | `book_factory.md` | Step 6 委托子 agent `master_outline_generator`，不再自己 Read 白皮书 | 43K |
| 2 | `plot_planner.md` | 新增返回约束：写完文件后只返回 `✅ 第N章{卷/章}纲已生成` | 22K/章 |

**效果：book_factory 在 Step 8b 上下文 ~128K → ~63K。dryrun 安全。**

### P1 — 清理固定包袱（待实施）

| # | 文件 | 改动 | 省 |
|:--:|------|------|:--:|
| 3 | `style_mapper.md` | 自己 Write `赛道映射.json`，只返回路径 | 20K |
| 4 | `book_factory.md` Step 3 | 改为只传路径 | — |
| 5 | `salt_architect.md` | 自己 Write `project_salt.json`，只返回确认 | 25K |
| 6 | `book_factory.md` Step 5 | 改为只传路径 | — |

**效果：上下文 ~63K → ~18K。**

### P2 — 防每章累积（待实施）

| # | 文件 | 改动 | 省 |
|:--:|------|------|:--:|
| 7 | `book_factory.md` | bash 监控静默化 (`>/dev/null 2>&1`) | 7K/章 |
| 8 | `book_factory.md` | SOP 精简：模板文本提取或压缩 | 6K |

**效果：20 章仅需 ~58K，安全余量 70K。**

### P3 — 治本（长期）

| # | 改动 |
|:--:|------|
| 9 | 拆 book_factory 为三阶段独立 agent：`phase1_setup` / `phase2_planning` / `phase3_writing` |

---

## 实施状态

| 层级 | 状态 |
|:--:|:--:|
| P0 | ✅ 已实施 |
| P1 | ⬜ 待实施 |
| P2 | ⬜ 待实施 |
| P3 | ⬜ 长期规划 |
