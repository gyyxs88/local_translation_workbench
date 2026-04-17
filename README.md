# local_translation_workbench

本工具是一个本地翻译工作台，基于本地数据库和数据目录管理小说翻译流程。当前真实实现支持以下动作：

- `project.create` / `project.list` / `project.cancel` / `project.run_full`
- `provider.create` / `provider.list` / `provider.inspect` / `provider.health_check`
- `profile.create` / `profile.list` / `profile.inspect` / `profile.set_fallbacks`
- `workflow.create` / `workflow.list` / `workflow.inspect` / `workflow.set_default`
- `glossary.extract` / `glossary.normalize` / `glossary.review_relations` / `glossary.review_scope` / `glossary.finalize` / `glossary.inspect_pipeline`
- `translation.generate_draft` / `translation.review_draft` / `translation.rewrite_draft` / `translation.finalize` / `translation.inspect_pipeline`
- `stage.run` / `stage.inspect_runs`
- `inspect.project` / `inspect.glossary` / `inspect.synopsis` / `inspect.chapter` / `inspect.chapters` / `inspect.segment` / `inspect.translation` / `inspect.review` / `inspect.export`

## 运行入口

以下示例分为两种上下文：

### 独立 GitHub 仓库

如果当前目录就是 `local_translation_workbench` 仓库根目录，可直接执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run.ps1
python -m pytest tests -q
```

当前实现已经兼容独立仓库模式下的 `tools.local_translation_workbench` 导入路径。
如果它仍作为 `NovelT` 单体仓库下的 `tools/local_translation_workbench` 子目录使用，则继续走下面这组命令。

### NovelT 单体仓库

如果你仍在 `NovelT` 根目录里把它作为 `tools/local_translation_workbench` 子目录使用，则执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests -q
```

## 补充文档

- [路线图](docs/roadmap.md)
- [接入初始化手册](docs/operations/setup.md)
- [最小试跑手册](docs/operations/runbook.md)
- [真实 provider 联调 smoke 手册](docs/operations/provider-smoke.md)
- [常见故障排查](docs/operations/troubleshooting.md)

## 环境变量

凭证和运行配置必须通过环境变量提供，不能写进命令参数、代码、README 或配置文件。

数据库既可以是本机 MySQL，也可以是局域网内可访问的 MySQL 服务器；工具本身不要求必须在本机安装 MySQL，只要求当前机器能连通目标库。

- `LTW_DATABASE_URL`：数据库连接串，所有 action 都需要。
- `LTW_DATA_DIR`：数据目录，未设置时默认使用仓库根目录下的 `data/projects`；如果从 `NovelT` 单体仓库视角看，对应路径是 `tools/local_translation_workbench/data/projects`。
- `LTW_PROVIDER_BASE_URL`：模型服务的 OpenAI-compatible Base URL，`stage.run` 的 `glossary / translation` 阶段可用作默认 provider 回退。
- `LTW_PROVIDER_API_KEY`：模型服务 API Key，`stage.run` 的 `glossary / translation` 阶段可用作默认 provider 回退。

如果使用数据库级 `provider/profile` 配置层，数据库里只保存 `api_key_env_name`，真实 API Key 仍然必须放在环境变量里，例如：

- `LTW_PROVIDER_API_KEY_CODEX_HK`

## Windows 用户级持久化设置示例

下面示例会把变量写入当前用户的持久环境变量；设置后请重新打开 PowerShell、终端或 Codex App，使新值生效。

```powershell
[Environment]::SetEnvironmentVariable("LTW_DATABASE_URL", "mysql+pymysql://<db_user>:<db_password>@<db_host>:<db_port>/<db_name>", "User")
[Environment]::SetEnvironmentVariable("LTW_DATA_DIR", "D:/path/to/local_translation_workbench/data/projects", "User")
[Environment]::SetEnvironmentVariable("LTW_PROVIDER_BASE_URL", "https://<provider-host>/v1", "User")
[Environment]::SetEnvironmentVariable("LTW_PROVIDER_API_KEY", "<provider_api_key>", "User")
[Environment]::SetEnvironmentVariable("LTW_PROVIDER_API_KEY_CODEX_HK", "<provider_api_key>", "User")
```

