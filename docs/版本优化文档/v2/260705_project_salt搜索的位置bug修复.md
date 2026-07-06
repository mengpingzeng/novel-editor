# project_salt.json 搜索路径 bug 修复

**日期**: 2026-07-05  
**问题**: Phase 2 执行时，agent 在项目根目录寻找 `project_salt.json` / `仿写衍生总纲领.md`，但文件实际位于 `versions/{version}/` 子目录  
**影响范围**: 所有 Phase 2 执行（`chief_editor`、`plot_planner`、`quality_reviewer`、`content_writer`）

---

## 问题描述

执行 `bash scripts/run_pipeline.sh step` 时，Phase 2 的 `chief_editor` 报错：

```
Error: File not found: /mnt/data/novel-editor/workspace/books/凡人修仙传/project_salt.json
```

而实际文件位于：
```
workspace/books/凡人修仙传/versions/v2/project_salt.json
workspace/books/凡人修仙传/versions/v2/仿写衍生总纲领.md
```

## 根因分析

本项目存在两套不同的项目结构约定：

| | Flow 1（global_manager） | Flow 2（automation_manager / pipeline） |
|---|---|---|
| Salt 位置 | `$PROJECT_DIR/project_salt.json` | `versions/{version}/project_salt.json` |
| 总纲领位置 | `$PROJECT_DIR/仿写衍生总纲领.md` | `versions/{version}/仿写衍生总纲领.md` |
| 子目录 | `01-大纲/`、`02-正文/` 在根目录 | `versions/{version}/01-大纲/` 等 |

Pipeline 脚本使用 **Flow 2**（通过 `automation_manager`），Phase 1 将产物写入 `versions/v2/` 子目录。但 Phase 2 的 agent prompt 参考了 **Flow 1** 的路径约定，所有文件引用均为项目根目录下的相对路径（如 `./project_salt.json`、`./仿写衍生总纲领.md`、`./01-大纲/`）。

`chief_editor` 虽然在其初始化 SOP 中已经扫描 `versions/` 取最新版本号，但随后并未使用该版本号去组装文件路径。

## 修改方案

将所有 Phase 2 agent 的 prompt 中的文件路径从根目录相对路径改为版本子目录相对路径，使用 `{version}` 占位符表示由 agent 在运行时确定的版本号。

### 修改文件清单

| Agent | 模板路径 | 部署路径（5 本书） |
|-------|---------|------------------|
| `chief_editor.md` | `project-agents-template/.opencode/agents/chief_editor.md` | `workspace/books/{书名}/.opencode/agents/chief_editor.md` |
| `plot_planner.md` | `project-agents-template/.opencode/agents/plot_planner.md` | `workspace/books/{书名}/.opencode/agents/plot_planner.md` |
| `quality_reviewer.md` | `project-agents-template/.opencode/agents/quality_reviewer.md` | `workspace/books/{书名}/.opencode/agents/quality_reviewer.md` |
| `content_writer.md` | `project-agents-template/.opencode/agents/content_writer.md` | `workspace/books/{书名}/.opencode/agents/content_writer.md` |

### 具体改动

#### chief_editor.md

- `./project_salt.json` → `versions/{version}/project_salt.json`
- `./仿写衍生总纲领.md` → `versions/{version}/仿写衍生总纲领.md`
- 初始化 SOP 中：先确定版本号，再读取文件（原顺序为先读文件再确定版本号）
- 新增读取基准白皮书路径：`versions/{version}/00-素材/base_whitepaper.md`
- 子 agent 调用传入路径改为版本化路径
- 所有输出目录（`01-大纲/`、`02-正文/`、`03-纪要/`）加版本前缀

#### plot_planner.md

- 【强制输入输出约束】节中所有路径加 `versions/{version}/` 前缀
- `volume_rhythm_profile` 读取路径改为 `versions/{version}/project_salt.json`
- 爽点轮换检查、金手指变体检查中的 salt 读取路径改为版本化
- 总纲领路径引用改为版本化

#### quality_reviewer.md

- 【强制输入输出约束】节中所有路径加 `versions/{version}/` 前缀
- `fingerprint_variation_table` 读取路径改为 `versions/{version}/project_salt.json`
- 正文目录、纪要目录引用全部版本化

#### content_writer.md

- 【强制输入输出约束】节中所有路径加 `versions/{version}/` 前缀
- rewrite 模式中的纪要路径改为版本化

### 运行时行为

agent 在运行时仍遵循与修改前一致的工作流程：
1. `chief_editor` 扫描 `versions/` 确定最新版本号
2. 用该版本号组装所有文件路径（`versions/{version}/...`）
3. 子 agent 从 `chief_editor` 接收版本化路径作为参数

## 影响的书籍

已批量更新 5 本书的部署 agent：
- 凡人修仙传
- 斗破苍穹
- 甄嬛传
- 白夜行
- 赘婿
