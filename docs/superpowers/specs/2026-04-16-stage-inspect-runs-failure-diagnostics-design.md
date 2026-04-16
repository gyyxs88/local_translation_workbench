# Stage Inspect Runs 失败诊断增强设计

## 1. 背景

当前 `stage.inspect_runs` 的返回信息过薄，单条 run 基本只有：

- `id`
- `stage`
- `scope_type`
- `status`
- `summary`

其中 `summary` 目前还是 JSON 字符串。对于失败运行，这会带来两个直接问题：

- 调用方还得自己 parse `summary`
- 看不到“到底失败在哪个 step、用了哪个 profile、实际落到了哪个 model”

路线图里 `P1.4 可观测性与失败恢复增强` 的第一刀，不是一次性补齐所有 fallback、resume、rerun 细节，而是先把 `stage.inspect_runs` 做成一个更能直接定位失败原因的观察面。

## 2. 本轮目标

本轮目标只有四个：

1. 让 `stage.inspect_runs` 能直接返回结构化 `summary`
2. 让 failed run 额外带上标准化 `diagnostics`
3. 让 glossary / translation 这类 workflow stage 能直接指出主失败 step
4. 在不改底层落库结构的前提下，最大化复用现有 `StageRun / WorkflowRun / WorkflowStepRun` 记录

## 3. 非目标

本轮明确不做下面这些事情：

- 不新增数据库表
- 不修改 `StageRun.summary` 的写入格式
- 不重构 `WorkflowRun / WorkflowStepRun` 的写入逻辑
- 不补 `failed_steps[]`
- 不补 `fallback_depth / actual_model_profile_id`
- 不补 `resume / rerun` 标准化诊断字段
- 不扩 `inspect.glossary`、`inspect.translation`、`inspect.review` 等其他 inspect 面
- 不改 `stage.inspect_runs` 现有的筛选、排序、`limit` 语义

## 4. 方案选择

本轮评估三种方向：

### 4.1 方案 A：仅展开 `StageRun.summary`

做法：

- 只把 `summary` 从字符串解成对象
- 不补查 workflow / step 记录

优点：

- 改动最小

缺点：

- 拿不到稳定的 `failure_step`
- 拿不到较可靠的 `model_name`
- 对 workflow stage 的失败定位帮助有限

### 4.2 方案 B：做标准化诊断视图并补查 workflow 记录

做法：

- `summary` 直接返回对象
- 对 failed run 构建 `diagnostics`
- 对 glossary / translation 这类 workflow stage，补查关联的 `WorkflowRun / WorkflowStepRun`

优点：

- 不改底层写入逻辑
- 信息密度提升明显
- 风险可控，收益直接

缺点：

- 查询逻辑会比现在多一层关联解析

### 4.3 方案 C：先改写入侧，再展开读取

做法：

- 先统一 Stage/Workflow summary 顶层字段
- 再让 `stage.inspect_runs` 直接透出这些规范化字段

优点：

- 长远结构更整齐

缺点：

- 第一刀改动面过大
- 会同时卷入多个 stage 的写入路径

### 4.4 结论

本轮采用：

**方案 B：保留现有落库结构，在 `stage.inspect_runs` 上构建标准化失败诊断视图。**

原因很直接：

- 当前最急的是“先把失败看清楚”
- 不是先做一轮底层 summary 重构
- 现有数据已经足够支撑这第一刀

## 5. 返回结构设计

本轮对 `stage.inspect_runs` 的单条 run 返回结构做破坏性收口。

旧结构示意：

```json
{
  "id": 12,
  "stage": "translation",
  "scope_type": "chapter_range",
  "status": "failed",
  "summary": "{\"request_id\":\"...\"}"
}
```

新结构示意：

```json
{
  "id": 12,
  "stage": "translation",
  "scope_type": "chapter_range",
  "status": "failed",
  "summary": {
    "request_id": "...",
    "model_profile_id": "profile-request",
    "workflow_key": "translation_multi_llm_v1",
    "error": {
      "code": "provider_error",
      "message": "...",
      "status": 502
    }
  },
  "diagnostics": {
    "error": {
      "code": "provider_error",
      "message": "...",
      "status": 502
    },
    "failure_step": {
      "step_key": "review_drafts",
      "action": "translation.review_draft"
    },
    "model_profile_id": "profile-review",
    "model_name": "gpt-xxx"
  }
}
```

本轮明确规则：

- `summary` 继续叫 `summary`，但类型从字符串改成对象
- 不保留原始字符串版 `summary`
- `diagnostics` 只在 `status == "failed"` 时返回内容，其他状态一律返回 `null`
- `diagnostics.error` 直接复用 `summary.error`

## 6. `diagnostics` 字段边界

本轮 `diagnostics` 只收下面四个字段：

- `error`
- `failure_step`
- `model_profile_id`
- `model_name`

字段语义如下：

### 6.1 `error`

直接复用 `summary.error`。

目标是避免出现两套错误结构不一致的问题。

### 6.2 `failure_step`

只表示这次 failed run 的“主失败 step”：

```json
{
  "step_key": "review_drafts",
  "action": "translation.review_draft"
}
```

本轮不返回 `failed_steps[]`。

### 6.3 `model_profile_id`

优先表示失败 step 实际使用的 `model_profile_id`。  
如果拿不到 step 级信息，再回退到 stage summary 里的请求级 `model_profile_id`。

### 6.4 `model_name`

只表示失败 step 对应的模型名，不表示整次 stage.run 的请求目标模型。

## 7. `failure_step` 解析链路

### 7.1 适用范围

本轮先覆盖 workflow 型 stage：

- `glossary`
- `translation`

对下面这些 stage：

- `chaptering`
- `review`
- `export`

本轮不强行构造 step 级诊断。

### 7.2 关联链路

