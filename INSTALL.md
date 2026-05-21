# 发布包安装快速指引

本文档面向拿到 `local_translation_workbench` 发布包的用户。完整说明见
`docs/operations/release-install.md`。

源码仓库地址：`https://github.com/gyyxs88/local_translation_workbench.git`。

公开下载发布页：`https://github.com/gyyxs88/local_translation_workbench-releases/releases`。

## 适用范围

当前发布包是源码发布包，不包含虚拟环境、MySQL、模型服务凭证或用户数据。
使用前需要自行准备：

- Python 3.10+
- 可连接的 MySQL 业务库
- 可用的模型服务 base URL 与 API Key
- 可写的数据目录

## 最小安装流程

Windows:

```powershell
Expand-Archive .\local_translation_workbench-0.1.3.zip -DestinationPath D:\Tools
cd D:\Tools\local_translation_workbench-0.1.3

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .[test]

$env:LTW_DATABASE_URL = "mysql+pymysql://<db_user>:<db_password>@<db_host>:<db_port>/<db_name>"
$env:LTW_DATA_DIR = "D:/Tools/local_translation_workbench_data/projects"

.\.venv\Scripts\ltw.exe doctor
.\.venv\Scripts\ltw.exe migrate
.\.venv\Scripts\ltw.exe -Action project.list
```

Linux/macOS:

```sh
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -e '.[test]'

export LTW_DATABASE_URL="mysql+pymysql://<db_user>:<db_password>@<db_host>:<db_port>/<db_name>"
export LTW_DATA_DIR="/opt/local_translation_workbench_data/projects"

./.venv/bin/ltw doctor
./.venv/bin/ltw migrate
./.venv/bin/ltw -Action project.list
```

如果只按旧源码方式安装依赖，`requirements.txt` 仍可用；推荐新环境直接使用 `pip install -e .[test]`，这样会同时安装 `ltw` 命令。

## 必须初始化的模型配置

模型服务不再从 `LTW_PROVIDER_BASE_URL` 或 `LTW_PROVIDER_API_KEY` 读取。
必须先通过工具 action 写入数据库 provider / profile：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run.ps1 `
  -Action provider.create `
  -ProviderKey demo_main_provider `
  -ProviderType openai_compatible `
  -DisplayName "Demo Main Provider" `
  -BaseUrl "https://<provider-host>/v1" `
  -ApiKeyValue "<provider_api_key>"

powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run.ps1 `
  -Action profile.create `
  -ProfileKey demo_default_profile `
  -ProviderKey demo_main_provider `
  -ModelName "<model_name>" `
  -IsDefault true

powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run.ps1 `
  -Action provider.health_check `
  -ModelProfileId demo_default_profile
```

`api_key_value` 会明文保存到业务库，工具输出只会返回打码后的 key。
请按敏感数据保护业务库、备份和运维日志。

## Codex 接入要点

如果把本包作为 Codex external tool 使用，需要让 Codex 能读取包根目录的
`TOOL.json`。`TOOL.json` 已声明：

- 入口：`powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run.ps1`
- 必填配置：`LTW_DATABASE_URL`
- 可选配置：`LTW_DATA_DIR`
- action 参数 schema：`project.*`、`provider.*`、`profile.*`、`stage.*`、`inspect.*` 等

这能让 Codex 知道“需要哪些配置项和 action 参数”，但不会自动知道你的真实
MySQL 地址、账号密码、provider base URL、API Key 或默认 profile。这些值仍需用户
提供，或授权 Codex 按本文命令初始化。

如果希望 Codex 在对话中自动遵守本工具的 agent 规则，请把
`codex_skill/local_translation_workbench` 安装到 Codex skills 目录，例如：

```powershell
Copy-Item -Recurse -Force `
  .\codex_skill\local_translation_workbench `
  "$env:USERPROFILE\.codex\skills\local_translation_workbench"
```

安装后重新打开 Codex 会话。仅解压 zip 不一定会让 Codex 自动加载该 skill。

## 验收清单

安装完成后至少确认：

- `project.list` 返回 `ok=true`
- `provider.list` 可以看到已创建 provider
- `profile.list` 可以看到默认 profile
- `provider.health_check` 返回 `ok=true`
- 业务库 `alembic_version` 是当前包内 migrations 的 head
