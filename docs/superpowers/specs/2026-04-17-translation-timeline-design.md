# Translation Inspect Timeline 设计

## 1. 背景

当前 `inspect.translation` 已经具备两类历史查看能力：

- 能返回每个 segment 当前 `active version` 的 provenance
- 能在单段模式下对比当前 `active version` 与一条指定历史正式版本

这两刀已经解决了下面两类问题：

- 当前结果从哪里来
- 当前结果和某个旧版本有什么差异

但 `P1.3 历史版本与可追踪性增强` 还缺一块关键观察面：

- 当前这条正式译文一路经历了哪些关键事件
- selected draft 是什么时候生成的
- 它收到过哪些 review
- 最后是哪次 finalize 把它提交成正式版本

现在如果想回答这些问题，只能把 provenance、draft review、workflow step run 和 version 记录人工拼起来看，成本高，也不适合作为稳定 inspect 输出。

这轮的目标不是一次性做 full timeline，更不是把 review/export 全部串进来，而是先把“当前 active version 这条来源链”收成一个可直接读取的时间线。

## 2. 本轮目标

本轮目标只有四个：

1. 让 `inspect.translation` 能直接返回当前 `active version` 的来源时间线
2. 时间线只覆盖当前结果直接依赖的关键事件，不做全量历史回放
3. 事件结构统一、可扩展，为后续继续补 `P1.3` 留好协议空间
4. 不新增 action，不改数据库结构，直接复用现有 provenance 与 workflow 记录

## 3. 非目标

本轮明确不做下面这些事情：

- 不做该 segment 的 full timeline
- 不做 `inspect.review`、`inspect.export` 联动时间线
- 不做 chapter 级或 project 级聚合 timeline 摘要
- 不做 `active_version_switched` 事件
- 不做 selected draft 的 parent 链 review 展开
- 不做 provenance diff
- 不改任何 translation 相关表结构

这里特别强调不做 `active_version_switched` 的原因：

- 当前库里只有 `SegmentTranslation.active_version_id` 的现态指针
- 没有独立的 active switch 历史记录
- finalize 提交新版本时会更新 active 指针，但那已经由 `finalize_committed` 事件表达
- 在没有硬记录的前提下推断“曾经切换过”会让时间线失真

## 4. 方案选择

本轮评估三种方案：

### 4.1 方案 A：只做当前 active version 来源链时间线

做法：

- 只围绕当前 active version 组装 timeline
- 事件只使用现有硬数据
- 事件范围收成 `draft_created / review_created / finalize_committed`

优点：

- 最稳，不需要猜历史
- 和当前 provenance 完全同源
- 输出简洁，直接服务“当前结果怎么来的”

缺点：

- 还不能回答“这个 segment 全部历史都发生过什么”

### 4.2 方案 B：在方案 A 基础上推断 active switch 事件

做法：

- 根据 version 索引、创建时间和当前 active 指针反推是否发生过 active switch

优点：

- 表面上看更完整

缺点：

- 当前没有独立 switch 事件记录
- 推断结果不够硬，容易误导

### 4.3 方案 C：直接做 full timeline

做法：

- 该 segment 的全部 draft、review、finalize 事件全部铺出来

优点：

- 信息最全

缺点：

- 第一刀过重
- 反而会把“当前结果从哪来”这个核心问题淹没掉

### 4.4 结论

本轮采用：

**方案 A：只做当前 `active version` 来源链时间线。**

原因很直接：

- 当前最值钱的问题是“现在这条正式译文是怎么来的”
- 不是“这个 segment 所有历史都发生过什么”
- 只用现有硬数据，结果才可信

## 5. 时间线范围

本轮 `timeline` 只解释当前 active version 直接依赖的来源链。

具体包含三类事件：

1. `draft_created`
   表示 selected draft 是何时、由哪一步、用哪个 profile/model 生成的

2. `review_created`
   只表示 selected draft 自己收到过的 review 记录

3. `finalize_committed`
   表示当前 active version 是哪次 finalize 正式提交出来的

这条时间线要能直接回答：

- 当前正式译文对应的是哪条 draft
- 这条 draft 收到过哪些 review
- 最后是哪次 finalize 把它提交成正式版本

这条时间线明确不回答：

- 该 segment 的所有历史 draft 都发生过什么
- selected draft 的 parent 链 review 全貌
- 历史 active 指针如何变化
- review/export 外围运行全貌

