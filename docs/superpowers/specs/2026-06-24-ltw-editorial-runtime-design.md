# LTW Editorial Runtime 设计

## 1. 背景

当前 LTW 的核心形态是本地 CLI + MySQL 状态库 + provider/profile/route 驱动的小说翻译流水线。

这套结构适合把外部模型调用组织成可观测的阶段任务，但它的主语仍然是“工具调用流程”：项目创建、拆章、术语抽取、翻译、审校、导出都围绕单一 pipeline 展开。用户希望 LTW 从这个形态转向更接近真实编辑部的运行方式：

- 不再以外部模型调用为主，而是以 Codex/子 Agent 自主翻译为主。
- 不再依赖局域网 MySQL 服务器，而是使用本地文档事实源；SQLite 只作为索引和缓存。
- 不再把流程视作单一流水线，而是组织多个角色、多个工位协同。
- 不再以 CLI 作为主入口，而是由主线程 Codex 通过 skills 和工具完成调度、推定、验收。
- 最终不向后兼容；新架构是逐步并行建立、验证、替代旧流水线，而不是在旧入口上打补丁。

本设计把新架构命名为 `LTW Editorial Runtime`。

## 2. 目标

本轮目标是定义 Editorial Runtime 的底层运行模型，为后续落地实现提供稳定边界。

核心目标：

1. 建立以“编辑部工位”为中心的协作模型。
2. 建立本地文档事实源，确保正文、术语、审校、注释、验收记录可以脱离 MySQL 独立运行。
3. 明确 SQLite 的定位：可删除、可重建、不可作为最终事实源。
4. 明确 raw / review / revised / accepted 的权限边界，防止未验收内容污染翻译记忆。
5. 明确术语编辑为常驻关键岗位，而不是阶段性外挂任务。
6. 明确结构秘书、归档导出、外部参考评测是事件触发工位，不是常驻工位。
7. 明确 Codex skill 是主入口，CLI 只保留为 legacy 能力或底层工具，不再承载主流程入口语义。
8. 明确新运行层不向后兼容，优先保证新事实源、新状态机、新协作边界干净成立。

## 3. 非目标

本设计不做下面这些事：

- 不保证旧 CLI action、旧 MySQL schema、旧 route preset 的兼容。
- 不把旧 LTW 数据自动迁移为新事实源；迁移工具可以后续单独设计。
- 不在本轮实现真实翻译能力。
- 不在本轮设计人类 UI。
- 不把飞书 Base 作为正文、术语或翻译记忆事实源。
- 不把外部模型评测恢复为主流程依赖。
- 不让子 Agent 自证合规；验收必须由上游工位或总译审完成。

## 4. 总体结论

采用“文档事实源 + SQLite 索引缓存 + Codex skill 调度 + 编辑部工位协作”的新运行层。

关键决策：

- 方案基线为 A + D：Codex/子 Agent 自主翻译为主，本地术语、风格规则、accepted 翻译记忆驱动。
- 项目事实源采用文档目录；SQLite 只保存索引、检索、运行缓存和派生视图。
- 新运行层与旧 LTW 并行存在，逐步替代旧 pipeline，最终不向后兼容。
- 常驻工位分为决策工位和生产工位。
- 注释编辑不独立设岗；注释由双语审校提出需要，责编在修订时添加，必要时交术语编辑或总译审裁决。
- 术语编辑是常驻工位，负责项目级和章节级术语一致性，不降级为一次性抽取任务。

## 5. 工位模型

### 5.1 常驻决策工位

#### 总译审

职责：

- 建立项目翻译原则、风格方向、验收标准。
- 派章和定义章节任务边界。
- 裁决审校意见采纳范围。
- 验收 accepted 正文。
- 放行导出。
- 对跨章一致性、风格漂移、术语争议做最终裁决。

限制：

- 不常态兼任主译。
- 不用自己的翻译输出自证合格。
- 不直接把 raw 或 revised 写入翻译记忆。

#### 术语编辑

职责：

- 初始化项目术语表、命名规则、称谓规则、专名策略。
- 每章主译前准备术语包。
- 每章主译后处理新增术语候选、误用、冲突和废弃项。
- 对高风险章节做强制术语复核。
- 维护 `candidate / approved / locked / rejected / deprecated` 等术语状态。

限制：

- 不承担正文翻译。
- 不绕过总译审直接验收正文。
- approved / locked 术语变更必须留证据和版本记录。

### 5.2 常驻生产工位

#### 主译

职责：

- 读取 source、项目规则、术语包、上下文和 accepted 翻译记忆。
- 产出章节 raw 译稿。
- 标记不确定项、可能需要注释项、新术语候选。

