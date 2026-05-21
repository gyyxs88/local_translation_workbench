# local_translation_workbench

本工具是一个本地翻译工作台，基于本地数据库和数据目录管理小说翻译流程。当前真实实现支持以下动作：

- `project.create` / `project.list` / `project.cancel` / `project.run_full`
- `provider.create` / `provider.list` / `provider.inspect` / `provider.set_key` / `provider.health_check`
- `profile.create` / `profile.list` / `profile.inspect` / `profile.set_fallbacks`
- `profile.terminal_fallback_set` / `profile.terminal_fallback_inspect` / `profile.terminal_fallback_clear`
- `profile.route_set` / `profile.route_list` / `profile.route_inspect` / `profile.route_set_default`
- `workflow.create` / `workflow.list` / `workflow.inspect` / `workflow.set_default`
- `glossary.extract` / `glossary.normalize` / `glossary.review_relations` / `glossary.review_scope` / `glossary.review_consistency` / `glossary.finalize` / `glossary.inspect_pipeline`
- `glossary.entry.create` / `glossary.entry.update` / `glossary.entry.delete` / `glossary.entry.lock` / `glossary.entry.unlock`
- `glossary.candidate.create` / `glossary.candidate.update` / `glossary.candidate.approve` / `glossary.candidate.reject` / `glossary.candidate.delete` / `glossary.candidate.promote`
- `glossary.denylist.add` / `glossary.denylist.list` / `glossary.denylist.delete`
- `translation.generate_draft` / `translation.review_draft` / `translation.rewrite_draft` / `translation.finalize` / `translation.inspect_pipeline`
- `annotation.extract` / `annotation.inspect` / `annotation.approve` / `annotation.reject`
- `stage.run` / `stage.cancel` / `stage.inspect_runs`
- `inspect.project` / `inspect.glossary` / `inspect.synopsis` / `inspect.chapter` / `inspect.chapters` / `inspect.segment` / `inspect.translation` / `inspect.translation_samples` / `inspect.review` / `inspect.export` / `inspect.provider_calls` / `inspect.provider_costs`

## Codex skill

本工具按“skill + 代码”的方式使用时，agent 侧规则位于 `codex_skill/local_translation_workbench/SKILL.md`。
其中包含术语仲裁边界：工具代码只产出候选、证据和检查结果，多 LLM 术语结果的最终译名选择、降级为注释或拒绝进入 glossary，由使用工具的 agent 在 skill 规则下完成。

如果是拿到 zip 发布包的外部用户，优先阅读根目录 `INSTALL.md` 和
`docs/operations/release-install.md`。其中说明了如何解压、创建虚拟环境、设置
`LTW_DATABASE_URL` / `LTW_DATA_DIR`、初始化数据库、创建 provider/profile，以及如何把
`TOOL.json` 和 `codex_skill/local_translation_workbench` 接入自己的 Codex。

## 运行入口

当前默认仓库是独立 GitHub 仓库：

```text
https://github.com/gyyxs88/local_translation_workbench.git
```

本文档默认以 `local_translation_workbench` 仓库根目录为工作目录。新环境建议直接检出独立仓库：

```powershell
git clone https://github.com/gyyxs88/local_translation_workbench.git
cd local_translation_workbench
```

安装后优先使用标准 CLI：

```powershell
.\.venv\Scripts\python.exe -m pip install -e .[test]
.\.venv\Scripts\ltw.exe help
.\.venv\Scripts\ltw.exe doctor
.\.venv\Scripts\ltw.exe migrate
.\.venv\Scripts\ltw.exe -Action project.list
python -m pytest tests -q
```

Windows 源码模式仍兼容原入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run.ps1 help
```

Linux/macOS 源码模式使用：

```sh
sh scripts/run.sh help
```

当前实现已经兼容独立仓库模式下的 `tools.local_translation_workbench` 导入路径。
历史单体仓库形态仅作为旧环境兼容，不再作为本 README 的默认入口。

### NovelT 单体仓库

如果你仍在 `NovelT` 根目录里把它作为 `tools/local_translation_workbench` 子目录使用，则执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests -q
```

## 补充文档

- [发布包安装快速指引](INSTALL.md)
- [发布包安装与 Codex 接入手册](docs/operations/release-install.md)
- [在线发布手册](docs/operations/online-release.md)
- [路线图](docs/roadmap.md)
- [接入初始化手册](docs/operations/setup.md)
- [最小试跑手册](docs/operations/runbook.md)
- [真实 provider 联调 smoke 手册](docs/operations/provider-smoke.md)
- [常见故障排查](docs/operations/troubleshooting.md)

## 环境变量

供应商、模型和 provider API Key 统一通过数据库配置。provider API Key 会明文保存到数据库的 `api_key_value` 字段。

注意：数据库保存的 key 不会在 `provider.list / provider.inspect` 输出中明文返回，只会返回打码后的 `api_key_masked` 和 `api_key_source`。但数据库本身仍然是明文保存，必须按敏感数据保护。

数据库既可以是本机 MySQL，也可以是局域网内可访问的 MySQL 服务器；工具本身不要求必须在本机安装 MySQL，只要求当前机器能连通目标库。

- `LTW_DATABASE_URL`：数据库连接串，所有 action 都需要。
- `LTW_DATA_DIR`：数据目录，未设置时默认使用仓库根目录下的 `data/projects`。

