# 变更记录

本文件记录项目的重要变更。

格式参考 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)，当前项目仍采用手工发布流程。

## [Unreleased]

## [0.1.3] - 2026-05-21

### 变更

- 在线发布 workflow 改为优先使用 GitHub App 短期 installation token 发布公开 release，保留 `PUBLIC_RELEASE_TOKEN` 作为临时回退。
- 在线发布文档同步 GitHub App 安装范围、权限、secrets 和 token 边界。

## [0.1.2] - 2026-05-21

### 修复

- `scripts/run.ps1` 在没有仓库根目录 `.venv` 时会回退到 PATH 上的 `python`，适配 GitHub Actions 和已安装 Python 包的源码运行场景。
- 修正跨平台 smoke 测试：POSIX 环境不再硬依赖 Windows `.venv\Scripts\python.exe`，缺少 Windows PowerShell 时跳过对应 `run.ps1` 文件传参测试。

## [0.1.1] - 2026-05-21

### 新增

- 增加公开发布仓库 `gyyxs88/local_translation_workbench-releases` 的在线发布流程。
- 增加发布包构建脚本、GitHub Release 上传脚本和 tag 触发的 release workflow。
- 增加在线发布手册，明确私有源码仓库与公开下载仓库的边界。

### 变更

- 最低 Python 版本统一调整为 `3.10+`，匹配当前固定依赖 `json-repair==0.59.5` 的真实要求。
- GitHub Actions CLI smoke 矩阵从 Python 3.9/3.13 调整为 3.10/3.13。
- 已验证的完整回归基线刷新为 `441 passed, 1 skipped`。

### 新增

- 增加发布包安装快速指引与 Codex 接入手册，明确 zip 源码包的虚拟环境、数据库迁移、provider/profile 初始化、`TOOL.json` external tool 注册和 skill 安装要求。
- 增加 agent 侧术语表管理 action：`glossary.entry.create/update/delete/lock/unlock` 与 `glossary.candidate.create/update/approve/reject/delete/promote`。
- 增加本地 Codex skill 规则文件，明确多 LLM 术语结果由 agent 基于证据仲裁，工具代码只负责产出候选、证据和检查结果。
- `translation_multi_llm_v1` 已支持 `generate_primary / generate_secondary / review_drafts / rewrite_consensus / finalize_segments` 五个 step 内部按 segment 真并发执行，同时保留 draft version、draft review 与正式译文版本结构。
- 为 translation 多 LLM 真并发补齐回归覆盖，覆盖 generate / review / rewrite / finalize 的并发执行、部分失败保留已成功结果，以及 step payload 聚合字段校验。
- `inspect.translation` 已支持当前 active version 的 provenance 输出，能够显示 finalize step、selected draft 与 selected draft reviews。
- `inspect.translation` 已支持单段 compare 模式，可在当前 active version 与指定历史正式版本之间返回结构化变化摘要。
- `inspect.translation` 已支持当前 active version 来源链 `timeline`，能够显示 `draft_created / review_created / finalize_committed` 事件序列。
- `stage.inspect_runs` 已支持结构化 `summary` 和 failed run `diagnostics`，可直接查看 `error / failure_step / model_profile_id / model_name`。
- `stage.inspect_runs` 已支持结构化 `timing / recovery / fallback` 观测，可直接查看运行耗时、resume/rerun 来源和 fallback 命中深度。
- `stage.inspect_runs` 已支持稳定运行画像，直接返回 `scope_value / context / result / workflow`；glossary / translation run 可直接查看 workflow step 摘要、step counts、fallback depth 与实际模型名。
- glossary 已支持结构化 `gender` 字段，并贯通到 draft candidate、candidate、entry、`inspect.glossary`、`glossary.inspect_pipeline` 与 translation glossary prompt/snapshot。
- glossary 已支持结构化 `age_group` 字段，并贯通到 draft candidate、candidate、entry、`inspect.glossary`、`glossary.inspect_pipeline` 与 translation glossary prompt/snapshot。
- `inspect.glossary` 已支持 `relation_groups`，可直接查看同组术语的成员分布与结构化一致性告警。
- `glossary.inspect_pipeline` 已支持 `finalized_terms / finalized_relation_groups`，可直接查看 finalize 后的正式视角。
- `inspect.translation` 已支持单段 `version_id` 历史版本切换，`version / provenance / timeline / compare.current_version` 现已围绕当前选中正式版本组织。
- `inspect.review` / `inspect.export` 已支持顶层 `translation_source`；review/export run summary 也会记录轻量正式译文来源快照。

