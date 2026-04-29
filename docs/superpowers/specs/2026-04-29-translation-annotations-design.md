# 翻译注释与脚注层设计

## 背景

真实 5 万字测试中，审校发现“一个小目标”初译为 `A small target` 会丢失“一亿元”的文化梗义。这个问题不完全属于术语表，也不应该直接污染译文正文。译文应保持自然流畅，解释性信息应作为独立阅读辅助出现。

本设计新增一层独立的翻译注释层，用于解释中文俚语、文化梗、专有词、门派/制度/道具、计量与金额梗等内容。注释层不改变译文 active version，不改变 glossary entry 的翻译约定，只在 inspect/export 中作为可选信息输出。

## 目标

1. 注释独立存储，不写入译文正文，不改变 `SegmentTranslationVersion.translated_text`。
2. 同一概念在项目内保持一致解释，避免同一中文词条出现多套脚注口径。
3. 支持自动候选、审校线索和人工锁定三种来源。
4. 导出时支持脚注或章节尾注，并在 `manifest.json` 中结构化保留。
5. 第一版只服务文本导出与 inspect，不引入前端 UI。

## 非目标

- 不把所有 glossary note 自动变成脚注。
- 不把脚注插入 translation prompt 作为翻译硬约束。
- 不做人工审核界面。
- 不做跨项目全局注释库。
- 不对历史导出做自动回填。

## 核心概念

### Annotation

Annotation 是项目内可复用的注释定义，表示“这个中文概念应该如何向读者解释”。

关键字段：

- `project_id`
- `source_anchor`：原文锚点，例如 `一个小目标`
- `target_anchor`：译文锚点，例如 `one hundred million`
- `annotation_type`：`idiom / cultural_reference / proper_noun / worldbuilding / item / organization / measurement_money / pun / other`
- `canonical_key`：项目内稳定一致性键，例如 `idiom:一个小目标`
- `explanation`：目标语言解释文本
- `status`：`candidate / approved / rejected`
- `locked`：人工锁定标记
- `source`：`llm_annotation / glossary / review_issue / manual`
- `evidence_payload`：原文证据、译文证据、章节、分片、模型信息等 JSON

### Annotation Occurrence

Occurrence 是注释在具体译文版本中的一次出现位置，负责连接注释定义与 segment/version。

关键字段：

- `annotation_id`
- `project_id`
- `chapter_id`
- `segment_id`
- `version_id`
- `source_anchor`
- `target_anchor`
- `source_start / source_end`
- `target_start / target_end`
- `display_order`

第一版允许 `target_start / target_end` 为空，因为译文锚点定位可能受重译影响。导出时可先按 `target_anchor` 字符串查找插入脚注引用；找不到时降级为章节尾注。

## 一致性规则

1. `project_id + canonical_key` 唯一。
2. 同一 `canonical_key` 已有 `approved` 或 `locked` 注释时，自动生成只能复用，不允许创建不同解释。
3. `locked=true` 的注释不能被自动流程覆盖。
4. 若新候选与已有 approved 注释解释不同，保留为 `candidate`，并写入 `conflict_with_annotation_id`。
5. 同一译文版本中，同一 annotation 只渲染一次脚注引用；同章重复出现时只生成一次脚注正文。
6. 脚注解释使用目标语言，证据和内部审计字段可以保留中文原文。

## 数据流

### 1. 候选生成

新增 `annotation.extract` 服务，运行在 translation/review 之后。它读取：

- 当前 active translation version
- 当前 segment 原文
- 命中的 glossary entries
- 最新 review issues
- 已有 approved/locked annotations

LLM prompt 要求只返回 JSON，不返回 Markdown。候选必须包含：

- 原文锚点
- 译文锚点
- 类型
- 解释
- 为什么需要注释
- 是否复用已有 canonical key

### 2. 归一化与一致性合并

服务端负责生成或校验 `canonical_key`。归一化规则：

- 默认格式：`{annotation_type}:{source_anchor}`
- source anchor 去除首尾空白，保留中文原形
- 对金额/计量类可额外归一到语义键，例如 `measurement_money:一个小目标`

已有 `approved/locked` 注释优先。候选如果 source anchor 相同但类型不同，先归入 `other` 冲突候选，不自动覆盖。

### 3. 导出渲染

