# 常见故障排查

## 1. 跑测试时报 `缺少 LTW_TEST_DATABASE_URL`

现象：

```text
缺少 LTW_TEST_DATABASE_URL。测试必须显式指定独立测试库，禁止回退到共享库。
```

原因：

- 当前会话没有设置 `LTW_TEST_DATABASE_URL`
- 或者你开了新终端，但没有重新加载用户级环境变量

处理：

```powershell
$env:LTW_TEST_DATABASE_URL = "mysql+pymysql://<db_user>:<db_password>@<db_host>:<db_port>/<db_name>_ltw_test"
.\.venv\Scripts\python.exe -m pytest tests -q
```

注意：

- 测试库必须是独立库
- 绝对不要把业务库填到 `LTW_TEST_DATABASE_URL`

## 2. 独立仓库里仍然按旧模块路径调用

现象：

```text
ModuleNotFoundError: No module named 'tools'
```

原因：

- 你仍在使用旧的 `tools.local_translation_workbench...` 单体仓库模块路径
- 或者你并不是在 `local_translation_workbench` 独立仓库根目录执行
- 或者实际调用的 Python 不是当前项目使用的虚拟环境 Python

处理：

先确认当前目录就是独立仓库根目录，再执行新入口：

```powershell
.\.venv\Scripts\python.exe -m app.cli help
.\.venv\Scripts\python.exe -m pytest tests -q
```

## 3. `scripts/run.ps1` 报找不到虚拟环境 Python

现象：

```text
No available virtual environment Python was found.
```

原因：

- 仓库根目录或其上级目录没有 `.venv\Scripts\python.exe`
- 当前仓库还没有创建虚拟环境

处理：

- 优先在 `local_translation_workbench` 仓库根目录创建 `.venv`
- 如果你把虚拟环境放在上级目录，也要确保 `scripts/run.ps1` 向上查找时能找到它

## 4. Alembic 迁移时报缺少 `LTW_DATABASE_URL`

现象：

```text
缺少 LTW_DATABASE_URL，无法执行 Alembic 迁移。
```

原因：

- Alembic 直接读取 `LTW_DATABASE_URL`
- 当前会话没有设置这个变量

处理：

```powershell
$env:LTW_DATABASE_URL = "mysql+pymysql://<db_user>:<db_password>@<db_host>:<db_port>/<db_name>"
.\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
```

## 5. provider 创建成功，但运行 glossary / translation 时报缺少 API key

原因：

- 数据库 `provider` 记录里的 `api_key_value` 为空，且没有可用的 `api_key_secret_ref`
- 或者 `api_key_secret_ref` 指向的环境变量/本地文件不存在或为空
- 或者创建 provider 时传错了 key，后续调用被网关判定为无效凭证

检查：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run.ps1 `
  -Action provider.inspect `
  -ProviderKey <provider_key>
```

处理思路：

- 确认 `provider.inspect` 返回 `api_key_is_set=true`
- 如果未设置或要轮换 key，执行 `provider.set_key`，传 `api_key_value` 或 `api_key_secret_ref`
- 如果 key 已设置但健康检查失败，继续按 `attempts[].error_type` 排查

## 6. `provider.health_check` 失败

优先看返回里的：

- `requested_profile_id`
- `selected_profile_id`
- `attempts`

常见原因：

- 主 profile 的 API key 没设，或 secret ref 无法解析
- Base URL 不通
- fallback profile 根本没创建
- fallback profile 创建了，但对应 key 没设或 ref 不可解析
- 终端兜底 profile 没创建，或终端兜底 profile 对应 provider/key 不可用

处理顺序：

1. 先确认主 profile 的 provider/base_url/api_key_source/api_key_secret_ref 是否有效
2. 再确认普通 fallback 链是否完整
3. 如果配置了终端兜底，确认 `profile.terminal_fallback_inspect` 返回的 profile 都存在且 active
4. 最后再排查模型服务本身是否可用

辅助判断：

- `attempts[*].chain_role=primary` 表示请求入口 profile
- `attempts[*].chain_role=normal_fallback` 表示普通备用链
- `attempts[*].chain_role=terminal_fallback` 表示已经进入终端兜底层
- `terminal_fallback_used=true` 表示本次最终成功命中了终端兜底

## 7. `stage.run` 报 `not_found` 或 profile 找不到

原因：

- 显式传了一个不存在的 `-ModelProfileId`
- 命中的 profile key 没有创建

处理：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run.ps1 `
  -Action profile.list
```

如果你想走默认 profile，就传 `default` 或直接不传。

## 8. `stage.run` 报 scope 非法

常见情况：

- `chapter_range` 少了 `ScopeStart` 或 `ScopeEnd`
- `ScopeStart > ScopeEnd`
- `chapter_list` 少了 `ScopeChapters`
- 给 `review` 或 `export` 传了不支持的 scope

处理：

- `chaptering / glossary / export` 只用 `all / chapter_range / chapter_list`
- `translation` 可以用 `all / chapter_range / chapter_list / stale_only / failed_only / missing_only`
- `review` 可以用 `all / chapter_range / chapter_list / missing_only`

## 9. export 时报缺少目标语言 synopsis

现象：

```text
导出前缺少可用的目标语言简介
```

原因：

- 目标简介为空
- translation 阶段没有成功补齐 target synopsis
- 或 target synopsis 处于不可用状态

先检查：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run.ps1 `
  -Action inspect.synopsis `
  -ProjectId <project_id>
```

处理思路：

- 先确保 translation 阶段已成功执行
- 再确认 target synopsis 状态是 `ready` 或 `completed`
- 确认内容不是空白字符串

## 10. 重复 request_id 导致 replay 或冲突

现象：

- 同一阶段重复执行时返回旧结果
- 或提示请使用新的 `request_id`

原因：

- `request_id` 是幂等键
- 同阶段重复使用同一个 `request_id`，系统会按已有记录处理

处理：

- 每次新运行都生成新的 `request_id`
- 只有你明确要重放相同请求语义时，才复用旧 `request_id`

## 11. 不确定问题出在哪一层

推荐按这个顺序查：

1. `stage.inspect_runs`
2. `inspect.project`
3. 对应阶段的 `inspect.*`
4. `provider.health_check`

常用命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run.ps1 `
  -Action stage.inspect_runs `
  -ProjectId <project_id> `
  -Limit 10

powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run.ps1 `
  -Action inspect.project `
  -ProjectId <project_id>
```

排查原则：

- 先确认数据库和环境变量
- 再确认 provider/profile
- 再确认 stage.run 的参数
- 最后才怀疑业务逻辑本身
