# Glossary Gender 结构化建模设计

## 1. 背景

当前 glossary 链路已经支持这些结构化字段：

- `category`
- `note`
- `term_group_key`
- `relation_role`
- `scope_level`
- `scope_chapter_id`

但 `gender` 目前还没有单独建模，现状主要有两个问题：

- 人物术语的性别信息只能零散地写在 `note` 里，例如 `"Character name, female"`
- translation 侧的术语 snapshot 和 prompt 注入完全不知道这类信息，无法稳定消费

这会带来两个直接后果：

- `inspect.glossary` 看不到结构化 `gender`
- glossary 已经知道的人物性别信息，不能稳定传递到后续翻译阶段

路线图里 `P1.2 术语模型扩展` 的第一刀，不是一次性做复杂的人物属性系统，而是先把 `gender` 从自由文本里拉成一个可靠、可观察、可透传的结构化字段。

## 2. 本轮目标

本轮目标只有五个：

1. 给 glossary 主链路增加结构化 `gender`
2. 把 `gender` 贯通到 `draft candidate -> candidate -> entry`
3. 让 `inspect.glossary` 和 `glossary.inspect_pipeline` 能直接返回 `gender`
4. 让 translation 的 glossary snapshot 与 prompt 注入感知 `gender`
5. 把 `gender` 的语义收紧为一个稳定、可测试的最小模型

## 3. 非目标

本轮明确不做下面这些事情：

- 不做 `age_group`、`honorific_style`、`number` 等其他人物属性
- 不做独立的 `gender review_type`
- 不做从旧 `note` 自动回填 `gender`
- 不做历史 glossary 数据回填脚本
- 不做基于 `gender` 的代词自动替换、句法改写或译文后处理
- 不扩 `inspect.translation` 的 glossary 明细展示
- 不引入新的 metadata 表

## 4. 方案选择

本轮评估三种方案：

### 4.1 方案 A：把 `gender` 直接挂进 glossary 主链路

做法：

- 在现有 glossary 数据模型上新增 `gender`
- 让 extract / finalize / inspect / translation snapshot 一起消费该字段

优点：

- 链路最硬
- 查询和排障都简单
- 后续要继续扩人物属性时也有明确落点

缺点：

- 需要 migration
- glossary 与 translation 两侧都要一起改

### 4.2 方案 B：继续把 `gender` 放在 `note / evidence_payload`

做法：

- 不新增字段
- `inspect` 时临时解析 `note` 或 `evidence_payload`

优点：

- 改动最小

缺点：

- 结果不稳定
- 仍然依赖文本约定
- translation 侧很难稳定利用

### 4.3 方案 C：单独建 glossary metadata 表

做法：

- 新建 metadata 表，把 `gender` 与后续扩展属性都挂进去

优点：

- 理论扩展性最好

缺点：

- 对当前第一刀明显过重
- 会额外引入不必要的关联复杂度

### 4.4 结论

本轮采用：

**方案 A：把 `gender` 直接挂进 glossary 主链路。**

原因很直接：

- 当前目标是把人物性别信息结构化落地并传递到 translation
- 不是先做一个通用人物属性系统
- 在现有 glossary 链路上加一个收紧字段，性价比最高

## 5. 值模型与语义边界

### 5.1 值模型

本轮 `gender` 使用可空受限值：

- `female`
- `male`
- `nonbinary`
- `null`

本轮不引入 `unknown`。

`null` 同时表示：

- 当前术语不适用 `gender`
- 当前术语缺少足够依据，无法判断
- provider 未返回合法 `gender`

这样可以避免把 `null` 和 `unknown` 区分成两套容易含糊的语义。

### 5.2 适用范围

本轮 `gender` 只对 `category == "character"` 生效。

规则如下：

- `category == "character"` 时，允许 `gender` 为 `female / male / nonbinary / null`
- `category != "character"` 时，`gender` 必须为 `null`

也就是说：

- `title`
- `location`
- `organization`
- `item`
- `slang`
- `term`
- `other`

这些类别即使 provider 返回了 `gender`，最终也会被服务层归一为 `null`。

### 5.3 裁决策略

`gender` 的生产与确认分两层：

1. `extract` 先给出初值
2. `finalize` 保留最终确认权

这样做的原因是：

- extract 最接近单章局部上下文，容易识别人称和描写线索
- finalize 会看到整轮 draft candidate 与 review 结果，更适合做最后收口

本轮不增加单独的 gender review 阶段。

## 6. 数据模型设计