## 开发回归

- 跑 `pytest` 前必须显式提供 `LTW_TEST_DATABASE_URL`，并且必须指向独立测试库，不能直接复用业务库对应的 `LTW_DATABASE_URL`。
- 当前测试夹具会在会话开始时清空测试库里的全部表，再执行 Alembic 到 `head`；如果误指向业务库，会直接破坏真实数据。
- 不要并行对同一个测试库同时跑两组 `pytest`，否则容易在 MySQL 侧撞锁。
- `LTW_TEST_DATABASE_URL` 同样既可以指向本机测试库，也可以指向局域网 MySQL 上的独立测试库；关键是它必须和业务库彻底隔离。

Windows 用户级持久化示例：

```powershell
[Environment]::SetEnvironmentVariable("LTW_TEST_DATABASE_URL", "mysql+pymysql://<db_user>:<db_password>@<db_host>:<db_port>/<db_name>_ltw_test", "User")
```

局域网 MySQL 独立测试库示例：

```powershell
[Environment]::SetEnvironmentVariable("LTW_TEST_DATABASE_URL", "mysql+pymysql://<db_user>:<db_password>@192.168.31.212:3307/<db_name>_ltw_test", "User")
```

当前仓库实测可用的回归方式：

- 从 `NovelT` 根目录执行
- 当前会话或用户环境中已设置 `LTW_TEST_DATABASE_URL`
- 截至 `2026-04-17`，已验证的完整回归基线为：`242 passed`

```powershell
$env:LTW_TEST_DATABASE_URL = "mysql+pymysql://<db_user>:<db_password>@<db_host>:<db_port>/<db_name>_ltw_test"
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests -q
```

如果已经写入用户级环境变量，也可以直接从 `NovelT` 根目录回归：

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests -q
```

## GitHub Actions / CI

- GitHub Actions 会在临时 MySQL 8 service 上执行完整 `pytest` 回归。
- CI 使用独立测试库连接串，不会连接业务库。
- CI 中 `LTW_TEST_DATABASE_URL` 与 `LTW_DATABASE_URL` 都会指向同一个临时测试库，以保持与当前测试夹具行为一致。
- CI 不接真实 provider API，也不承担外部联调 smoke。

## 动作说明

### `project.create`

创建翻译项目，并在数据目录下初始化项目结构。真实必填参数如下：

- `request_id`：请求幂等标识。
- `source_path`：原文文件路径。后续 `chaptering` 会从这个路径读取源文件。
- `source_language`：源语言。
- `target_language`：目标语言。

创建后会生成项目记录、`project_key`，并在数据目录下创建对应的项目子目录。

### `project.list`

返回当前项目列表，以及每个项目的基本信息和阶段计数摘要。

### `project.cancel`

必填参数：

- `project_id`
- `request_id`

执行后会把项目状态标记为 `cancelled`。已取消项目会拒绝后续 `stage.run`。

### `project.run_full`

必填参数：

- `project_id`
- `request_id`

可选参数：

- `from_stage`
- `until_stage`
- `model_profile_id`
- `resume`
- `rerun`

它只是组合器，默认顺序执行：

- `chaptering`
- `glossary`
- `translation`
- `review`
- `export`

可以用 `from_stage` / `until_stage` 截取阶段窗口。
其中 `model_profile_id` 会传给 `glossary` 和 `translation` 两个模型阶段。

### `provider.create / provider.list / provider.inspect / provider.health_check`

用于管理供应商配置。当前真实支持的 `provider_type` 只有：

- `openai_compatible`
- `anthropic_messages`

`provider.create` 的关键参数包括：

- `provider_key`
- `provider_type`
- `display_name`
- `base_url`
- `api_key_env_name`

注意：这里传入的是“环境变量名”，不是 API Key 本体。
当 `translation` 命中数据库 `profile` 时，真实 key 仍然只会从 `api_key_env_name` 对应的环境变量读取，数据库里不会保存明文 key。
对 Claude 网关，推荐优先使用 `anthropic_messages` 路线，而不是继续走 `openai_compatible` 兼容层。

`provider.health_check` 用于真实探测某个 profile 当前是否可用，并按需要展开 fallback 链：

- `model_profile_id`：可选；未传时按默认 profile 解析。
- `include_fallbacks`：可选，默认 `true`。为 `true` 时会按 profile fallback 链顺序探测，直到某个候选成功或全部失败。
- 返回值里会包含：
- `requested_profile_id`
- `selected_profile_id`
- `attempts`

其中 `attempts` 会列出每个候选 profile 的成功/失败情况、耗时、错误码和错误消息，便于上层 skill 或 agent 判断后续动作。

Claude 路线示例：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action provider.create `
  -ProviderKey codex_hk_anthropic `
  -ProviderType anthropic_messages `
  -DisplayName "Codex HK Anthropic" `
  -BaseUrl "https://codex-api.hk.pe" `
  -ApiKeyEnvName LTW_PROVIDER_API_KEY_CODEX_HK