## 文本计数规则

- 中文、日文、韩文文本的“字数”按去空白字符数统计。
- 非中文、日文、韩文文本的“字数”按单词数统计，例如英文译文按 words 计数，不按字母数或字符数计数。
- 返回 `length` 的摘要类 payload 会同时返回 `length_unit`，当前取值为 `characters` 或 `words`。

模型阶段不再读取 `LTW_PROVIDER_BASE_URL / LTW_PROVIDER_API_KEY` 作为 provider 回退；必须先创建数据库 `provider/profile`。

## Windows 用户级持久化设置示例

下面示例会把变量写入当前用户的持久环境变量；设置后请重新打开 PowerShell、终端或 Codex App，使新值生效。

```powershell
[Environment]::SetEnvironmentVariable("LTW_DATABASE_URL", "mysql+pymysql://<db_user>:<db_password>@<db_host>:<db_port>/<db_name>", "User")
[Environment]::SetEnvironmentVariable("LTW_DATA_DIR", "D:/path/to/local_translation_workbench/data/projects", "User")
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
[Environment]::SetEnvironmentVariable("LTW_TEST_DATABASE_URL", "mysql+pymysql://<db_user>:<db_password>@<db_host>:<db_port>/<db_name>_ltw_test", "User")
```

当前仓库实测可用的回归方式：

- 从 `local_translation_workbench` 仓库根目录执行
- 当前会话或用户环境中已设置 `LTW_TEST_DATABASE_URL`
- 截至 `2026-05-11`，已验证的完整回归基线为：`431 passed`

```powershell
$env:LTW_TEST_DATABASE_URL = "mysql+pymysql://<db_user>:<db_password>@<db_host>:<db_port>/<db_name>_ltw_test"
.\.venv\Scripts\python.exe -m pytest tests -q
```

如果已经写入用户级环境变量，也可以直接从仓库根目录回归：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
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

返回当前项目列表，以及每个项目的基本信息、源文件可读名称、简介状态、重复导入提示、阶段计数摘要和下一步建议。

列表项会包含：

- `title`：从 `source_path` 文件名推导出的小说名，便于直接识别项目。
- `source_path`：项目原文路径。
- `source_synopsis_status / target_synopsis_status`：项目简介状态。
- `is_duplicate / duplicate_group_key / duplicate_count / duplicate_project_ids`：按规范化源文件路径识别出的重复导入项目，只做提示，不自动合并或删除。
- `counts.segments`：章节分片数，可辅助判断翻译是否已覆盖全部分片。
- `next_stage_hint`：根据当前计数给出的下一步建议，例如继续 `chaptering / glossary / translation / review / export`，其中 `scope_type` 可直接作为后续 `stage.run` 的参考。

### `project.cancel`

必填参数：

- `project_id`
- `request_id`

执行后会把项目状态标记为 `cancelled`。已取消项目会拒绝后续 `stage.run`。
如果项目中仍存在 `running` 的 stage run、workflow run 或 workflow step run，取消动作会把这些运行记录标记为 `cancelled`，并清理当前项目 lease。正在执行中的 `stage.run` 会在后续 heartbeat 处感知取消并中止。

### `project.run_full`

必填参数：

- `project_id`
- `request_id`

可选参数：

- `from_stage`
- `until_stage`
- `model_profile_id`
- `route_preset_key`
- `resume`
- `rerun`

它只是组合器，默认顺序执行：

- `chaptering`
- `glossary`
- `translation`
- `review`
- `export`

可以用 `from_stage` / `until_stage` 截取阶段窗口。
其中 `model_profile_id` 会传给 `glossary`、`translation` 和默认 `hybrid` 的 `review` 模型阶段。
如果同时传入 `route_preset_key`，则模型 workflow 会按 route preset 为不同 step 选择不同 profile。

### `provider.create / provider.list / provider.inspect / provider.set_key / provider.health_check`

用于管理供应商配置。当前真实支持的 `provider_type` 只有：

- `openai_compatible`
- `anthropic_messages`

`provider.create` 的关键参数包括：

- `provider_key`
- `provider_type`
- `display_name`
- `base_url`
- `api_key_value`：必填，明文 API Key。

`provider.inspect` 会返回 `api_key_is_set / api_key_source / api_key_masked`，不会返回完整 key。
对 Claude 网关，推荐优先使用 `anthropic_messages` 路线，而不是继续走 `openai_compatible` 兼容层。

`provider.set_key` 用于更新已有 provider 的 key 配置：

- `provider_key`
- `api_key_value`

`provider.health_check` 用于真实探测某个 profile 当前是否可用，并按需要展开 fallback 链：

- `model_profile_id`：可选；未传时按默认 profile 解析。
- `include_fallbacks`：可选，默认 `true`。为 `true` 时会按普通 profile fallback 链顺序探测；如果普通链全部失败且配置了终端兜底链，会继续探测终端兜底链。为 `false` 时只探测请求 profile。
- 返回值里会包含：
- `requested_profile_id`
- `selected_profile_id`
- `terminal_fallback_used`
- `attempts`

其中 `attempts` 会列出每个候选 profile 的成功/失败情况、链路角色 `chain_role`、耗时、错误码、错误类型和错误消息，便于上层 skill 或 agent 判断后续动作。`chain_role` 当前包括 `primary / normal_fallback / terminal_fallback`。当前错误类型包括 `rate_limit / policy_block / timeout / json_parse_failed / empty_response / auth_error / network_error / server_error / not_found / invalid_arguments / unknown`。

