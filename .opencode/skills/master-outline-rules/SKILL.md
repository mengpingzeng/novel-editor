---
name: master-outline-rules
description: 仿写衍生总纲生成规则——融合计算、10节模板、差异化约束表、质量铁律
---

你是仿写衍生总纲生成专家。基于基准白皮书、平台规则、门面信息、项目盐值，生成一份完整的《仿写衍生总纲领》。

---

## 一、字数融合计算

```
目标字数 = (optimal_min + optimal_max) / 2，取整
允许浮动 = (optimal_max - optimal_min) / 2，取整
```

记录融合公式到总纲第二节元数据字段。

---

## 二、10 节总纲结构模板

写入 `master_outline_path`，严格按以下结构，每节必须从对应输入文件提取数据填充，**禁止写"占位"或"_____"**。

### 第 1 节：书名与简介

数据来源：facade_path

```
# 《{book_title}》仿写衍生总纲领

## 一、书名与简介
- 书名：{book_title}
- 备选书名：{book_title_alt}
- 一句话梗概：{one_line_tagline}
- 简介：{book_blurb}
```

### 第 2 节：平台适配

数据来源：platform_rules_path + §1 融合计算

```
## 二、平台适配
- 目标平台：{platform}
- 合规专员来源：{platform}合规专员规则集 v{version}
- 字数标准：目标 {目标字数} 字，允许浮动 ±{允许浮动} 字
- 字数来源：{platform}规则集 v{version} + 白皮书节奏模型融合计算
- 内容红线：（逐条列出 content_red_lines）
- 排版要求：{formatting 原文}
- 钩子要求：{hook_requirement 原文}
- 开篇要求：{first_chapters_requirement，如无则省略}
- 对话占比要求：{dialogue_ratio，如无则省略}
```

### 第 3 节：分类标识

数据来源：salt_path → classification

```
## 三、分类标识
- 一级分类：{primary_category}
- 平台标签：{platform_label}
- 核心标签：{tags 列表}
- 标签约束：（逐条列出 tag_constraints）
- 风格取向：{style_orientation}
- 受众匹配：{audience_match}
```

### 第 4 节：世界观框架

数据来源：whitepaper_path §二 + salt_path → world_mapping
- 继承白皮书§二内容，保留 {底层逻辑} + 替换 [表层变量]
- 叠加盐值 world_mapping

### 第 5 节：角色系统

数据来源：whitepaper_path §三 + salt_path → character_mapping
- 继承白皮书§三（主角 {底层逻辑} + [表层变量]、配角表、反派层级）
- 叠加盐值 character_mapping

### 第 6 节：爽点体系

数据来源：whitepaper_path §四 + salt_path → pleasure_point_model / pleasure_rotation / anti_similarity
- 继承白皮书§四（爽点公式+频率统计）
- 叠加盐值 pleasure_point_model / pleasure_rotation
- 差异化声明来自 anti_similarity.pleasure_diff

### 第 7 节：节奏模型

数据来源：whitepaper_path §五 + salt_path → volume_rhythm_profile / chapter_rhythm / anti_similarity
- 继承白皮书§五
- 叠加盐值 volume_rhythm_profile / chapter_rhythm
- 差异化声明来自 anti_similarity.rhythm_diff

```
## 七、节奏模型
- 五段式结构占比：{从白皮书§五提取}
- 赛道节奏签名：{从 volume_rhythm_profile.pacing_signature 提取}
- 高潮间隔规律：小高潮每_{N}_章 / 大高潮每_{M}_章
- 章节类型占比：日常_{X}% / 冲突酝酿_{Y}% / 高潮_{Z}% / 过渡_{W}%
- 节奏差异声明（来自 anti_similarity.rhythm_diff）
```

### 第 8 节：文风句式

数据来源：whitepaper_path §六 + salt_path → writing_style

```
## 八、文风句式

### 8.1 量化指标
- 平均句长、对话占比、段落密度

### 8.2 句式模式库
（从白皮书§6.9提取 5-8 种句式，逐条列出结构/场景/效果/替换规则）

### 8.3 社会语言层次模型
（从白皮书§6.5提取权力语言梯度表）

### 8.4 角色语言指纹库
（从白皮书§6.6提取角色×5维指纹表 + 主角-反派对比）
```

### 第 9 节：剧情模板

数据来源：whitepaper_path §七 + salt_path → plot_templates / anti_similarity

```
## 九、剧情模板
- 卷级剧情范式（起承转合模板）：仅描述形式结构
- 章节批级剧情单元模板：仅描述节奏排列模式

⚠️ 本节硬约束：
  · 禁止包含任何具体角色姓名
  · 禁止包含任何具体事件描述
  · 禁止包含具体章节编号
  · 禁止包含具体场景/地点名称
  · 正确示例：「埋梗章→酝酿章→小高潮章→过渡章→大高潮章」
  · 错误示例：「第N章拍卖会主角偶遇宿敌→...」
```

### 第 10 节：禁止改动底层逻辑清单与写作禁止清单

数据来源：salt_path → prohibited_changes + whitepaper_path §六 + platform_rules_path

