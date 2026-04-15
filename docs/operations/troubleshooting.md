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
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests -q
```

注意：

- 测试库必须是独立库
- 绝对不要把业务库填到 `LTW_TEST_DATABASE_URL`

## 2. 在独立仓库模式下仍然报 `No module named 'tools'`

现象：

```text
ModuleNotFoundError: No module named 'tools'
```

原因：

- 你当前代码版本还没有包含独立仓库兼容层
- 或者你并不是在 `local_translation_workbench` 仓库根目录执行
- 或者实际调用的 Python 不是当前项目使用的虚拟环境 Python

处理：

先确认当前目录就是独立仓库根目录，再执行：

```powershell
python -m pytest tests -q
```

如果你仍在 `NovelT` 单体仓库里使用它，则从 `D:\Project\NovelT` 根目录执行：

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests -q
```

## 3. `scripts/run.ps1` 报找不到虚拟环境 Python

现象：

```text
No available virtual environment Python was found.
```

原因：

- `D:\Project\NovelT\.venv\Scripts\python.exe` 不存在
- 工具目录自己的 `.venv` 也不存在

处理：

- 优先确保 `D:\Project\NovelT\.venv` 存在
- 如果单体仓库环境有冲突，再单独给工具目录准备自己的 `.venv`

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
.\.venv\Scripts\python.exe -m alembic -c tools/local_translation_workbench/alembic.ini upgrade head
```

## 5. provider 创建成功，但运行 glossary / translation 时报缺少 API key

原因：

- 数据库里保存的是 `api_key_env_name`
- 真实 key 必须存在于同名环境变量

检查：

```powershell
Get-ChildItem Env:LTW_PROVIDER_API_KEY*
```

再检查 provider 配置：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action provider.inspect `
  -ProviderKey <provider_key>
```

处理思路：

- 确认 `api_key_env_name` 拼写正确
- 确认当前终端里该环境变量确实存在
- 重新打开终端后再试

## 6. `provider.health_check` 失败

优先看返回里的：

- `requested_profile_id`
- `selected_profile_id`
- `attempts`

常见原因：

- 主 profile 的 API key 没设
- Base URL 不通
- fallback profile 根本没创建
- fallback profile 创建了，但对应 key 也没设

处理顺序：

1. 先确认主 profile 的 provider/base_url/api_key_env_name
2. 再确认 fallback 链是否完整
3. 最后再排查模型服务本身是否可用

## 7. `stage.run` 报 `not_found` 或 profile 找不到

原因：

- 显式传了一个不存在的 `-ModelProfileId`
- 命中的 profile key 没有创建

处理：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
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
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
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
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action stage.inspect_runs `
  -ProjectId <project_id> `
  -Limit 10

powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action inspect.project `
  -ProjectId <project_id>
```

排查原则：

- 先确认数据库和环境变量
- 再确认 provider/profile
- 再确认 stage.run 的参数
- 最后才怀疑业务逻辑本身
