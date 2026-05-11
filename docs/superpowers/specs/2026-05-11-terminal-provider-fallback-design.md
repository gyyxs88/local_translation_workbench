# 独立终端兜底层设计

## 1. 背景

当前 provider/profile 已支持普通 fallback 链：

```text
requested profile -> fallback_profile_keys_json -> fallback 的 fallback_profile_keys_json -> ...
```

这条链路可以解决主 provider 失败后的自动切换问题，但它有一个配置耦合：中间备用 profile 如果自己维护了 fallback，就会影响最终调用链。用户希望把“最终兜底层”单独拿出来，做到：

- 普通链可以自由配置主模型和备用模型。
- 兜底层固定独立维护。
- 普通链全部失败后，总是进入兜底层。
- 中间备用层无论怎么配置，都不会改变兜底层。

本设计把这层定义为 `terminal fallback`。

## 2. 目标

本轮目标是新增独立的终端兜底配置，并接入所有模型调用入口。

调用顺序固定为：

```text
普通链：
requested profile -> normal fallback 1 -> normal fallback 2

终端兜底层：
terminal fallback 1 -> terminal fallback 2

最终尝试顺序：
requested profile -> normal fallback 1 -> normal fallback 2 -> terminal fallback 1 -> terminal fallback 2
```

触发规则：

- 只要普通链全部失败，就进入终端兜底层。
- 不限制错误类型；`policy_block / rate_limit / timeout / json_parse_failed / empty_response / network_error / server_error` 等 provider 失败都可触发。
- 如果普通链已有任意 profile 成功，不调用终端兜底层。

## 3. 非目标

本轮不做下面这些事：

- 不按错误类型配置不同兜底链。
- 不按 stage 配不同兜底链。
- 不修改 provider 原始请求协议。
- 不改变普通 `fallback_profile_keys_json` 的现有语义。
- 不引入人工交互式修复或自动降级成本策略。
- 不把模型返回的 200 正常拒答文本识别为失败；本轮只处理已经抛出 `ToolError` 的失败。

## 4. 方案选择

### 4.1 方案 A：继续把兜底挂在每个 profile 的 fallback 末尾

做法：

- 手工把最终兜底 profile 加到每条普通 fallback 链最后。

优点：

- 不需要改 schema 或代码。

缺点：

- 配置分散，容易漏。
- 中间备用 profile 的 fallback 仍然会影响最终链路。
- 无法表达“全局固定兜底”这个产品语义。

### 4.2 方案 B：新增全局终端兜底配置

做法：

- 新增独立配置表，保存有序 terminal fallback profile 列表。
- provider 解析时先展开普通链，再追加 terminal fallback 链。
- terminal fallback 链只读取自身配置，不递归读取普通 fallback。

优点：

- 语义清晰。
- 配置集中。
- 中间备用层不会影响最终兜底。
- 改动范围可控。

缺点：

- 需要新增 migration、action、测试和文档。

### 4.3 方案 C：新增按 stage 或按错误类型的兜底策略

做法：

- 针对 glossary / translation / review 或不同 error_type 维护不同兜底链。

优点：

- 最灵活。

缺点：

- 当前需求只要求“普通链失败后固定兜底”。
- 配置面过大，容易让运行链路难以解释。

### 4.4 结论

采用方案 B：新增全局终端兜底配置。

原因：

- 它直接满足“兜底层单独拿出来”的语义。
- 它不破坏现有普通 fallback。
- 后续如果需要按错误类型或 stage 拆分，可以在全局配置之上继续扩展。

## 5. 数据模型

新增表：`ltw_terminal_fallback_profiles`

字段：

- `id`
- `profile_key`
- `position`
- `status`
- `note`
- `created_at`
- `updated_at`

约束：

- `profile_key` 唯一。
- `position` 用于维护有序链。
- `status` 支持 `active / inactive`。
- 写入时要求 `profile_key` 指向已存在的 `ModelProfile`。

这张表只表达终端兜底层，不嵌入到 `ModelProfile.fallback_profile_keys_json`。

## 6. Action 设计

新增三个 action：

- `profile.terminal_fallback_set`
- `profile.terminal_fallback_inspect`
- `profile.terminal_fallback_clear`

### 6.1 `profile.terminal_fallback_set`

参数：

- `fallback_profile_keys_json`：字符串数组 JSON。
- `note`：可选。

语义：

- 整体替换当前终端兜底链。
- 自动去重，保留首次出现顺序。
- 不允许空字符串。
- 不允许不存在的 profile。
- 不读取这些 profile 自己的普通 fallback。

