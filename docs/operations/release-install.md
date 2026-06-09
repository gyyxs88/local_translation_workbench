# 发布包安装与 Codex 接入手册

## 1. 适用范围

本文档面向拿到 `local_translation_workbench` zip 发布包的用户，目标是把一个
全新的本地环境接到可运行状态。

源码仓库地址：`https://github.com/gyyxs88/local_translation_workbench.git`。

当前发布包是源码发布包，不是免配置安装器。它包含工具代码、迁移、测试、
`TOOL.json`、Codex skill 和文档，但不包含：

- Python 虚拟环境
- MySQL 服务或数据库
- 模型服务 API Key
- 默认 provider / profile 数据
- 用户项目数据

## 1.1 给 Codex 的安装指令模板

外部用户可以把下面这段直接发给自己的 Codex：

```text
请从 https://github.com/gyyxs88/local_translation_workbench-releases/releases/latest 下载最新 local_translation_workbench 发布包，解压后阅读包内 INSTALL.md、docs/operations/release-install.md、TOOL.json 和 codex_skill/local_translation_workbench/SKILL.md。请完成虚拟环境、依赖安装、LTW_DATABASE_URL、LTW_DATA_DIR、数据库迁移、provider/profile 初始化、Codex skill 接入和健康检查。缺少配置时先问我；模型配置请先确认我是全流程使用同一套模型，还是要按 glossary/translation 的不同 step 配置不同 provider/profile，并在需要时创建 route preset。
```

Codex 不应猜测用户的数据库密码、provider API Key、模型名或模型路由策略；缺失时应询问用户，
拿到配置后再执行后续命令。

## 2. 用户需要准备什么

| 项目 | 是否必需 | 说明 |
| --- | --- | --- |
| Python 3.10+ | 必需 | 用于运行 CLI、Alembic 和测试 |
| MySQL 业务库 | 必需 | `LTW_DATABASE_URL` 指向该库 |
| 数据目录 | 建议显式配置 | `LTW_DATA_DIR` 指向项目文件、工件和导出目录 |
| 模型服务凭证 | 运行模型阶段必需 | 通过 `provider.create` 写入业务库；可是一套，也可以是多套 |
| 模型路由策略 | 建议明确 | 选择全流程单 profile，或按 workflow step 绑定不同 profile |
| 测试库 | 开发回归必需 | `LTW_TEST_DATABASE_URL`，必须和业务库隔离 |

数据库既可以在本机，也可以在局域网服务器上；工具只要求当前机器能连通目标库。

## 3. 解压与虚拟环境

```powershell
Expand-Archive .\local_translation_workbench-0.1.4.zip -DestinationPath D:\Tools
cd D:\Tools\local_translation_workbench-0.1.4

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .[test]
```

Linux/macOS：

```sh
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -e '.[test]'
```

`scripts/run.ps1` 会从工具目录开始向上查找 `.venv\Scripts\python.exe`，`scripts/run.sh`
会优先使用发布包根目录下的 `./.venv/bin/python`。因此把 `.venv` 放在发布包根目录即可。

## 3.1 运行入口选择

- 已安装 Python 包时，优先使用 `ltw`。
- Windows 源码/zip 模式可继续使用 `scripts/run.ps1`。
- Linux/macOS 源码/zip 模式使用 `scripts/run.sh`。

三种入口最终都会进入同一个 Python console，业务 action 参数保持一致。

## 3.2 更新检查

发布包安装完成后，可以手动检查公开发布仓库是否有新版：

```powershell
.\.venv\Scripts\ltw.exe update-check
```

Linux/macOS：

```sh
./.venv/bin/ltw update-check
```

返回值会包含 `current_version / latest_version / update_available / download_url /
sha256_url`。该命令只提示，不会自动覆盖当前安装目录。

`ltw doctor` 也会附带一次轻量更新提醒。为了避免频繁访问 GitHub，默认 24 小时内复用本机
缓存；网络不可用时只返回 `status=unavailable`，不影响 doctor 的其他检查。

可选环境变量：

- `LTW_DISABLE_UPDATE_CHECK=1`：关闭更新检测。
- `LTW_UPDATE_CHECK_INTERVAL_HOURS=24`：调整 doctor 的缓存间隔。
- `LTW_UPDATE_CHECK_TIMEOUT_SECONDS=2`：调整 GitHub Release API 超时时间。
- `LTW_UPDATE_CHECK_CACHE_PATH`：指定缓存文件路径。

