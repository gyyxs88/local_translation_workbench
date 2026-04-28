# Glossary 暂存术语一致性检查优化记录

日期：2026-04-28

## 背景

章节级并发后，同一批次内新抽出的 draft candidate 不再作为其它章节 extractor prompt 的即时上下文。这提升了吞吐，但也带来批内一致性风险：同一原文术语可能出现不同译名，同一关系组可能出现多个 canonical，或者同一类别的术语翻译风格偏离项目已有正式术语。

## 本次改动

- 新增 glossary workflow 步骤 `glossary.review_consistency`，位置在 `review_scope` 之后、`finalize` 之前。
- `glossary_single_llm_v1` 与 `glossary_multi_llm_v1` 内置链路都已接入 `review_consistency`。
- 一致性结果继续写入 `GlossaryCandidateReview`，`review_type=consistency`，不新增数据库迁移。
- 确定性预检覆盖：
  - 同一 `source_term` 在本批 draft 中出现多个 `suggested_term`。
  - draft 译名与已有 active glossary 同源术语冲突，locked entry 优先。
  - 同一 `term_group_key` 内缺失 canonical、多个 canonical、混合 category、gender 冲突、age_group 冲突。
- LLM 风格审核 prompt 会显式传入已有 active glossary 作为“正式术语风格基准”。
- 每条 consistency review 的 `structured_payload.style_baseline.source` 固定为 `active_glossary`。
- `glossary.finalize` prompt 会收到 consistency review evidence，并明确要求风格取舍优先遵循已有正式术语基准。
- 当没有终审 provider 结果时，fallback finalize 会使用 consistency review 给出的 `suggested_term`，确保 locked active glossary 的既有译名不会被本批 draft 覆盖。

## 关键语义

风格检查不能以本批 draft 自己作为基准。存在同 category 的 active glossary 时，以 active glossary 的正式译名风格为准；不存在正式基准时，只做本批内部冲突检查，并把 `style_baseline.status` 标为 `missing`。

## 已验证

- `tests/test_glossary_workflow_domain_service.py` 覆盖：
  - 风格审核 prompt 必须包含 active glossary baseline。
  - 同源不同译会生成 `source_translation_conflict`。
  - locked active glossary 冲突会优先建议 locked target term。
- `tests/test_workflow_actions.py` 覆盖：
  - 内置 workflow 步骤列表包含 `review_consistency`。
  - multi glossary workflow 在 finalize 前执行一致性审核。
- `tests/test_glossary_stage.py` 已同步默认 glossary 链路新增的一次 consistency review 调用。
- 局部回归：`67 passed in 191.63s (0:03:11)`。
- 完整回归：`351 passed in 585.45s (0:09:45)`。
