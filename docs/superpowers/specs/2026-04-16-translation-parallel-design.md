# Translation Multi-LLM 并发执行设计

## 1. 背景

当前 `translation_multi_llm_v1` 已经具备：

- `generate_primary`
- `generate_secondary`
- `review_drafts`
- `rewrite_consensus`
- `finalize_segments`

这条完整 workflow 链路，也已经能把 draft、review、rewrite、finalize 的中间产物写入现有 workflow 存储。

但当前真实执行模型仍然是串行的：

- workflow step 之间按顺序执行
- 每个 step 内部也按整批 segment 串行处理
- `review_drafts` 和 `rewrite_consensus` 还是“整批 prompt -> 整批 JSON 返回”的单次调用模式

这会带来三个直接问题：

- 总耗时随 segment 数量近似线性增长，multi workflow 的吞吐收益不明显
- `review_drafts` / `rewrite_consensus` 的单次大 prompt 容易变大，规模上去后不稳定
- 当前 glossary 已经有真并发模式，但 translation 还没有承接同类 runtime 能力，两个模块的执行策略不一致

用户已经明确要求本轮走：

- 覆盖 `generate / review / rewrite / finalize`
- 兼容优先

也就是：

- 不推翻当前 `translation_multi_llm_v1` 的外部 workflow 语义
- 不重新定义 inspect 与历史产物结构
- 主要通过执行层并发提升吞吐

## 2. 目标

本轮目标有五个：

1. 在不改变 `translation_multi_llm_v1` 外部步骤顺序的前提下提升吞吐
2. 保持 `generate -> review -> rewrite -> finalize` 的现有业务语义
3. 保持现有 draft version、draft review、正式译文版本的落库结构兼容
4. 让失败结果仍然可 inspect、可分析，而不是一失败就整批信息丢失
5. 为后续 translation 的历史追踪和可观测性增强打基础

## 3. 非目标

本轮明确不做下面这些事情：

- 不把 `review_drafts` 和 `rewrite_consensus` 变成彼此并发的 step
- 不改 `translation_multi_llm_v1` 的 step 定义和对外 action 名称
- 不引入消息队列、进程池、外部任务系统
- 不重做 draft/review/finalize 的表结构
- 不在本轮重做 `failed_only` 的全链路语义
- 不顺手补历史版本 inspect 增强，这属于后续 P1.3

## 4. 方案选择

本轮考虑三种方案：

### 4.1 方案 A：只并发双 draft step

做法：

- 只把 `generate_primary` 和 `generate_secondary` 变成真并发
- 后续 `review_drafts -> rewrite_consensus -> finalize_segments` 保持当前整批串行

优点：

- 风险最低
- 与 glossary extractor 并发模式最接近

缺点：

- 提升有限
- 不能覆盖用户已经明确要求的 review / rewrite / finalize 吞吐问题

### 4.2 方案 B：步骤内部按 segment 分片并发

做法：

- 外部 workflow step 顺序不变
- 每个 step 内部按 segment 切分成独立 worker 并发执行
- 主线程只负责 step run 创建、worker 调度、结果汇总

优点：

- 兼容性最好
- 可以覆盖 generate、review、rewrite、finalize 全链路
- 不需要重写现有 inspect 与历史版本结构

缺点：

- 实现复杂度中等
- 需要把 translation pipeline 从“整批处理器”拆成“批量调度器 + 单 segment worker”

### 4.3 方案 C：内部流式流水线

做法：

- 对外仍然保留 5 个 step
- 但内部允许部分 segment 先进入 review / rewrite，不等整批 generate 完成

优点：

- 理论吞吐最高

缺点：

- 对当前 step summary、inspect、失败恢复语义冲击最大
- 很容易在“兼容优先”目标下失控

### 4.4 结论

本轮采用：

**方案 B：保持 step 顺序不变，步骤内部按 segment 分片并发**

这是当前约束下最稳的折中：

- 对外仍然是现有 `translation_multi_llm_v1`
- 对内通过 segment worker 提升吞吐
- 能复用 glossary 已验证过的“独立 session + 独立 pipeline worker + 主线程汇总”模式

## 5. 并发边界

本轮并发边界严格限定为：

- `translation_multi_llm_v1`
- 每个 step 内部的 segment 处理

也就是说：

