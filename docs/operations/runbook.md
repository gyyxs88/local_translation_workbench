# 最小试跑手册

## 1. 目标

本文档用于完成一次从项目创建到导出的最小闭环试跑，验证下面这条主线是否可用：

`project.create -> chaptering -> glossary -> translation -> review -> export`

默认假设：

- 已按 [接入初始化手册](./setup.md) 配好数据库、数据目录和 provider/profile
- 当前从 `D:\Project\NovelT` 根目录执行

先生成一组本次试跑专用的请求后缀，避免重复使用固定 `request_id` 触发幂等重放：

```powershell
$runId = Get-Date -Format "yyyyMMddHHmmss"
```

## 2. 准备样例输入

临时文件统一放 `temp/`：

```powershell
New-Item -ItemType Directory -Force temp | Out-Null
@'
## 简介

这是一个最小试跑用的简介。

## 正文

### 1

林溪第一次见到赵馨宁。

### 2

两人约定明天再见。
'@ | Set-Content -Encoding UTF8 temp\ltw-smoke-source.md
```

## 3. 创建项目

```powershell
$createRaw = powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action project.create `
  -RequestId "smoke-project-create-$runId" `
  -SourcePath "D:/Project/NovelT/temp/ltw-smoke-source.md" `
  -SourceLanguage zh `
  -TargetLanguage en

$create = $createRaw | ConvertFrom-Json
$projectId = $create.data.id
$projectId
```

检查点：

- `ok = true`
- 记录返回的 `data.id`
- `data.project_key` 已生成

## 4. 运行 chaptering

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action stage.run `
  -ProjectId $projectId `
  -Stage chaptering `
  -ScopeType all `
  -RequestId "smoke-chaptering-$runId"
```

建议马上检查：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action inspect.synopsis `
  -ProjectId $projectId

powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action inspect.chapters `
  -ProjectId $projectId `
  -IncludeSegments true
```

预期：

- 章节被正确切开
- source synopsis 状态为 `ready` 或已有有效内容
- 章节和段落统计看起来正常

## 5. 运行 glossary

如果你已经配置了默认 profile，可以直接省略 `-ModelProfileId`；为了让试跑过程更明确，这里显式传 `default`：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action stage.run `
  -ProjectId $projectId `
  -Stage glossary `
  -ScopeType all `
  -ModelProfileId default `
  -RequestId "smoke-glossary-$runId"
```

检查：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action inspect.glossary `
  -ProjectId $projectId
```

预期：

- glossary 阶段返回 `ok = true`
- `inspect.glossary` 能看到术语条目或结构化结果

## 6. 运行 translation

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action stage.run `
  -ProjectId $projectId `
  -Stage translation `
  -ScopeType all `
  -ModelProfileId default `
  -RequestId "smoke-translation-$runId"
```

检查：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action inspect.translation `
  -ProjectId $projectId

powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action inspect.segment `
  -ProjectId $projectId `
  -ChapterIndex 1 `
  -SegmentIndex 1
```

预期：

- 各段落已有 active version
- target synopsis 已经补齐或保持可用
- `inspect.segment` 能直接看到当前 active 译文

## 7. 运行 review

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action stage.run `
  -ProjectId $projectId `
  -Stage review `
  -ScopeType all `
  -RequestId "smoke-review-$runId"
```

检查：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action inspect.review `
  -ProjectId $projectId
```

预期：

- review 阶段返回 `ok = true`
- 能看到 review run 和 issue 列表

## 8. 运行 export

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action stage.run `
  -ProjectId $projectId `
  -Stage export `
  -ScopeType all `
  -RequestId "smoke-export-$runId"
```

检查：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action inspect.export `
  -ProjectId $projectId

powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action stage.inspect_runs `
  -ProjectId $projectId `
  -Limit 10
```

预期：

- export 阶段返回 `ok = true`
- `inspect.export` 能看到导出 run 和 artifact 列表
- `stage.inspect_runs` 能看到从 chaptering 到 export 的阶段记录

## 9. 常用变体

### 9.1 只跑指定章节

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action stage.run `
  -ProjectId $projectId `
  -Stage translation `
  -ScopeType chapter_list `
  -ScopeChapters 1,2 `
  -ModelProfileId default `
  -RequestId "smoke-translation-chapter-list-$runId"
```

### 9.2 只补翻未生成译文的段落

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action stage.run `
  -ProjectId $projectId `
  -Stage translation `
  -ScopeType missing_only `
  -ModelProfileId default `
  -RequestId "smoke-translation-missing-only-$runId"
```

### 9.3 只补 review 缺失的段落

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_translation_workbench/scripts/run.ps1 `
  -Action stage.run `
  -ProjectId $projectId `
  -Stage review `
  -ScopeType missing_only `
  -RequestId "smoke-review-missing-only-$runId"
```

## 10. 试跑通过标准

满足下面条件，就可以认为最小闭环试跑通过：

- `project.create` 成功
- `chaptering / glossary / translation / review / export` 全部返回 `ok = true`
- `inspect.synopsis / inspect.chapters / inspect.translation / inspect.review / inspect.export` 都能返回结构化结果
- 导出产物已落盘
- `stage.inspect_runs` 能看到完整阶段记录

如果中途任何一步失败，直接看 [常见故障排查](./troubleshooting.md)。
