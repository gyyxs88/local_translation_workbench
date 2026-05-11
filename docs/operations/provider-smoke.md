# 真实 provider 联调 smoke 手册

## 1. 目标

本文档用于验证真实 provider 在当前环境下是否能完成最关键的模型调用链，重点覆盖：

- `provider.health_check`
- `glossary` 阶段的真实调用
- `translation` 阶段的真实调用
- `synopsis` 在 translation 阶段中的真实生成与翻译
- 普通 fallback 链和终端兜底链在真实环境中的基本可用性

这份 smoke 不追求覆盖全部业务分支，而是追求：

- 低成本
- 快速定位
- 失败后容易判断到底是环境、provider、profile 还是业务逻辑问题

## 2. 什么时候要跑

建议在下面这些场景运行一次：

- 新接入一个 provider
- 新建一个 profile
- 新配置一条普通 fallback 链或终端兜底链
- provider 的 Base URL、网关或模型名发生变化
- 准备发布一个会影响 provider 调用链的重要版本

## 3. 不建议怎么跑

真实 provider smoke 不建议这样做：

- 不要直接 `project.run_full`
- 不要一上来就跑多章、多段、大文本
- 不要优先跑 multi workflow
- 不要直接把失败归因到业务逻辑，先分层排查

更稳的做法是：

1. 先做 `provider.health_check`
2. 再做单章小样本 `glossary`
3. 再做单章小样本 `translation`
4. 最后用 `inspect.*` 看结果是否完整

## 4. 成本控制建议

为了降低真实 provider 调用成本，推荐固定遵守下面这些约束：

- 样本文本只保留 1 章，正文 1 到 2 段
- glossary 只跑 `chapter_range 1..1`
- translation 只跑 `chapter_range 1..1`
- 显式传 `workflow_key=glossary_single_llm_v1`
- 显式传 `workflow_key=translation_single_llm_v1`
- 每次 smoke 都使用新的 `request_id`

## 5. 前置条件

开始前请确认：

- 已完成 [接入初始化手册](./setup.md)
- 当前从 `D:\Path\To\Workspace` 根目录执行
- 已存在可用的 provider 与 profile
- 如果要测普通 fallback，主 profile 和备份 profile 都已经创建
- 如果要测终端兜底，终端兜底 profile 已经创建，并已通过 `profile.terminal_fallback_set` 配置
- 当前终端里已加载对应的 API Key 环境变量

推荐先确认 profile 列表：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action profile.list
```

## 6. 准备 smoke 样例

### 6.1 生成运行后缀

```powershell
$runId = Get-Date -Format "yyyyMMddHHmmss"
```

### 6.2 准备最小样本文本

```powershell
New-Item -ItemType Directory -Force temp | Out-Null
@'
## 简介

林溪和赵馨宁在河边重逢。

## 正文

### 1

林溪望着赵馨宁，低声说终于找到你了。

赵馨宁笑了笑，说这次不要再走散了。
'@ | Set-Content -Encoding UTF8 temp\ltw-provider-smoke.md
```

## 7. 先做 provider 健康检查

假设要验证的主 profile 是 `demo_default_profile`。
如果你实际环境里用的是别的 profile，请替换成真实 key。

### 7.1 只检查主链，不展开 fallback

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action provider.health_check `
  -ModelProfileId demo_default_profile `
  -IncludeFallbacks false
```

通过标准：

- `ok = true`
- `data.requested_profile_id = demo_default_profile`
- `data.selected_profile_id = demo_default_profile`
- `data.attempts` 至少有一条
- 第一条 attempt 为成功

如果这一步就失败，先不要继续跑 glossary / translation。

### 7.2 再检查 fallback 链

如果该 profile 配置了普通 fallback，或系统配置了终端兜底，再跑一次：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action provider.health_check `
  -ModelProfileId demo_default_profile `
  -IncludeFallbacks true
```

重点关注：

- `requested_profile_id`
- `selected_profile_id`
- `attempts[].ok`
- `attempts[].chain_role`
- `terminal_fallback_used`
- `attempts[].error_code`
- `attempts[].error_message`

说明：

- CLI 帮助不会列出所有扩展参数，但像 `-IncludeFallbacks` 这类参数仍然可以直接传
- `-IncludeFallbacks false` 更适合验证主链是否单独可用
- `-IncludeFallbacks true` 更适合验证普通 fallback 和终端兜底是否能接住主链失败
- `chain_role=terminal_fallback` 表示已经进入全局终端兜底层

## 8. 创建 smoke 项目

```powershell
$createRaw = powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action project.create `
  -RequestId "provider-smoke-project-create-$runId" `
  -SourcePath "D:/path/to/workspace/temp/ltw-provider-smoke.md" `
  -SourceLanguage zh `
  -TargetLanguage en