```
## 十、禁止改动底层逻辑清单与写作禁止清单

### 10.1 底层逻辑禁止改动（来源：salt prohibited_changes）
逐条提取，不可合并、不可缩写

### 10.2 写作禁止清单（来源：白皮书 §六 + 平台规则集）
逐条列出，每条必须包含四部分：[规则] + [量化阈值] + [✅ 正例] + [❌ 反例]
禁止项示例：
| # | 规则 | 量化阈值 | ✅ 正例 | ❌ 反例 |

### 10.3 赛道级禁止模式（来源：salt forbidden_patterns，如有）
```

§10 输出铁律：
- §10.2 每一条必须包含 [规则] + [量化阈值] + [✅ 正例] + [❌ 反例] 四部分
- "少内心独白"必须改写为"内心独白占比 ≤15%（约300字/章）"
- "适配移动端"必须改写为"段落长度 80-150 字（3-5句）"
- 任何开放式判断词必须附属量化阈值

---

## 三、末尾标注

总纲末尾必须包含：
```
版本：v1.0 | 生成日期：{当前日期}
```

---

## 四、质量铁律

1. **禁止占位**：任何一节不得出现"占位""_____""待补充""详见后续"等字样
2. **逐条展开**：标签约束、内容红线、禁止改动清单必须逐条列出，不可合并
3. **数据有源**：每一节的内容必须能从输入文件中追溯到具体章节/字段
4. **继承+叠加**：白皮书内容作为基线（继承），盐值内容作为差异（叠加）
5. **差异化可见**：anti_similarity 中的三条差异声明必须体现到对应的总纲章节中
6. **§10 正反例强制**：§10.2 每条禁止项必须包含 [✅ 正例] + [❌ 反例] 对照
7. **模糊表述量化**：凡出现"少""多""合适""自然""足够"等词，必须附属量化阈值

---

## 五、差异化约束表生成规则

本步骤在总纲全部 10 节生成完毕后执行。核心变动：从卷级升级为 phase 级（~120 行）。

### 5.1 预检算法

对每个 phase：
a. 提取原著事件类型序列（从白皮书 §一 对应章节区间）
b. 提取仿写事件类型预期序列（从本总纲 §九 + 盐值 core_diff）
c. 逐位比对计分：
   - 同一位置事件类型相同 + 角色功能相同 → 标记"同构"，计 1 次重叠
   - 事件类型相同但角色功能不同 → 标记"近似"，计 0.5 次重叠
   - 事件类型不同 → 标记"偏离"，不计重叠
   - 仿写引入原著没有的事件类型 → 标记"新增"，计 -1 次（奖励差异化，抵扣不超过 phase 章节数的 20%）
d. 计算重叠率：重叠次数 / phase 内章节数
e. 判定：

| 重叠率 | 判定 | 行为 |
|:---:|:---:|:---|
| < 20% | ✅ SAFE | 差异化充分，写入基础禁止清单 |
| 20-35% | ⚠️ CAUTION | 中度重叠，至少 1 条禁止事件映射 + 1 条强制新事件 |
| 35-50% | 🔴 DANGER | 高度重叠，≥2 条禁止映射 + ≥2 条强制新事件 + danger=true |
| > 50% | ❌ PRE-FAIL | 降级为 50%，标注"需人工复核的 phase" |

### 5.2 约束表 JSON Schema

```json
{
  "version": "2.0",
  "base_novel": "{白皮书的书名}",
  "derivative_novel": "{门面中的书名}",
  "phase_differentiation": [
    {
      "volume": 1,
      "phase_index": 0,
      "phase_name": "{盐值 phases[0].name}",
      "chapter_range": "Ch1-Ch9",
      "original_event_type_sequence": ["..."],
      "expected_derivative_event_type_sequence": ["..."],
      "overlap_rate": "{0.0~1.0}",
      "overlap_assessment": "{SAFE/CAUTION/DANGER/PRE-FAIL}",
      "ban_forbidden_event_mapping": ["..."],
      "required_new_event_types": ["..."],
      "required_min_overlap_rate": "{数值}",
      "differentiation_dimensions": ["..."],
      "high_risk_original_nodes": ["..."],
      "danger": "{true/false}",
      "notes": "{提醒}"
    }
  ],
  "global_constraints": {
    "max_consecutive_similar_events": 3,
    "opening_differentiation_bonus": "前5章差异度应≥30%，10章后应≥50%",
    "forbidden_direct_mappings": ["至少 3 条"],
    "writer_note": "{PRE-FAIL phase 列表 + 全局提醒}"
  },
  "differentiation_escalation": "前5章差异度≥30%，10章后≥50%，30章后建立独立剧情生态"
}
```

### 5.3 关键约束

1. Phase 级粒度：`phase_differentiation` 条目数 = 全书总 phase 数，每 phase 逐条填充
2. 差异化必须可验证：`differentiation_dimensions` 中的每条差异必须能在 downstream 被验证
3. 禁止性约束优先：先告诉下游"不要做什么"
4. 预检嵌入约束表：overlap_rate + overlap_assessment + danger 标记随表传递
5. 完成后确认：约束表文件写入、phase 条目数匹配、ban/required 与 overlap_assessment 匹配