## 4. 环境变量

### 4.1 当前会话临时配置

```powershell
$env:LTW_DATABASE_URL = "mysql+pymysql://<db_user>:<db_password>@<db_host>:<db_port>/<db_name>"
$env:LTW_DATA_DIR = "D:/Tools/local_translation_workbench_data/projects"
```

`LTW_DATABASE_URL` 是必填项；所有 action 都依赖它。`LTW_DATA_DIR` 可选，但发布
部署时建议显式设置到包目录之外，避免升级包时误删项目数据。

### 4.2 Windows 用户级持久配置

```powershell
[Environment]::SetEnvironmentVariable("LTW_DATABASE_URL", "mysql+pymysql://<db_user>:<db_password>@<db_host>:<db_port>/<db_name>", "User")
[Environment]::SetEnvironmentVariable("LTW_DATA_DIR", "D:/Tools/local_translation_workbench_data/projects", "User")
```

设置后请重新打开 PowerShell、终端或 Codex App。

## 5. 数据库初始化

首次使用或升级发布包后，执行数据库迁移。推荐入口：

```powershell
.\.venv\Scripts\ltw.exe migrate
```

Linux/macOS：

```sh
./.venv/bin/ltw migrate
```

源码模式下仍可直接使用 Alembic：

```powershell
.\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
```

快速确认业务库可访问：

```powershell
.\.venv\Scripts\ltw.exe -Action project.list
```

如果数据库 schema 落后，`stage.run` / `project.run_full` 会返回
`schema_migration_required`，并提示先执行 `alembic upgrade head`。

## 6. provider / profile 初始化

模型供应商和模型 metadata 统一存入数据库，不再读取
`LTW_PROVIDER_BASE_URL` 或 `LTW_PROVIDER_API_KEY`。
API Key 可以通过旧 `api_key_value` 存入数据库，也可以通过 `api_key_secret_ref`
引用 `env:NAME` 或 `file:path`。

### 6.1 创建 provider

OpenAI-compatible 示例：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run.ps1 `
  -Action provider.create `
  -ProviderKey demo_main_provider `
  -ProviderType openai_compatible `
  -DisplayName "Demo Main Provider" `
  -BaseUrl "https://<provider-host>/v1" `
  -ApiKeyValue "<provider_api_key>"
```

Anthropic Messages 示例：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run.ps1 `
  -Action provider.create `
  -ProviderKey demo_anthropic `
  -ProviderType anthropic_messages `
  -DisplayName "Demo Anthropic" `
  -BaseUrl "https://<provider-host>" `
  -ApiKeyValue "<provider_api_key>"
```

`api_key_value` 会明文保存到业务库。新环境也可以使用
`-ApiKeySecretRef "env:LTW_PROVIDER_DEMO_KEY"` 或
`-ApiKeySecretRef "file:D:/path/to/provider-key.txt"`，让业务库只保存引用。
工具输出不会回显完整 key；无论哪种方式，都不要把真实 key 写入文档、脚本、提交记录或普通聊天。

### 6.2 创建默认 profile

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run.ps1 `
  -Action profile.create `
  -ProfileKey demo_default_profile `
  -ProviderKey demo_main_provider `
  -ModelName "<model_name>" `
  -IsDefault true
```

`stage.run` 默认使用 `model_profile_id=default`。如果没有默认 profile，模型阶段会
直接失败，不会回退到旧环境变量。

### 6.3 可选 fallback

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run.ps1 `
  -Action profile.set_fallbacks `
  -ProfileKey demo_default_profile `
  -FallbackProfileKeysJson "[\"demo_backup_profile\"]"
```

### 6.4 健康检查

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run.ps1 `
  -Action provider.health_check `
  -ModelProfileId demo_default_profile
