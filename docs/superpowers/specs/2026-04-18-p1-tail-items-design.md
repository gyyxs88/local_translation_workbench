# P1.2 / P1.3 尾项收口设计

## 1. 背景

当前主线已经完成下面这些能力：

- `P1.2` 已落地 `gender / age_group / term_group_key / relation_role`
- `P1.3` 已落地 `translation provenance / compare / timeline`
- `inspect.review` / `inspect.export` 也已经具备基础 run 查询

但剩下两个明显尾项还没真正闭环：

- `P1.2` 里，术语关系虽然已经入库，但 `inspect.glossary` 和 `glossary.inspect_pipeline` 仍然更像“平铺列表”，很难直接看出一组术语的关系、角色分布和一致性问题；同时 translation prompt 仍然是平铺术语行，同组命中多条时可读性一般。
- `P1.3` 里，`inspect.translation` 还是默认围绕 current active version 组织；review/export 虽然已经有 run 记录，但还不能直接回答“这次 review/export 是基于哪些译文版本做的”。

这意味着：

- `P1.2` 的结构化关系模型已经存在，但观察面和注入面还没收口
- `P1.3` 的版本追踪已经打了底，但历史浏览和 review/export 链接还缺最后一层

本轮目标就是把这两块补完，并且明确做法是：

**不再继续扩 schema，而是在现有模型上补观察面、读模型和 summary 快照。**

## 2. 本轮目标

本轮目标只有五个：

1. 让 `inspect.glossary` 能直接返回关系组视图，而不只是平铺 entry/candidate
2. 让 `glossary.inspect_pipeline` 补上 finalized 视角，能看到最终术语分组而不是只看 draft/review 碎片
3. 校准 translation glossary 注入，使同组多术语命中时的 prompt 输出稳定、可读、无歧义
4. 让 `inspect.translation` 在单段模式下支持查看任意历史正式版本，并基于“当前选中版本”做 compare
5. 让 `inspect.review` / `inspect.export` 直接带出“本次 run 基于哪些译文版本”的结构化来源快照

## 3. 非目标

本轮明确不做下面这些事情：

- 不新增 glossary 相关数据库字段
- 不新增独立 provenance 表
- 不把 `inspect.translation` 扩成全项目级 full history 浏览器
- 不给 `inspect.chapter` / `inspect.chapters` / `inspect.segment` 补历史版本切换
- 不补 review/export 的全文级时间线
- 不做旧数据回填脚本
- 不改 action 名，也不新增新的 inspect action

## 4. 方案选择

本轮评估三种方向：

### 4.1 方案 A：继续补字段，把关系和历史都落到更细 schema

做法：

- glossary 再增角色字段
- review/export 再补来源关联表
- `inspect.translation` 再补更完整版本维度结构

优点：

- 长远看最“规范”

缺点：

- 这一刀会把 `P1.2 / P1.3` 尾项同时卷进 schema 扩张
- 当前缺的其实不是“没有字段”，而是“已有信息没有组织出来”

### 4.2 方案 B：保持 schema 不动，补读模型、汇总视图和 summary 快照

做法：

- glossary 用读模型聚合 `relation_groups`
- translation prompt 改成组感知输出
- review/export 在 run summary 里落轻量版本来源快照
- `inspect.translation` 增加历史版本选择能力

优点：

- 改动集中
- 直接补当前缺口
- 风险可控，能一次性收掉 `P1.2 / P1.3` 的剩余缺口

缺点：

- 需要在 service 层多做一层显式组装

### 4.3 方案 C：先做一个统一 history/query 子系统，再把 glossary/review/export 全部挂进去

做法：

- 抽象统一的 inspection/history domain
- 所有 inspect 都统一经由新子系统查询

优点：

- 架构最完整

缺点：

- 对当前尾项来说过重
- 范围会立刻膨胀

### 4.4 结论

本轮采用：

**方案 B：不动 schema，补读模型、历史视图和 summary 快照。**

原因很直接：

- 当前尾项本质上是“最后一层观察面没有补齐”
- 不是底层存储模型不够
- 这一刀应该收尾，不应该再开新战线

## 5. P1.2 设计

### 5.1 明确结论：本轮不新增 glossary 字段

路线图里原本留着“继续评估更细角色字段”的口子，但到当前实现阶段，这个口子应该收掉。