```

### `profile.create / profile.list / profile.inspect / profile.set_fallbacks`

用于管理可复用模型 profile 和 fallback 链。`glossary / translation` 两个模型阶段的解析规则是：

- `model_profile_id` 显式命中数据库 profile 时，按该 profile 解析 provider 和真实模型名。
- `model_profile_id` 处于默认路径时，也就是未传或传 `default` 时，先尝试数据库默认 profile；只有数据库默认 profile 不存在时，才回退到 `LTW_PROVIDER_BASE_URL + LTW_PROVIDER_API_KEY`。
- `model_profile_id` 显式传入一个不存在的 profile key 时，直接报 `not_found`，不会回退到环境变量。
- 如果命中的 profile 配置了 `fallback_profile_keys`，则无论 `model_profile_id` 是默认解析还是显式传入，运行时都会先尝试该 profile，再按 fallback 顺序自动切换。
- 当 fallback 链里的所有候选都失败时，工具会返回结构化 `provider_error`，并把每次尝试写进 `error.details.attempts`；后续如何处理，由使用该工具的 skill 或 agent 决定。

如果命中数据库 profile，真实 API Key 仍会通过 `provider` 记录里的 `api_key_env_name` 去读取对应环境变量。
`profile.create` 的最小关系是“先有 provider，再挂 profile”，也就是 `profile_key` 绑定 `provider_key`，而 `provider_key` 决定走哪条 `provider_type` 路线。

`profile.set_fallbacks` 用于配置有序 fallback 列表：

- `profile_key`
- `fallback_profile_keys_json`：字符串数组 JSON，例如 `["gpt_5_4_kxaug"]`

fallback 链按给定顺序展开，且会自动去重，避免递归配置导致死循环。

### `workflow.create / workflow.list / workflow.inspect / workflow.set_default`

用于管理 glossary / translation workflow profile。当前真实内置了四条 builtin：

- `glossary_single_llm_v1`：默认 workflow，链路为 `extract -> normalize -> review_relations -> review_scope -> finalize`。
- `glossary_multi_llm_v1`：显式启用的多 LLM glossary workflow，链路为 `extract_primary -> extract_secondary -> normalize -> review_relations -> review_scope -> finalize`。
- `translation_single_llm_v1`：默认 workflow，链路为 `generate_primary -> finalize_segments`。
- `translation_multi_llm_v1`：显式启用的多 LLM translation workflow，链路为 `generate_primary -> generate_secondary -> review_drafts -> rewrite_consensus -> finalize_segments`。

当前 multi workflow 的真实状态如下：

- `glossary_multi_llm_v1` 的两个 extractor step 已改为真实并发执行，运行时会为每个 extractor 使用独立 session 和独立 pipeline worker。
- `glossary_multi_llm_v1` 仍然保留 draft candidate 与 review evidence 的结构化存储，便于后续 inspect / rerun。
- `glossary_multi_llm_v1` 的 tolerant group 语义保持不变；当只成功一路 extractor 时，workflow 仍可按 degraded 状态继续推进。
- glossary 默认 workflow 仍然是 `glossary_single_llm_v1`，translation 默认 workflow 仍然是 `translation_single_llm_v1`，都不会自动切到 multi。
- `translation_multi_llm_v1` 现在会在 `generate_primary / generate_secondary / review_drafts / rewrite_consensus / finalize_segments` 五个 step 内部按 segment 并发执行，同时保留现有 draft version、draft review 与正式译文版本结构。

`chaptering` 当前已验证支持两类常见章节边界：

- 传统正文标题，例如 `第1章`、`第2回`
- Markdown 数字标题，例如 `### 1`、`### 2`