```

检查返回值：

- `ok` 应为 `true`
- `selected_profile_id` 应为预期 profile
- 如果发生 fallback，`attempts` 会显示完整尝试链

## 6.5 模型点位与 route preset

初始化时不要只问“模型是什么”。本工具允许所有点位共用一套 profile，也允许不同点位使用
不同供应商、模型或 API Key。

推荐 Codex 先向用户确认以下策略：

- `single`：全流程共用一个默认 profile；适合首次安装、低成本试跑和简单项目。
- `multi`：创建多套 profile，并把不同 workflow step 绑定到不同 profile；适合主模型 +
  副模型互审、GPT + DeepSeek 双模型、或把重写/终审交给更强模型。
- `fallback`：在主 profile 后配置普通 fallback，或设置全局终端兜底 profile；适合限流、
  网络波动或供应商不稳定的环境。

当前内置 workflow 的可配置 step_key 如下：

| stage | workflow | step_key | 常见用途 |
| --- | --- | --- | --- |
| glossary | `glossary_single_llm_v1` / `glossary_multi_llm_v1` | `extract_primary` | 主术语抽取 |
| glossary | `glossary_multi_llm_v1` | `extract_secondary` | 副术语抽取，用于交叉证据 |
| glossary | 两者 | `normalize_candidates` | 候选清洗与合并 |
| glossary | 两者 | `review_relations` | 关系组审阅 |
| glossary | 两者 | `review_scope` | 适用范围审阅 |
| glossary | 两者 | `review_consistency` | 一致性审阅 |
| glossary | 两者 | `finalize_terms` | 术语最终落表 |
| translation | `translation_single_llm_v1` / `translation_multi_llm_v1` | `generate_primary` | 主译文草稿 |
| translation | `translation_multi_llm_v1` | `generate_secondary` | 副译文草稿 |
| translation | `translation_multi_llm_v1` | `review_drafts` | 多草稿审阅 |
| translation | `translation_multi_llm_v1` | `rewrite_consensus` | 汇总重写 |
| translation | 两者 | `finalize_segments` | 正式译文落库 |

`review_mode=hybrid` 和 synopsis 生成当前跟随阶段入口 profile；route preset 主要控制
glossary / translation workflow 内部 step。如果用户希望 review 或 synopsis 使用不同模型，
优先在运行对应 stage 时显式传 `-ModelProfileId`，或把它作为后续自定义 workflow/扩展需求处理。

创建多模型 route preset 的典型流程是：

```powershell
New-Item -ItemType Directory -Force temp
@'
[
  {"stage":"glossary","step_key":"extract_primary","model_profile_id":"primary_profile"},
  {"stage":"glossary","step_key":"extract_secondary","model_profile_id":"secondary_profile"},
  {"stage":"glossary","step_key":"normalize_candidates","model_profile_id":"primary_profile"},
  {"stage":"glossary","step_key":"review_relations","model_profile_id":"primary_profile"},
  {"stage":"glossary","step_key":"review_scope","model_profile_id":"primary_profile"},
  {"stage":"glossary","step_key":"review_consistency","model_profile_id":"primary_profile"},
  {"stage":"glossary","step_key":"finalize_terms","model_profile_id":"primary_profile"},
  {"stage":"translation","step_key":"generate_primary","model_profile_id":"primary_profile"},
  {"stage":"translation","step_key":"generate_secondary","model_profile_id":"secondary_profile"},
  {"stage":"translation","step_key":"review_drafts","model_profile_id":"primary_profile"},
  {"stage":"translation","step_key":"rewrite_consensus","model_profile_id":"primary_profile"},
  {"stage":"translation","step_key":"finalize_segments","model_profile_id":"primary_profile"}
]
'@ | Set-Content -Encoding UTF8 temp\route-bindings.json

powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run.ps1 `
  -Action profile.route_set `
  -PresetKey multi_default `
  -DisplayName "Multi model default route" `
  -BindingsJsonFile temp\route-bindings.json `
  -IsDefault true

powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run.ps1 `
  -Action profile.route_set_default `
  -PresetKey multi_default `
  -WorkflowMode multi
