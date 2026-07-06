# `/iterate step` 卡住分析报告

日期：2026-07-06

---

## 1. `/iterate step` 的流程

`/iterate step` 触发 `automation_manager`（Phase 1 框架层），按 `iteration-state.json` 中的 `active_books` 列表，逐本执行：

```
原作拆解 → 平台规则 → 赛道映射 → 门面生成 → 盐值校验 → 总纲生成 → 写入 .phase1_done
```

完成后**应停止**，不自动进入 Phase 2。Phase 2（写书）和 Phase 3（审稿）需手动分步执行。

---

## 2. 卡住的原因（证据链）

### 问题一：`phase` 字段被改为 `"writing"`

**文件**：`workspace/iteration-state.json:3`

```json
"phase": "writing"
```

但 `automation_manager` 的规范（`.opencode/agents/automation_manager.md`）定义的是 `"phase": "phase1"`。

**证据**：备份文件 `workspace/.iteration-state.json.bak.20260705-124709` 中 `phase` 是 `"phase1"`，之后被人为改成了 `"writing"`。

**影响**：LLM 看到 `"writing"` 会误以为自己该执行写书（Phase 2）任务，而不是只做框架生成（Phase 1），导致它无法正确判断终止条件，持续消耗 token。

---

### 问题二：版本号不一致

| 书名 | state 中的 version | `.phase1_done` 中的 version | `versions/` 目录 |
|------|-------------------|----------------------------|-------------------|
| 斗破苍穹 | v1 | v2 | v1, v2 |
| 甄嬛传 | v1 | v2 | v1, v2 |
| 白夜行 | v1 | v2 | v1, v2 |

`automation_manager` 的版本递增逻辑会检测到 `versions/` 下有 v2 目录，算出新版本号为 v3。但 `.phase1_done` 已经是 v2，且 `state` 中记录为 v1——三者矛盾导致 agent 可能反复尝试重新生成。

---

### 问题三：`白夜行` 的 `"writing"` 状态是残留的

`白夜行` 的状态 `"writing"` 是从 **V1 旧系统（book_factory）** 遗留下来的。

**证据**：`workspace/books/白夜行/versions/v1/execution-log.md` 最后一条记录：

```
| 2026-07-04 12:22:00 | 第3章初稿 | content_writer | ... | 进行中 |
```

V1 系统在写第3章初稿时卡住了（`进行中`），这个 `"writing"` 状态从未被清理，一直带到 V2 的 `iteration-state.json` 中。

---

### 问题四：`automation_manager` 没有跳过已完成书籍的逻辑

`automation_manager.md` 规范中，仅对 `base_whitepaper.md` 存在时做了跳过（第71行）：

```
a. 原作拆解：调用 @original_analyst...
   - 若 workspace/repo/{source_name}/base_whitepaper.md 已存在 → 跳过
```

但对已经存在 `.phase1_done` 的整本书没有跳过逻辑。这意味着即使 Phase 1 全部完成，再次运行时它仍会从头处理所有 5 本书，每本都重新走一遍完整 pipeline。

---

### 问题五：`active_books` 被扩容 + Phase 2 进程并行运行

**备份**（12:47:09）中 `active_books` 仅 1 本（凡人修仙传），当前版本（17:07:02）扩容为 5 本，是手动修改的结果。

同时，`chief_editor`（Phase 2）进程被独立启动：

| 书 | Phase 2 状态 | 日志文件 |
|----|-------------|---------|
| 凡人修仙传 | 5章全部完成 | `versions/v2/自动化处理日志.md` |
| 斗破苍穹 | 卡在第3章初稿 | `versions/v2/自动化处理日志.md` — `进行中` |
| 赘婿 | 卡在第1卷卷纲后 | `versions/v2/自动化处理日志.md` |
| 白夜行 | 未启动 | `versions/v2/02-正文/` 为空 |
| 甄嬛传 | 未启动 | 无 Phase 2 产物 |

`content_writer` / `quality_reviewer` 子 agent 在生成章节草稿时可能陷入重写循环（质检不通过 → 重写 → 仍不通过 → 再重写），持续消耗 token。

---

## 3. 当前状态汇总

**Phase 1（框架层）**：全部完成

```
凡人修仙传 .phase1_done v2  2026-07-05 17:07:05
斗破苍穹   .phase1_done v2  2026-07-05 13:04:19
甄嬛传     .phase1_done v2  2026-07-05 13:23:42
白夜行     .phase1_done v2  2026-07-05 13:49:41
赘婿       .phase1_done v2  2026-07-05 17:07:07
```

**Phase 2（内容层）**：仅凡人修仙传完成，斗破苍穹和赘婿卡住

---

## 4. 建议修复方向

1. **修正 `iteration-state.json`**：将 `phase` 改回 `"phase1"`（或 Phase 1 完成后改为 `"phase1_done"`），统一 version 为 v2
2. **清理白夜行的残留状态**：将白夜行的 `status` 从 `"writing"` 改为 `"pending"` 或与 Phase 1 完成状态一致
3. **给 `automation_manager` 增加跳过逻辑**：在处理每本书之前检查 `.phase1_done` 是否存在，若存在且 version 匹配则跳过
4. **终止卡住的 Phase 2 进程**：斗破苍穹和赘婿的 `chief_editor` 进程需要单独处理（kill 进程 + 清理中间状态）