原因如下：

- 现有 `term_group_key + relation_role + gender + age_group` 已经足够表达当前真正使用到的关系信息
- 当前缺的是“怎么展示”“怎么注入”，不是“再加几个字段”
- 再扩 schema 只会把 `P1.2` 从收尾变成新一轮建模工程

因此本轮明确把 `P1.2` 的剩余工作收口为：

- 关系组读模型
- finalized 视角补齐
- translation 注入校准

### 5.2 `inspect.glossary` 新增 `relation_groups`

`GlossaryService.inspect()` 现有输出保留：

- `entries`
- `candidates`

在此基础上新增：

- `relation_groups`

`relation_groups` 只聚合“真正有关系意义”的组，规则如下：

- `term_group_key` 相同
- 且满足以下任一条件：
  - 组内成员数大于 1
  - 存在成员 `relation_role != "independent"`

单个完全独立的普通术语不进入 `relation_groups`，避免输出噪音。

返回结构示意：

```json
{
  "term_group_key": "char_linxi",
  "member_count": 2,
  "category_distribution": {
    "character": 2
  },
  "role_distribution": {
    "canonical": 1,
    "alias": 1
  },
  "consistency": {
    "category_consistent": true,
    "gender_consistent": true,
    "age_group_consistent": true,
    "warnings": []
  },
  "members": [
    {
      "entry_id": 11,
      "source_term": "林溪",
      "target_term": "Lin Xi",
      "category": "character",
      "gender": "female",
      "age_group": "teen",
      "relation_role": "canonical",
      "status": "active",
      "locked": 0
    },
    {
      "entry_id": 12,
      "source_term": "小溪",
      "target_term": "Little Xi",
      "category": "character",
      "gender": "female",
      "age_group": "teen",
      "relation_role": "alias",
      "status": "active",
      "locked": 0
    }
  ]
}
```

一致性规则明确如下：

- `category_consistent`
  - 组内去重后只有一个 `category` 时为 `true`
- `gender_consistent`
  - 只对 `category=character` 的成员做判断
  - 非空 `gender` 去重后不超过一个时为 `true`
- `age_group_consistent`
  - 只对 `category=character` 的成员做判断
  - 非空 `age_group` 去重后不超过一个时为 `true`

`warnings` 本轮只收下面几类稳定规则：

- `missing_canonical`
- `multiple_canonical`
- `mixed_category`
- `gender_conflict`
- `age_group_conflict`

这里不做“模糊建议”，只做可稳定判断的结构化告警。

### 5.3 `glossary.inspect_pipeline` 补 finalized 视角

当前 `GlossaryPipelineService.inspect_pipeline()` 只返回：

- `draft_candidates`
- `reviews`

这会导致 finalize 后仍然只能从 draft/review 侧推测最终结果。  
本轮补两个字段：

- `finalized_terms`
- `finalized_relation_groups`

规则如下：

- 如果 workflow 还没走到 finalize，则两个字段都返回空数组 `[]`
- 如果 finalize 已完成，则使用与 finalize 落库一致的 hydrated terms 作为数据源

`finalized_terms` 的字段口径与 finalize 落库前的最终术语对象一致，至少包括：

- `draft_candidate_id`
- `chapter_id`
- `source_term`
- `target_term`
- `category`
- `note`
- `gender`
- `age_group`
- `term_group_key`
- `relation_role`
- `scope_level`
- `scope_chapter_id`

`finalized_relation_groups` 与 `inspect.glossary.relation_groups` 共用同一套分组逻辑，只是成员来源换成 finalized terms。

这样做的目的很简单：

- `inspect.glossary` 回答“当前正式 glossary 长什么样”
- `glossary.inspect_pipeline` 回答“这次 workflow finalize 最终裁成了什么样”

两者各自清楚，不再混用。

### 5.4 translation glossary 注入改成组感知输出

当前 `TranslationAssetsService.build_prompt_glossary_entries()` 的核心问题不是“匹配错了”，而是“输出还是平铺的”。  
当同一段里同时命中同组多个表面形式时，虽然每行已经带 `role/group`，但 prompt 的组织方式仍然不够直观。

本轮做三件事：

1. 保持“只注入正文实际命中的 source_term”这条规则不变
2. 对命中的 glossary entries 按 `term_group_key` 分组
3. 按稳定顺序输出 group block，而不是简单平铺