```

`-WorkflowMode multi` 会把 glossary / translation 默认 workflow 切到内置多模型 workflow。
如果只想保留当前 workflow 默认值，只设置 route preset，则使用 `-WorkflowMode keep`。

## 7. Codex 如何知道配置要求

发布包根目录包含 `TOOL.json`，用于 external tool 场景的机器可读描述。

`TOOL.json` 已声明：

- 工具入口：`powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run.ps1`
- 运行时：Python 3.10+
- 必填配置：`database_url`，对应环境变量 `LTW_DATABASE_URL`
- 可选配置：`data_dir`，对应环境变量 `LTW_DATA_DIR`
- action 参数 schema：包含 `project.*`、`provider.*`、`profile.*`、`workflow.*`、
  `stage.*`、`inspect.*`、`glossary.*`、`translation.*`、`annotation.*`

因此，只要对方的 Codex 正式加载了这个 external tool，它能知道“需要数据库连接串、
数据目录和每个 action 的参数”。但它不会自动知道用户自己的真实值，包括：

- MySQL 主机、端口、库名、用户名、密码
- `LTW_DATA_DIR` 实际落盘位置
- provider base URL
- provider API Key
- 模型名
- 默认 profile / fallback / route preset 策略
- 单模型或多模型路由点位选择

这些值必须由用户提供，或由用户授权 Codex 按本文步骤创建。

## 8. Codex skill 安装

发布包内置 agent 侧规则：

```text
codex_skill/local_translation_workbench/SKILL.md
```

它会告诉 Codex：

- 运行前先读 README 和相关运维文档
- 优先用 `stage.run` 与 `inspect.*`
- 真实运行前检查数据库与 provider
- 初始化时确认单模型/多模型策略，以及 route preset 是否需要设为默认
- 不把真实 provider key 写入仓库文档、脚本或提交记录
- 多 LLM 术语结果由 agent 基于证据仲裁，工具代码只产出候选、证据和检查结果

如果希望 Codex 在对话里自动遵守这些规则，需要把 skill 安装到 Codex 的 skills 目录。
Windows 示例：

```powershell
Copy-Item -Recurse -Force `
  .\codex_skill\local_translation_workbench `
  "$env:USERPROFILE\.codex\skills\local_translation_workbench"
```

安装后重新打开 Codex 会话。只解压 zip 不一定会让 Codex 自动加载该 skill。

## 9. Codex external tool 注册检查

不同 Codex 版本或团队封装的 external tool 注册方式可能不同。无论具体入口是什么，
最终都要满足：

- Codex 能读取发布包根目录的 `TOOL.json`
- Codex 执行 action 时的工作目录是发布包根目录，或能正确解析 `scripts/run.ps1`
- Codex 运行环境里有可用 `.venv`
- Codex 运行环境里能读取 `LTW_DATABASE_URL`
- Codex 运行环境里能连通 MySQL 和 provider base URL

可用下面的动作做最低限度验收：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run.ps1 -Action project.list
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run.ps1 -Action provider.list
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run.ps1 -Action profile.list
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run.ps1 -Action provider.health_check
```

## 10. 创建第一个项目

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run.ps1 `
  -Action project.create `
  -RequestId "demo-project-001" `
  -SourcePath "D:/Novels/source/demo.md" `
  -SourceLanguage "zh" `
  -TargetLanguage "en"
```

保留返回的 `project_id`，然后按阶段运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run.ps1 `
  -Action stage.run `
  -RequestId "demo-chaptering-001" `
  -ProjectId <project_id> `
  -Stage chaptering

powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run.ps1 `
  -Action stage.run `
  -RequestId "demo-glossary-001" `
  -ProjectId <project_id> `
  -Stage glossary
```

完整流程也可以使用：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run.ps1 `
  -Action project.run_full `
  -RequestId "demo-full-001" `
  -ProjectId <project_id>
```

## 11. 开发回归

如果要在发布包里跑测试，必须使用独立测试库，不能复用业务库。

```powershell
$env:LTW_TEST_DATABASE_URL = "mysql+pymysql://<db_user>:<db_password>@<db_host>:<db_port>/<db_name>_ltw_test"
.\.venv\Scripts\python.exe -m pytest tests -q
```

测试夹具会清空测试库里的全部表并迁移到 head。误把
`LTW_TEST_DATABASE_URL` 指向业务库会破坏真实数据。

## 12. 常见问题

### Codex 读到了 TOOL.json，为什么仍不能运行？

常见原因是运行环境没有 `.venv`、没有 `LTW_DATABASE_URL`，或 Codex 进程没有重启读取
新的用户级环境变量。

### health_check 失败怎么办？

先检查 `provider.inspect` 和 `profile.inspect`，确认 provider key 已设置或 secret ref 可解析、base URL 正确、
profile 指向的模型名真实存在。若配置了 fallback，查看 `provider.health_check` 返回的
`attempts`。

### 可以把 API Key 写到文档里吗？

不建议。旧 `api_key_value` 会把 key 明文保存到业务库；新 `api_key_secret_ref`
只保存引用，但真实 key 仍应放在环境变量、本地受控文件或后续 vault 中。
文档、脚本、提交记录中应只保留占位符或 ref 名称。

### 升级发布包会影响项目数据吗？

只要 `LTW_DATA_DIR` 指向包目录之外，升级代码包不会覆盖项目数据。升级后仍需执行
`alembic upgrade head`，确保业务库 schema 与新包一致。
