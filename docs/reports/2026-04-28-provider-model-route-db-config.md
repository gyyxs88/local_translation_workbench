# 供应商与模型路由数据库化改造报告

## 目标

把供应商、模型 profile 和主/副 LLM 路由都放进数据库，便于在测试和正式任务之间快速切换。

## 已完成

- `ltw_provider_configs` 增加 `api_key_value`，允许 provider key 明文入库。
- `provider.create` 要求提供 `api_key_value`，模型 provider 不再读取环境变量 key。
- 新增 `provider.set_key`，可更新已有 provider 的 key 来源。
- 新增 `ltw_model_route_presets / ltw_model_route_bindings`，用于保存模型路由 preset。
- 新增 `profile.route_set / profile.route_list / profile.route_inspect / profile.route_set_default`。
- `stage.run / project.run_full` 新增 `route_preset_key`，workflow step 会按 preset 精确切换 profile。
- workflow 运行时已支持同一次任务内按 step 切换 provider，例如 `extract_primary` 用 GPT-5.5，`extract_secondary` 用 DeepSeek。

## 安全行为

- 数据库里的 `api_key_value` 是明文保存。
- `provider.list / provider.inspect` 不返回完整 key，只返回 `api_key_source`、`api_key_is_set` 和 `api_key_masked`。
- 运行时只读取数据库 `api_key_value`。

## 推荐路由示例

```json
[
  {"stage":"glossary","step_key":"extract_primary","model_profile_id":"gpt_5_5_aicodelink"},
  {"stage":"glossary","step_key":"extract_secondary","model_profile_id":"deepseek_v4_pro"},
  {"stage":"translation","step_key":"generate_primary","model_profile_id":"gpt_5_5_aicodelink"},
  {"stage":"translation","step_key":"generate_secondary","model_profile_id":"deepseek_v4_pro"},
  {"stage":"translation","step_key":"review_drafts","model_profile_id":"gpt_5_5_aicodelink"},
  {"stage":"translation","step_key":"rewrite_consensus","model_profile_id":"gpt_5_5_aicodelink"}
]
```

## 验证

- `tests/test_model_route_actions.py`：覆盖 DB key、route preset 持久化、action 入口和 workflow step provider 切换。
- `tests/test_provider_profile_actions.py`
- `tests/test_provider_resolution_service.py`
- `tests/test_workflow_actions.py`