### 6.2 `profile.terminal_fallback_inspect`

返回当前 active 终端兜底链：

```json
{
  "fallback_profile_keys": ["gpt_5_5_kxaug"],
  "profiles": [
    {
      "profile_key": "gpt_5_5_kxaug",
      "provider_key": "kxaug",
      "model_name": "gpt-5.5",
      "status": "active"
    }
  ]
}
```

### 6.3 `profile.terminal_fallback_clear`

语义：

- 清空终端兜底链。
- 普通 fallback 链不受影响。

## 7. 运行时解析

`ProviderResolutionService.resolve_profile_chain()` 继续负责解析普通链。

新增内部步骤：

1. 展开普通链。
2. 读取 active 终端兜底链。
3. 过滤已经在普通链出现过的 profile，避免重复调用。
4. 构建最终候选列表。

候选需要带 `chain_role`：

- `primary`
- `normal_fallback`
- `terminal_fallback`

`fallback_depth` 继续表示最终候选列表里的 0-based 深度，保持现有观测兼容。

新增可观测字段：

- `chain_role`
- `terminal_fallback_used`

成功命中终端兜底时：

```json
{
  "actual_model_profile_id": "gpt_5_5_kxaug",
  "fallback_depth": 2,
  "chain_role": "terminal_fallback",
  "terminal_fallback_used": true
}
```

## 8. 健康检查

`provider.health_check` 默认继续展开普通 fallback。

本轮调整：

- `include_fallbacks=true` 时，同时包含终端兜底链。
- 每个 attempt 返回 `chain_role`。
- 如果成功候选来自终端兜底，返回 `terminal_fallback_used=true`。

`include_fallbacks=false` 时只检查 requested profile，不检查普通 fallback，也不检查 terminal fallback。

## 9. 与 workflow / route preset 的关系

route preset 只决定某个 workflow step 的 requested profile。

例如某 step 绑定：

```text
model_profile_id = gpt_5_5_aicodelink
```

运行时仍按统一规则解析：

```text
gpt_5_5_aicodelink -> 该 profile 的普通 fallback -> 全局 terminal fallback
```

终端兜底不被 route preset 覆盖，也不从 route preset 读取。

## 10. 错误处理

如果普通链和终端兜底链全部失败，最终仍抛出 `provider_error`。

`error.details.attempts` 必须包含所有尝试，并标记：

- `profile_key`
- `provider_key`
- `provider_type`
- `model_name`
- `fallback_depth`
- `chain_role`
- `error_code`
- `error_type`
- `error_message`

这样调用方可以区分：

- 普通链是否失败。
- 是否进入过终端兜底。
- 终端兜底失败原因是什么。

## 11. 测试策略

新增和调整测试覆盖以下场景：

1. 普通链成功
   - 不调用终端兜底。
   - 返回 `terminal_fallback_used=false`。

2. 普通链全部失败，终端兜底成功
   - 返回终端兜底 profile。
   - `chain_role=terminal_fallback`。
   - `terminal_fallback_used=true`。

3. 普通链和终端兜底都失败
   - `provider_error.details.attempts` 包含完整尝试链。
   - attempts 中的 `chain_role` 正确。

4. 中间备用 profile 配置了自己的 fallback
   - 普通递归链仍按现有逻辑展开。
   - 终端兜底固定追加在普通链之后。
   - 修改中间备用的 fallback 不会改变终端兜底配置。

5. health check
   - `include_fallbacks=true` 展开普通 fallback 和 terminal fallback。
   - `include_fallbacks=false` 只检查 requested profile。

6. action
   - set / inspect / clear 正常工作。
   - 不存在 profile、空 key、重复 key 有稳定行为。

## 12. 文档更新

需要同步更新：

- `README.md`
- `docs/operations/setup.md`
- `docs/operations/provider-smoke.md`
- `docs/operations/troubleshooting.md`
- `TOOL.json`

文档重点说明：

- 普通 fallback 和 terminal fallback 的区别。
- 终端兜底会在普通链全部失败后触发。
- 终端兜底不是敏感内容专用。
- route preset 不会覆盖终端兜底。

## 13. 完成标准

本轮完成后，需要满足：

1. 可以通过 action 单独配置终端兜底链。
2. 普通链全部失败后自动进入终端兜底层。
3. 中间备用层的配置不会影响终端兜底层本身。
4. health check 和运行观测能看出是否命中终端兜底。
5. 相关测试通过。
6. 本地中文文档已更新。
