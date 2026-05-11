# 公开发布检查清单

本目录是公开发布候选版本，只保留代码、测试、迁移、CI、安装文档和运行手册。

公开前请确认：

- 不包含 `data/projects/`、`novels/`、`temp/`、`.worktrees/`、`.pytest_cache/`。
- 不包含 `docs/reports/`、`docs/superpowers/` 等本地测试报告或内部计划材料。
- 不包含 `.env`、数据库 dump、本地 SQLite、证书、私钥或真实 provider/API key。
- 示例数据库连接串、provider 地址、profile key 均使用占位值。
- Git 历史从公开候选版本的首提交开始，不继承私有仓库历史。

如果要把现有远端仓库转公开，推荐先删除或替换所有旧分支和 tag，再推送本候选仓库的干净历史。
更稳妥的做法是新建一个公开仓库，将本候选仓库作为初始内容推送。
