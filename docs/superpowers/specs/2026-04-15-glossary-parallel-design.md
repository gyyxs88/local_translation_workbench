# Glossary Multi-LLM 真并发设计

## 1. 背景

当前 `glossary_multi_llm_v1` 虽然已经具备“双 extractor + 后续裁决”的 workflow 结构，但 `extract_primary` 和 `extract_secondary` 仍然是顺序执行。

这带来两个直接问题：

- 总耗时基本等于两个 extractor 串行耗时之和，multi workflow 的收益被明显削弱。
- 当前 workflow runtime 虽然已经有 tolerant group、`failure_mode`、`minimum_success`、degraded summary 等机制，但还没有真正承载并发执行。

本轮只解决 glossary multi workflow 的“真并发 extractor”问题，不扩到 translation。

## 2. 目标

本轮目标只有四个：

1. 让 `glossary_multi_llm_v1` 里的两个 extractor 真正并发执行
2. 保持现有 `failure_mode / minimum_success / degraded` 语义不变
3. 保持现有 draft candidate、candidate review、finalize 落库结构不变
4. 为下一轮 `translation_multi_llm_v1` 并发化沉淀一套可复用的 runtime 模式

## 3. 非目标

本轮明确不做下面这些事情：

- 不改 `translation_multi_llm_v1`
- 不改 glossary finalize、review_relations、review_scope 的业务裁决逻辑
- 不引入进程级 worker、消息队列、外部任务系统
- 不修改 provider fallback 的业务语义
- 不把所有 tolerant step group 都一口气改成并发

## 4. 方案选择

本轮采用的方案是：

**进程内并发 + 每个并发 step 使用独立数据库 session 与独立 pipeline 实例**

放弃的两个方向：

- 共享同一个 SQLAlchemy session 跨线程执行：风险太高，SQLAlchemy session 本身不是线程安全对象
- 直接上进程级 worker：对当前代码体量来说过重，调试和回归成本都不划算

选择这个方案的原因：

- 当前 provider 调用本质上是网络 I/O，适合在同一进程内并发
- 当前 `WorkflowRuntimeService` 已经有 `sessionmaker` 基础，扩成“并发 worker 各拿一套 session”比较顺
- 可以在不推翻现有 workflow runtime 的前提下，把并发边界控制在 extractor group 内

## 5. 并发边界

本轮的并发边界严格限定为：

- `glossary_multi_llm_v1`
- `glossary.extract`
- 同一 tolerant group 内的两个 extractor step

也就是说：

- `extract_primary`
- `extract_secondary`

将改为并发执行。

下面这些步骤保持串行：

- `normalize_candidates`
- `review_relations`
- `review_scope`
- `finalize_terms`

这样做的原因是：

- 两个 extractor 彼此独立，只依赖相同的 project/scope 输入，最适合并发
- normalize 之后的步骤都依赖 extractor 已经把 draft candidate 写完，天然需要在 extractor group 完成后再继续

## 6. 运行时模型

### 6.1 当前问题

现有 `_execute_glossary_step_group` 本质上还是：

- 依次执行每个 step
- 每个 step 共用当前 runtime 的 session
- 共用当前传入的 pipeline 实例

这在串行时没问题，但一旦并发就会撞上两个风险：

- 同一个 session 不能安全地跨线程复用
- 同一个 pipeline/GlossaryService 内部如果持有 session，也不能安全地跨线程复用

### 6.2 新模型

并发 extractor group 的执行模型改成：

1. 主线程先创建 workflow run
2. 主线程识别到当前 step group 属于 glossary tolerant extractor group
3. 为 group 中的每个 step 分别提交一个并发 worker
4. 每个 worker 自己创建：
   - 独立 SQLAlchemy session
   - 独立 `GlossaryPipelineService`
   - 独立 `GlossaryService`
   - 独立 `WorkflowRepository` 访问上下文
5. 每个 worker 自己完成：
   - step run 创建
   - glossary.extract 执行
   - step run 状态更新
   - 本 worker session commit / rollback
6. 主线程等待所有 worker 结束，收集 step log，再按现有 quorum/degraded 规则判断是否继续

## 7. Session 与 Provider 策略

### 7.1 Session 策略

每个并发 extractor worker 必须使用独立 session。

要求：

- worker 内部禁止复用主 runtime 的 `self.session`
- worker 内部禁止把主线程创建的 pipeline 实例直接拿过去用
- worker 成功时自行 commit
- worker 失败时自行 rollback
- 主线程只汇总结果，不直接参与 worker 的数据库写入

### 7.2 Provider 策略

当前 provider 对象是轻量 HTTP 调用封装，没有共享数据库状态。
本轮优先采用：