## 6. 返回位置与整体结构

`timeline` 直接挂在 `inspect.translation -> translations[*]` 上，和 `version / provenance / compare` 平级。

示意结构如下：

```json
{
  "translations": [
    {
      "segment_id": 12,
      "active_version_id": 34,
      "version": { ... },
      "provenance": { ... },
      "compare": { ... },
      "timeline": [
        { ... },
        { ... },
        { ... }
      ]
    }
  ],
  "versions": [
    { ... }
  ]
}
```

返回边界：

- 项目级 `inspect.translation`：每条 row 都可以带自己的 `timeline`
- 单段 `inspect.translation`：返回该 row 的 `timeline`
- `versions[]` 历史版本列表完全不变
- `compare` 结构完全不变，不把 timeline 塞进 compare

## 7. 事件结构设计

`translations[*].timeline` 是一个按稳定事件顺序排列的事件数组。

统一事件结构如下：

```json
{
  "type": "draft_created",
  "occurred_at": null,
  "step_run_id": 77,
  "step_key": "rewrite_consensus",
  "action": "translation.rewrite_draft",
  "model_profile_id": "profile-rewrite",
  "model_name": "model-rewrite",
  "payload": {
    "draft_version_id": 56,
    "draft_role": "rewrite",
    "parent_draft_id": 41,
    "status": "completed"
  }
}
```

```json
{
  "type": "review_created",
  "occurred_at": null,
  "step_run_id": 76,
  "step_key": "review_drafts",
  "action": "translation.review_draft",
  "model_profile_id": "profile-review",
  "model_name": "model-review",
  "payload": {
    "review_id": 91,
    "review_type": "quality",
    "decision": "keep",
    "score": 0.91,
    "reason_codes": ["faithful"]
  }
}
```

```json
{
  "type": "finalize_committed",
  "occurred_at": null,
  "step_run_id": 78,
  "step_key": "finalize_segments",
  "action": "translation.finalize",
  "model_profile_id": "profile-final",
  "model_name": "model-final",
  "payload": {
    "translation_version_id": 34,
    "version_index": 2,
    "status": "completed"
  }
}
```

统一规则如下：

- 顶层固定字段：`type / occurred_at / step_run_id / step_key / action / model_profile_id / model_name / payload`
- `payload` 只放事件特有细节
- `occurred_at` 当前实现统一返回 `null`
- 原因是当前 timeline 依赖的 `TranslationDraftVersion / TranslationDraftReview / SegmentTranslationVersion / WorkflowStepRun` 还没有独立 `created_at`
- 这轮先保证事件序列可信与稳定，不伪造时间戳
- `timeline` 没有事件时返回空数组 `[]`，不返回 `null`

## 8. 事件来源与组装规则

本轮事件全部只使用现有硬数据，不做推断。

### 8.1 `draft_created`

来源：

- 当前 active `SegmentTranslationVersion.origin_draft_version_id`
- 对应的 `TranslationDraftVersion`

字段规则：

- `occurred_at = null`
- `step_run_id = draft.step_run_id`
- `model_profile_id = draft.model_profile_id`
- `model_name = draft.model_name`
- `payload.draft_version_id = draft.id`
- `payload.draft_role = draft.draft_role`
- `payload.parent_draft_id = draft.parent_draft_id`
- `payload.status = draft.status`

`step_key / action` 来源：

- 优先取 `draft.step_run_id` 对应的 `WorkflowStepRun`
- 如果 step run 缺失，允许 `step_key = null`、`action = null`
- 事件本身仍然保留，因为 draft 记录本身已经成立

### 8.2 `review_created`

来源：

- selected draft 自己的 `TranslationDraftReview[]`

字段规则：

- `occurred_at = null`
- `step_run_id = review.step_run_id`
- `payload.review_id = review.id`
- `payload.review_type = review.review_type`
- `payload.decision = review.decision`
- `payload.score = review.score`
- `payload.reason_codes = review.reason_codes`

`step_key / action / model_profile_id / model_name` 来源：

- 优先取 `review.step_run_id` 对应的 `WorkflowStepRun`
- `model_name` 优先使用 `WorkflowStepRun` 上可取到的实际模型名
- 如果 step run 缺失或缺少模型信息，允许这些字段退化为 `null`

### 8.3 `finalize_committed`

来源：

- 当前 active `SegmentTranslationVersion`
- 以及它的 `origin_step_run_id` 对应的 `WorkflowStepRun`

