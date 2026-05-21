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

## 2. 用户需要准备什么

| 项目 | 是否必需 | 说明 |
| --- | --- | --- |
| Python 3.9+ | 必需 | 用于运行 CLI、Alembic 和测试 |
| MySQL 业务库 | 必需 | `LTW_DATABASE_URL` 指向该库 |
| 数据目录 | 建议显式配置 | `LTW_DATA_DIR` 指向项目文件、工件和导出目录 |
| 模型服务凭证 | 运行模型阶段必需 | 通过 `provider.create` 写入业务库 |
| 测试库 | 开发回归必需 | `LTW_TEST_DATABASE_URL`，必须和业务库隔离 |

数据库既可以在本机，也可以在局域网服务器上；工具只要求当前机器能连通目标库。

## 3. 解压与虚拟环境

```powershell
Expand-Archive .\local_translation_workbench-0.1.0-20260509-145713.zip -DestinationPath D:\Tools
cd D:\Tools\local_translation_workbench-0.1.0-20260509-145713

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

模型供应商、模型和 API Key 统一存入数据库，不再读取
`LTW_PROVIDER_BASE_URL` 或 `LTW_PROVIDER_API_KEY`。

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

`api_key_value` 会明文保存到业务库。工具输出不会回显完整 key，但业务库本身必须按
敏感数据保护。

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

## 7. Codex 如何知道配置要求

发布包根目录包含 `TOOL.json`，用于 external tool 场景的机器可读描述。

`TOOL.json` 已声明：

- 工具入口：`powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run.ps1`
- 运行时：Python 3.9+
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

先检查 `provider.inspect` 和 `profile.inspect`，确认 provider key 已设置、base URL 正确、
profile 指向的模型名真实存在。若配置了 fallback，查看 `provider.health_check` 返回的
`attempts`。

### 可以把 API Key 写到文档里吗？

不建议。工具会把 key 明文保存到业务库 `api_key_value` 字段，文档、脚本、提交记录中应只
保留占位符。

### 升级发布包会影响项目数据吗？

只要 `LTW_DATA_DIR` 指向包目录之外，升级代码包不会覆盖项目数据。升级后仍需执行
`alembic upgrade head`，确保业务库 schema 与新包一致。