Claude 路线示例：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run.ps1 `
  -Action provider.create `
  -ProviderKey codex_hk_anthropic `
  -ProviderType anthropic_messages `
  -DisplayName "Codex HK Anthropic" `
  -BaseUrl "https://provider.example.com" `
  -ApiKeyValue "<provider_api_key>"
```

### `profile.create / profile.list / profile.inspect / profile.set_fallbacks`

用于管理可复用模型 profile 和 fallback 链。`glossary / translation` 两个模型阶段的解析规则是：

- `model_profile_id` 显式命中数据库 profile 时，按该 profile 解析 provider 和真实模型名。
- `model_profile_id` 处于默认路径时，也就是未传或传 `default` 时，必须存在数据库默认 profile；不存在则直接报错。
- `model_profile_id` 显式传入一个不存在的 profile key 时，直接报 `not_found`，不会回退到环境变量。
- 如果命中的 profile 配置了 `fallback_profile_keys`，则无论 `model_profile_id` 是默认解析还是显式传入，运行时都会先尝试该 profile，再按普通 fallback 顺序自动切换。
- 如果普通 fallback 链全部失败，且已经配置终端兜底链，运行时会继续尝试终端兜底 profile。终端兜底链独立维护，不读取中间备用 profile 自己的 fallback 配置。
- 当 fallback 链里的所有候选都失败时，工具会返回结构化 `provider_error`，并把每次尝试写进 `error.details.attempts`；后续如何处理，由使用该工具的 skill 或 agent 决定。

如果命中数据库 profile，真实 API Key 会从 `provider` 记录里的 `api_key_value` 读取。
`profile.create` 的最小关系是“先有 provider，再挂 profile”，也就是 `profile_key` 绑定 `provider_key`，而 `provider_key` 决定走哪条 `provider_type` 路线。

`profile.set_fallbacks` 用于配置有序 fallback 列表：

- `profile_key`
- `fallback_profile_keys_json`：字符串数组 JSON，例如 `["fallback_gpt_profile"]`

fallback 链按给定顺序展开，且会自动去重，避免递归配置导致死循环。

### `profile.terminal_fallback_set / profile.terminal_fallback_inspect / profile.terminal_fallback_clear`

用于管理独立的“终端兜底链”。它和普通 profile fallback 的区别是：

- 普通 fallback 属于某个 profile，例如 `主 profile -> 备用 profile`。
- 终端兜底链是全局固定尾链，只有当普通链全部失败后才会触发。
- 终端兜底不是敏感内容专用；限流、超时、网络错误、上游 5xx、JSON 解析失败、空响应、`policy_block` 等普通链失败都可触发。
- 中间备用 profile 怎么配置，都不会改变终端兜底链本身。
- 如果普通链已经成功，不会调用终端兜底，避免额外成本。

配置示例：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run.ps1 `
  -Action profile.terminal_fallback_set `
  -FallbackProfileKeysJson "[\"gpt_5_5_kxaug\"]" `
  -Note "全局终端兜底"
```

查看与清空：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run.ps1 `
  -Action profile.terminal_fallback_inspect

powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run.ps1 `
  -Action profile.terminal_fallback_clear
```

### PowerShell 下的 UTF-8 文件参数

复杂 JSON 或包含较多中文的文本不要直接塞进 PowerShell 原生命令参数。所有 action 参数都支持两种 UTF-8 文件读取方式：

- `-XxxFile <path>`：例如 `-BindingsJsonFile temp/bindings.json`、`-DefinitionJsonFile temp/workflow.json`、`-NoteFile temp/note.txt`。
- `@<path>`：例如 `-Note @temp/note.txt`，当 `@` 后面的路径存在时，CLI 会按 UTF-8/UTF-8-SIG 读取文件内容。

因此涉及 `bindings_json`、`definition_json`、`fallback_profile_keys_json`、中文 `note`、中文 `display_name` 等配置时，推荐先写入 `temp/` 下的 UTF-8 文件，再用 `-XxxFile` 传入，避免 PowerShell 对 JSON 引号或中文管道文本做二次处理。

### `profile.route_set / profile.route_list / profile.route_inspect / profile.route_set_default`

用于管理“模型路由 preset”。这层配置解决的是同一个 workflow 里不同 step 使用不同模型的问题，例如主 LLM 用 GPT-5.5，副 LLM 用 DeepSeek。

当前配置层次是：

- `provider`：供应商、base URL、key 来源。
- `profile`：具体模型，例如 `primary_gpt_profile`、`secondary_deepseek_profile`。
- `route preset`：把 workflow step 绑定到 profile，例如 `extract_primary -> primary_gpt_profile`、`extract_secondary -> secondary_deepseek_profile`。

`profile.route_set` 会创建或覆盖一套 preset，关键参数包括：

- `preset_key`
- `display_name`
- `bindings_json`：对象数组 JSON。
- `bindings_json_file`：从 UTF-8 文件读取对象数组 JSON，PowerShell 入口可写成 `-BindingsJsonFile`。
- `is_default`
- `status`
- `note`

`bindings_json` 的最常用写法是按 `stage + step_key` 绑定：