字段规则：

- `occurred_at = null`
- `step_run_id = version.origin_step_run_id`
- `model_profile_id = version.model_profile_id`
- `model_name = version.model_name`
- `payload.translation_version_id = version.id`
- `payload.version_index = version.version_index`
- `payload.status = version.status`

`step_key / action` 来源：

- 优先取 `origin_step_run_id` 对应的 `WorkflowStepRun`
- 如果 step run 缺失，允许 `step_key / action = null`
- 事件本身仍然保留，因为正式 version 记录本身已经成立

## 9. 排序规则

事件最终统一这样排序：

1. 先收出全部可信事件
2. 去掉根本无法成立的事件
3. 按固定优先级排序：
   - `draft_created`
   - `review_created`
   - `finalize_committed`
4. 同类型事件内部再按本类主键升序稳定排序：
   - `draft_created` 按 `draft_version_id`
   - `review_created` 按 `review_id`
   - `finalize_committed` 按 `translation_version_id`

这样做的目的有两个：

- 输出顺序稳定
- 在没有事件时间戳的前提下，结果仍然可预测

## 10. 退化规则

本轮 timeline 采用“尽量保留可信事件，不做整条清空”的退化策略。

规则如下：

- 没有 active version：`timeline = []`
- active version 没有 provenance：`timeline = []`
- selected draft 找不到：只保留 `finalize_committed`（如果当前 version 仍在）
- review 对应的 `WorkflowStepRun` 找不到：`review_created` 事件仍保留，但 `step_key / action / model_profile_id / model_name` 允许为 `null`
- draft 或 finalize 对应的 `WorkflowStepRun` 找不到：对应事件仍保留，但 `step_key / action` 允许为 `null`

这里和 provenance 的设计不同：

- provenance 讲究完整来源链，缺一环就宁可返回 `null`
- timeline 讲的是“有哪些可信事件”，少一环不代表整条线都不可信

## 11. 查询实现边界

实现范围建议只收在 `TranslationService.inspect()` 及其相关 helper 内，不扩新 service。

建议新增的实现职责：

- 在构建 `translations[*]` row 时增加 `timeline`
- 批量加载当前 active version 对应的 selected draft
- 批量加载 selected draft 自己的 reviews
- 批量加载 timeline 所需的 `WorkflowStepRun`
- 在内存中统一组装事件数组

不建议这轮做的事：

- 不新增 repository 复杂查询接口，只为 timeline 小题大做
- 不引入单独的 timeline service
- 不修改现有 `compare` 或 `provenance` 协议

## 12. 测试边界

本轮至少补下面五类测试：

### 12.1 single LLM 时间线

场景：

- 当前 active version 来自 single workflow
- selected draft 没有 review

断言：

- `timeline` 返回 2 个事件
- 顺序为 `draft_created -> finalize_committed`

### 12.2 multi LLM 时间线

场景：

- 当前 active version 来自 multi workflow
- selected draft 自己有 review

断言：

- `timeline` 返回 `draft_created -> review_created(1..n) -> finalize_committed`
- 只包含 selected draft 自己的 review

### 12.3 legacy active version

场景：

- 当前 active version 没有 provenance 指针

断言：

- `timeline = []`

### 12.4 step run 缺失退化

场景：

- 手工构造或清空对应 `WorkflowStepRun`

断言：

- 事件仍保留
- `step_key / action / model_profile_id / model_name` 按规则退化为 `null`

### 12.5 compare 共存

场景：

- 单段 compare 模式下查看当前 row

断言：

- `timeline` 仍正常返回
- 不影响现有 `compare` 结构与断言

## 13. 完成标准

本轮完成后，应当满足：

- 人工查看 `inspect.translation` 时，可以直接看懂当前正式译文的来源事件链
- 不需要再手工拼 provenance、draft review 和 finalize 记录
- timeline 输出稳定，不依赖历史猜测
- 已有 `provenance` 和 `compare` 能力不被破坏

## 14. 后续衔接

这轮 timeline 只是 `P1.3` 的第三刀，不是终态。

后续如果继续增强，可在这个协议上向前走：

- 真正的 `active_version_switched` 事件
- full timeline
- `inspect.review / inspect.export` 的外围时间线
- chapter / project 级 timeline 聚合

但这些都应建立在“先有硬记录，再有事件输出”的前提上，不能靠猜。