`manifest.json` 增加：

```json
{
  "annotations": [
    {
      "id": 1,
      "canonical_key": "idiom:一个小目标",
      "source_anchor": "一个小目标",
      "target_anchor": "one hundred million",
      "annotation_type": "idiom",
      "explanation": "A Chinese internet meme meaning one hundred million yuan.",
      "occurrences": [
        {
          "chapter_index": 3,
          "segment_index": 1,
          "version_id": 163
        }
      ]
    }
  ]
}
```

`export.md` 第一版采用章节尾注，避免当前 fenced code block 破坏 Markdown 原生脚注渲染。格式示例：

````markdown
#### 译文

```text
Teng Yuan said solemnly, “A small target—one hundred million. What do you think?”
```

#### 注释

- [1] 一个小目标 / one hundred million：A Chinese internet meme meaning one hundred million yuan.
````

后续如果导出格式改为非 fenced 正文，可再支持原生 Markdown 脚注 `[^ch3-1]`。

## 与 glossary 的关系

glossary 负责“怎么翻译”，annotation 负责“读者为什么需要解释”。两者可以互相引用，但不互相覆盖。

允许的联动：

- glossary entry 的 `note` 可作为 annotation 候选上下文。
- annotation 可记录 `glossary_entry_id` 到 evidence payload。
- translation prompt 继续只注入 glossary，不注入 annotation。

禁止的联动：

- 不把 annotation explanation 写回 glossary note。
- 不用 annotation 自动改写 target term。
- 不因 annotation 变化刷新 glossary snapshot。

## 与 review 的关系

review issue 可以成为 annotation 候选来源。例如“一个小目标”的问题如果已通过重译修复，仍可生成一个 `idiom` 注释，解释这个表达的背景。

review 仍负责判断是否需要重译；annotation 负责解释已接受译文中的文化信息。

## CLI 与 inspect

新增动作：

- `annotation.extract`
- `annotation.inspect`
- `annotation.approve`
- `annotation.reject`

第一版 stage 不强制把 annotation 纳入 `project.run_full`。用户可以在 review 之后手动运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run.ps1 `
  -Action annotation.extract `
  -ProjectId 17 `
  -ScopeType chapter_range `
  -ScopeStart 1 `
  -ScopeEnd 14 `
  -ModelProfileId gpt_5_5_aicodelink `
  -RequestId annotation-lingjing-5w
```

`export` 默认包含 `approved` 注释；可通过参数选择是否包含 `candidate` 注释。第一版默认只导出 `approved`，避免模型候选污染正式产物。

## 存储设计

新增两张表：

- `ltw_annotations`
- `ltw_annotation_occurrences`

`ltw_annotations` 约束：

- `project_id + canonical_key` 唯一
- `status` 限定为 `candidate / approved / rejected`
- `annotation_type` 限定为允许枚举

`ltw_annotation_occurrences` 约束：

- `annotation_id + version_id + source_anchor + target_anchor` 唯一
- 删除项目、章节、分片、版本时级联或置空策略遵循现有翻译数据关系

## 错误处理

- LLM 返回非 JSON：返回 `provider_error`，不写入候选。
- scope 内没有 active version：返回 `invalid_arguments`。
- 候选缺少 source anchor 或 explanation：跳过并记录 skipped count。
- 自动候选与 locked annotation 冲突：保留冲突候选，不覆盖 locked 注释。
- export 找不到 target anchor：不向正文插入引用，只在章节注释区输出。

## 测试策略

1. schema 测试：确认新增表和唯一约束存在。
2. prompt/parse 测试：确认 annotation extractor 只接受结构化 JSON。
3. 一致性测试：同一 source anchor 多次出现时复用同一 annotation。
4. locked 测试：locked 注释不被自动覆盖。
5. export 测试：manifest 包含 annotations，Markdown 输出章节注释区。
6. 回归测试：现有 glossary/translation/review/export 行为不变。

## 第一版验收标准

- 能为“一个小目标”生成独立 annotation，而不改译文 version。
- 同一项目内再次出现“一个小目标”时复用同一 canonical annotation。
- export manifest 中有结构化 annotation 数据。
- export markdown 中有章节注释区。
- `annotation.inspect` 能看见注释定义、状态、出现位置和冲突信息。
- 完整 `pytest tests -q` 通过。