```json
[
  {"stage":"glossary","step_key":"extract_primary","model_profile_id":"primary_gpt_profile"},
  {"stage":"glossary","step_key":"extract_secondary","model_profile_id":"secondary_deepseek_profile"},
  {"stage":"translation","step_key":"generate_primary","model_profile_id":"primary_gpt_profile"},
  {"stage":"translation","step_key":"generate_secondary","model_profile_id":"secondary_deepseek_profile"},
  {"stage":"translation","step_key":"review_drafts","model_profile_id":"primary_gpt_profile"},
  {"stage":"translation","step_key":"rewrite_consensus","model_profile_id":"primary_gpt_profile"}
]
```

也可以用 `action / llm_role / draft_role` 做更宽的匹配；优先级是精确 `step_key` 最高，其次按 action/role 匹配。

运行时如果传了 `route_preset_key`，workflow step 会先查 route preset；命中绑定时使用绑定的 `model_profile_id`，未命中时回退到 workflow 原本的 `model_profile_id` 或本次请求的默认 profile。

`profile.route_set_default` 会把某个 route preset 设为默认；之后 `stage.run` 如果没有显式传 `route_preset_key`，会自动使用这个默认 preset。它还支持 `workflow_mode`：

- `keep`：默认值，只切默认 route preset，不改 workflow 默认值。
- `multi`：同时把 `glossary_multi_llm_v1 / translation_multi_llm_v1` 设为默认，适合 GPT + DeepSeek 双模型路线。
- `single`：同时把 `glossary_single_llm_v1 / translation_single_llm_v1` 设为默认，适合回到单模型路线。

### `workflow.create / workflow.list / workflow.inspect / workflow.set_default`

`workflow.create` 支持 `definition_json` 和 `definition_json_file`。在 Windows PowerShell 下创建自定义 workflow 时，优先使用 `-DefinitionJsonFile` 传 UTF-8 JSON 文件。

用于管理 glossary / translation workflow profile。当前真实内置了四条 builtin：

- `glossary_single_llm_v1`：默认 workflow，链路为 `extract -> normalize -> review_relations -> review_scope -> review_consistency -> finalize`。
- `glossary_multi_llm_v1`：显式启用的多 LLM glossary workflow，链路为 `extract_primary -> extract_secondary -> normalize -> review_relations -> review_scope -> review_consistency -> finalize`。
- `translation_single_llm_v1`：默认 workflow，链路为 `generate_primary -> finalize_segments`。
- `translation_multi_llm_v1`：显式启用的多 LLM translation workflow，链路为 `generate_primary -> generate_secondary -> review_drafts -> rewrite_consensus -> finalize_segments`。

当前 multi workflow 的真实状态如下：

- `glossary_multi_llm_v1` 的两个 extractor step 已改为真实并发执行，运行时会为每个 extractor 使用独立 session 和独立 pipeline worker。
- `glossary.extract` 在每个 extractor 内部还会按章节并发执行，默认最多 3 个章节 worker；因此 multi glossary 在默认设置下最多会形成“2 路 extractor × 3 个章节 worker”的并发扇出。
- 章节级并发只依赖已落库的 active glossary 和当前章节命中的术语上下文；同一批次中新抽出的术语会在后续 normalize / review / finalize 后进入正式术语表，不作为同批其它章节 extractor prompt 的即时上下文。
- `glossary_multi_llm_v1` 仍然保留 draft candidate 与 review evidence 的结构化存储，便于后续 inspect / rerun。
- `review_consistency` 会在 finalize 前统一检查本批 draft candidate 的一致性：同源不同译、与 locked/active 正式术语冲突、关系组内 category/gender/age/canonical 冲突，以及按 category 的翻译风格一致性。
- 风格检查必须以已有 active glossary 中同 category 的正式术语作为基准；没有正式术语基准的 category 只做本批内部一致性检查，不把本批 draft 自己当成风格基准。
- `glossary_multi_llm_v1` 的 tolerant group 语义保持不变；当只成功一路 extractor 时，workflow 仍可按 degraded 状态继续推进。
- glossary 默认 workflow 仍然是 `glossary_single_llm_v1`，translation 默认 workflow 仍然是 `translation_single_llm_v1`，都不会自动切到 multi。
- `translation_multi_llm_v1` 现在会在 `generate_primary / generate_secondary / review_drafts / rewrite_consensus / finalize_segments` 五个 step 内部按 segment 并发执行，同时保留现有 draft version、draft review 与正式译文版本结构。

`chaptering` 当前已验证支持两类常见章节边界：

- 传统正文标题，例如 `第1章`、`第2回`
- Markdown 数字标题，例如 `### 1`、`### 2`

对于 Markdown 输入，如果章节标题前还有书名、简介、`## 正文` 之类的前置内容，`chaptering` 会把它们从正文里识别出来；其中显式简介会进入项目级 synopsis，不再混进第一章正文。

当前 `segment` 的真实语义已经收口为“章节内翻译分片”：

- 短章节默认只生成 1 个 `segment`
- 长章节会按固定规则拆成多个 `segment`
- 切分优先使用自然段边界；如果单个自然段超长，再退化到句级切分
- `segment_index` 表示“本章第几个翻译分片”，不是自然段编号

### glossary 联动

