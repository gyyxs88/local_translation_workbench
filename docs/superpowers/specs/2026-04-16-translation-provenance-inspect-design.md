# Translation Inspect Provenance 设计

## 1. 背景

当前 `translation` 链路已经具备下面这些能力：

- `translation_single_llm_v1` 与 `translation_multi_llm_v1` 两条 workflow
- draft version、draft review、正式译文 version 的结构化落库
- `inspect.translation` 能返回当前 active version 和历史 versions 列表

但现在的 `inspect.translation` 还回答不了最关键的一类问题：

- 当前生效的正式译文是从哪一轮 finalize 写出来的
- finalize 最终选中了哪条 draft
- 这条 selected draft 在进入 finalize 之前经历过哪些 review 结论

这意味着人工复核和问题排查时，虽然能看到“现在是什么”，但还看不清“为什么会是现在这样”。

路线图里 `P1.3 历史版本与可追踪性增强` 的第一刀，目标不是一次性做完整历史时间线，而是先把 `inspect.translation` 的当前结果来源链路补齐。

## 2. 本轮目标

本轮目标只有四个：

1. 让 `inspect.translation` 能解释每个 segment 当前 `active version` 的来源
2. 把来源链路稳定收口到 `active version -> finalize step -> selected draft -> selected draft reviews`
3. 保持现有 `inspect.translation` 主体结构兼容，不打乱已有调用面
4. 为后续 `P1.3 / P1.4` 的版本追踪与可观测性增强埋下硬指针，而不是依赖运行时猜测

## 3. 非目标

本轮明确不做下面这些事情：

- 不做 `inspect.segment`、`inspect.chapter`、`inspect.chapters` 的 provenance 扩展
- 不给 `data["versions"]` 历史 version 列表补 provenance
- 不做 top-level 的 workflow/review/export 时间线汇总
- 不做 review/export stale 关联透出
- 不做历史数据回填脚本
- 不改 CLI action 名，也不新增新的 inspect action

## 4. 方案选择

本轮评估三种方案：

### 4.1 方案 A：在 inspect 时反推来源

做法：

- 不改表结构
- `inspect.translation` 现场通过 `segment_id / translated_text / source_hash / model_profile_id` 去推测当前 active version 对应哪条 draft 和哪次 finalize

优点：

- 改动最小
- 不需要 migration

缺点：

- 结果不稳定
- 多次 rerun 产出相同文本时容易歧义
- 后续排障时不能保证来源链路可信

### 4.2 方案 B：把 provenance 指针落到正式版本上

做法：

- 在 `ltw_segment_translation_versions` 上增加 provenance 字段
- finalize 落正式版本时同步写入来源指针
- `inspect.translation` 只读这些硬指针，不做猜测

优点：

- 结果稳定、可解释
- 查询简单
- 后续扩展到更完整时间线时可继续复用

缺点：

- 需要新增 migration
- 旧数据不会自动获得 provenance

### 4.3 方案 C：单独建 provenance 表

做法：

- 新建专门的 provenance 关系表，记录 version 与 draft/finalize 的映射

优点：

- 规范，理论扩展性最好

缺点：

- 对当前这一刀来说过重
- 增加不必要的表与关联复杂度

### 4.4 结论

本轮采用：

**方案 B：把 provenance 指针直接落到正式译文版本上。**

原因很直接：

- 当前目标是把“当前 active version 从哪来”讲清楚
- 不是先做一个完整的事件溯源系统
- 直接在正式版本上挂硬指针，既够准，也足够轻

## 5. 数据链路设计

本轮要串起来的最小链路是：

- `SegmentTranslation.active_version_id`
- `SegmentTranslationVersion.origin_step_run_id`
- `WorkflowStepRun`（finalize step）
- `SegmentTranslationVersion.origin_draft_version_id`
- `TranslationDraftVersion`
- `TranslationDraftReview[]`（仅 selected draft 自身的 reviews）

这条链路要能回答下面四个问题：

- 当前生效的是哪条正式 version
- 这条正式 version 是哪次 `translation.finalize` 写出来的
- finalize 当时选中了哪条 draft
- 这条 selected draft 收到过哪些 review 结论

## 6. 数据模型变更

本轮在 `ltw_segment_translation_versions` 上新增三个可空字段：

- `origin_workflow_run_id`
- `origin_step_run_id`
- `origin_draft_version_id`

设计要求：

- 三个字段都允许为 `NULL`，用于兼容旧数据
- 都使用外键约束，分别指向：
  - `ltw_workflow_runs.id`
  - `ltw_workflow_step_runs.id`
  - `ltw_translation_draft_versions.id`
- 这三个字段只描述“当前这条正式 version 的来源”，不承担通用历史事件存储职责

为什么三个都保留：

- `origin_draft_version_id` 用来直接找到 selected draft
- `origin_step_run_id` 用来直接找到 finalize step
- `origin_workflow_run_id` 让后续扩展到 workflow 级追踪时不用再做间接反推

## 7. 写入策略

正式版本的 provenance 只在 finalize 时写入。

具体规则：

1. finalize 先按现有逻辑选出 `selected draft`
2. 创建 `SegmentTranslationVersion` 时，把下列 provenance 同步写入：
   - `origin_workflow_run_id = selected_draft.workflow_run_id`
   - `origin_step_run_id = workflow_step_run_id`
   - `origin_draft_version_id = selected_draft.id`
3. provenance 字段与正式 version 本体在同一个 session、同一次 flush 里落库

这里强调“同一次落库”是因为：

- finalize 现在已经支持 segment 级并发 worker
- 如果 provenance 采用事后补写，就容易出现“version 已经创建，但 provenance 缺失”的半链路状态

## 8. `inspect.translation` 返回结构