限制：

- 只写 raw。
- 不修改 accepted。
- 不修改术语表的 approved / locked 项。
- 不宣布翻译通过。

#### 双语审校

职责：

- 对照 source、raw、术语包和项目规则做 bilingual review。
- 标记误译、漏译、术语误用、语气偏差、连续性问题。
- 提出 `needs_annotation`，说明为什么需要注释。
- 区分必须修改、建议修改、需总译审裁决的问题。

限制：

- 只写 review。
- 不直接修改 raw、revised 或 accepted。
- 不把审校意见视为自动采纳。

#### 责编

职责：

- 根据总译审采纳范围和审校意见产出 revised。
- 处理必要注释。
- 执行风格统一、可读性修订和中文表达打磨。
- 保留无法处理或需要裁决的问题。

限制：

- 只写 revised 和 annotation candidate。
- 不新增剧情事实。
- 不改 source 事实源。
- 不改术语策略。
- 不宣布 accepted。

### 5.3 事件触发工位

#### 结构秘书

触发时机：

- 项目初始化。
- source 文件变更。
- 拆章、分片、简介隔离或结构异常需要重建。

职责：

- 建立 source manifest。
- 拆分章节和片段。
- 隔离简介、正文、番外、作者注等不同材料。
- 记录 source hash 和结构变更。
- 触发受影响章节 stale。

结论：

- 结构秘书不是常驻工位。拆完章后，除非 source 或结构发生变化，不参与每章翻译循环。

#### 归档导出

触发时机：

- 总译审放行导出。
- 阶段性归档。
- 需要生成交付包。

职责：

- 只读取 accepted 正文和 approved annotation。
- 生成导出文件和 export manifest。
- 记录导出范围、hash、时间和版本。

限制：

- 不读取 raw 或 revised 作为导出正文。
- 不自行补写未验收章节。

#### 外部参考评测

触发时机：

- 总译审要求参考外部模型意见。
- 某章质量争议较高。
- 阶段性质量抽检。

职责：

- 只提供参考报告。
- 可比较不同译稿、指出风险或建议改写。

限制：

- 不进入主流程依赖。
- 不拥有验收权。
- 不直接写正文事实源。

### 5.4 不设独立工位

#### 注释编辑

取消独立工位。

处理方式：

- 双语审校提出 `needs_annotation`。
- 总译审裁决是否需要注释。
- 责编在 revised 阶段添加注释。
- 世界观、专名、称谓、文化背景等核心注释，必要时交术语编辑或总译审裁决。
- 只有 approved annotation 可以进入导出。

#### 风格编辑

取消独立工位。

处理方式：

- 总译审制定风格规则。
- 责编执行风格统一。
- 阶段性连读时检查风格漂移。

#### 翻译记忆管理员

取消独立工位。

处理方式：

- 翻译记忆只从 accepted 正文派生。
- SQLite 或 jsonl 只保存派生结果。
- 总译审负责 accepted 边界，间接控制 TM 质量。

#### 外部模型评测员

取消独立工位。

处理方式：

- 外部模型只是工具或事件触发任务。
- 它不参与常驻工位，也不成为主流程的默认依赖。

## 6. 项目事实源结构

建议目录结构：

```text
projects/<project_key>/
  manifest.yaml
  editorial-ledger.yaml
  source/
    manifest.yaml
    synopsis.md
    chapters/
      ch001.md
    segments/
      ch001-s001.md
  rules/
    style-guide.md
    glossary.yaml
    glossary-candidates.yaml
  memory/
    tm.accepted.jsonl
  chapters/
    ch001/
      task.md
      term-pack.md
      raw/
        main-translator.md
      review/
        bilingual-review.md
      revised/
        line-editor.md
      accepted/
        accepted.md
      annotations.md
      record.yaml
  exports/
    export.md
    manifest.json
  .ltw-cache/
    index.sqlite
```

事实源规则：

- `source/` 是原文事实源。
- `rules/` 是术语和风格事实源。
- `chapters/*/raw/` 是主译输出，不得作为下游事实源。
- `chapters/*/review/` 是审校诊断，不直接改变正文。
- `chapters/*/revised/` 是责编修订稿，不等于 accepted。
- `chapters/*/accepted/` 是总译审验收后的正文事实源。
- `memory/tm.accepted.jsonl` 只能由 accepted 派生。
- `.ltw-cache/index.sqlite` 可删除、可重建；与文档冲突时，文档获胜。

## 7. 状态机

### 7.1 章节状态

