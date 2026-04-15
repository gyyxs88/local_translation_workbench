# 接入初始化手册

## 1. 适用范围

本文档用于完成 `local_translation_workbench` 的首次接入，目标是把下面几件事一次配齐：

- Python 虚拟环境与执行入口
- 局域网 MySQL 业务库 / 测试库
- Alembic 迁移初始化
- provider / profile / workflow 基础配置

当前推荐的执行位置是 `NovelT` 单体仓库根目录，也就是 `D:\Project\NovelT`。
如果你把这个工具单独检出成独立仓库，也支持直接在仓库根目录执行 `scripts/run.ps1` 和 `python -m pytest tests -q`。

## 2. 前置条件

开始前请确认：

- 已存在可用虚拟环境：`D:\Project\NovelT\.venv`
- 当前机器可以连通局域网 MySQL
- 已准备独立业务库和独立测试库
- 已拿到至少一组可用模型服务凭证

当前工具不要求必须在本机安装 MySQL，只要求当前机器能连到目标数据库。

## 3. 环境变量

### 3.1 必填变量

| 变量名 | 用途 | 说明 |
| --- | --- | --- |
| `LTW_DATABASE_URL` | 业务库连接串 | 所有 action 都依赖它 |
| `LTW_TEST_DATABASE_URL` | 测试库连接串 | `pytest` 必填，必须和业务库隔离 |
| `LTW_DATA_DIR` | 本地数据目录 | 项目源文件、导出文件、工件都会落这里 |

推荐使用下面这种连接串格式：

```text
mysql+pymysql://<db_user>:<db_password>@<db_host>:<db_port>/<db_name>
```

测试库连接串格式：

```text
mysql+pymysql://<db_user>:<db_password>@<db_host>:<db_port>/<db_name>_ltw_test
```

### 3.2 provider 相关变量

如果你准备走数据库里的 `provider/profile` 配置层，还需要准备一组或多组 API Key 环境变量，例如：

- `LTW_PROVIDER_API_KEY_MAIN`
- `LTW_PROVIDER_API_KEY_BACKUP`

数据库里只保存 `api_key_env_name`，不会保存真实 key。

### 3.3 PowerShell 持久化示例

```powershell
[Environment]::SetEnvironmentVariable("LTW_DATABASE_URL", "mysql+pymysql://<db_user>:<db_password>@192.168.31.212:3307/<db_name>", "User")
[Environment]::SetEnvironmentVariable("LTW_TEST_DATABASE_URL", "mysql+pymysql://<db_user>:<db_password>@192.168.31.212:3307/<db_name>_ltw_test", "User")
[Environment]::SetEnvironmentVariable("LTW_DATA_DIR", "D:/Project/NovelT/tools/local_translation_workbench/data/projects", "User")
[Environment]::SetEnvironmentVariable("LTW_PROVIDER_API_KEY_MAIN", "<provider_api_key>", "User")
```

设置完成后请重新打开 PowerShell、终端或 Codex App。

## 4. 数据库初始化

### 4.1 业务库迁移

在 `D:\Project\NovelT` 根目录执行：

```powershell
$env:LTW_DATABASE_URL = "mysql+pymysql://<db_user>:<db_password>@<db_host>:<db_port>/<db_name>"
.\.venv\Scripts\python.exe -m alembic -c tools/local_translation_workbench/alembic.ini upgrade head
```

### 4.2 测试库迁移

如果你想手动初始化测试库，也可以单独执行一次：

```powershell
$env:LTW_DATABASE_URL = "mysql+pymysql://<db_user>:<db_password>@<db_host>:<db_port>/<db_name>_ltw_test"
.\.venv\Scripts\python.exe -m alembic -c tools/local_translation_workbench/alembic.ini upgrade head
```

说明：

- Alembic 直接读取 `LTW_DATABASE_URL`
- 这条命令已经在局域网 MySQL 测试库上验证过可用
- `pytest` 自己也会在测试会话开始时清空测试库并迁移到 `head`

## 5. 执行入口检查

### 5.1 CLI 帮助

```powershell
.\.venv\Scripts\python.exe -m tools.local_translation_workbench.app.cli help
```

### 5.2 脚本入口

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1
```

`scripts/run.ps1` 会自动优先使用 `D:\Project\NovelT\.venv\Scripts\python.exe`，然后切到工具目录执行 `app.cli`。

## 6. provider / profile 初始化

### 6.1 创建 provider

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action provider.create `
  -ProviderKey demo_main_provider `
  -ProviderType openai_compatible `
  -DisplayName "Demo Main Provider" `
  -BaseUrl "https://<provider-host>/v1" `
  -ApiKeyEnvName LTW_PROVIDER_API_KEY_MAIN
```

### 6.2 创建默认 profile

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action profile.create `
  -ProfileKey demo_default_profile `
  -ProviderKey demo_main_provider `
  -ModelName "gpt-5.4" `
  -IsDefault true
```

### 6.3 可选：配置 fallback

先创建备份 provider / profile，再设置 fallback：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action profile.set_fallbacks `
  -ProfileKey demo_default_profile `
  -FallbackProfileKeysJson "[\"demo_backup_profile\"]"
```

### 6.4 健康检查

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action provider.health_check `
  -ModelProfileId demo_default_profile
```

推荐至少确认以下几点：

- `ok = true`
- `selected_profile_id` 是预期 profile
- 如果发生 fallback，`attempts` 里能看见完整尝试链

## 7. workflow 初始化

当前内置 workflow 已经足够支撑主流程，首次接入通常不需要手动创建：

- `glossary_single_llm_v1`
- `glossary_multi_llm_v1`
- `translation_single_llm_v1`
- `translation_multi_llm_v1`

先看现有列表：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action workflow.list
```

只有在你需要切换默认 workflow 或引入自定义 workflow 时，才需要额外执行 `workflow.create` 或 `workflow.set_default`。

## 8. 接入完成检查

完成接入后，至少执行下面这组检查：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 -Action provider.list
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 -Action profile.list
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 -Action workflow.list
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 -Action project.list
```

预期结果：

- provider / profile / workflow 返回 `ok = true`
- `project.list` 可以正常返回空列表或已有项目列表
- 没有出现数据库连接、迁移缺失或环境变量缺失错误

## 9. 接下来做什么

接入完成后，直接继续看：

- [最小试跑手册](./runbook.md)
- [真实 provider 联调 smoke 手册](./provider-smoke.md)
- [常见故障排查](./troubleshooting.md)