分组与排序规则如下：

- 组排序：按该组最早命中的 source span 位置升序
- 组内排序：
  - 先按命中位置升序
  - 再按 `relation_role` 优先级：
    - `canonical`
    - `alias`
    - `title`
    - `variant`
    - `independent`
  - 最后按 `source_term` 字典序

prompt 文字说明同步加强：

- 明确“同组命中的多条表面形式必须分别按各自 source_term 对应 target_term 翻译，不能互换”
- 明确“不要把当前命中的 alias/title 改写成同组 canonical，反之亦然”

渲染格式采用组块输出，示意如下：

```text
术语表：
[group char_linxi]
- 林溪 => Lin Xi | role: canonical | category: character | gender: female | age_group: teen
- 小溪 => Little Xi | role: alias | category: character | gender: female | age_group: teen

[group title_lord_qin]
- 秦大人 => Lord Qin | role: title | category: character
```

注意：

- 本轮不把 canonical 未命中时强行补进 prompt
- 本轮不做“同组自动补全”
- 只做实际命中项的分组排序和解释增强

这样能最大限度避免 prompt 变重，同时把“同组但不可互换”这件事说清楚。

### 5.5 推荐实现边界

为避免 `GlossaryService` 和 `GlossaryPipelineService` 继续长大，本轮新增一个共享读模型服务：

- `GlossaryRelationGroupService`

职责只有两个：

1. 从 glossary entries 构建 `relation_groups`
2. 从 finalized terms 构建 `finalized_relation_groups`

它不负责数据库写入，不负责 provider 调用，只负责把平铺术语对象聚合成关系组视图。

## 6. P1.3 设计

### 6.1 `inspect.translation` 新增 `version_id`

当前 `TranslationInspectionService.inspect()` 已支持：

- 项目级列表
- 单段查看
- `compare_version_id`

本轮新增一个可选参数：

- `version_id`

参数约束如下：

- `version_id` 只能在单段模式下使用
- 使用 `version_id` 时，必须同时提供单段定位：
  - `segment_id`
  - 或 `chapter_index + segment_index`
- `version_id` 必须属于当前定位到的那个 segment translation
- 项目级模式下传 `version_id` 直接报 `invalid_arguments`

### 6.2 单段 inspect 的“当前查看版本”语义改为显式

本轮后，单段 `inspect.translation` 的版本语义如下：

- 未传 `version_id`：
  - `version` 仍然表示当前 active version
- 传了 `version_id`：
  - `version` 改为表示当前选中的历史正式版本
  - `active_version_id` 仍然表示当前系统激活版本

为了避免混淆，单段 `translations[0]` 新增两个字段：

- `inspected_version_id`
- `inspected_version_is_active`

示意：

```json
{
  "segment_id": 12,
  "active_version_id": 34,
  "inspected_version_id": 21,
  "inspected_version_is_active": false,
  "version": {
    "id": 21,
    "version_index": 1,
    "model_profile_id": "gpt4_history"
  },
  "provenance": { "...": "..." },
  "timeline": [ "..."]
}
```

这两个字段的目的不是重复信息，而是把“当前在看谁”和“系统当前生效的是谁”明确拆开。

### 6.3 `compare` 改为“当前选中版本 vs 指定版本”

本轮不改 `compare_version_id` 这个参数名，但语义扩成：

- 如果未传 `version_id`，比较逻辑与现在一致：
  - `current active version` vs `compare_version_id`
- 如果传了 `version_id`，则变成：
  - `selected version` vs `compare_version_id`

约束如下：

- `compare_version_id` 不能等于当前选中版本
- 两个 version 必须同属同一个 `segment_translation`

`compare` 返回结构不变，仍然保持：

- `base_version`
- `current_version`
- `changed`
- `summary`

其中：

- `current_version` 表示“当前 inspect 选中的版本”
- `base_version` 表示“compare_version_id 指向的版本”

这样可以把改动压到最小，不额外发明一套 compare 结构。

### 6.4 provenance / timeline 改为围绕“当前选中版本”构建

本轮后：

- `provenance` 不再隐含“只解释 active version”
- `timeline` 也不再隐含“只解释 active version”

它们统一改成：

- 解释当前 `version` 对应的来源链