$create = $createRaw | ConvertFrom-Json
$projectId = $create.data.id
$projectId
```

然后先跑 chaptering：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action stage.run `
  -ProjectId $projectId `
  -Stage chaptering `
  -ScopeType all `
  -RequestId "provider-smoke-chaptering-$runId"
```

建议检查：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action inspect.synopsis `
  -ProjectId $projectId
```

预期：

- source synopsis 已被抽出
- 章节数量和段落数量都正常

## 9. glossary smoke

这里显式使用单 LLM workflow，方便控制成本和定位问题：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action stage.run `
  -ProjectId $projectId `
  -Stage glossary `
  -ScopeType chapter_range `
  -ScopeStart 1 `
  -ScopeEnd 1 `
  -ModelProfileId demo_default_profile `
  -WorkflowKey glossary_single_llm_v1 `
  -RequestId "provider-smoke-glossary-$runId"
```

检查：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action inspect.glossary `
  -ProjectId $projectId
```

通过标准：

- `stage.run` 返回 `ok = true`
- `data.stage = glossary`
- `data.candidate_count >= 1` 或 inspect 结果里能看到结构化条目

## 10. translation smoke

translation smoke 的价值不只是看正文译文，还要顺带验证 synopsis 相关调用是否正常。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action stage.run `
  -ProjectId $projectId `
  -Stage translation `
  -ScopeType chapter_range `
  -ScopeStart 1 `
  -ScopeEnd 1 `
  -ModelProfileId demo_default_profile `
  -WorkflowKey translation_single_llm_v1 `
  -RequestId "provider-smoke-translation-$runId"
```

检查：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action inspect.synopsis `
  -ProjectId $projectId

powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action inspect.translation `
  -ProjectId $projectId

powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action inspect.segment `
  -ProjectId $projectId `
  -ChapterIndex 1 `
  -SegmentIndex 1
```

通过标准：

- `stage.run` 返回 `ok = true`
- `data.stage = translation`
- `data.translated_segments >= 1`
- `data.active_version_ids` 非空
- `inspect.synopsis` 中 target synopsis 为 `ready` 或 `completed`
- `inspect.segment` 能看到当前 active 译文

## 11. 可选：review / export 收尾检查

这两步不属于 provider 核心联调范围，但如果你想顺手确认小闭环，也可以继续跑：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action stage.run `
  -ProjectId $projectId `
  -Stage review `
  -ScopeType chapter_range `
  -ScopeStart 1 `
  -ScopeEnd 1 `
  -RequestId "provider-smoke-review-$runId"

powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action stage.run `
  -ProjectId $projectId `
  -Stage export `
  -ScopeType chapter_range `
  -ScopeStart 1 `
  -ScopeEnd 1 `
  -RequestId "provider-smoke-export-$runId"
```

## 12. smoke 通过标准

满足下面条件，就可以认为这次真实 provider smoke 通过：

- 主 profile 的 `provider.health_check` 成功
- 如果配置了普通 fallback 或终端兜底，fallback 链检查结果可解释
- `glossary` 单章 smoke 成功
- `translation` 单章 smoke 成功
- `inspect.synopsis / inspect.translation / inspect.segment` 返回结构化结果
- 没有出现环境变量缺失、profile 丢失、模型网关不可用、结构化结果无法落库等错误

## 13. 失败分层判断

### 13.1 health_check 就失败

优先排查：

- API Key 环境变量
- provider 的 Base URL
- profile 对应的 provider_key
- 普通 fallback 链是否完整
- 终端兜底链是否完整

这类问题通常先不要怀疑 glossary / translation 业务逻辑。

### 13.2 health_check 成功，但 glossary 失败

优先怀疑：

- glossary prompt 输出格式不符合预期
- 当前模型对 JSON 输出约束不稳定
- workflow / glossary finalize 的结构化裁决失败

### 13.3 glossary 成功，但 translation 失败

优先怀疑：

- translation prompt 或结构化中间产物异常
- synopsis 生成 / 翻译环节异常
- glossary 注入后触发了模型输出漂移

### 13.4 translation 成功，但 inspect 结果异常

优先怀疑：

- 结果已调用成功，但落库或 active version 切换异常
- synopsis / translation 元数据写入不完整

## 14. 建议保留的 smoke 记录

每次 smoke 最好至少保留下列信息，方便后续排查：

- smoke 日期和执行人
- 使用的 provider/profile key
- 是否展开 fallback
- 是否配置并命中终端兜底
- 样本文本路径
- `provider.health_check` 的关键返回
- `glossary` 和 `translation` 的关键返回
- 如果失败，失败发生在哪一步、报错是什么

## 15. 相关文档

- [接入初始化手册](./setup.md)
- [最小试跑手册](./runbook.md)
- [常见故障排查](./troubleshooting.md)
