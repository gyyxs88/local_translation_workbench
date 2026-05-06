# 《地府叫我小先生》前 10 万字流程可用性测试修复报告

日期：2026-05-05
工具：local_translation_workbench
目标模型栈：gpt_5_5_aicodelink + deepseek_v4_pro
Todoist 项目：local_translation_workbench 可用性测试

## 结论

本轮围绕《地府叫我小先生》前 10 万字所在章节的完整流程做了可用性测试、问题归类、Todoist 同步和逐项修复。所有已发现的 P0/P1/P2 问题均已修复并关闭 Todoist 任务。最终全量回归结果：

```text
409 passed in 281.38s
```

测试过程中新冒出的 4 个问题也已作为 Todoist 任务创建并关闭：

- P2-7：stage.inspect_runs 报告扫描重新查询大 JSON 列
- P2-8：默认 route 覆盖显式 ModelProfileId
- P2-9：route 默认值测试污染后续用例
- P2-10：全跳过术语抽取测试基线仍按旧语义断言

## 已修复问题清单

| 编号 | 类型 | 问题 | 修复结果 | 验证 |
| --- | --- | --- | --- | --- |
| P0-1 | 架构/流程 | 默认翻译流程没有真正体现双模型路由，用户配置 gpt_5_5 + deepseek 后仍容易走单模型路径 | 增补多模型 workflow 默认切换能力，route default 可同步切换 glossary/translation 为 multi workflow | workflow/model route 定向测试通过 |
| P0-2 | 逻辑 | glossary.extract 全章节跳过仍可能以 completed+0 candidates 结束 | 全章节跳过改为 provider_error，保留失败 step、token_usage 和 stage_report | glossary stage 测试通过 |
| P0-3 | 稳定性 | LLM 返回空内容、代码块 JSON、非法 JSON 时处理不一致 | 抽出 JSON 响应解析与空响应重试语义，Provider/Workflow 统一处理 | provider 与 workflow draft 测试通过 |
| P0-4 | 可恢复性 | 长流程取消/中断后的状态表达与恢复入口不足 | 增加取消检查、stage.cancel、resume/rerun 冲突检查与失败上下文持久化 | stage resume/conflict 测试通过 |
| P1-1 | 性能 | stage.inspect_runs 可能按大 JSON payload 排序或加载过重 | 改为先查 id 再取实体，避免 output_payload 进入有序查询 | project action 测试通过 |
| P1-2 | 可恢复性 | resume 后部分成功结果不能自动收口 finalize | 增补 resume 自动 finalize 和 stale/missing/failed only 范围处理 | stage resume、translation 测试通过 |
| P1-3 | 可观测性 | provider 失败、fallback 和实际模型名不够透明 | provider.health_check、fallback_depth、actual_model_name、token_usage 接入 inspect 输出 | provider/model route 测试通过 |
| P1-4 | 部署安全 | 数据库 schema 版本不匹配时仍可能继续执行 | 增加 schema_version guard，stage.run 前校验 Alembic head | schema version 测试通过 |
| P1-5 | 审校 | hybrid review 的 LLM rewrite 进度、问题写入与 inspect 暴露不足 | 增补质量循环字段、progress、rewrite version、LLM issue 持久化 | review LLM quality loop 测试通过 |
| P1-6 | 翻译质量 | hard-only glossary_term_missing 有单字术语误报和拼写符号误报 | 单 CJK 术语过滤，目标术语比对忽略大小写/标点/连字符差异 | review/export 与 glossary extraction 测试通过 |
| P1-7 | 质检能力 | 缺少翻译样本抽查入口，难以按来源复核 GPT/DeepSeek/rewrite 结果 | 增加 inspect.translation_samples，并清理 draft/rewrite/finalize 尾随空格 | translation inspection 测试通过 |
| P2-1 | CLI/编码 | PowerShell 中文 JSON/备注/密钥参数容易乱码或转义失败 | 增加 `-XxxFile` 与 `@utf8-file` 参数读取，覆盖 route/profile/workflow 等入口 | CLI UTF-8 文件参数测试通过 |
| P2-2 | 报告 | 阶段完成后没有统一问题报告，用户要靠日志拼状态 | 增加 StageCompletionReportService，stage.run/inspect_runs 输出 stage_report | stage completion report 测试通过 |
| P2-3 | 导出 | export 没有显式标记 pending/needs_revision 审校风险 | manifest/markdown 增加 review_risk、needs_revision/pending 统计和章节风险块 | review export 测试通过 |
| P2-4 | 默认配置 UX | 默认 route/default workflow 缺少闭环，用户需要手动传 route | route_set_default 支持 workflow_mode；stage.run 可自动使用默认 route | model route/stage action 测试通过 |
| P2-5 | 术语风格 | 缺少抽样后的术语/称谓风格决策表 | 产出术语风格决策文档，区分强制术语、软术语、注释优先、称谓组 | 文档完成 |
| P2-6 | 注释层 | 文化典故/民俗语缺少抽样清单 | 产出注释层抽样清单和 annotation.extract 建议章节 | 文档完成 |
| P2-7 | 性能回归 | 新 stage_report 扫描跳过章节时重新带上 output_payload 大 JSON 列 | 报告扫描同样改为 id-first 读取 | 全量回归通过 |
| P2-8 | UX 回归 | 默认 route 会覆盖用户显式传入的 ModelProfileId | 仅当 ModelProfileId 为空/default 且未传 RoutePresetKey 时自动套默认 route | 全量回归通过 |
| P2-9 | 测试稳定性 | 默认 route/workflow 测试留下全局状态，污染后续用例 | 测试 finally 恢复 single workflow 默认并清除默认 route | 全量回归通过 |
| P2-10 | 测试基线 | 全跳过术语抽取旧测试仍期待 completed | 更新为失败语义并验证 token_usage 保留 | 全量回归通过 |

## 产出文档

- `docs/reports/2026-05-05-difu-glossary-term-missing-analysis.md`
- `docs/reports/2026-05-05-difu-translation-sample-review.md`
- `docs/reports/2026-05-05-difu-term-style-decision-table.md`
- `docs/reports/2026-05-05-difu-annotation-sample-checklist.md`
- `docs/reports/2026-05-05-difu-usability-fix-final-report.md`

## 当前状态

- Todoist：本轮已知任务均已创建并关闭。
- 自动化测试：全量通过。
- 仍需人工关注：翻译文本本身仍建议继续做读者视角抽样，尤其是术语强制程度、民俗注释密度、人物称谓一致性三类问题。工具层面这次发现的阻断项已经收口。
