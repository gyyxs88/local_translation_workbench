# local_translation_workbench 路线图

## 1. 当前基线

- 当前版本基线为 `v0.1.0`。
- 主线闭环已经完成：`project.create -> chaptering -> glossary -> translation -> review -> export`。
- 当前仓库已具备 Alembic 迁移、数据库持久化、provider/profile/workflow 配置、阶段编排、inspect 查询与全量测试。
- 当前已验证的完整回归基线为：`237 passed`。
- 当前测试环境采用独立测试库，允许使用局域网 MySQL，不要求必须在本机安装 MySQL。
- 当前阶段判断：里程碑 A 对应的交付稳态已经基本达成，后续工作以 P1 强化项为主。

## 2. 路线图目标

后续工作不再以“补主流程”为主，而是围绕下面三件事推进：

- 把当前可用版本收口成更稳定的交付形态。
- 把多模型、多阶段、失败恢复等能力做强。
- 把工具从“开发者可用”继续推进到“长期维护和团队协作更顺手”。

## 3. P0：交付稳态

P0 的目标是先把“能跑”收口成“可持续使用、可重复接入、可低风险交付”。

当前状态：

- P0 范围内的接入文档、最小试跑手册、provider smoke 手册、排障手册都已落地。
- 独立仓库与 NovelT 单体仓库两种运行入口已经在 README 与 CLI smoke 回归里收口。
- P0 后续主要是按发布节奏持续校正文档和回归基线，不再是补主流程能力。

### 3.1 接入与运维文档补齐

范围：

- 补一份面向使用者的接入文档，覆盖局域网 MySQL、测试库、provider/profile/workflow 的初始化流程。
- 补一份最小可运行手册，明确项目创建、阶段执行、inspect 查询、导出检查的推荐顺序。
- 补一份常见故障排查手册，覆盖测试库误配、provider key 缺失、fallback 链失败、导出失败等问题。

完成标准：

- 新接手的人不翻源码，只看文档就能完成环境接入与一次完整试跑。
- 文档中明确区分业务库与测试库，避免误跑到业务库。

### 3.2 真实 provider 联调 smoke 流程

范围：

- 设计一套不进 CI 的手工 smoke 流程，用于验证真实 provider 能否正常完成 glossary、translation、synopsis 相关调用。
- 固化 smoke 输入样例、执行命令、预期输出和失败判断标准。
- 明确什么时候需要跑 smoke，例如新 provider、新 profile、新 fallback 链、重要发布前。

完成标准：

- 在不改代码的情况下，可以按文档重复完成一次真实 provider 冒烟验证。
- 失败时能快速判断是环境问题、provider 问题还是业务逻辑问题。

### 3.3 运行入口与仓库形态统一

范围：

- 收口“独立仓库运行”和“NovelT 单体仓库运行”之间的导入路径差异。
- 让测试、CLI、迁移脚本在两种仓库形态下都有一致且明确的入口。
- 减少依赖 `tools.local_translation_workbench` 这类固定包路径带来的运行歧义。

完成标准：

- README 里的运行入口与真实代码行为完全一致。
- 不再出现“文档写法能跑、实际导入失败”的情况。

## 4. P1：能力增强

P1 的目标是把当前工作台从“可用”推进到“更强、更快、更适合真实生产场景”。

### 4.1 多 LLM workflow 真并发

范围：

- 已完成：`glossary_multi_llm_v1` 已从顺序双 extractor 升级为真实并发执行。
- 已完成：`translation_multi_llm_v1` 已从顺序多轮链路升级为步骤内部按 segment 的可控并发执行。
- 保留现有 draft candidate、draft review、review evidence 的结构化存储。

完成标准：

- 多 LLM workflow 在不破坏现有结果结构的前提下缩短总耗时。
- 并发失败、部分成功、fallback 命中时的结果仍然可解释、可 inspect。

### 4.2 术语模型扩展

范围：

- 已完成第一刀：`gender` 已结构化建模，并贯通到 glossary draft/candidate/entry、`inspect.glossary`、`glossary.inspect_pipeline` 与 translation glossary prompt/snapshot。
- 已完成第二刀：`age_group` 已结构化建模，并贯通到 glossary draft/candidate/entry、`inspect.glossary`、`glossary.inspect_pipeline` 与 translation glossary prompt/snapshot。
- 继续评估是否需要补充更细的角色属性字段，以及这些字段是否真的值得进入 glossary 主链路。
- 梳理正式名、简称、称号、关系角色之外是否还需要更细的关系表达。
- 校准 glossary finalize 与 translation 注入逻辑，避免新增字段后出现裁决歧义。