对于 Markdown 输入，如果章节标题前还有书名、简介、`## 正文` 之类的前置内容，`chaptering` 会把它们从正文里识别出来；其中显式简介会进入项目级 synopsis，不再混进第一章正文。

### glossary 联动

- `glossary` 现在会通过 workflow runner 调用 glossary 原子动作，不再是示例硬编码词表。
- glossary 原子动作已对外暴露：`glossary.extract / glossary.normalize / glossary.review_relations / glossary.review_scope / glossary.finalize / glossary.inspect_pipeline`。
- `glossary_single_llm_v1` 和 `glossary_multi_llm_v1` 都已内置；前者仍是默认，后者需要显式传 `workflow_key`。
- 抽取 prompt 要求模型直接返回 JSON，当前收口字段对齐生产侧常见口径：`source_term / translated_term / category / note / gender / age_group / term_group_key / relation_role`。
- 本地正式术语表当前保存为 `source_term / target_term / category / note / gender / age_group / term_group_key / relation_role`。
- `gender` 当前只对 `category=character` 生效，取值收口为 `female / male / nonbinary / null`。
- `age_group` 当前只对 `category=character` 生效，取值收口为 `child / teen / adult / elderly / null`。
- `term_group_key / relation_role` 允许正式名、简称、称号等多个表面形式共存，例如 `张望月 / 望月`、`林溪 / 小溪`。
- 像 `第1章`、`第一卷` 这类纯结构壳会在裁决阶段剔除，但标题里的真实术语会保留。
- multi glossary workflow 会保留结构化 draft candidate 与 review evidence；最终 finalize 再落正式 glossary entry。
- `inspect.glossary` 现在会返回 `entries[*].gender / age_group`，以及 `candidates[*].category / note / gender / age_group`；`glossary.inspect_pipeline` 的 draft candidate 也会返回 `gender / age_group`。
- `translation` 会读取当前有效术语，按正文实际命中做 span 级匹配和局部重叠裁决，只把命中当前段落正文的最终术语注入 prompt，不再走全局最长优先。
- 当 glossary entry 的 `gender` 非空时，translation prompt 会额外注入 `| gender: ...`。
- 当 glossary entry 的 `age_group` 非空时，translation prompt 会额外注入 `| age_group: ...`。
- 译文版本里的 `glossary_snapshot_id` 现在基于当前有效术语表实时计算，不再写死占位值，并且会感知 `gender / age_group` 变化。
- `translation` 已收口到 workflow runner，当前默认走 `translation_single_llm_v1`；显式传 `translation_multi_llm_v1` 时，会按 `generate_draft -> review_draft -> rewrite_draft -> finalize` 跑多轮链路。
- `translation.generate_draft / review_draft / rewrite_draft` 只写 workflow 中间产物，不会提前切 active version；只有 `translation.finalize` 会写正式 `SegmentTranslationVersion`。
- 当 glossary / translation / synopsis 命中 fallback 链时，当前实现会保留真实命中的模型元数据：
- synopsis 行会记录真实 `model_profile_id`
- draft version / 正式译文版本会记录真实 `model_profile_id`
- workflow step payload 会补充 `requested_model_profile_id / actual_model_profile_id / fallback_depth`

### synopsis 联动