### 6.1 新增字段

本轮新增五处字段：

- `ltw_glossary_draft_candidates.gender`
- `ltw_glossary_candidates.category`
- `ltw_glossary_candidates.note`
- `ltw_glossary_candidates.gender`
- `ltw_glossary_entries.gender`

其中：

- `gender` 为可空字符串
- `GlossaryCandidate` 这轮顺手补齐 `category + note + gender`，让它真正成为 finalize 结果快照，而不是一个信息残缺的中间层

### 6.2 服务层类型

`GlossaryExtraction` dataclass 新增：

```python
gender: str | None
```

同时 glossary repository 的下面三个创建接口要按各自职责补齐入参：

- `create_draft_candidate(...)` 增加 `gender`
- `create_candidate(...)` 增加 `category / note / gender`
- `create_entry(...)` 增加 `gender`

### 6.3 统一归一规则

服务层新增统一的 `gender` 归一逻辑，语义要求如下：

- 仅接受 `female / male / nonbinary`
- 大小写变体与首尾空白可被归一
- 空串、未知值、无效值一律转成 `None`
- `category != "character"` 时强制 `None`
- 不从 `note` 反向推断 `gender`

本轮的原则是：

**provider 可以建议，服务层负责收口。**

## 7. glossary 链路变更

### 7.1 extract

`glossary.extract` 的 provider 输出对象新增字段：

- `gender`

extract prompt 需要明确要求：

- 仅当 `category == "character"` 且文本有足够依据时才填写 `gender`
- 合法值仅允许 `female / male / nonbinary`
- 其他情况返回 `null`

解析时：

- 先读取 provider 返回的 `gender`
- 再通过统一归一逻辑收口
- 结果写入 `GlossaryExtraction.gender`

### 7.2 decision / normalize / relation / scope

本轮不为这些中间步骤新增专门的 `gender` 判断逻辑。

中间步骤的原则是：

- 不主动生成新的 `gender`
- 只透传 extract 已有的 `gender`

原因是这几个步骤当前职责分别是：

- decision：保留/剔除候选
- relation：同组关系裁决
- scope：项目级/章节级裁决

它们都不是本轮 `gender` 的主要裁决位点。

### 7.3 finalize

`glossary.finalize` 终审 prompt 同样增加 `gender` 字段，并明确要求：

- 最终保留或修正 `gender`
- 非 `character` 项必须输出 `null`
- 如果依据不足，输出 `null`

provider 返回最终术语时，`gender` 要进入 provider term payload。

随后 hydration / fallback finalize 逻辑都必须把 `gender` 带入最终 `finalized_terms`。

### 7.4 落库

finalize 落库时：

- `GlossaryEntry` 写入 `gender`
- `GlossaryCandidate` 同步写入 `category / note / gender`

如果遇到已存在且未锁定的 `GlossaryEntry`：

- 允许按现有更新语义覆盖 `target_term / category / note / relation_role / scope`
- 同时覆盖 `gender`

锁定 entry 的现有语义保持不变，不因为本轮 `gender` 而改变。

## 8. inspect 返回结构

### 8.1 `inspect.glossary`

`inspect.glossary` 返回的两个列表都增加 `gender`：

```json
{
  "entries": [
    {
      "id": 1,
      "source_term": "傅慕宁",
      "target_term": "Fu Muning",
      "category": "character",
      "gender": "female",
      "term_group_key": "character-fu-muning",
      "relation_role": "canonical"
    }
  ],
  "candidates": [
    {
      "id": 11,
      "source_term": "傅慕宁",
      "suggested_term": "Fu Muning",
      "category": "character",
      "note": "Character name",
      "gender": "female",
      "term_group_key": "character-fu-muning",
      "relation_role": "canonical"
    }
  ]
}
```

也就是说：

- `entries[*].gender`
- `candidates[*].category`
- `candidates[*].note`
- `candidates[*].gender`

都会成为对外可见字段。

### 8.2 `glossary.inspect_pipeline`

`inspect_draft_candidates()` 返回中新增：

- `gender`

这样 workflow draft candidate 的观察面也能直接看见结构化 `gender`。

本轮不新增单独的 `gender_reviews` 或额外 inspect action。

## 9. translation 联动

### 9.1 glossary prompt 注入

translation 侧术语注入继续沿用现有字符串风格，只在 `gender` 非空时附带：

```text
- 傅慕宁 => Fu Muning | role: canonical | group: character-fu-muning | category: character | gender: female | note: Character name
```