本轮只增强 `data["translations"]`，不改 `data["versions"]`。

每条 `translations[*]` 新增一个字段：

- `provenance`

返回约定如下：

```json
{
  "segment_id": 12,
  "active_version_id": 34,
  "version": {
    "id": 34,
    "version_index": 2,
    "source_hash": "....",
    "glossary_snapshot_id": "....",
    "provider_name": "provider",
    "model_profile_id": "profile-final",
    "model_name": "model-final",
    "source_text": "...",
    "translated_text": "...",
    "translated_text_path": "...",
    "status": "completed"
  },
  "provenance": {
    "finalize_step": {
      "step_run_id": 78,
      "step_key": "finalize_segments",
      "action": "translation.finalize"
    },
    "selected_draft": {
      "id": 56,
      "workflow_run_id": 21,
      "step_run_id": 77,
      "draft_role": "rewrite",
      "parent_draft_id": 41,
      "provider_name": "provider",
      "model_profile_id": "profile-rewrite",
      "model_name": "model-rewrite",
      "translated_text_path": "...",
      "status": "completed",
      "evidence_payload": {},
      "reviews": [
        {
          "id": 91,
          "step_run_id": 76,
          "review_type": "quality",
          "decision": "keep",
          "score": 0.91,
          "reason_codes": ["faithful"],
          "structured_payload": {}
        }
      ]
    }
  }
}
```

约束如下：

- `version` 的现有结构不改
- `provenance` 只解释当前 active version
- `selected_draft.reviews` 只返回 selected draft 自己的 reviews，不返回同 segment 其他 draft 的 reviews
- `selected_draft` 保留 `parent_draft_id`，方便后续继续向上追 rewrite 的来源

## 9. 兼容与退化策略

本轮采用“新数据增强、旧数据安全退化”的兼容策略。

规则如下：

- 段落没有 `active_version_id` 时：`provenance = null`
- active version 存在，但 provenance 字段为空时：`provenance = null`
- provenance 指向的 draft 或 step 因历史数据缺失无法加载时：`provenance = null`

这里不做“部分链路也尽量返回”的半残结果，原因是：

- provenance 一旦开始返回，就应该是可信的
- 与其返回一条缺半截的链，不如明确返回 `null`

## 10. 查询与组装策略

`TranslationService.inspect()` 的实现建议遵循下面的边界：

1. 先按现有逻辑拿到 `translations` 和 `versions` 主体数据
2. 对 active version 中 provenance 指针不为空的记录，批量加载：
   - `WorkflowStepRun`
   - `TranslationDraftVersion`
   - `TranslationDraftReview`
3. 在内存中按 `draft_version_id` 聚合 reviews
4. 只给 `translations[*]` 填充 `provenance`

这样做的原因：

- 不需要在主查询里再堆更多 join
- 可以把 provenance 组装逻辑控制在 `inspect.translation` 内部
- 后续如果要扩到 `versions[]`，也能复用同一套组装函数

## 11. 实现触点

本轮预计只修改下面这些位置：

- `migrations/versions/*.py`
  - 新增 provenance 字段 migration
- `app/db/models.py`
  - 给 `SegmentTranslationVersion` 增加 provenance 字段
- `app/repositories/translations.py`
  - 扩展 `create_version(...)` 入参
- `app/services/translation_pipeline_service.py`
  - finalize 时写入 provenance
- `app/services/translation_service.py`
  - `inspect.translation` 组装 `provenance`
- `tests/test_translation_stage.py`
  - 增加 provenance inspect 覆盖
- 可能小幅调整 `tests/test_review_export.py`
  - 保持 CLI inspect 断言与新结构兼容

## 12. 风险点

本轮风险主要有三个：

### 12.1 finalize 并发写入时的 provenance 丢失

因为 finalize 现在是 segment 级并发 worker，如果 provenance 不跟正式 version 一起落库，就容易出现链路缺失。

规避方式：

- provenance 字段必须在 `create_version(...)` 时一次性写入

### 12.2 single workflow 没有 review/rewrite

`translation_single_llm_v1` 的 selected draft 通常是 primary draft，没有 review/rewrite。

规避方式：

- `selected_draft.reviews` 稳定返回空数组
- 不假设 selected draft 一定来自 rewrite

### 12.3 旧数据没有 provenance

老版本正式译文不会自动获得 provenance。

规避方式：

- 明确把旧数据视作正常退化场景
- `inspect.translation` 对缺失指针稳定返回 `null`

## 13. 测试方案

本轮至少覆盖下面四类测试：

1. `translation_single_llm_v1`
   - `inspect.translation` 返回 active version provenance
   - selected draft 为 primary
   - `reviews` 为空数组

2. `translation_multi_llm_v1`
   - `inspect.translation` 返回 active version provenance
   - selected draft 为最终实际选中的 draft
   - 如果选中的是 rewrite，则 provenance 中返回 rewrite draft

3. 未翻译段落
   - `active_version_id is None`
   - `provenance is None`

4. 旧数据 / 无 provenance 指针
   - 即使存在 active version
   - 也稳定返回 `provenance is None`

验证顺序：

- 先跑 `tests/test_translation_stage.py`
- 再跑 `tests/test_translation_workflow_actions.py`
- 最后跑完整 `pytest tests -q`

## 14. 本轮完成标准

本轮完成后，`inspect.translation` 至少能够让人直接看懂：

- 当前 active version 是哪条
- 这条 version 来自哪次 finalize
- finalize 选中了哪条 draft
- 这条 draft 的 review 结论是什么

同时满足下面三个约束：

- 现有 `inspect.translation` 结构保持兼容
- 旧数据不会因为没有 provenance 而报错
- 完整回归保持通过