- `generate_primary`：多个 segment 并发生成 primary draft
- `generate_secondary`：多个 segment 并发生成 secondary draft
- `review_drafts`：多个 segment 并发审核对应 draft
- `rewrite_consensus`：多个 segment 并发生成 rewrite draft
- `finalize_segments`：多个 segment 并发落正式版本

但下面这些关系保持不变：

- `generate_primary` 仍然先于 `generate_secondary`
- `generate_secondary` 仍然先于 `review_drafts`
- `review_drafts` 仍然先于 `rewrite_consensus`
- `rewrite_consensus` 仍然先于 `finalize_segments`

原因很简单：

- `review_drafts` 依赖两个 draft 已经存在
- `rewrite_consensus` 依赖 review 结果
- `finalize_segments` 依赖可选出的最终 draft

所以本轮不是“step 间并发”，而是“step 内并发”。

## 6. 运行时模型

### 6.1 总体模型

每个 translation workflow step 的执行模型调整为：

1. 主线程创建 workflow run / step run
2. 主线程解析当前 step 所需的 segment 集合
3. 主线程准备共享的只读上下文
4. 主线程提交多个 segment worker
5. 每个 worker 使用独立 session 和独立 pipeline 实例执行业务
6. 主线程等待所有 worker 完成
7. 主线程汇总 step 结果并更新 step run 状态

### 6.2 共享上下文与 worker 边界

主线程负责准备的共享上下文包括：

- `project_id`
- `workflow_run_id`
- `workflow_step_run_id`
- `scope`
- 当前 step 的 resolved model 信息
- segment 列表与只读索引
- glossary snapshot
- synopsis 前置状态

worker 内部禁止复用主线程对象：

- 禁止复用主 runtime 的 `self.session`
- 禁止复用主线程持有的 pipeline/service/repository
- 禁止直接写主线程的可变内存状态

worker 只接收最小输入：

- 当前 step 的元信息
- 当前 segment 的标识与必要内容
- 只读上下文副本

### 6.3 Session 与 Provider 策略

每个 worker 必须：

- 自己创建独立 SQLAlchemy session
- 自己基于新 session 构造 `TranslationPipelineService` 克隆实例
- 成功时自行 commit
- 失败时自行 rollback

本轮默认：

- provider 对象允许线程间复用
- pipeline / service / repository 不允许线程间复用

如果后续发现某条 provider 路线不是线程安全的，再把 provider 构造也下沉到 worker 内部，但这不是本轮默认方案。

## 7. Translation Pipeline 拆分

### 7.1 现状问题

当前 `TranslationPipelineService` 主要面向“整批 step”：

- `generate_draft` 内部按 segment 循环
- `review_draft` 构造全量 prompt，一次返回所有 segment 的 reviews
- `rewrite_draft` 构造全量 prompt，一次返回所有 segment 的 rewrites
- `finalize` 一次处理全部 segment 的最终定稿

这不利于并发。

### 7.2 新职责拆分

本轮把 translation pipeline 拆成两层：

- 批量调度层：负责准备上下文、分发 segment worker、聚合结果
- 单 segment 执行层：负责真正处理单个 segment

要求：

- 对外暴露的 action 仍然是现有四个
- 但 action 内部允许调用新的 `_generate_draft_for_segment`、`_review_draft_for_segment`、`_rewrite_draft_for_segment`、`_finalize_segment` 这类辅助执行单元

### 7.3 `fork_for_session()`

`TranslationPipelineService` 需要新增：

- `fork_for_session(session)`

作用：

- 基于新 session 克隆一个 translation pipeline 实例
- 复用 `base_data_dir`
- 复用 provider
- 重新初始化 repository / synopsis service / glossary repository

这样 runtime 才能像 glossary 并发路径那样安全分发 worker。

## 8. 各 step 的具体设计

### 8.1 `generate_primary` / `generate_secondary`

主线程先做一次性的前置准备：

- 校验 project / provider / scope
- 解析 segment 列表
- 补齐 synopsis
- 计算 glossary snapshot

随后每个 segment worker 独立完成：

- 读取原文
- 构造 prompt
- 调 provider
- 写 workflow 目录下的 draft 文件
- 写 `TranslationDraftVersion`

保持不变的点：

- `draft_role` 仍然是 `primary` 或 `secondary`
- `evidence_payload` 仍然保留 fallback 信息
- 不会提前切 active version