建议章节状态：

- `planned`：已建任务，未开始。
- `term_ready`：本章术语包已准备。
- `raw_ready`：主译 raw 已产出。
- `review_ready`：双语审校已完成。
- `revision_ready`：责编 revised 已完成。
- `accepted`：总译审已验收。
- `stale`：source、术语或规则变化导致需要复核。
- `blocked`：存在未裁决问题。
- `cancelled`：章节任务取消。

关键约束：

- `accepted` 只能由总译审写入。
- `active` 或 `latest` 不等于 `accepted`。
- `stale` 章节不能直接导出。
- `blocked` 章节不能进入 accepted，除非总译审明确记录豁免原因。

### 7.2 术语状态

建议术语状态：

- `candidate`：候选项。
- `approved`：已批准，可用于生产。
- `locked`：关键术语，变更需要术语编辑或总译审授权。
- `rejected`：不采用。
- `deprecated`：历史采用过，但后续弃用。

关键约束：

- 主译可以提出 candidate。
- 双语审校可以指出误用和新增候选。
- 责编不能自行批准或锁定术语。
- 核心术语未决时，相关章节不得进入 accepted，除非总译审记录风险接受。

### 7.3 注释状态

建议注释状态：

- `candidate`：由责编根据审校意见添加。
- `approved`：总译审批准，可导出。
- `rejected`：不采用。
- `locked`：关键注释，变更需要总译审授权。

关键约束：

- 注释没有独立工位。
- 导出只读取 approved annotation。
- 注释不得替代正文修正；误译必须改正文。

### 7.4 运行状态

建议运行状态：

- `queued`
- `running`
- `completed`
- `failed`
- `cancelled`

运行记录必须保存：

- 工位名称。
- 输入文件列表。
- 输入 hash。
- 输出文件列表。
- 输出 hash。
- 使用的术语表版本。
- 使用的风格规则版本。
- 使用的 accepted/TM 快照。
- thread_id 或 run_id。
- 人工裁决记录。

## 8. 标准流程

### 8.1 初始化流程

```text
结构秘书建立 source manifest
-> 结构秘书拆章、分片、简介隔离
-> 总译审确认项目原则和风格
-> 术语编辑建立初始术语表
-> 建立 editorial-ledger
```

### 8.2 单章生产流程

```text
总译审派章
-> 术语编辑准备本章术语包
-> 主译产出 raw
-> 双语审校写 review
-> 总译审裁决采纳范围，必要时交术语编辑裁决
-> 责编产出 revised，并处理必要注释
-> 总译审验收 accepted
-> accepted 派生 TM 和后续上下文
```

### 8.3 阶段性流程

每 3 到 5 章触发一次阶段性检查：

- 连读检查。
- 术语漂移检查。
- 风格一致性检查。
- 人物称谓和关系检查。
- 伏笔、设定和时间线一致性检查。

阶段性检查只产生报告和待办，不直接修改 accepted。

### 8.4 导出流程

```text
总译审选择导出范围
-> 检查所有章节 accepted 状态
-> 检查 annotation approved 状态
-> 归档导出工位生成文件
-> 写入 export manifest
```

导出限制：

- 未 accepted 章节不得导出为正式正文。
- stale 章节不得导出。
- candidate annotation 不得导出。

## 9. 变更触发规则

source 变更：

- 结构秘书重建 source manifest。
- 受影响章节标记 stale。
- 相关 accepted 和 TM 派生视图标记需要复核。

术语变更：

- 新增 approved 术语后，影响章节进入 risk 状态或生成复核任务。
- locked 术语变更必须记录裁决人和原因。
- 已 accepted 章节不自动改写，但必须进入阶段性一致性检查。

风格规则变更：

- 新规则版本写入 `rules/style-guide.md`。
- 后续章节使用新版本。
- 已 accepted 章节是否重修由总译审裁决。

审校意见变更：

- review 变更不自动改 revised。
- 总译审重新裁决后，责编再产出新 revised。

## 10. SQLite 定位

SQLite 只作为本地索引和缓存。

允许保存：

- 文件索引。
- hash 索引。
- 章节状态派生视图。
- 术语检索索引。
- TM 检索索引。
- run 查询缓存。

不允许保存为唯一事实源：

- accepted 正文。
- approved 术语。
- approved annotation。
- 总译审裁决。
- 导出 manifest。

验收要求：

- 删除 `.ltw-cache/index.sqlite` 后，可以从文档事实源完整重建。
- SQLite 与文档冲突时，必须以文档为准。
- 任何写 SQLite 的动作都不能绕过文档写入。