- `chaptering` 会抽取显式简介，并从正文剥离。
- `translation` 会先补齐项目级 synopsis，再翻正文。
- `inspect.synopsis` 可查看 synopsis 全文和元数据。
- `inspect.chapter / inspect.chapters` 可按章节查看段落状态、active version 和变脏情况。
- `inspect.segment` 可按单段直接查看原文、当前 active 译文和元数据。
- `export` 会独立输出原文/目标语言简介，目标简介支持 `ready` / `completed`，空白内容视为无效，并在缺少可用 target synopsis 时拒绝导出；简介会用隔离的 fenced 文本块输出。
- 如果 synopsis 调用命中了 fallback 链，source / target synopsis 也会保留真实命中的 `model_profile_id`，而不是只保留请求入口的 profile。

### `stage.run`

运行阶段任务。真实支持的 `stage` 值如下：

- `chaptering`
- `glossary`
- `translation`
- `review`
- `export`

真实必填参数如下：

- `request_id`：请求幂等标识。
- `project_id`：项目 ID。
- `stage`：阶段名称。

可选参数如下：

- `scope_type`：作用范围，默认 `all`。
- `scope_start`：`chapter_range` 时必填。
- `scope_end`：`chapter_range` 时必填。
- `scope_chapters`：`chapter_list` 时必填，逗号分隔整数列表。
- `model_profile_id`：模型配置名，默认 `default`。
- `workflow_key`：可选。`glossary` 阶段可显式指定 `glossary_single_llm_v1` 或 `glossary_multi_llm_v1`；`translation` 阶段可显式指定 `translation_single_llm_v1` 或 `translation_multi_llm_v1`。
- `resume`：布尔值，恢复最近一次失败/运行中的同阶段任务。
- `rerun`：布尔值，基于最近一次同范围任务重新执行。

`scope_type` 的真实支持值是：

- `all`
- `chapter_range`
- `chapter_list`
- `stale_only`
- `failed_only`
- `missing_only`

各阶段支持边界如下：

- `chaptering / glossary / export`：只支持 `all / chapter_range / chapter_list`
- `translation`：支持 `all / chapter_range / chapter_list / stale_only / failed_only / missing_only`
- `review`：支持 `all / chapter_range / chapter_list / missing_only`

补充语义：

- `stale_only` 仅允许 `translation` 阶段使用。
- `failed_only` 仅允许 `translation` 阶段使用，且只会补跑已经标记为 `translation_status=failed` 的段落。
- `missing_only` 允许 `translation / review` 使用；`translation` 会筛选“还没有 active version”的段落，`review` 会筛选“已有 active version 但还没 reviewed”的段落。

补充约束：

- `chapter_range` 必须同时提供 `scope_start` 和 `scope_end`，且 `scope_start` 不能大于 `scope_end`。
- `chapter_list` 必须提供 `scope_chapters`，格式是逗号分隔的章节编号。
- `resume` 和 `rerun` 不能同时为真。
- `glossary / translation` 阶段都要求存在可用 provider。
- 如果 `model_profile_id` 能命中数据库 profile，则 `glossary / translation` 阶段都会改为要求对应的 `api_key_env_name` 已在环境变量里设置。
- 如果默认 profile 不存在，则 `glossary / translation` 会回退到 `LTW_PROVIDER_BASE_URL + LTW_PROVIDER_API_KEY`。
- 如果命中的数据库 profile 配置了 fallback 链，则 `stage.run` 会自动按“请求 profile -> fallback profile 列表”的顺序尝试；即使显式传了 `model_profile_id` 也一样。
- 若某次调用最终落到 fallback profile，正式 synopsis / glossary workflow payload / translation workflow payload / 正式译文版本都会保留真实命中的 profile 信息。
- 若 fallback 链全部失败，`stage.run` 会返回结构化 `provider_error`，其中 `error.details.attempts` 可直接用于上层 agent 的后续决策。

### `stage.inspect_runs`

查看阶段执行记录。必填参数：

- `project_id`

可选参数：

- `stage`
- `limit`

返回结果里：

- `summary` 现在直接是对象，不再是 JSON 字符串
- failed run 会额外返回 `diagnostics`
- 当前 `diagnostics` 会包含：
  - `error`
  - `failure_step`
  - `model_profile_id`
  - `model_name`

### `inspect.project`

查看项目基本信息和各类统计计数。必填参数只有：

