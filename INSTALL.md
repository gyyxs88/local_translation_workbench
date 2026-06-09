# 发布包安装快速指引

本文档面向拿到 `local_translation_workbench` 发布包的用户。完整说明见
`docs/operations/release-install.md`。

源码仓库地址：`https://github.com/gyyxs88/local_translation_workbench.git`。

公开下载发布页：`https://github.com/gyyxs88/local_translation_workbench-releases/releases`。

## 给 Codex 的安装指令模板

可以把下面这段直接发给对方自己的 Codex：

```text
请从 https://github.com/gyyxs88/local_translation_workbench-releases/releases/latest 下载最新 local_translation_workbench 发布包，解压后阅读包内 INSTALL.md 和 docs/operations/release-install.md。请完成虚拟环境、依赖安装、LTW_DATABASE_URL、LTW_DATA_DIR、数据库迁移、provider/profile 初始化、Codex skill 接入和健康检查。缺少配置时先问我；模型配置请先确认我是全流程使用同一套模型，还是要按 glossary/translation 的不同 step 配置不同 provider/profile，并在需要时创建 route preset。
```

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
Expand-Archive .\local_translation_workbench-0.1.4.zip -DestinationPath D:\Tools
cd D:\Tools\local_translation_workbench-0.1.4

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .[test]

$env:LTW_DATABASE_URL = "mysql+pymysql://<db_user>:<db_password>@<db_host>:<db_port>/<db_name>"
$env:LTW_DATA_DIR = "D:/Tools/local_translation_workbench_data/projects"

.\.venv\Scripts\ltw.exe doctor
.\.venv\Scripts\ltw.exe update-check
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
./.venv/bin/ltw update-check
./.venv/bin/ltw migrate
./.venv/bin/ltw -Action project.list
```

如果只按旧源码方式安装依赖，`requirements.txt` 仍可用；推荐新环境直接使用 `pip install -e .[test]`，这样会同时安装 `ltw` 命令。

## 更新检查

`ltw update-check` 会检查公开 GitHub Releases 中的最新版本，并返回下载地址与 sha256
校验文件地址。`ltw doctor` 也会附带更新提醒，但默认会缓存 24 小时，网络失败不会阻断
本地检查。

如不希望工具联网检查更新，可设置：

```powershell
$env:LTW_DISABLE_UPDATE_CHECK = "1"
```

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

`api_key_value` 是旧路径，会明文保存到业务库，工具输出只会返回打码后的 key。
新环境也可以改用 `-ApiKeySecretRef "env:LTW_PROVIDER_DEMO_KEY"` 或
`-ApiKeySecretRef "file:D:/path/to/provider-key.txt"`，让业务库只保存 secret reference。
无论哪种方式，都不要把真实 key 写入文档、脚本、提交记录或普通聊天。

### 单模型和多模型策略

初始化时 Codex 至少应该先问用户：

- 是否所有模型点位都使用同一套 provider/profile。
- 是否需要为不同点位使用不同供应商、模型或 API Key。
- 是否需要 fallback profile 或全局终端兜底 profile。

最简单方案是全流程共用一个默认 profile，也就是上面的 `demo_default_profile`。

如果用户要多模型路线，则需要先创建多套 provider/profile，再用 route preset 把 workflow
step 绑定到不同 profile。常见可配置点位包括：

- glossary：`extract_primary`、`extract_secondary`、`normalize_candidates`、`review_relations`、`review_scope`、`review_consistency`、`finalize_terms`
- translation：`generate_primary`、`generate_secondary`、`review_drafts`、`rewrite_consensus`、`finalize_segments`

其中 `review(hybrid)` 和 synopsis 当前跟随阶段入口 profile；route preset 主要控制
glossary / translation workflow 内部 step。详细示例见
`docs/operations/release-install.md` 的“模型点位与 route preset”。

## Codex 接入要点

如果把本包作为 Codex external tool 使用，需要让 Codex 能读取包根目录的
`TOOL.json`。`TOOL.json` 已声明：

- 入口：`powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run.ps1`
- 必填配置：`LTW_DATABASE_URL`
- 可选配置：`LTW_DATA_DIR`
- action 参数 schema：`project.*`、`provider.*`、`profile.*`、`stage.*`、`inspect.*` 等

这能让 Codex 知道“需要哪些配置项和 action 参数”，但不会自动知道你的真实
MySQL 地址、账号密码、provider base URL、API Key、模型名、单模型/多模型策略或 route
preset 绑定关系。这些值仍需用户提供，或授权 Codex 按本文命令初始化。

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