## 11. Skill 与入口

Editorial Runtime 的主入口是 Codex skill，而不是 CLI。

建议 skill 暴露的动作语义：

- `project.init_editorial`
- `source.prepare`
- `chapter.assign`
- `terms.prepare_pack`
- `chapter.translate_raw`
- `chapter.review_bilingual`
- `review.adjudicate`
- `chapter.revise`
- `chapter.accept`
- `memory.derive_from_accepted`
- `export.build`
- `cache.rebuild`
- `inspect.status`

主线程 Codex 的职责：

- 选择下一步。
- 派发或续接子 Agent。
- 检查工位输出是否越权。
- 回填正式文档、飞书 Base 状态和 Todoist 动作。
- 最终验收设计、流程和交付物。

子 Agent 的职责：

- 只完成被派发工位任务。
- 在输出中记录读取的文件和 hash。
- 不跨工位写文件。
- 不自证合规。

CLI 的新定位：

- 可保留为 legacy 调试工具。
- 可承载底层文件校验、cache 重建、导出打包等机械动作。
- 不再是主流程入口。

## 12. 与旧 LTW 的关系

Editorial Runtime 不是旧 LTW 的兼容升级。

迁移原则：

- 旧 LTW 保留为 legacy 能力和历史参考。
- 新运行层优先建立干净的目录事实源、状态机、工位记录和 skill 调度协议。
- 旧 MySQL 数据不直接成为新事实源。
- 后续如果需要迁移，只设计单向 import 或参考工具，不维护双写兼容。
- 新项目默认使用 Editorial Runtime。
- 旧 CLI action 是否保留，由后续清理阶段决定；不作为新架构约束。

这意味着后续实现可以删除或重写旧入口、旧 action、旧 schema、旧 provider 依赖，不需要为了旧流程保持行为兼容。

## 13. 验收策略

第一阶段验收：

1. 可以创建 Editorial Runtime 项目目录模板。
2. 可以生成 source manifest 和章节任务。
3. 可以写入并校验五个常驻工位记录。
4. 可以完成一个单章 dry-run：term pack -> raw -> review -> adjudication -> revised -> accepted。
5. 可以从 accepted 派生 TM。
6. 可以删除 SQLite 并从文档重建索引。
7. 导出只能读取 accepted 和 approved annotation。
8. raw、review、revised 不会进入 TM。
9. 每个工位输出都有输入 hash、输出 hash 和 run 记录。
10. 子 Agent 输出越权时可以被检查出来。

第二阶段验收：

1. 多章连续生产时，术语编辑能持续处理新增候选和冲突。
2. 每 3 到 5 章能产生阶段性一致性报告。
3. source 或术语变更能正确触发 stale / risk。
4. 总译审可以裁决重修、豁免或继续。
5. 飞书 Base 只回填支线状态、证据和下一步，不承载正文事实源。

## 14. 落地顺序

建议按以下顺序推进：

```text
设计文档
-> 项目目录模板
-> 工位记录模板
-> 状态机和文件事实源校验
-> Codex skill 调度协议
-> 单章 dry-run 样例
-> SQLite cache rebuild
-> 导出只读 accepted 验证
-> 旧 LTW 能力拆分或迁移工具
```

原因：

- 先固定事实源和权限边界，避免把旧流水线形态带进新架构。
- 先验证单章闭环，再扩展多章和阶段性检查。
- 先让 SQLite 可重建，再引入更复杂的检索和 TM 能力。
- 先让 skill 调度成立，再决定 CLI 保留范围。

## 15. 仍需讨论的问题

后续实现计划前建议继续确认：

1. accepted 的严格度：是否允许带风险接受，还是必须零阻塞。
2. TM 粒度：按句段、段落，还是双层索引。
3. 阶段性检查频率：固定 3 章、5 章，还是按作品复杂度配置。
4. 外部参考评测的调用边界：何时允许、如何记录成本和证据。
5. 飞书 Base 字段：需要记录到什么颗粒度，避免把正文管理搬回 Base。
6. 旧 LTW 清理节奏：是先冻结 legacy，还是先实现 import 工具。

## 16. 完成标准

本设计被接受后，下一步进入 implementation plan。

implementation plan 必须满足：

- 不以兼容旧 CLI/MySQL 流程为目标。
- 第一批改动只落目录模板、记录模板、状态校验和 skill 调度协议。
- 不先接外部模型。
- 不先做 UI。
- 不让 raw/revised 污染 accepted 或 TM。
- 不把 SQLite 当事实源。
- 每个新增能力都能用单章 dry-run 验证。