### 8.2 `review_drafts`

本轮不再走“单次大 prompt 审整批段落”的模式，而改成：

- 每个 segment 独立构造 review prompt
- 每个 segment 独立调 provider
- 每个 segment 独立写对应 draft 的 `TranslationDraftReview`

保持不变的点：

- review 仍然是挂在现有 `TranslationDraftReview` 表上
- `review_type / decision / score / reason_codes / structured_payload` 结构保持兼容

变化点：

- 不再依赖 provider 一次返回整批 `reviews`
- step payload 改为汇总型结果，而不是整批 JSON 的直接映射

### 8.3 `rewrite_consensus`

每个 segment worker 独立完成：

- 读取该 segment 的 draft 与 review
- 构造 rewrite prompt
- 调 provider
- 写 `draft_role="rewrite"` 的 `TranslationDraftVersion`

保持不变的点：

- rewrite 仍然只是 workflow 中间产物
- 仍然通过 `parent_draft_id` / `parent_draft_role` 记录来源

### 8.4 `finalize_segments`

每个 segment worker 独立完成：

- 读取当前 segment 的 draft / review
- 选择最终 draft
- 写正式 `SegmentTranslationVersion`
- 更新 `SegmentTranslation.active_version_id`
- 将 segment 标记为 `translated`
- 将 segment 的 `review_status` 标记为 `pending`

主线程汇总后再统一做：

- `review/export` 相关 run 标脏
- `active_version_ids` 聚合
- 受影响章节范围聚合

这样可以避免多个 worker 重复扫表和重复标脏。

## 9. 落库与输出约束

本轮坚持：

- 不新增数据库 schema
- 不改 draft / review / official version 现有表的核心语义
- 不把 inspect 输出改成全新结构

### 9.1 保持兼容的落库对象

继续沿用现有对象：

- `TranslationDraftVersion`
- `TranslationDraftReview`
- `SegmentTranslation`
- `SegmentTranslationVersion`

### 9.2 Step Payload 扩展

每个 step 的 `output_payload` 在保留现有核心字段的同时，增加汇总字段：

- `succeeded_segment_count`
- `failed_segment_count`
- `failed_segments`
- `actual_model_profiles`
- `max_fallback_depth`

必要时还可补：

- `written_draft_count`
- `written_review_count`
- `finalized_segment_count`

这样做的目的是：

- 不破坏现有 payload 消费方
- 让后续 inspect / 排障可以直接看到 segment 级失败信息

### 9.3 文件输出约束

仍然保持当前目录结构：

- workflow 中间 draft 写在 `translations/workflows/<workflow_run_id>/segments/...`
- 正式译文版本写在 `translations/segments/<segment_id>/...`

本轮不改目录层级。

## 10. 失败语义与恢复策略

### 10.1 generate quorum 语义

`generate_primary` 和 `generate_secondary` 仍然属于 tolerant quorum 语义。

保持不变的点：

- 只要 step 组成功数满足 `minimum_success`
- workflow 就允许继续
- summary 中仍可标记 degraded

变化点：

- 每个 generate step 自身也会有 segment 级成功/失败统计
- group 汇总时要同时保留 step 级失败和 segment 级失败信息

### 10.2 review / rewrite / finalize 语义

这三个 step 继续保持 `required` 语义：

- 任一 segment worker 失败，当前 step run 标记 `failed`
- workflow run 也按现有逻辑标记 `failed`

但为了可追踪性：

- 已成功 worker 产生的 review / rewrite / finalized version 不回滚
- 失败细节要留在 step payload 和 workflow summary 中

### 10.3 Resume / Rerun 边界

本轮不重写 stage 级 `resume / rerun` 语义。

保持不变：

- stage 失败后仍通过既有 `resume=True` 或 `rerun=True` 走新一轮 stage run
- workflow run 与 stage run 仍按当前方式记录

本轮新增的是：

- 更细的 step payload 失败信息
- 更容易定位“失败发生在哪些 segment”

### 10.4 `failed_only` 边界

当前仓库里几乎没有完整自动化逻辑把 `ChapterSegment.translation_status` 写成 `failed`。

因此本轮明确：

- 不把“补齐 `failed_only` 全链路失败标记”纳入本次并发改造
- 不额外引入新的 segment 状态机
- 只通过 workflow payload 暴露 segment 级失败列表