- provider 对象允许在线程间复用
- 但 pipeline / service / repository 不允许跨线程复用

如果实现时发现某条 provider 路线带有线程安全问题，再把 provider 构造也下沉到 worker 内部。

本轮不预设必须为 provider 新增复杂工厂层。

## 8. 结果汇总与降级语义

本轮必须保持现有 tolerant group 语义不变。

### 8.1 全成功

如果两个 extractor 都成功：

- group `success_count = 2`
- workflow 不 degraded
- 后续 normalize / review / finalize 正常继续

### 8.2 部分成功

如果一个成功、一个失败，且 `minimum_success = 1`：

- group 仍然允许继续
- workflow summary 继续标记为 degraded
- `failed_step_keys` 保留失败 extractor
- 后续步骤继续消费已经写入的 draft candidate

### 8.3 全失败

如果两个 extractor 都失败，或成功数低于 `minimum_success`：

- 仍然返回现有 `workflow_quorum_failed`
- 失败上下文里保留全部 step log
- workflow run 标记为 failed

## 9. 落库约束

为了避免并发 extractor 相互覆盖，本轮坚持下面几个约束：

- draft candidate 仍然各写各的，不做“写前去重”
- normalize 阶段继续承担后续收口职责
- 每个 step run 仍然保留独立 `workflow_step_run_id`
- `evidence_payload` 里保留原本的 `workflow_step_run_id / chapter_id / chapter_index / chapter_title`

这样可以保证：

- 后续 inspect 仍能清楚区分两路 extractor 的产物
- 失败时能追溯到具体是哪一路 extractor 出的问题

## 10. 对现有代码结构的影响

本轮预期会触达的核心点：

- `app/services/workflow_runtime_service.py`
  - 增加 glossary extractor 并发执行分支
  - 增加 worker 级 session / pipeline 构造
  - 保持现有串行路径和 translation 路径不变
- `app/services/glossary_pipeline_service.py`
  - 原则上不改业务语义
  - 如有必要，仅补最小的并发友好辅助接口
- `tests/test_workflow_actions.py`
  - 增加真正验证并发行为的回归测试
  - 增加并发场景下部分失败仍降级继续的回归测试

本轮不计划改数据库 schema。

## 11. 风险与控制

### 风险 1：并发写库导致 session/事务混乱

控制方式：

- 每个 worker 独立 session
- worker 内部独立 commit / rollback
- 主线程不共享 session 给 worker

### 风险 2：并发行为改了，但 summary/degraded 语义跑偏

控制方式：

- 保持现有 `success_count / failed_step_keys / degraded / terminal_status` 汇总逻辑
- 用现有串行行为作为回归基线

### 风险 3：测试只证明“能跑”，没证明“真并发”

控制方式：

- 增加专门的并发测试，不只看 step 数量和最终结果
- 用可控阻塞 provider 或事件同步方式验证两个 extractor 确实同时起跑

### 风险 4：translation 路径被误伤

控制方式：

- 本轮只改 glossary extractor group 的并发路径
- translation group 维持当前实现不动
- 保留全量回归覆盖

## 12. 测试策略

本轮至少要覆盖下面三类测试。

### 12.1 真并发回归

目标：

- 证明 `extract_primary` 和 `extract_secondary` 不是串行跑完再跑下一个

做法：

- 用可控 provider / pipeline 记录两个 extractor 的启动时机
- 断言第二个 extractor 在第一个 extractor 结束前已经进入执行

### 12.2 部分失败降级回归

目标：

- 一个 extractor 失败、另一个成功时，workflow 仍然进入 degraded 但可继续的状态

做法：

- 保留现有 `workflow_quorum_failed` 语义边界
- 断言 workflow summary 中 `degraded = true`
- 断言 finalize 仍可完成

### 12.3 全量回归

目标：

- 确认 monorepo 模式与独立仓库模式都不被并发改造打坏

做法：

- 继续跑完整 `pytest`
- 保持现有双运行上下文验证方式

## 13. 成功标准

本轮完成后，需要同时满足：

1. `glossary_multi_llm_v1` 的两个 extractor 真并发执行
2. 现有 `failure_mode / minimum_success / degraded` 语义保持不变
3. draft candidate、review、finalize 的 inspect 结果结构保持兼容
4. 不引入新的数据库 schema 变更
5. monorepo 与独立仓库两种上下文全量回归通过

## 14. 后续衔接

如果这一轮落地顺利，下一轮 `translation_multi_llm_v1` 并发化会直接复用下面这些成果：

- tolerant step group 的并发执行骨架
- worker 级独立 session 模式
- 并发 step log 收集与降级汇总逻辑
- 真并发回归测试范式
