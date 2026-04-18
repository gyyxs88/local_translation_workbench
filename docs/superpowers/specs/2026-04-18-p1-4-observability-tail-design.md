# P1.4 可观测性尾项收口设计

## 1. 背景

当前主线已经完成 `P1.4` 的两刀基础工作：

- `stage.inspect_runs` 已支持结构化 `summary`
- failed run 已支持 `diagnostics`
- run 级观测已支持 `timing / recovery / fallback`

这些底座已经足够回答一部分问题，例如：

- 这次 stage 是成功还是失败
- 失败时卡在哪个 workflow step
- 有没有 resume / rerun
- fallback 有没有命中

但当前还存在一个明显尾项：

**运行观测已经有了“点状字段”，但还缺“稳定的运行画像”。**

现在查看 `stage.inspect_runs` 时，调用方仍然需要自己拼下面几层信息：

- 真正的 `scope_value`
- 这次运行对应的 `request_id / workflow_key / workflow_run_id`
- 各 stage 真正的结果摘要
- glossary / translation workflow 内部 step 的整体状态

这会导致两个问题：

1. 你能知道“失败了”，但不够快地看出“这次到底跑了什么范围、内部跑到哪一步”
2. 不同 stage 的 `summary` 口径分散，调用方必须知道内部字段细节才能读懂

本轮目标就是把这层读模型收口出来，让 `stage.inspect_runs` 真正成为一个可直接排障、可直接人工审查的入口。

## 2. 本轮目标

本轮只做四件事：

1. 给 `stage.inspect_runs` 补 `scope_value`
2. 给 `stage.inspect_runs` 补统一的 `context`
3. 给 `stage.inspect_runs` 补按 stage 收口后的 `result`
4. 给 glossary / translation stage 补 workflow 级摘要 `workflow`

目标不是“增加更多原始字段”，而是：

**把当前已经分散在 `StageRun.summary`、`WorkflowRun`、`WorkflowStepRun` 里的信息，整理成稳定、易读、低耦合的 inspect 读模型。**

## 3. 非目标

本轮明确不做下面这些事：

- 不修改 `stage.run` 的即时返回结构
- 不新增数据库表或 schema 字段
- 不引入统一事件流或 timeline 子系统
- 不重写 `StageRun.summary` 的持久化格式
- 不新增 action
- 不把 `inspect.project`、`inspect.review`、`inspect.export` 一起改造成同口径运行画像
- 不补全文级错误日志、provider 原始响应、token 统计

## 4. 方案选择

本轮评估三个方向：

### 4.1 方案 A：只增强 `stage.inspect_runs` 读模型

做法：

- 保持现有 `StageRun.summary` 写法不变
- 在 query service 中补 `scope_value / context / result / workflow`
- `diagnostics` 和 `observability` 继续复用已有逻辑

优点：

- 风险最低
- 不改运行语义
- 不会把 CLI / action 契约一起卷进去

缺点：

- 仍然保留 `summary` 的 stage 内部差异
- 需要在 query service 多做一层显式组装

### 4.2 方案 B：同时重整 `StageRun.summary`

做法：

- 统一所有 stage 的 summary 持久化结构
- `stage.inspect_runs` 直接读取统一 summary

优点：

- 模型更整齐

缺点：

- 会同时改写 run 时写入和 inspect 时读取
- 风险明显高于当前尾项所需

### 4.3 方案 C：新建统一运行历史子系统

做法：

- 抽象新的 history / run query domain
- 把 stage/workflow 运行都汇总到新子系统

优点：

- 长期看最完整

缺点：

- 范围过大
- 已经偏离“尾项收口”

### 4.4 结论

本轮采用：

**方案 A：只增强 `stage.inspect_runs` 的读模型，不改 `stage.run` 即时返回，不动持久化 schema。**

原因很直接：

- 当前缺的是“观测视图不够完整”
- 不是“运行记录写错了”
- 这轮目标是收尾，不是再开一轮运行架构改造

## 5. 目标返回结构

### 5.1 保留现有字段

`stage.inspect_runs` 当前已返回：

- `id`
- `stage`
- `scope_type`
- `status`
- `summary`
- `observability`
- `diagnostics`

这些字段全部保留，不做破坏式替换。

### 5.2 新增 `scope_value`

当前只有 `scope_type`，但排障时经常需要知道这次跑的是：

- `all`
- `chapter_range`
- `chapter_list`
- `missing_only`

所以本轮直接把 `StageRun.scope_value` 解码后透出：

```json
{
  "scope_type": "chapter_range",
  "scope_value": {
    "type": "chapter_range",
    "start": 1,
    "end": 3
  }
}
```

### 5.3 新增 `context`

`context` 用来统一表达“这次运行是谁、基于什么上下文跑的”，字段固定如下：

- `request_id`
- `model_profile_id`
- `workflow_key`
- `workflow_run_id`

说明：

- 这些值优先来自已有 `summary` 和 workflow 查询，不新增新存储
- 非 workflow stage 的 `workflow_key / workflow_run_id` 允许为 `null`

示意：

```json
{
  "context": {
    "request_id": "translation-run-001",
    "model_profile_id": "profile-main",
    "workflow_key": "translation_multi_llm_v1",
    "workflow_run_id": 17
  }
}
```

### 5.4 新增 `result`

`result` 是对各 stage 运行产出的稳定摘要，不再要求调用方去理解每个 stage 的原始 summary 细节。