如果 `gender is null`，则不输出 `| gender: ...` 片段。

这样做的好处是：

- 现有 prompt 结构几乎不变
- 新信息紧贴 glossary entry 本身
- 不会把 `gender` 又塞回自由文本 `note`

### 9.2 glossary snapshot

`glossary_snapshot_id` 的计算 payload 必须把 `gender` 纳入。

这意味着：

- 当前有效术语表里某个 entry 的 `gender` 变化
- 即使 `source_term / target_term / category / note / relation_role` 都不变
- snapshot 也会变化

这是本轮必须做到的要求，因为 translation 既然开始消费 `gender`，snapshot 身份就必须对它敏感。

### 9.3 本轮不做的 translation 能力

虽然 `gender` 会进入 translation prompt，但本轮明确不做：

- 自动代词替换
- 基于 `gender` 的语气调整
- 译文一致性规则扩展
- 任何超出术语提示范围的后处理逻辑

本轮 translation 联动只到：

- glossary prompt 注入
- glossary snapshot 身份更新

## 10. prompt 设计要求

### 10.1 extract prompt

extract prompt 需要新增下面这类约束：

- 每个术语对象字段包含 `gender`
- 仅人物术语允许填写
- 必须基于章节正文可见线索，不要猜测
- 无法确认时返回 `null`

### 10.2 finalize prompt

finalize prompt 需要新增下面这类约束：

- 最终输出项包含 `gender`
- 终审可以保留或修正 draft `gender`
- 非人物术语必须输出 `null`
- 证据不足时必须输出 `null`

### 10.3 容错要求

本轮把下面这些情况都视为正常容错场景：

- provider 完全不返回 `gender`
- provider 返回空串
- provider 返回未知值
- provider 给非人物术语填了 `gender`

系统都不应报错，只需要按归一规则收口。

## 11. 测试边界

本轮至少需要覆盖下面五组测试：

1. extract 解析与归一  
   人物术语的 `gender` 能被正确解析为 `female / male / nonbinary`

2. 非人物清零  
   非 `character` 术语即使 provider 返回了 `gender`，最终也会被收口为 `null`

3. finalize 落库链路  
   `draft candidate -> candidate -> entry` 三层都能正确保留 `gender`

4. inspect 观察面  
   `inspect.glossary` 与 `glossary.inspect_pipeline` 都会返回 `gender`，且 `candidates` 现在能返回 `category / note / gender`

5. translation 联动  
   `_format_glossary_entry()` 在 `gender` 非空时附带 `gender`  
   `_compute_glossary_snapshot_id()` 在 `gender` 变化时产生新哈希

如果本轮还补 CLI 覆盖，则只做最小增量，重点验证：

- `inspect.glossary` 返回的结构化字段里包含 `gender`

## 12. 兼容与迁移策略

本轮采用“新字段即时生效，旧数据自然退化”的策略：

- migration 只增加字段，不做历史回填
- 旧 glossary 记录没有 `gender` 时，视为 `null`
- 旧 `note` 里即使仍写着 `female / male`，系统也不自动抽取

这样可以保证：

- 本轮范围可控
- 不引入脆弱的历史推断
- 新跑出来的数据从第一天起就是结构化的

## 13. 风险与取舍

本轮最主要的风险有三个：

### 13.1 provider 会乱猜 `gender`

缓解方式：

- prompt 明确要求“无依据就返回 `null`”
- 服务层严格归一，不接受任意自由文本

### 13.2 非人物术语被错误标成有 `gender`

缓解方式：

- 服务层用 `category` 做最后闸门
- 非 `character` 一律强制 `null`

### 13.3 只加 `gender` 会不会让 candidate 继续结构不对称

本轮已经明确避免这个问题：

- `GlossaryCandidate` 一起补齐 `category + note + gender`

这样三层数据模型会更一致，也更利于 inspect 使用。

## 14. 最终结论

本轮 `P1.2` 第一刀采用下面这组收口：

- `gender` 作为 glossary 主链路的结构化字段落地
- 值模型限定为 `female / male / nonbinary / null`
- 仅 `category == "character"` 生效
- extract 提供初值，finalize 保留最终确认权
- draft / candidate / entry / inspect / translation snapshot / translation prompt 全链路感知 `gender`
- 不做历史回填，不做代词规则，不做额外 review 类型

这能以最小复杂度把人物性别信息从自由文本提升为可靠结构，同时为后续更广的术语模型扩展留下稳定落点。
