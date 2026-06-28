# 目录结构

novel_workflow_demo/                  # 工作根目录（全局任务在此启动）
├── opencode.json                  # 根目录配置：指定全局代理目录+默认主代理
├── .opencode/
│   └── agents/                    # 全局公共代理（根目录级，处理基准训练、创建新书）
│       ├── global_manager.md      # 全局调度主代理（Primary）
│       ├── original_analyst.md    # 原作分析师
│       ├── salt_architect.md      # 盐值架构师
│       ├── style_urban.md         # 都市风格专员
│       ├── style_xuanhuan.md      # 玄幻风格专员
│       ├── compliance_tomato.md   # 番茄合规专员
│       └── compliance_qimao.md    # 七猫合规专员
│
├── project-template/              # 衍生小说项目模板（创建新书时复制）
│   ├── opencode.json              # 项目级配置模板
│   └── .opencode/
│       └── agents/                # 项目写作流水线代理模板
│           ├── chief_shturl.cc    # 项目主编（Primary）
│           ├── plot_planner.md    # 剧情规划师
│           ├── content_writer.md  # 正文撰稿师
│           ├── quality_reviewer.md# 质检编审
│           └── data_operator.md   # 数据运营师
│
└── workspace/
    ├── repo/                      # 全局原作基准库
    │   ├── novel_a/
    │   │   ├── source.txt
    │   │   └── base_whitepaper.md
    │   └── novel_b/
    └── books/                     # 所有衍生小说项目（自动创建）
        ├── novel_a_salt_001/      # 从 project-template 完整复制而来
        │   ├── opencode.json
        │   ├── project_salt.json
        │   └── .opencode/
        │       └── agents/        # 本项目专属代理
        └── novel_a_salt_002/

# 任务 1：增量训练基准小说

在 novel_workflow_demo 根目录启动：
```
执行基准小说增量训练
```

# 任务 2：创建新衍生小说

在根目录的 OpenCode 会话中发送：

```
创建新衍生小说：
基准原作：娘娘本纪
风格赛道：都市
盐值编号：001
目标平台：番茄
```

# 任务 3：写作小说

进入项目目录启动：

```
cd novel_workflow_demo/books/娘娘本纪_salt_001
opencode
```

发送指令：
```
全自动执行第1~10章生产
```