兼容策略保持简单：

- 选中的 version 没有 provenance 指针时，`provenance = null`
- 选中的 version 没有完整来源链时，`timeline = []`

项目级 `inspect.translation` 仍然按 active version 组织，不引入全项目 `version_id` 语义。

### 6.5 `review.run` summary 新增 `translation_source`

`ReviewService.run()` 当前 summary 只有：

- `request_id`
- `issue_count`
- `segment_count`

本轮新增：

- `translation_source`

这是一份轻量来源快照，用来回答：

- review 当时基于哪些 active translation versions 做的

返回结构示意：

```json
{
  "request_id": "req_review_001",
  "issue_count": 3,
  "segment_count": 10,
  "translation_source": {
    "segment_count": 10,
    "version_count": 10,
    "version_ids": [101, 102, 103],
    "segments": [
      {
        "segment_id": 12,
        "chapter_id": 3,
        "chapter_index": 1,
        "segment_index": 2,
        "translation_status": "completed",
        "review_status": "pending",
        "version": {
          "id": 101,
          "version_index": 2,
          "provider_name": "openai_compatible",
          "model_profile_id": "gpt_5_4_main",
          "model_name": "gpt-5.4",
          "status": "completed",
          "source_hash": "...",
          "glossary_snapshot_id": "..."
        }
      }
    ]
  }
}
```

边界明确如下：

- 只记录 version 元信息，不记录全文 `source_text / translated_text`
- `segments[*].version` 允许为 `null`
  - 对应 review 跑在缺失译文的段落上
- `version_ids` 只收非空 version id，且去重排序

这样既能表达来源，又不会把 summary 撑成一份小 manifest。

### 6.6 `export.run` summary 新增 `translation_source`

`ExportService.run()` 当前有完整 manifest，但 `summary` 太薄，`inspect.export` 只能看到 run 外壳。

本轮在 export run summary 里同步新增：

- `translation_source`

结构与 review 保持同口径，只是 `segments[*].review_status` 会保留导出当时的真实值。

原因很简单：

- manifest 适合产物消费
- summary 适合 inspect 快速浏览

两者服务不同场景，不能再让 `inspect.export` 依赖人工去读 manifest。

### 6.7 `inspect.review` / `inspect.export` 顶层直接透出来源快照

为了让调用方不用自己再去 `summary["translation_source"]` 里翻字段，本轮两处 inspect 都加顶层透出：

- `inspect.review` 的每条 `runs[*]` 新增 `translation_source`
- `inspect.export` 的每条 `runs[*]` 新增 `translation_source`

规则如下：

- 值直接来自 summary 解码后的 `translation_source`
- summary 本体仍然保留，不拆掉
- 如果历史 run 没有这个字段，则顶层返回 `null`

这样调用方可以两种方式拿：

- 直接看 `translation_source`
- 或看原始 `summary`

### 6.8 推荐实现边界

为避免 `ReviewService` / `ExportService` 各写一套版本来源组装逻辑，本轮新增一个共享服务：

- `TranslationSourceSnapshotService`

职责只有两个：

1. 从 review/export 的 segment rows 构建轻量 `translation_source` 快照
2. 统一 version 元信息的裁剪口径

它不负责 inspect，不负责运行调度，只负责“把这次 run 基于哪些 translation versions”稳定编码成一个轻量结构。

## 7. 返回结构与参数规则汇总

### 7.1 `inspect.glossary`

新增：

- `relation_groups`

保留：

- `entries`
- `candidates`

### 7.2 `glossary.inspect_pipeline`

新增：

- `finalized_terms`
- `finalized_relation_groups`

保留：

- `draft_candidates`
- `reviews`

### 7.3 `inspect.translation`

新增入参：

- `version_id`

新增字段：

- `inspected_version_id`
- `inspected_version_is_active`

语义变化：

- `version / provenance / timeline / compare.current_version` 全部围绕当前选中版本

### 7.4 `inspect.review`

每条 `runs[*]` 新增：

- `translation_source`

### 7.5 `inspect.export`

每条 `runs[*]` 新增：

- `translation_source`

## 8. 实现触点

本轮预计只修改下面这些位置：

- `app/services/glossary_service.py`
  - `inspect()` 增加 `relation_groups`
