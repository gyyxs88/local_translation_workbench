# 变更记录

本文件记录项目的重要变更。

格式参考 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)，当前项目仍采用手工发布流程。

## [Unreleased]

### 新增

- `translation_multi_llm_v1` 已支持 `generate_primary / generate_secondary / review_drafts / rewrite_consensus / finalize_segments` 五个 step 内部按 segment 真并发执行，同时保留 draft version、draft review 与正式译文版本结构。
- 为 translation 多 LLM 真并发补齐回归覆盖，覆盖 generate / review / rewrite / finalize 的并发执行、部分失败保留已成功结果，以及 step payload 聚合字段校验。
- `inspect.translation` 已支持当前 active version 的 provenance 输出，能够显示 finalize step、selected draft 与 selected draft reviews。

### 变更

- 项目文档已同步到 translation 多 LLM 真并发落地后的真实状态。
- translation 正式译文版本已补充 provenance 指针，便于后续历史追踪与问题排查。
- 已验证的完整回归基线从 `198 passed` 刷新为 `208 passed`。

## [0.1.0] - 2026-04-15

### 新增

- 增加本地翻译工作台的核心 action 面，覆盖 project、provider、profile、workflow、stage orchestration 与 inspection 查询。
- 增加 chaptering、glossary、translation、review、export、synopsis 全链路能力，并通过 Alembic 迁移和 MySQL 完成持久化。
- 增加 provider profile fallback 解析与 provider 健康检查支持。
- 增加章节级与段落级 inspect 动作：`inspect.chapter`、`inspect.chapters`、`inspect.segment`。
- 增加自动化回归覆盖，并验证了 `198 passed` 的初始稳定基线。