### 变更

- `TOOL.json` action 枚举已同步真实 handler，补齐 `annotation.*`、`glossary.denylist.*`、`stage.cancel` 与 provider 调用观测 inspect action。
- `docs/operations` 接入与排障文档已同步数据库 `api_key_value` 配置方式，移除旧 `api_key_env_name` 指引。
- README、Codex skill 与运维手册已收口到独立 GitHub 仓库 `https://github.com/gyyxs88/local_translation_workbench.git`，默认入口统一为仓库根目录下的 `scripts/run.ps1`。
- Anthropic Messages provider 默认输出上限提升到 `8192`，并在 `stop_reason=max_tokens` 时返回结构化 provider 错误，避免截断译文被当作成功结果落库。
- CLI 数字参数解析统一返回结构化 `invalid_arguments`，避免非法数字参数泄出 Python traceback。
- glossary 质量过滤会剔除 standalone 届数结构壳，例如 `67届`，避免它们进入术语候选或正式术语。
- `TOOL.json` 与 CLI help 已同步最新 provider/profile 路由、glossary 管理和 annotation action 面。
- 项目文档已同步到 glossary gender 建模、translation provenance、stage inspect diagnostics 和 translation 多 LLM 并发落地后的真实状态。
- 项目文档已同步到 glossary age group 建模落地后的真实状态。
- 项目文档已同步到 translation inspect version compare 落地后的真实状态。
- 项目文档已同步到 translation inspect timeline 落地后的真实状态。
- `translation` 运行链路已进一步收口：inspect、run、draft workflow、execution layer 都已拆到专用 service，`translation_service` 与 `translation_pipeline_service` 只保留薄入口编排。
- `stage` 执行链路已进一步收口：run orchestrator、action execution helper、response formatter 与 pipeline action support 已拆分，`stage_service`、`stage_handlers` 与 `project.run_full` 入口显著变薄。
- `action_router` 已收为薄路由壳；通用参数/session helper 独立到 `action_support`，handler 层不再把 `action_router` 当工具箱，仅保留 `model stage provider` 解析 seam。
- translation 正式译文版本已补充 provenance 指针，便于后续历史追踪与问题排查。
- `stage.inspect_runs` 不再返回字符串形式的 `summary`，而是直接返回对象。
- glossary snapshot 现在会感知 `gender` 变化，translation 术语 prompt 会在 `gender` 非空时附带 `gender`。
- glossary snapshot 现在也会感知 `age_group` 变化，translation 术语 prompt 会在 `age_group` 非空时附带 `age_group`。
- translation glossary prompt 现在按关系组渲染 `[group ...]` block，只注入正文真实命中的表面形式，不再把同组未命中的 canonical 术语顺带扩写进去。
- 项目文档已同步到 `P1.2 / P1.3` 尾项完成后的真实状态。
- 项目文档已同步到 `P1.4` 尾项完成后的真实状态。
- 完成本地翻译工作台维护性瘦身，拆分 workflow runtime、translation workflow execution 与 glossary service 的内部职责；本轮不新增 action、不改数据库 schema。
- 已验证的完整回归基线从 `237 passed` 刷新为 `242 passed`。
- 已验证的完整回归基线进一步刷新为 `269 passed`。
- 已验证的完整回归基线进一步刷新为 `281 passed`。
- 已验证的完整回归基线进一步刷新为 `284 passed`。
- 已验证的完整回归基线进一步刷新为 `302 passed`。
- 已验证的完整回归基线进一步刷新为 `375 passed`。
- 已验证的完整回归基线进一步刷新为 `425 passed`。
- 已验证的完整回归基线进一步刷新为 `431 passed`。

## [0.1.0] - 2026-04-15

### 新增

- 增加本地翻译工作台的核心 action 面，覆盖 project、provider、profile、workflow、stage orchestration 与 inspection 查询。
- 增加 chaptering、glossary、translation、review、export、synopsis 全链路能力，并通过 Alembic 迁移和 MySQL 完成持久化。
- 增加 provider profile fallback 解析与 provider 健康检查支持。
- 增加章节级与段落级 inspect 动作：`inspect.chapter`、`inspect.chapters`、`inspect.segment`。
- 增加自动化回归覆盖，并验证了 `198 passed` 的初始稳定基线。