- `glossary` 现在会通过 workflow runner 调用 glossary 原子动作，不再是示例硬编码词表。
- glossary 原子动作已对外暴露：`glossary.extract / glossary.normalize / glossary.review_relations / glossary.review_scope / glossary.review_consistency / glossary.finalize / glossary.inspect_pipeline`。
- agent 侧手工维护术语时，使用 `glossary.entry.*` 管理正式术语，使用 `glossary.candidate.*` 管理临时候选术语；这些 action 面向 agent 编排，不面向人工交互 UI。
- `glossary_single_llm_v1` 和 `glossary_multi_llm_v1` 都已内置；前者仍是默认，后者需要显式传 `workflow_key`。
- 抽取 prompt 要求模型直接返回 JSON envelope：有新增术语时返回 `{"extraction_status":"terms_found","terms":[...]}`；无新增术语时必须返回 `{"extraction_status":"no_new_terms","terms":[],"reason":"..."}`，不能用空字符串、`null`、空数组或缺少 status 的 `{"terms":[]}` 表示空结果。
- 术语抽取会先注入当前章节标题和正文真实命中的已有术语，用于保持译名和 `term_group_key / relation_role` 一致；未命中当前章节的全局术语不会进入 extractor prompt。
- 本地正式术语表当前保存为 `source_term / target_term / category / note / gender / age_group / term_group_key / relation_role`。
- `gender` 当前只对 `category=character` 生效，取值收口为 `female / male / nonbinary / null`。
- `age_group` 当前只对 `category=character` 生效，取值收口为 `child / teen / adult / elderly / null`。
- `term_group_key / relation_role` 允许正式名、简称、称号等多个表面形式共存，例如 `张望月 / 望月`、`林溪 / 小溪`。
- 像 `第1章`、`第一卷` 这类纯结构壳会在裁决阶段剔除，但标题里的真实术语会保留。
- 单个中文字符的候选术语会被质量层过滤为 `unsafe_short_source_term`，不会进入翻译 prompt 或 hard review 的术语命中检查；这类短项缺少可靠分词边界，容易把普通语境误判成专有术语。
- multi glossary workflow 会保留结构化 draft candidate 与 review evidence；最终 finalize 再落正式 glossary entry。
- `glossary.review_consistency` 的 review evidence 会写入 `review_type=consistency`，其中包含 `decision / reason_codes / issues / style_baseline`；`style_baseline.source` 固定为 `active_glossary`，表示风格基准来自已有正式术语。
- `inspect.glossary` 现在会返回 `entries[*].gender / age_group`、`candidates[*].category / note / gender / age_group`，以及按 `term_group_key` 聚合的 `relation_groups`。
- `inspect.glossary` 还会返回 `chapter_statuses`，用于判断每章术语提取是否跑过、结果是 `terms_found / no_new_terms / suspicious_empty / skipped`、当前章节文本是否因 hash 变化变脏。
- `glossary.denylist.*` 可维护术语拒收规则；抽取阶段创建 draft candidate 前会过滤命中项，并在 `glossary.extract` 的 `rejected_terms` 里保留来源词和命中的 rule。
- `glossary.inspect_pipeline` 除 draft candidate / reviews 外，当前还会返回 `finalized_terms / finalized_relation_groups`，可直接查看 finalize 视角。
- `translation` 会读取当前有效术语，按正文实际命中做 span 级匹配和局部重叠裁决，只把命中当前分片正文的最终术语注入 prompt，不再走全局最长优先。
- 当 glossary entry 的 `gender` 非空时，translation prompt 会额外注入 `| gender: ...`。
- 当 glossary entry 的 `age_group` 非空时，translation prompt 会额外注入 `| age_group: ...`。
- translation glossary prompt 现在按关系组渲染 `[group ...]` block；同组内只注入正文真实命中的表面形式，不会把未命中的 canonical 术语顺带扩写进去。
- translation draft / rewrite / finalize 写入前会统一去除每行尾随空白，避免模型返回 Markdown 硬换行空格导致导出格式漂移。
- 译文版本里的 `glossary_snapshot_id` 现在基于当前有效术语表实时计算，不再写死占位值，并且会感知 `gender / age_group` 变化。
- `translation` 已收口到 workflow runner，当前默认走 `translation_single_llm_v1`；显式传 `translation_multi_llm_v1` 时，会按 `generate_draft -> review_draft -> rewrite_draft -> finalize` 跑多轮链路。
- `translation.generate_draft / review_draft / rewrite_draft` 只写 workflow 中间产物，不会提前切 active version；只有 `translation.finalize` 会写正式 `SegmentTranslationVersion`。
- `review` 默认是混合审校：先运行本地硬质检，再运行 LLM 质检；如果发现阻断问题，会把问题、原文、当前译文和命中术语输入翻译 LLM 进行重译，默认最多重译 2 轮。`review_mode=hard_only` 可用于只跑本地规则质检。
- hard review 检查约定译名时会忽略大小写、常见标点、空白和连字符差异，例如 `Ziheche` 与 `zi-he-che` 视为同一术语译名。
- `review` 会在运行开始时创建 `ReviewRun`，并持续写入 `summary.progress`；hybrid 模式逐段推进时，`inspect.review` 和 `stage.inspect_runs` 都能看到当前 phase、已完成分片数、正在处理的 segment 与 rewrite 计数。
- 当 glossary / translation / synopsis 命中 fallback 链时，当前实现会保留真实命中的模型元数据：
- synopsis 行会记录真实 `model_profile_id`
- draft version / 正式译文版本会记录真实 `model_profile_id`
- workflow step payload 会补充 `requested_model_profile_id / actual_model_profile_id / fallback_depth / chain_role / terminal_fallback_used`

