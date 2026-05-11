# 接入初始化手册

## 1. 适用范围

本文档用于完成 `local_translation_workbench` 的首次接入，目标是把下面几件事一次配齐：

- Python 虚拟环境与执行入口
- 局域网 MySQL 业务库 / 测试库
- Alembic 迁移初始化
- provider / profile / workflow 基础配置

当前推荐的执行位置是 `NovelT` 单体仓库根目录，也就是 `D:\Path\To\Workspace`。
如果你把这个工具单独检出成独立仓库，也支持直接在仓库根目录执行 `scripts/run.ps1` 和 `python -m pytest tests -q`。

## 2. 前置条件

开始前请确认：

- 已存在可用虚拟环境：`D:\Path\To\Workspace\.venv`
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

### 3.2 provider key 保存方式

provider API Key 通过 `provider.create` / `provider.set_key` 写入数据库的 `api_key_value` 字段。工具输出不会回显完整 key，但数据库字段本身是明文，业务库备份、访问账号和日志排查都要按敏感数据处理。

### 3.3 PowerShell 持久化示例

```powershell
[Environment]::SetEnvironmentVariable("LTW_DATABASE_URL", "mysql+pymysql://<db_user>:<db_password>@<db_host>:<db_port>/<db_name>", "User")
[Environment]::SetEnvironmentVariable("LTW_TEST_DATABASE_URL", "mysql+pymysql://<db_user>:<db_password>@<db_host>:<db_port>/<db_name>_ltw_test", "User")
[Environment]::SetEnvironmentVariable("LTW_DATA_DIR", "D:/path/to/workspace/tools/local_translation_workbench/data/projects", "User")
```

设置完成后请重新打开 PowerShell、终端或 Codex App。

## 4. 数据库初始化

### 4.1 业务库迁移

在 `D:\Path\To\Workspace` 根目录执行：

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

`scripts/run.ps1` 会自动优先使用 `D:\Path\To\Workspace\.venv\Scripts\python.exe`，然后切到工具目录执行 `app.cli`。

## 6. provider / profile 初始化

### 6.1 创建 provider

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action provider.create `
  -ProviderKey demo_main_provider `
  -ProviderType openai_compatible `
  -DisplayName "Demo Main Provider" `
  -BaseUrl "https://<provider-host>/v1" `
  -ApiKeyValue "<provider_api_key>"
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

先创建备份 provider / profile，再设置普通 fallback：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action profile.set_fallbacks `
  -ProfileKey demo_default_profile `
  -FallbackProfileKeysJson "[\"demo_backup_profile\"]"
```

如果希望所有普通链失败后还有固定兜底层，可以单独配置终端兜底。终端兜底不挂在某个普通 profile 上，中间备用 profile 怎么配置都不会改变它：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action profile.terminal_fallback_set `
  -FallbackProfileKeysJson "[\"demo_terminal_profile\"]" `
  -Note "全局终端兜底"
```

终端兜底不是敏感内容专用；普通链因为限流、超时、网络错误、上游 5xx、JSON 解析失败、空响应或 `policy_block` 等原因全部失败后，都会进入终端兜底。

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
- `attempts[*].chain_role` 可区分 `primary / normal_fallback / terminal_fallback`
- `terminal_fallback_used=true` 表示本次最终命中了终端兜底

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
