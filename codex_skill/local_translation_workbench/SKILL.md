---
name: local_translation_workbench
description: 使用仓库内 `tools/local_translation_workbench` 管理本地小说翻译项目时使用。适用于创建项目、拆章、简介隔离、术语抽取与审阅、注释层抽取、翻译、审校、导出，以及基于多 LLM 结果做 agent 侧术语仲裁。
---

# Local Translation Workbench

仅当任务涉及本地翻译工作台的项目运行、检查、调试或结果评估时使用本 skill。

## 默认策略

- 先读工具目录内的 `README.md`，再按需阅读 `docs/operations/` 或测试报告。
- 工具入口固定为：
  - `powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1`
- 优先使用 `stage.run` 和 `inspect.*` 完成常规流程；只有需要细粒度重跑或诊断时，才直调 `glossary.*`、`translation.*`、`annotation.*` 原子动作。
- 本工具面向 agent 编排，不面向人工交互 UI；agent 写回术语仲裁结果时使用结构化 action，不直接改数据库。
- 真实运行前确认数据库环境变量有效，测试库与业务库必须隔离；不要把真实 provider key 写入仓库文档、脚本或提交记录。
- 测试报告和临时脚本默认不进入远端仓库；临时脚本放在 `temp/`。

## 推荐流程

1. `provider.health_check` 确认本次模型 profile 可用。
2. `project.create` 创建新项目，保留返回的 `project_id` 与 `project_key`。
3. `stage.run -Stage chaptering` 先完成拆章；随后用 `inspect.synopsis` 与 `inspect.chapters` 确认简介未混入第一章。
4. `stage.run -Stage glossary` 抽取术语；多模型对比时显式传 `workflow_key=glossary_multi_llm_v1` 和对应 `route_preset_key`。
5. 用 `inspect.glossary` 与 `glossary.inspect_pipeline` 查看正式术语、候选、关系组、review evidence 和每章状态。
6. 需要读者说明时，再运行 `annotation.extract`；注释层独立于译文和 glossary，不直接改译文正文。
7. 继续翻译前，先处理 locked/active glossary 冲突、明显误收录项和重要译名不一致。

## 术语仲裁

术语仲裁属于使用本工具的 agent 责任，不写进工具代码。工具代码只产出证据：候选术语、正式术语、关系组、review evidence、多 LLM 差异、注释候选和报告；最终采用哪个译名、哪些项降级为注释、哪些项拒绝进入 glossary，由 agent 根据上下文判断。

仲裁时按以下优先级处理：

1. 已有 `locked` 或 `active` 正式术语优先，除非用户明确要求重定译名。
2. 人名、地名、组织名、家族名等专有名词优先保持全书一致；发现同一来源在多次运行中出现转写漂移时，选稳定且可复用的形式。
3. 世界观、能力体系、物品、头衔等系列术语优先保持形态、大小写和 category 风格一致。
4. 技能名、称号、招式名允许为了英文自然度调整，但不能牺牲核心语义。
5. 俚语、文化梗、中文特有表达、需要读者说明的概念优先进入 annotation 层，不为了“解释”污染译文或 glossary。
6. 上下文短语、临时描述、序数壳、带角色视角的组合短语，默认拒绝或降级，不作为正式术语。典型例子包括 `67届`、`67届的剑花`、`亚修的意识光幕`、`剑术天才美少女` 这类依赖局部句境的表达。
7. 当两个 LLM 都给出不理想译名时，agent 可以给出第三个 canonical 译名，但必须说明依据。

多 LLM 术语结果不一致时，agent 输出独立仲裁记录，不直接改写正文。建议记录字段：

```text
source_term | chosen_target | source_run | reason_code | note
```

常用 `reason_code`：

- `existing_locked_term`
- `proper_name_consistency`
- `series_consistency`
- `semantic_accuracy`
- `english_naturalness`
- `category_style`
- `reject_context_phrase`
- `needs_annotation`
- `manual_review`

仲裁结论应作为报告或后续操作依据；只有用户明确要求更新术语表时，才通过工具动作写回 glossary。

写回时使用这些 action：

- `glossary.entry.create/update/delete/lock/unlock` 管理正式术语。
- `glossary.candidate.create/update/approve/reject/delete/promote` 管理临时候选术语。
- `glossary.candidate.approve/reject` 只改候选状态；`glossary.candidate.promote` 才会写入正式术语。
- 删除 locked 正式术语或用候选覆盖 locked 正式术语时，必须显式传 `force=true`。
- 正式术语变化会让受影响章节的下游 translation/review/export 变 stale；候选状态变化不会污染正式译文。

## 失败时怎么退

- provider 失败：先看 `provider.health_check` 和 `stage.inspect_runs` 的 fallback/attempts 明细，再决定是否换 profile 或补跑。
- 拆章异常：先用 `inspect.synopsis`、`inspect.chapters` 和章节源文件确认简介、前言、正文标题边界。
- 术语异常：先看 `glossary.inspect_pipeline`，区分 extractor 输出差、review evidence 拒绝、finalize 合并、locked/active 冲突。
- 注释异常：先确认目标分片已有 active translation version；annotation 不应被用来修译文或修 glossary。