这样可以避免本轮 scope 从“并发提升”扩散到“失败恢复模型重做”。

## 11. 对现有代码结构的影响

本轮预期会触达的核心点：

- `app/services/workflow_runtime_service.py`
  - 为 translation step 增加“步骤内部并发调度”路径
  - 复用 glossary 已有的 worker session 模式
  - 保持外部 workflow 编排语义不变
- `app/services/translation_pipeline_service.py`
  - 增加 `fork_for_session()`
  - 拆出单 segment worker 级辅助接口
  - 将 review / rewrite 从整批 prompt 模式改成 segment 级 prompt 模式
- `tests/test_translation_workflow_actions.py`
  - 增加 translation 并发回归
  - 增加 review / rewrite / finalize 的 segment 级失败保留回归
- 可能补充：
  - `tests/test_translation_stage.py`
  - `tests/test_stage_resume_and_conflict.py`

本轮不计划改数据库迁移。

## 12. 风险与控制

### 风险 1：并发文件写入与数据库写入不一致

控制方式：

- 每个 worker 先写单 segment 自己的文件
- 同 worker 内完成对应记录落库
- worker 异常时只回滚本 worker，并清理本 worker 新建文件

### 风险 2：review / rewrite 从整批 prompt 改成单 segment prompt 后，结果风格波动

控制方式：

- 保持 prompt 结构和字段要求尽量一致
- 先以结构兼容和吞吐改进为主，不在本轮重新设计评审标准
- 用回归测试验证落库结构与选择逻辑不被打坏

### 风险 3：step payload 信息量变大，汇总逻辑不稳

控制方式：

- 统一抽一个 translation step 汇总函数
- 让所有 translation step 都走同一套成功数/失败数/failed segment 列表聚合逻辑

### 风险 4：finalize 并发导致 review/export 标脏重复执行

控制方式：

- finalize worker 只负责单 segment 定稿
- 章节范围聚合与 run 标脏仍在主线程统一处理

### 风险 5：线程数放太大导致 provider 或数据库压力过高

控制方式：

- 使用有上限的 `ThreadPoolExecutor`
- worker 数量采用“segment 数量与固定上限取最小值”的策略
- 固定上限先保持保守，后续再视真实 provider 行为调优

## 13. 测试策略

本轮至少覆盖下面五类测试。

### 13.1 generate 真并发回归

目标：

- 证明多个 segment 的 draft 生成不是串行执行

做法：

- 用带同步屏障的 fake pipeline / fake provider
- 断言第二个 segment worker 在第一个结束前已经启动

### 13.2 review 真并发回归

目标：

- 证明 `review_drafts` 已从整批 prompt 改成 segment 级并发执行

做法：

- 用可控 provider 统计 prompt 次数和并发启动时机
- 断言 review 调用次数与 segment 数匹配

### 13.3 rewrite 真并发回归

目标：

- 证明 `rewrite_consensus` 已改成 segment 级并发执行

做法：

- 与 review 类似，用同步工具验证多个 segment rewrite worker 的并发启动

### 13.4 部分失败保留回归

目标：

- 证明某些 segment 失败时，已成功 segment 的中间产物仍保留

做法：

- 构造单 segment review / rewrite / finalize 失败
- 断言 workflow run 失败
- 断言已成功 segment 的 draft/review/version 仍可 inspect

### 13.5 全量回归

目标：

- 确认并发改造不会打坏 monorepo 和 standalone 两种运行方式

做法：

- 跑 translation 相关目标集
- 跑完整 `pytest`
- 保持独立测试库前提不变

## 14. 成功标准

本轮完成后，需要同时满足：

1. `translation_multi_llm_v1` 对外仍是同一条 5-step workflow
2. generate、review、rewrite、finalize 都能在步骤内部按 segment 并发执行
3. 现有 draft/review/finalize 落库结构保持兼容
4. workflow 失败时仍可 inspect 已成功 segment 的中间产物
5. 不引入新的数据库 schema 变更
6. translation 相关目标测试与全量回归通过

## 15. 后续衔接

如果本轮落地顺利，后续可以直接接上：

- P1.3 历史版本与可追踪性增强
- P1.4 可观测性与失败恢复增强

因为本轮已经提前沉淀了两类基础设施：

- step payload 的 segment 级汇总结构
- translation worker 级独立 session / 独立 pipeline 模式