完成标准：

- 新增字段有明确来源、明确语义、明确落库位置。
- glossary 与 translation 的联动行为在测试中可稳定验证。

### 4.3 历史版本与可追踪性增强

范围：

- 已完成第一刀：`inspect.translation` 已支持 current active version 的 provenance，可直接查看 finalize step、selected draft 与 selected draft reviews。
- 已完成第二刀：`inspect.translation` 已支持“当前 active version vs 指定历史正式版本”的单段 compare，可直接查看文本和关键元数据变化摘要。
- 为 translation/review/export 增加更完整的历史查看能力，而不是只看 current active version。
- 增加版本切换、对比、问题来源追踪所需的 inspect 能力。
- 强化 workflow step payload、版本元数据和阶段运行记录之间的关联。

完成标准：

- 能清楚回答“当前结果从哪里来、经历了哪些步骤、为什么变成现在这样”。
- 人工复核和问题排查时，不需要直接查库才能看懂历史演变。

### 4.4 可观测性与失败恢复增强

范围：

- 已完成第一刀：`stage.inspect_runs` 已支持结构化 `summary` 和 failed run `diagnostics`，可直接查看 `error / failure_step / model_profile_id / model_name`。
- 继续补阶段耗时、fallback 命中、resume/rerun 诊断等更完整的运行观测信息。
- 提升 inspect 和运行记录的信息密度，方便快速定位异常。

完成标准：

- 遇到失败时，可以快速知道失败发生在哪个阶段、哪一轮、哪一个 profile。
- 运行记录足以支撑基本的线上排障和人工审查。

## 5. P2：产品化与体验优化

P2 的目标是降低使用门槛，让工具更像一个团队可长期维护的产品，而不只是开发中的内部工具。

### 5.1 标准 demo 与样例工程

范围：

- 提供最小输入样例、推荐 workflow、推荐 profile 组合。
- 提供一次标准试跑的预期产物，便于新环境验收。

完成标准：

- 新环境接入后，可以用标准样例快速验证工具是否工作正常。

### 5.2 输出与报告体验优化

范围：

- 优化 `stage.run`、`inspect.*`、`export` 的摘要信息和展示结构。
- 提升对常见人工操作场景的友好度，例如快速看章节状态、快速看失败段落、快速确认导出结果。

完成标准：

- 常用信息可以通过工具输出直接获取，而不是依赖人工拼接多个 inspect 结果。

### 5.3 批量项目与模板能力

范围：

- 评估是否需要支持批量项目操作、导出模板、标准报告格式。
- 仅在真实使用场景明确提出需求后再推进，避免过早膨胀。

完成标准：

- 新增能力能明显降低重复劳动，而不是增加维护负担。

## 6. 建议推进顺序

推荐顺序如下：

1. `P1.3` 历史版本与可追踪性增强
2. `P1.4` 可观测性与失败恢复增强
3. `P1.2` 术语模型扩展
4. 按发布节奏回补 P0 文档与回归基线
5. `P2` 体验与产品化优化

## 7. 暂不建议提前做的事情

下面这些方向暂时不建议提前做：

- 为了“看起来完整”而先做复杂 UI。
- 在没有真实使用压力前过早扩展批量能力。
- 在主流程已经稳定前大规模重构现有模块边界。
- 在缺少真实联调样本前过度优化 provider 抽象。

## 8. 阶段性里程碑建议

### 里程碑 A：稳定交付

要求：

- P0 全部完成
- 接入文档可用
- smoke 流程可重复执行
- 运行入口与实际行为一致

当前状态：

- 已基本完成，可视为当前版本已经到达。

### 里程碑 B：生产强化

要求：

- P1.3、P1.4 完成，并在现有并发基础上把历史追踪与失败恢复补强
- 多模型能力、历史追踪、失败恢复具备生产级可解释性

### 里程碑 C：产品化打磨

要求：

- P2 中确认有真实价值的部分完成
- 工具对新使用者更友好，维护成本可控