failed run 的 `failure_step` 按下面顺序解析：

1. 先解析当前 `StageRun.summary`
   - 读取 `request_id`
   - 读取 `workflow_key`
   - 读取请求级 `model_profile_id`

2. 关联对应的 `WorkflowRun`
   - 优先按 `WorkflowRun.summary.stage_run_id == StageRun.id`
   - 若历史记录中缺少该指针，则退回按 `project_id + stage + request_id` 匹配
   - 如果仍找不到，`failure_step = null`

3. 读取这个 `WorkflowRun` 下的 failed `WorkflowStepRun`
   - 查询 `status == "failed"` 的 step runs
   - 只有一条时直接使用
   - 有多条时按 `id ASC` 取第一条，作为主失败 step

### 7.3 多失败 step 的取值规则

对 tolerant group / quorum failed 这类场景，可能同一条 run 下存在多条 failed step。

本轮约定：

- `failure_step` 只返回第一条 failed step
- 该“第一条”的定义是 `WorkflowStepRun.id` 最小的那条 failed 记录

原因：

- 当前字段是单数 `failure_step`
- 需要先给调用方一个稳定、不漂移的主定位点
- 更完整的 `failed_steps[]` 留到后续迭代

## 8. `model_profile_id` 与 `model_name` 取值规则

拿到目标 failed `WorkflowStepRun` 后，字段取值优先级如下：

### 8.1 `model_profile_id`

1. `WorkflowStepRun.model_profile_id`
2. `StageRun.summary.model_profile_id`
3. 取不到则 `null`

### 8.2 `model_name`

1. `WorkflowStepRun.output_payload.actual_model_name`
2. `WorkflowStepRun.output_payload.provider_model_name`
3. `WorkflowStepRun.summary.provider_model_name`
4. 取不到则 `null`

### 8.3 部分缺失时的返回策略

如果 workflow 补查失败，或 step 级字段不完整：

- `diagnostics.error` 仍正常返回
- `diagnostics.model_profile_id` 允许回退到请求级 profile
- `diagnostics.failure_step` 可为 `null`
- `diagnostics.model_name` 可为 `null`

也就是说，本轮允许 `diagnostics` 是“部分有值”的：

```json
{
  "diagnostics": {
    "error": { "...": "..." },
    "failure_step": null,
    "model_profile_id": "profile-request",
    "model_name": null
  }
}
```

这比“查不全就整个 `diagnostics = null`”更实用。

## 9. 查询与组装策略

`ProjectQueryService.inspect_stage_runs()` 的实现建议拆成三个职责清晰的辅助函数：

1. `_decode_summary_payload(...)`
   - 把 `StageRun.summary` JSON 文本解成对象
   - 保证外部拿到的 `summary` 一定是对象或 `null`

2. `_build_failed_run_diagnostics(...)`
   - 只处理 `status == "failed"` 的 run
   - 组装 `error / failure_step / model_profile_id / model_name`

3. `_resolve_workflow_failure_step(...)`
   - 专门做 `StageRun -> WorkflowRun -> WorkflowStepRun` 的关联
   - 返回主失败 step 与模型元信息

为了保持查询职责清晰，建议在 `WorkflowRepository` 里补最小 helper，而不是让 `ProjectQueryService` 直接堆原始 SQL。

## 10. 实现触点

本轮预计只修改下面这些位置：

- `app/services/project_query_service.py`
  - `stage.inspect_runs` 的 `summary` 解码与 `diagnostics` 组装
- `app/repositories/workflows.py`
  - 增加最小 workflow run / failed step 查询 helper
- `tests/test_project_actions.py`
  - 锁定 `stage.inspect_runs` 的新返回结构
- 视测试构造难度，可能补少量：
  - `tests/test_glossary_stage.py`
  - 或 `tests/test_translation_stage.py`

## 11. 测试方案

本轮至少覆盖下面四类测试：

1. completed run
   - `summary` 已经是对象
   - `diagnostics is None`

2. workflow failed run
   - `diagnostics.error` 正确展开
   - `diagnostics.failure_step.step_key/action` 正确
   - `diagnostics.model_profile_id` 取到 failed step 的 profile
   - `diagnostics.model_name` 能从 step payload 或 step summary 中取到

3. 非 workflow failed run
   - `diagnostics.error` 正常返回
   - `diagnostics.failure_step is None`
   - `diagnostics.model_name is None`

4. 多 failed steps
   - `failure_step` 固定取第一条 failed step
   - 同一 run 下多条 failed 记录不会导致结果漂移

验证顺序建议：

- 先跑 `tests/test_project_actions.py`
- 如有新增 stage 级补充测试，再跑对应单文件
- 最后跑完整 `pytest tests -q`

## 12. 风险点

本轮风险主要有三个：

### 12.1 历史失败记录不一定都带 `stage_run_id`

规避方式：

- 关联 `WorkflowRun` 时先查 `stage_run_id`
- 查不到再退回 `project_id + stage + request_id`

### 12.2 tolerant group 失败时会有多条 failed step

规避方式：

- 明确约定 `failure_step` 只取第一条 failed step
- 用测试把这条规则锁住

### 12.3 step 级模型信息可能不完整

规避方式：

- `model_profile_id` 允许回退到 stage summary
- `model_name` 允许为 `null`
- 不因为字段缺失而让整个 `diagnostics` 消失

## 13. 本轮完成标准

本轮完成后，`stage.inspect_runs` 至少要做到：

- `summary` 直接返回对象，不再需要调用方手动 parse
- failed run 能直接看到 `error`
- glossary / translation failed run 能直接看到主失败 step
- 能尽量指出失败时使用的 profile 与 model

同时满足下面三个约束：

- 不新增数据库结构
- 不改底层写入路径
- 完整回归保持通过
