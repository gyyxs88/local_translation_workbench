# 在线发布手册

## 1. 发布形态

当前采用“私有源码仓库 + 公开发布仓库”的形态：

- 私有源码仓库：`gyyxs88/local_translation_workbench`
- 公开发布仓库：`gyyxs88/local_translation_workbench-releases`

公开仓库只用于提供 GitHub Releases 下载，不承载源码开发历史、用户数据、虚拟环境、
模型服务密钥、数据库配置或内部开发文档。

## 2. 发布包内容

发布包由 `scripts/build_release_package.ps1` 从 `git ls-files` 生成，只包含受版本控制的发布文件。

额外排除：

- `docs/superpowers/`
- `docs/reports/`
- `data/projects/`
- `novels/`
- `temp/`

发布包包含：

- Python 工具源码
- `TOOL.json`
- `codex_skill/local_translation_workbench/SKILL.md`
- `INSTALL.md`
- `docs/operations/release-install.md`
- 测试与迁移文件

## 3. 本地生成发布包

在仓库根目录执行：

```powershell
.\scripts\build_release_package.ps1
```

生成物位于 `dist/`：

- `local_translation_workbench-<version>-<timestamp>.zip`
- `local_translation_workbench-<version>-<timestamp>.zip.sha256`

如需生成稳定文件名，执行：

```powershell
.\scripts\build_release_package.ps1 -NoTimestamp
```

## 4. 在线发布仓库

公开下载地址：

```text
https://github.com/gyyxs88/local_translation_workbench-releases/releases
```

当前公开 release：

```text
https://github.com/gyyxs88/local_translation_workbench-releases/releases/tag/v0.1.2
```

## 5. 自动发布

`.github/workflows/release.yml` 会在推送 `v*` tag 时构建发布包。

如果配置了源码仓库 secret `PUBLIC_RELEASE_TOKEN`，workflow 会把发布包同步上传到公开发布仓库。
如果没有配置该 secret，workflow 仍会生成 GitHub Actions artifact，但不会发布到公开仓库。

`PUBLIC_RELEASE_TOKEN` 应使用专门创建的 GitHub token，权限范围只需要覆盖公开发布仓库的 release
写入能力。不要把临时 token、个人主力 token 或模型服务 API Key 写入仓库文件。

## 6. 手动发布到公开仓库

先生成发布包：

```powershell
.\scripts\build_release_package.ps1 -NoTimestamp
```

然后设置本次 shell 的 token 环境变量，再发布：

```powershell
$env:PUBLIC_RELEASE_TOKEN = "<github_token>"
.\scripts\publish_github_release.ps1 `
  -Repository "gyyxs88/local_translation_workbench-releases" `
  -Tag "v0.1.2" `
  -Name "local_translation_workbench 0.1.2" `
  -NotesFile "dist/release-notes.md" `
  -Assets @(
    "dist/local_translation_workbench-0.1.2.zip",
    "dist/local_translation_workbench-0.1.2.zip.sha256"
  )
```

手动发布时 token 只应进入当前 shell 环境变量，不写入文档、脚本、git commit 或远端仓库。

## 7. 发布前检查

发布前至少确认：

```powershell
git status --short
python -m local_translation_workbench help
ltw help
ltw doctor
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run.ps1 help
```

若修改了业务逻辑，还需要跑完整测试：

```powershell
python -m pytest tests -q
```
