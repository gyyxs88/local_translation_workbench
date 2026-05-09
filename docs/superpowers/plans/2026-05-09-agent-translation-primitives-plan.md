# Agent 翻译构建原语第一批实施计划

## 背景

老翻译平台面向人工操作，新工具面向 Agent 调用。本批开发只吸收老平台在翻译构建链路里的后端能力，不迁移人工 UI。

## 目标

1. Provider 调用失败要能给 Agent 返回可判别的错误类型，便于自动决定重试、切模型、暂停或要求人工补配置。
2. Provider 调用要有结构化账本与汇总 inspect，便于 Agent 看成本、token、fallback、失败类型和执行归因。
3. Glossary 要支持 denylist/reject rules，阻止章节标题、泛称、噪声词进入术语候选。
4. 明确维持 `no_new_terms` 为成功语义，不把“无新增术语”误判成失败。

## 非目标

- 不开发或迁移人工编辑 UI。
- 不引入后台队列。
- 不扩展新的 provider 协议。
- 不改多 LLM 仲裁边界：工具只提供候选、证据和结构化事实，最终仲裁仍由 Agent 完成。

## 实施步骤

1. 测试先行
   - Provider 错误分类与 fallback attempts 中的 `error_type`。
   - Provider 成功结果保留 usage，避免 fallback 包装丢 token。
   - Provider call ledger 的记录、汇总和 inspect action。
   - Glossary denylist 的增删查、匹配过滤和 action 注册。
   - 复用既有 `no_new_terms` 测试作为回归证据。

2. Provider 错误分类
   - 新增 `provider_error_classifier` 服务。
   - 在 `FailoverProvider.generate_text` 和 `health_check` attempts 中写入 `error_type`。
   - 成功 fallback 包装 `TextGenerationResult` 时保留 `usage`。

3. Provider 调用账本
   - 新增 `ProviderCallLog` 模型与 `0024` migration。
   - 新增 repository/service，支持记录、列表、按 stage/profile/status 汇总。
   - 新增 `inspect.provider_calls` 与 `inspect.provider_costs`。
   - 第一批以 workflow step output payload 的 token 和模型元数据为数据源，生成 step 级账本；后续再下钻到每一次 provider 调用。

4. Glossary denylist
   - 新增 `GlossaryDenylistRule` 模型与 repository/service。
   - 支持 `exact / contains / regex` 三种匹配。
   - `glossary.extract` 创建 draft candidate 前过滤命中项，并在输出 payload 中保留 rejected_terms 证据。
   - 新增 `glossary.denylist.add/list/delete` action。

5. 文档与回归
   - 更新 README action 列表和 glossary/provider 说明。
   - 跑相关测试，最后跑工具测试子集或完整回归。

## 验收

- Agent 能通过 action 管理术语拒收规则。
- Agent 能从 inspect action 看 provider 调用账本和成本/token 汇总。
- Provider fallback 的失败详情有稳定 `error_type`。
- `no_new_terms` 仍表现为成功章节状态。