- `project_id`

### `inspect.glossary`

查看术语表信息。必填参数只有：

- `project_id`

返回内容当前至少包括：

- `entries[*].gender`
- `entries[*].age_group`
- `candidates[*].category`
- `candidates[*].note`
- `candidates[*].gender`
- `candidates[*].age_group`

### `inspect.synopsis`

查看 synopsis 全文和元数据。必填参数只有：

- `project_id`

### `inspect.chapter`

查看单章详情。必填参数：

- `project_id`

章节定位参数必须且只能提供一个：

- `chapter_id`
- `chapter_index`

返回内容包括：

- 章节基础信息
- 章节级摘要，例如段落数、已翻译数、失败数、已审校数、active version 数
- 当前章节全部段落的 `translation_status / review_status`
- 每个段落当前 active version 的核心元数据与译文内容

### `inspect.chapters`

查看多章节摘要。必填参数：

- `project_id`

可选参数：

- `scope_type`：默认 `all`，只支持 `all / chapter_range / chapter_list`
- `scope_start`：`chapter_range` 时必填
- `scope_end`：`chapter_range` 时必填
- `scope_chapters`：`chapter_list` 时必填
- `include_segments`：布尔值，默认 `false`；为 `true` 时会额外展开每章的段落明细

注意：

- `inspect.chapters` 不支持 `stale_only / failed_only / missing_only`
- 默认只返回章节级摘要；需要段落级明细时再显式传 `include_segments=true`

### `inspect.segment`

查看单段详情。必填参数：

- `project_id`

段落定位参数必须且只能使用一种方式：

- `segment_id`
- `chapter_index + segment_index`

返回内容包括：

- 段落基础信息
- `translation_status / review_status / active_version_id`
- `source_text / translated_text`
- 当前 active version 的核心元数据

注意：

- 当段落没有 active version 时，`translated_text` 和 `current_version` 都会返回 `null`
- 当前只返回 current active version，不返回历史版本列表

### `inspect.translation`

查看翻译版本、当前激活版本、当前 `active version` 的 provenance、当前来源链 `timeline`，以及单段 compare 结果。当前 provenance 会解释：

- 这条正式译文来自哪次 `translation.finalize`
- finalize 最终选中了哪条 draft
- 这条 selected draft 收到过哪些 review 结论

当前 `timeline` 会补充这条 active version 的来源链事件序列，当前事件类型固定为：

- `draft_created`
- `review_created`
- `finalize_committed`

当前 `timeline` 约束：

- 只解释当前 active version 的来源链，不返回 full timeline
- 没有 active version 或 provenance 缺失时，返回空数组 `[]`
- 当前 `occurred_at` 统一返回 `null`，因为底层事件表还没有独立时间戳字段

普通模式必填参数只有：

- `project_id`

可选单段定位参数：

- `segment_id`
- `chapter_index + segment_index`

compare 模式规则：

- 只能在单段模式下使用
- 需要额外传 `compare_version_id`
- 返回当前 active version 与指定历史正式版本之间的结构化变化摘要

当前 compare 摘要只覆盖：

- `translated_text_changed`
- `source_hash_changed`
- `glossary_snapshot_changed`
- `model_profile_changed`
- `model_name_changed`
- `status_changed`

### `inspect.review`

查看审校信息。必填参数只有：

- `project_id`

### `inspect.export`

查看导出运行和导出产物。必填参数只有：

- `project_id`

## 默认数据目录

如果没有设置 `LTW_DATA_DIR`，工具会使用：

```text
data/projects
```

每个项目会在该目录下创建自己的子目录，并继续划分 `source`、`translation`、`artifacts`、`exports` 等内容。

如果当前仍从 `NovelT` 单体仓库根目录看这套工具，对应实际路径就是：

```text
tools/local_translation_workbench/data/projects
```

## 发布建议流程

1. 更新 `CHANGELOG.md`
2. 确认本地回归与 GitHub Actions CI 通过
3. 打 tag，例如 `v0.1.0`
4. 在 GitHub 创建 Release，并把本次变更摘要写入 Release notes
