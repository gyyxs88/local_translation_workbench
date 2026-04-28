# Glossary 章节并发与可观测性优化记录

日期：2026-04-28

## 背景

前 5 万字真实测试中，`glossary_multi_llm_v1` 已经具备主/副 extractor 两路并发，但每个 extractor 内部仍按章节顺序处理。大范围章节运行时，吞吐受单章节 LLM 调用串行限制；同时运行中只能看到 step 处于 `running`，缺少“当前跑到哪一章、哪一章卡住、失败多少章”的细粒度进度。

## 本次改动

- `glossary.extract` 增加章节级 bounded 并发，默认每个 extractor 最多 3 个章节 worker。
- multi glossary 保留原有两路 extractor 并发，因此默认最大并发形态为 `2 路 extractor × 3 个章节 worker`。
- 每个章节 worker 使用独立 SQLAlchemy session，避免跨线程复用 session。
- `WorkflowStepRun.output_payload.progress` 增加运行中进度：章节总数、queued/running/completed/skipped/failed 计数、每章状态、候选数、错误信息、开始/更新时间。
- `stage.inspect_runs` 的 `workflow.steps[*]` 会在存在 progress 时直接返回该字段。
- 完成、跳过、失败的 progress 写入移动到章节事务 commit/rollback 之后，避免 worker 写 `GlossaryChapterStatus` 后再用另一个 session 锁同一 `WorkflowStepRun` 造成自锁等待。
- 失败路径的 workflow 持久化改为优先更新已存在的 `WorkflowRun` / `WorkflowStepRun`，避免 stage orchestrator 在已提交 workflow run 后重复补记失败 run。

## 语义取舍

章节级并发后，同一批次内刚抽出的 draft 术语不会即时作为其它章节 extractor prompt 的上下文。extractor prompt 仍会注入已落库 active glossary 和当前章节命中的既有术语；本批新增术语会在 normalize / review / finalize 后进入正式术语表，供后续阶段或后续运行使用。

## 验证

- 新增并发红测：确认同一 extractor 内至少两个章节 worker 会同时进入 provider 调用。
- 新增可观测性红测：确认 `stage.inspect_runs` 暴露 `workflow.steps[*].progress`。
- 完整回归：`348 passed in 543.19s (0:09:03)`。