### 术语表管理 action

这些 action 供 agent 在完成术语仲裁后结构化写回，不设计成人工后台 UI。

正式术语 `glossary.entry.*`：

- `glossary.entry.create`：创建正式术语。必填 `project_id / source_term / target_term`；可选 `category / note / gender / age_group / locked / term_group_key / relation_role / scope_level / scope_chapter_id / status`。
- `glossary.entry.update`：更新正式术语。用 `entry_id` 定位，或用 `project_id + source_term + scope_level/scope_chapter_id` 定位；只更新传入字段。用 `entry_id` 定位时，`source_term` 可作为新源词写回。
- `glossary.entry.lock` / `glossary.entry.unlock`：锁定或解锁正式术语，定位方式同 update。
- `glossary.entry.delete`：删除正式术语，定位方式同 update；locked 术语必须显式传 `force=true` 才允许删除。

临时候选术语 `glossary.candidate.*`：

- `glossary.candidate.create`：创建候选术语。必填 `project_id / chapter_id / source_term / suggested_term`；可选字段同 entry。
- `glossary.candidate.update`：按 `candidate_id` 更新候选术语，只更新传入字段。
- `glossary.candidate.approve` / `glossary.candidate.reject`：按 `candidate_id` 修改候选状态，不直接改正式术语。
- `glossary.candidate.promote`：把候选提升为正式术语；若目标正式术语已 locked，必须显式传 `force=true`。
- `glossary.candidate.delete`：按 `candidate_id` 删除候选术语。

术语拒收规则 `glossary.denylist.*`：

- `glossary.denylist.add`：新增拒收规则。可选 `project_id`；不传时为全局规则。必填 `source_term` 或 `pattern`；可选 `match_type=exact/contains/regex`、`reason_code`、`note`、`status`。
- `glossary.denylist.list`：列出拒收规则。可选 `project_id / include_global / status`。
- `glossary.denylist.delete`：按 `rule_id` 删除规则。

正式术语创建、更新、删除、锁定状态变化，以及候选 promote 都会把受影响章节的下游 translation/review/export 标记为 stale；单纯维护候选状态不会污染已完成译文。

### synopsis 联动

- `chaptering` 会抽取显式简介，并从正文剥离。
- `chaptering` 现在会先保留章节级 source/normalized 文件，再额外为每章生成 `1..N` 个稳定 `segment` 文件。
- `translation` 会先补齐项目级 synopsis，再翻正文。
- `inspect.synopsis` 可查看 synopsis 全文和元数据。
- `inspect.chapter / inspect.chapters` 可按章节查看分片状态、active version 和变脏情况。
- `inspect.segment` 可按单个翻译分片直接查看原文、当前 active 译文和元数据。
- `export` 会独立输出原文/目标语言简介，目标简介支持 `ready` / `completed`，空白内容视为无效，并在缺少可用 target synopsis 时拒绝导出；简介会用隔离的 fenced 文本块输出；当章节被拆成多个 `segment` 时，导出会按 `chapter_index + segment_index` 回拼成章节级正文。
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
- `route_preset_key`：模型路由 preset。传入后，不同 workflow step 可以按 preset 绑定到不同 profile；未传时，如果存在 active 默认 route preset，会自动使用默认 preset。
- `workflow_key`：可选。`glossary` 阶段可显式指定 `glossary_single_llm_v1` 或 `glossary_multi_llm_v1`；`translation` 阶段可显式指定 `translation_single_llm_v1` 或 `translation_multi_llm_v1`。
- `review_mode`：`review` 阶段可选，默认 `hybrid`。`hybrid` 会执行硬质检 + LLM 质检 + 最多 2 轮重译；`hard_only` 只执行本地规则质检。
- `max_rewrite_rounds`：`review` 阶段可选，默认 `2`，表示 LLM 质检发现阻断问题后最多重译几轮。
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
- `failed_only` 仅允许 `translation` 阶段使用，且只会补跑已经标记为 `translation_status=failed` 的分片。
- `missing_only` 允许 `translation / review` 使用；`translation` 会筛选“还没有 active version”的分片，`review` 会筛选“已有 active version 但还没 reviewed”的分片。

补充约束：