字段设计按 stage 收口：

#### `chaptering`

- `chapter_count`
- `segment_count`

#### `glossary`

- `candidate_count`

#### `translation`

- `translated_segments`
- `active_version_count`

其中 `active_version_count` 优先从 `active_version_ids` 推导；没有时返回 `0`。

#### `review`

- `issue_count`
- `review_run_id`

#### `export`

- `artifact_count`
- `export_run_id`
- `manifest_path`

示意：

```json
{
  "result": {
    "translated_segments": 28,
    "active_version_count": 28
  }
}
```

### 5.5 新增 `workflow`

只对 `glossary / translation` stage 补这一层；其它 stage 返回 `null`。

字段如下：

- `id`
- `workflow_key`
- `status`
- `step_counts`
- `steps`

其中：

- `step_counts.total`
- `step_counts.completed`
- `step_counts.failed`
- `step_counts.running`

`steps[*]` 固定返回：

- `step_run_id`
- `step_key`
- `action`
- `llm_role`
- `model_profile_id`
- `status`
- `fallback_depth`
- `actual_model_name`

`fallback_depth` 的读取口径：

- 优先读 `output_payload.fallback_depth / output_payload.max_fallback_depth`
- 其次读 step summary
- 都没有时返回 `0`

`actual_model_name` 的读取口径：

- 优先读 `output_payload.actual_model_name`
- 其次读 `output_payload.provider_model_name`
- 再次读 step summary 里的 `provider_model_name`
- 都没有时返回 `null`

示意：

```json
{
  "workflow": {
    "id": 17,
    "workflow_key": "translation_multi_llm_v1",
    "status": "failed",
    "step_counts": {
      "total": 5,
      "completed": 2,
      "failed": 1,
      "running": 2
    },
    "steps": [
      {
        "step_run_id": 31,
        "step_key": "generate_primary",
        "action": "translation.generate_draft",
        "llm_role": "translator",
        "model_profile_id": "profile-primary",
        "status": "completed",
        "fallback_depth": 1,
        "actual_model_name": "gpt-5.4"
      }
    ]
  }
}
```

## 6. 与现有字段的关系

### 6.1 `summary`

保留原样。

原因：

- `summary` 仍然是运行时真实写入的原始摘要
- 对调试和兼容仍然有价值
- 本轮只是新增更稳定的读模型，不替换底层原始数据

### 6.2 `diagnostics`

继续只在 failed run 上返回。

但本轮新增 `workflow.steps` 后，`diagnostics` 的角色会更明确：

- `diagnostics` 负责给出“失败入口”
- `workflow` 负责给出“完整运行画像”

两者不是重复，而是层级不同。

### 6.3 `observability`

保留当前三段：

- `timing`
- `recovery`
- `fallback`

本轮不再往 `observability` 里塞更多业务字段，避免语义发散。

## 7. 推荐实现边界

本轮实现保持小改动：

- `StageRunOrchestratorService`
  - 不改 summary 持久化契约
  - 只在必要时补当前已有结果字段的读取兼容

- `ProjectQueryService`
  - 作为本轮唯一主修改点
  - 负责组装 `scope_value / context / result / workflow`
  - 继续复用现有 `diagnostics / observability` 逻辑

如果读模型组装开始明显变胖，可以在本轮内部新增一个很小的辅助 service，例如：

- `StageRunInspectionViewService`

但前提是：

- 只有在 `ProjectQueryService` 已经明显失焦时才拆
- 不为了“看起来整齐”而过度设计

## 8. 测试策略

本轮测试只围绕 `stage.inspect_runs`：

### 8.1 非 workflow stage

验证：

- `scope_value` 正确解码
- `context` 能返回 `request_id / model_profile_id`
- `result` 能按 stage 返回稳定字段
- `workflow` 为 `null`

### 8.2 workflow stage 成功场景

验证：

- `context.workflow_key / workflow_run_id` 正确
- `workflow.step_counts` 正确
- `steps[*]` 能返回 `fallback_depth / actual_model_name`
- `result` 能正确汇总 translation / glossary 产出

### 8.3 workflow stage 失败场景

验证：

- `diagnostics` 继续返回首个失败 step
- `workflow.steps` 同时能显示其它 step 的状态
- `observability.fallback.max_depth` 与 step 级 fallback 汇总一致

## 9. 风险与处理

### 9.1 历史 run 字段不完整

旧数据可能没有：

- `workflow_key`
- `active_version_ids`
- `fallback_depth`

处理原则：

- 一律允许返回 `null / 0`
- 不因为历史 run 字段缺失而报错

### 9.2 `summary` 与 workflow 实际状态不完全一致

理论上可能出现：

- stage summary 写了 `workflow_key`
- 但找不到对应 workflow run

处理原则：

- `context` 尽量返回 summary 中已有值
- `workflow` 查不到时返回 `null`
- 不把这种情况升级成接口错误

## 10. 完成标准

本轮完成后，`stage.inspect_runs` 需要能直接回答下面这些问题，而不需要人工查库：

1. 这次跑的是什么范围
2. 是哪个 request / profile / workflow 发起的
3. 各 stage 实际产出了什么
4. glossary / translation workflow 一共几步，分别跑到什么状态
5. 失败时卡在哪一步，fallback 有没有命中

如果以上五个问题都能直接从 `stage.inspect_runs` 单次返回中读出来，就可以视为 `P1.4` 这轮尾项完成。