- `app/services/glossary_pipeline_service.py`
  - `inspect_pipeline()` 增加 finalized 视角
- `app/services/translation_assets_service.py`
  - glossary prompt 注入改成组感知排序和渲染
- `app/services/translation_inspection_service.py`
  - 增加 `version_id` 选择逻辑
  - `provenance / timeline / compare` 切到“当前选中版本”语义
- `app/services/review_service.py`
  - summary 写入 `translation_source`
  - inspect 透出 `translation_source`
- `app/services/export_service.py`
  - summary 写入 `translation_source`
  - inspect 透出 `translation_source`
- 新增共享服务：
  - `app/services/glossary_relation_group_service.py`
  - `app/services/translation_source_snapshot_service.py`
- 测试：
  - `tests/test_glossary_stage.py`
  - `tests/test_translation_workflow_actions.py`
  - `tests/test_translation_inspection_service.py`
  - `tests/test_review_export.py`
  - 如需入口断言，再补 `tests/test_project_actions.py`

## 9. 风险点

### 9.1 review/export summary 体积变大

因为要把 segment -> version 的来源快照写进 summary，run summary 会比现在大。

规避方式：

- summary 只保留 version 元信息
- 不写全文 source/translation 文本
- `version_ids` 去重，避免重复冗余

### 9.2 历史 run 没有 `translation_source`

旧 review/export run 不会自动有来源快照。

规避方式：

- inspect 顶层 `translation_source` 对旧数据稳定返回 `null`
- 不做回填，不把旧数据视作异常

### 9.3 `version_id` 语义容易和 `active_version_id` 混淆

规避方式：

- 明确新增 `inspected_version_id`
- 明确新增 `inspected_version_is_active`
- 文档和测试都按这条语义锁住

### 9.4 glossary group warning 容易过度推断

如果 warning 规则太“聪明”，结果会漂。

规避方式：

- 本轮 warning 只做结构冲突，不做语义建议
- 只返回稳定可判定的 5 类 warning code

## 10. 测试方案

本轮至少覆盖下面九类测试：

1. `inspect.glossary`
   - 多成员同组会生成 `relation_groups`
   - `missing_canonical / multiple_canonical / gender_conflict / age_group_conflict` 规则稳定

2. `glossary.inspect_pipeline`
   - finalize 前 `finalized_terms / finalized_relation_groups` 为空
   - finalize 后返回 hydrated final terms 与 relation groups

3. translation glossary prompt
   - 同组多命中时按 group block 输出
   - 组排序与组内排序稳定
   - 不会注入正文未命中的同组术语

4. `inspect.translation`
   - 单段不传 `version_id` 时仍查看 active version

5. `inspect.translation`
   - 单段传 `version_id` 时返回历史正式版本
   - `inspected_version_is_active` 正确

6. `inspect.translation compare`
   - 未传 `version_id` 时仍是 active vs compare target
   - 传 `version_id` 时变成 selected version vs compare target

7. `inspect.translation` 非法参数
   - 项目级模式传 `version_id` 报错
   - `version_id` 不属于当前 segment 报错
   - `compare_version_id` 等于当前选中版本报错

8. `inspect.review`
   - `runs[*].translation_source` 能直接看到来源快照
   - 历史无该字段 run 稳定返回 `null`

9. `inspect.export`
   - `runs[*].translation_source` 能直接看到来源快照
   - summary 里没有全文文本，只保留轻量版本元信息

验证顺序建议：

- 先跑对应单测文件
- 再跑 `python -m pytest tests -q`

## 11. 本轮完成标准

本轮完成后，`P1.2 / P1.3` 可以视为收尾完成，判断标准如下：

### 11.1 `P1.2` 完成标准

- `inspect.glossary` 能直接看见关系组、角色分布和一致性告警
- `glossary.inspect_pipeline` 能看见 finalized 视角，而不只是 draft/review
- translation prompt 对同组多命中术语有稳定、分组、无歧义的输出

### 11.2 `P1.3` 完成标准

- 单段 `inspect.translation` 可以切到任意历史正式版本
- compare 可以围绕当前选中版本工作，而不是被 active version 绑死
- `inspect.review` / `inspect.export` 能直接看见本次 run 使用的译文版本来源快照

同时满足下面三个约束：

- 不新增 schema
- 不引入新的 inspect action
- 完整回归保持通过