- `chapter_range` 必须同时提供 `scope_start` 和 `scope_end`，且 `scope_start` 不能大于 `scope_end`。
- `chapter_list` 必须提供 `scope_chapters`，格式是逗号分隔的章节编号。
- `resume` 和 `rerun` 不能同时为真。
- `stage.run` / `project.run_full` 会在业务执行前检查数据库 `alembic_version` 是否等于当前 migrations head；如果不一致，会返回 `schema_migration_required` 并提示先执行 `python -m alembic -c alembic.ini upgrade head`。
- `glossary / translation` 阶段都要求存在可用 provider；`review` 的默认 `hybrid` 模式也要求存在可用 provider，`review_mode=hard_only` 不需要 provider。
- `glossary / translation / review(hybrid)` 阶段要求存在可用数据库 provider/profile，并且 provider 必须有 `api_key_value`。
- 如果默认 profile 不存在，`model_profile_id=default` 会直接失败，不再回退环境变量 provider。
- 如果传入 `route_preset_key` 或已配置默认 route preset，`stage.run` 会先为当前 stage 选择该 preset 中的主 profile 作为阶段入口 provider；进入 workflow 后，每个 step 再按 preset 精确切换 profile。
- 即使未传 `route_preset_key`，自定义 workflow step 里显式写定的 `model_profile_id` 也会切换到该 profile 对应的 provider 和 fallback 链。
- 如果命中的数据库 profile 配置了 fallback 链，则 `stage.run` 会自动按“请求 profile -> 普通 fallback profile 列表”的顺序尝试；即使显式传了 `model_profile_id` 或 route preset 绑定了某个 profile 也一样。
- 若普通 fallback 链全部失败，并且配置了终端兜底链，`stage.run` 会继续尝试终端兜底 profile；route preset 只决定请求入口 profile，不覆盖终端兜底链。
- 若某次调用最终落到 fallback profile，正式 synopsis / glossary workflow payload / translation workflow payload / 正式译文版本都会保留真实命中的 profile 信息。
- 若 fallback 链全部失败，`stage.run` 会返回结构化 `provider_error`，其中 `error.details.attempts` 可直接用于上层 agent 的后续决策。
- 阶段结束后会在 `StageRun.summary.stage_report` 自动写入结构化报告，并在 `stage.run` 响应里返回 `stage_run_id / stage_report`。报告包含 `problem_count / problems / degradation`，当前覆盖 stage 失败、workflow 降级、失败 step、术语抽取跳过章节、review issue 聚合。

### `stage.cancel`

取消单个运行中的 stage run，不会把整个项目标记为 `cancelled`。必填参数：

- `project_id`
- `request_id`

可选定位参数：

- `stage_run_id`：优先按具体 stage run ID 取消。
- `stage`：未传 `stage_run_id` 时，取消该项目下最近一个运行中的指定阶段。

执行后会把命中的 running `StageRun`、关联的 running `WorkflowRun` 和 running `WorkflowStepRun` 标记为 `cancelled`，并清理当前项目 lease。运行中的 worker 会在 heartbeat 处发现取消并停止。

### `stage.inspect_runs`

查看阶段执行记录。必填参数：

- `project_id`

可选参数：

- `stage`
- `limit`

返回结果里：

- `summary` 现在直接是对象，不再是 JSON 字符串
- `scope_value` 会直接返回本次 run 的完整 scope
- `context` 会统一返回 `request_id / model_profile_id / workflow_key / workflow_run_id`
- `result` 会按 stage 返回稳定结果摘要
- `report` 会返回阶段结束时生成的结构化报告；旧数据缺少 `summary.stage_report` 时，inspect 会按现有 run 记录即时补算。
- failed run 会额外返回 `diagnostics`
- 所有 run 都会返回结构化 `observability`
- `glossary / translation` run 还会额外返回 `workflow`
- 当前 `diagnostics` 会包含：
  - `error`
  - `failure_step`
  - `model_profile_id`
  - `model_name`
- 当前 `observability` 会包含：
  - `timing`
  - `recovery`
  - `fallback`
- 当前 `workflow` 会包含：
  - `id / workflow_key / status`
  - `step_counts`
  - `steps[*].step_run_id / step_key / action / llm_role / model_profile_id / status / fallback_depth / actual_model_name`
  - 当 step 正在执行或保留了细粒度进度时，`steps[*].progress` 会返回结构化进度；当前 `glossary.extract` 会包含章节总数、queued/running/completed/skipped/failed 计数、默认章节 worker 数、每章状态、候选数、错误信息和更新时间。

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
- `chapter_statuses[*].extraction_status / candidate_count / finalized_count / is_stale`
- `relation_groups[*].term_group_key / member_count / role_distribution / consistency / members`

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
- 章节级摘要，例如分片数、已翻译数、失败数、已审校数、active version 数
- 当前章节全部分片的 `translation_status / review_status`
- 每个分片当前 active version 的核心元数据与译文内容

### `inspect.chapters`

查看多章节摘要。必填参数：

- `project_id`

可选参数：

- `scope_type`：默认 `all`，只支持 `all / chapter_range / chapter_list`
- `scope_start`：`chapter_range` 时必填
- `scope_end`：`chapter_range` 时必填
- `scope_chapters`：`chapter_list` 时必填
- `include_segments`：布尔值，默认 `false`；为 `true` 时会额外展开每章的分片明细

注意：

- `inspect.chapters` 不支持 `stale_only / failed_only / missing_only`
- 默认只返回章节级摘要；需要分片级明细时再显式传 `include_segments=true`

### `inspect.segment`

查看单个翻译分片详情。必填参数：

- `project_id`

分片定位参数必须且只能使用一种方式：

- `segment_id`
- `chapter_index + segment_index`

返回内容包括：

- 分片基础信息
- `translation_status / review_status / active_version_id`
- `source_text / translated_text`
- 当前 active version 的核心元数据

注意：

- 当分片没有 active version 时，`translated_text` 和 `current_version` 都会返回 `null`
- 当前只返回 current active version，不返回历史版本列表

### `inspect.translation`

查看翻译版本、当前激活版本、当前选中正式版本的 provenance、当前来源链 `timeline`，以及单段 compare 结果。当前 provenance 会解释：

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

项目级列表模式可选范围参数：

- `scope_type`：默认 `all`，支持 `all / chapter_range / chapter_list / stale_only / failed_only / missing_only`
- `scope_start` / `scope_end`：`chapter_range` 时必填
- `scope_chapters`：`chapter_list` 时必填

注意：非 `all` 的 `scope` 只用于项目级列表，不能和单段定位参数同时使用。

可选单段定位参数：

- `segment_id`
- `chapter_index + segment_index`
- `version_id`：单段模式下可选；传入后 `version / provenance / timeline / compare.current_version` 都围绕该正式版本组织，而不是默认 active version

compare 模式规则：

- 只能在单段模式下使用
- 需要额外传 `compare_version_id`
- 返回当前选中正式版本与指定历史正式版本之间的结构化变化摘要

当前 compare 摘要只覆盖：

- `translated_text_changed`
- `source_hash_changed`
- `glossary_snapshot_changed`
- `model_profile_changed`
- `model_name_changed`
- `status_changed`

### `inspect.translation_samples`

查看正式译文的质量抽样池。必填参数只有：

- `project_id`

可选参数：

- `scope_type`：默认 `all`，支持 `all / chapter_range / chapter_list / stale_only / failed_only / missing_only`
- `scope_start` / `scope_end`：`chapter_range` 时必填
- `scope_chapters`：`chapter_list` 时必填
- `limit`：每类来源返回的样本数，默认 `3`，最大 `20`

返回内容会把当前 active translation version 按来源分桶：

- `gpt`：非 rewrite 且模型标识包含 GPT 的正式译文
- `deepseek`：非 rewrite 且模型标识包含 DeepSeek 的正式译文
- `rewrite`：由 `draft_role=rewrite` 选中的正式译文
- `other`：无法归入以上三类的译文

每个样本会返回章节、分片、version/draft id、`draft_role`、模型信息、原文和译文全文，用于人工或 agent 侧做固定抽样复核。

### `inspect.provider_calls`

查看 provider 调用账本。必填参数只有：

- `project_id`

可选参数：

- `stage`
- `status`
- `limit`：默认 `100`，最大 `500`

返回内容会按调用记录列出 `stage / action / step_key / llm_role / requested_model_profile_id / actual_model_profile_id / provider_name / model_name / fallback_depth / status / error_type / token_usage` 等字段。当前账本以 workflow step 输出为第一批数据源，适合 Agent 追踪某次阶段运行的模型、fallback、失败类型与 token 使用。

### `inspect.provider_costs`

查看 provider 调用汇总。必填参数只有：

- `project_id`

可选参数：

- `stage`

返回内容包含 `totals / by_stage / by_model_profile`，当前会汇总调用数、失败调用数、fallback 调用数、输入/输出/总 token、cache token 和 `cost_usd`。如果 provider 未提供单价或调用侧未写入成本，`cost_usd` 会保持为 `0.0`。

### `inspect.review`

查看审校信息。必填参数只有：

- `project_id`

`runs[*]` 现在会直接返回 `translation_source`，可快速查看该次 review 基于哪些正式译文版本运行。

`issues[*]` 会返回 `segment_id / version_id / issue_source / round_index / requires_rewrite / structured_payload`，用于追踪硬质检、LLM 质检和重译链路。

### annotation 注释层

annotation 用于保存俚语、文化梗、中文专有词、组织、物品和世界观概念的读者说明。它是独立于译文和 glossary 的一层：不会写入 `SegmentTranslationVersion.translated_text`，不会改写 glossary 译名约束，也不会刷新 glossary snapshot。

当前支持的动作：

- `annotation.extract`：在已有 active translation version 上用 LLM 抽取注释候选，支持 `all / chapter_range / chapter_list` 范围。
- `annotation.inspect`：查看项目内注释定义、状态、冲突关系和出现位置。
- `annotation.approve`：将候选注释设为 approved，可配合 `-Locked true` 固定解释。
- `annotation.reject`：拒绝候选注释。

导出时默认只包含 `approved` 注释。`manifest.json` 会写入结构化 `annotations`，`export.md` 会在对应章节译文后追加独立 `#### 注释` 区，不在译文正文里插入脚注标记。

导出会显式标注审校风险：

- `manifest.translations[*].review_status` 会区分 `reviewed / pending / needs_revision`，并附带 `review_risk`。
- `manifest.review_summary.review_status` 会在任一分片为 `needs_revision` 时返回 `needs_revision`，同时给出 `needs_revision_segment_count / pending_segment_count / segment_review_status_counts`。
- `export.md` 的 Review Summary 会打印 `review_status / needs_revision_segment_count / pending_segment_count`；章节内如果不是 `reviewed`，会额外输出 `#### 审校风险`，避免把待修订内容误当成可交付稿。

### `inspect.export`

查看导出运行和导出产物。必填参数只有：

- `project_id`

`runs[*]` 现在也会直接返回 `translation_source`，不用再手动翻 summary 或 manifest 才能确认导出来源。

## 默认数据目录

如果没有设置 `LTW_DATA_DIR`，工具会使用：

```text
data/projects
```

每个项目会在该目录下创建自己的子目录，并继续划分 `source`、`translation`、`artifacts`、`exports` 等内容。

## 发布建议流程

1. 更新 `CHANGELOG.md`
2. 确认本地回归与 GitHub Actions CI 通过
3. 打 tag，例如 `v0.1.3`
4. 由 GitHub Actions 生成发布包；配置 `PUBLIC_RELEASE_TOKEN` 后会同步发布到公开 releases 仓库
