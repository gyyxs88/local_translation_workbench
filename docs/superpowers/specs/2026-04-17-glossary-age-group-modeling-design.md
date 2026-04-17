# Glossary Age Group 结构化建模设计

## 1. 背景

当前 glossary 链路已经完成 `gender` 的结构化建模，并且打通了：

- `draft candidate -> candidate -> entry`
- `inspect.glossary`
- `glossary.inspect_pipeline`
- translation glossary prompt
- `glossary_snapshot_id`

这意味着人物术语的部分结构化属性已经能稳定进入 glossary 主链路和 translation 主链路。

但 `age_group` 目前仍然没有单独建模，现状主要有两个问题：

- 人物年龄层信息只能零散地留在 `note` 或 provider 自由文本里
- translation 侧完全感知不到这类信息，无法把“儿童 / 少年 / 成人 / 老年角色”作为结构化术语线索消费

路线图里 `P1.2 术语模型扩展` 的第二刀，不是继续扩一大串人物属性，而是沿着已经落稳的 `gender` 链路，把 `age_group` 也收成一个最小、保守、可测试的结构化字段。

## 2. 本轮目标

本轮目标只有五个：

1. 给 glossary 主链路增加结构化 `age_group`
2. 把 `age_group` 贯通到 `draft candidate -> candidate -> entry`
3. 让 `inspect.glossary` 和 `glossary.inspect_pipeline` 能直接返回 `age_group`
4. 让 translation 的 glossary prompt 与 `glossary_snapshot_id` 感知 `age_group`
5. 把 `age_group` 的判定语义收紧为一个保守、稳定、可验证的最小模型

## 3. 非目标

本轮明确不做下面这些事情：

- 不做 `middle_aged`、`young_adult` 等更细分枚举
- 不做 `age_group` 的宽松语义映射
- 不从敬称、职位、关系角色自动推断年龄层
- 不做历史 glossary 数据回填脚本
- 不扩 `inspect.translation`、`inspect.segment` 等其他观察面
- 不基于 `age_group` 做译文后处理、语气改写或一致性规则
- 不回头重构 `gender` 的既有实现，只做必要的对称扩展

## 4. 方案选择

本轮评估三种方案：

### 4.1 方案 A：全链路镜像 `gender`

做法：

- 在现有 glossary 数据模型上新增 `age_group`
- 让 extract / finalize / inspect / translation prompt / snapshot 一起消费该字段

优点：

- 语义和链路最统一
- 后续维护成本最低
- translation 能直接消费结构化年龄层信息

缺点：

- 改动面最大
- 需要 migration，并且 glossary 与 translation 两侧都要一起改

### 4.2 方案 B：先只做 glossary 内闭环

做法：

- 新增 `age_group`
- 只打通 `draft / candidate / entry / inspect`
- translation 暂时不消费该字段

优点：

- 范围更小
- 落库与 inspect 可以先稳定

缺点：

- 新字段短期帮不到翻译
- 后面大概率还要再补一刀 translation 联动

### 4.3 方案 C：只放在中间产物里

做法：

- 把 `age_group` 留在 draft candidate 或 evidence payload
- 不进正式 glossary entry

优点：

- 改动最轻

缺点：

- 长期价值很低
- 会留下“半结构化字段”技术债
- translation 无法稳定消费

### 4.4 结论

本轮采用：

**方案 A：全链路镜像 `gender`。**

原因很直接：

- 当前仓库已经有一条成熟的 `gender` 对称路径
- `age_group` 的业务价值只有进入 translation 主链路后才真正成立
- 在现有结构上增加一个保守字段，性价比最高

## 5. 值模型与语义边界

### 5.1 值模型

本轮 `age_group` 使用可空受限值：

- `child`
- `teen`
- `adult`
- `elderly`
- `null`

本轮不引入 `unknown`。

`null` 同时表示：

- 当前术语不适用 `age_group`
- 当前术语缺少足够依据，无法判断
- provider 未返回合法 `age_group`

这样可以避免把 `null` 和 `unknown` 分裂成两套模糊语义。

### 5.2 适用范围

本轮 `age_group` 只对 `category == "character"` 生效。

规则如下：

- `category == "character"` 时，允许 `age_group` 为 `child / teen / adult / elderly / null`
- `category != "character"` 时，`age_group` 必须为 `null`

也就是说，像 `title / location / organization / item / slang / term / other` 这些类别，即使 provider 返回了 `age_group`，最终也会被服务层强制清成 `null`。

### 5.3 判定原则

本轮 `age_group` 采用保守判定策略：

- 只接受明确年龄段线索
- 不接受宽松语义联想
- 不根据敬称、职位、关系词去猜年龄层

可以接受的明确线索包括：

- `孩子 / 小孩` -> `child`
- `少年 / 少女` -> `teen`
- `成年人 / 明确成人身份` -> `adult`
- `老人 / 老太太 / 老者` -> `elderly`

不作为单独判定依据的线索包括：

- `先生`
- `小姐`
- `哥`
- `姐`
- `阿姨`

本轮不要求服务层把任意自由文本强行映射成枚举值；如果 provider 没有返回合法规范值，系统直接收口为 `null`。

### 5.4 裁决策略

`age_group` 的生产与确认分两层：

1. `extract` 先给出初值
2. `finalize` 保留最终确认权

这样做的原因是：

- extract 最接近章节局部上下文，适合初步识别年龄层线索
- finalize 能看到整轮 draft candidate，更适合做最后收口

本轮不增加单独的 `age_group review` 阶段。

## 6. 数据模型设计

### 6.1 新增字段

本轮新增三处字段：

- `ltw_glossary_draft_candidates.age_group`
- `ltw_glossary_candidates.age_group`
- `ltw_glossary_entries.age_group`

其中：

- `age_group` 为可空字符串
- 取值由服务层收口为 `child / teen / adult / elderly / null`

### 6.2 服务层类型

`GlossaryExtraction` dataclass 新增：

```python
age_group: str | None
```

同时 glossary repository 的下面三个创建接口要补齐入参：

- `create_draft_candidate(...)` 增加 `age_group`
- `create_candidate(...)` 增加 `age_group`
- `create_entry(...)` 增加 `age_group`

### 6.3 统一归一规则

服务层新增统一的 `age_group` 归一逻辑，语义要求如下：

- 仅接受 `child / teen / adult / elderly`
- 大小写变体与首尾空白可被归一
- 空串、未知值、无效值一律转成 `None`
- `category != "character"` 时强制 `None`
- 不从 `note` 反向推断 `age_group`
- 不把 `young / old / middle-aged / girl / boy` 这类自由文本自动折算成规范值

本轮的原则是：

**provider 可以建议，服务层负责收口。**

## 7. glossary 链路变更

### 7.1 extract

`glossary.extract` 的 provider 输出对象新增字段：

- `age_group`

extract prompt 需要明确要求：

- 仅当 `category == "character"` 且正文或术语里有明确年龄段线索时才填写 `age_group`
- 合法值只允许 `child / teen / adult / elderly`
- 没有明确线索时返回 `null`
- 不要根据敬称、语气、职位或关系词猜测年龄层

解析时：

- 先读取 provider 返回的 `age_group`
- 再通过统一归一逻辑收口
- 结果写入 `GlossaryExtraction.age_group`

### 7.2 decision / normalize / relation / scope

本轮不为这些中间步骤新增专门的 `age_group` 裁决逻辑。

中间步骤的原则是：

- 不主动生成新的 `age_group`
- 只透传 extract 已有的 `age_group`

原因与 `gender` 一样：

- 这些步骤的职责不是新增人物属性判断
- 本轮的主要裁决位点仍然是 `extract` 和 `finalize`

### 7.3 finalize

`glossary.finalize` 终审 prompt 同样增加 `age_group` 字段，并明确要求：

- 最终保留、修正或清空 `age_group`
- 非 `character` 项必须输出 `null`
- 没有明确线索时必须输出 `null`
- 不允许输出枚举之外的自由文本

provider 返回最终术语时，`age_group` 要进入 provider term payload。

随后 hydration / fallback finalize 逻辑都必须把 `age_group` 带入最终 `finalized_terms`。

### 7.4 落库

finalize 落库时：

- `GlossaryEntry` 写入 `age_group`
- `GlossaryCandidate` 同步写入 `age_group`

如果遇到已存在且未锁定的 `GlossaryEntry`：

- 允许按现有更新语义覆盖 `target_term / category / note / relation_role / scope`
- 同时覆盖 `age_group`

锁定 entry 的既有语义保持不变，不因为本轮 `age_group` 而改变。

## 8. inspect 返回结构

### 8.1 `inspect.glossary`

`inspect.glossary` 返回的两个列表都增加 `age_group`：

```json
{
  "entries": [
    {
      "id": 1,
      "source_term": "林溪",
      "target_term": "Lin Xi",
      "category": "character",
      "gender": "female",
      "age_group": "teen",
      "term_group_key": "character-linxi",
      "relation_role": "canonical"
    }
  ],
  "candidates": [
    {
      "id": 11,
      "source_term": "林溪",
      "suggested_term": "Lin Xi",
      "category": "character",
      "note": "Character name",
      "gender": "female",
      "age_group": "teen",
      "term_group_key": "character-linxi",
      "relation_role": "canonical"
    }
  ]
}
```

也就是说：

- `entries[*].age_group`
- `candidates[*].age_group`

都会成为对外可见字段。

### 8.2 `glossary.inspect_pipeline`

`inspect_draft_candidates()` 返回中新增：

- `age_group`

这样 pipeline draft candidate 的观察面也能直接看见结构化 `age_group`。

本轮不新增单独的 `age_group reviews` 或额外 inspect action。

## 9. translation 联动

### 9.1 glossary prompt 注入

translation 侧术语注入继续沿用现有字符串风格，只在 `age_group` 非空时附带：

```text
- 林溪 => Lin Xi | role: canonical | group: character-linxi | category: character | gender: female | age_group: teen | note: Character name
```

如果 `age_group is null`，则不输出 `| age_group: ...` 片段。

本轮不改变 prompt 的整体结构，只是在 glossary entry 现有展示串上增加一个新片段。

### 9.2 glossary snapshot

`glossary_snapshot_id` 的计算 payload 必须把 `age_group` 纳入。

这意味着：

- 当前有效术语表里某个 entry 的 `age_group` 变化
- 即使其他字段不变
- snapshot 也会变化

这是本轮必须做到的要求，因为 translation 既然开始消费 `age_group`，snapshot 身份就必须对它敏感。

### 9.3 本轮不做的 translation 能力

虽然 `age_group` 会进入 translation prompt，但本轮明确不做：

- 基于年龄层的用词后处理
- 代词规则扩展
- 译文口吻或语气自动调整
- 超出术语提示范围的任何推断逻辑

本轮 translation 联动只到：

- glossary prompt 注入
- glossary snapshot 身份更新

## 10. prompt 设计要求

### 10.1 extract prompt

extract prompt 需要新增下面这类约束：

- 每个术语对象字段包含 `age_group`
- 仅人物术语允许填写
- 必须基于正文或术语里的明确年龄段线索，不要猜测
- 无法确认时返回 `null`

### 10.2 finalize prompt

finalize prompt 需要新增下面这类约束：

- 最终输出项包含 `age_group`
- 终审可以保留、修正或清空 draft `age_group`
- 非人物术语必须输出 `null`
- 没有明确线索时必须输出 `null`

### 10.3 容错要求

本轮把下面这些情况都视为正常容错场景：

- provider 完全不返回 `age_group`
- provider 返回空串
- provider 返回未知值
- provider 给非人物术语填了 `age_group`
- provider 返回自由文本而不是规范枚举

系统都不应报错，只需要按归一规则收口。

## 11. 测试边界

本轮至少需要覆盖下面五组测试：

1. schema 层  
   `GlossaryDraftCandidate / GlossaryCandidate / GlossaryEntry` 都有 `age_group` 列，且允许为空

2. extract 解析与归一  
   人物术语的 `age_group` 能被正确解析为 `child / teen / adult / elderly`

3. 非人物或无明确线索清零  
   非 `character` 术语，或缺少明确年龄段线索的术语，最终都会被收口为 `null`

4. finalize 落库链路  
   `draft candidate -> candidate -> entry` 三层都能正确保留 `age_group`

5. translation 联动  
   `_format_glossary_entry()` 在 `age_group` 非空时附带 `age_group`  
   `_compute_glossary_snapshot_id()` 在 `age_group` 变化时产生新哈希

如果本轮补 CLI 覆盖，则只做最小增量，重点验证：

- `inspect.glossary` 返回的结构化字段里包含 `age_group`

## 12. 兼容与迁移策略

本轮采用“新字段即时生效，旧数据自然退化”的策略：

- migration 只增加字段，不做历史回填
- 旧 glossary 记录没有 `age_group` 时，视为 `null`
- 旧 `note` 里即使写着“少年 / 老人”等信息，系统也不自动反推 `age_group`

这样可以保证：

- 本轮范围可控
- 不引入脆弱的历史推断
- 新跑出来的数据从第一天起就是结构化的

## 13. 风险与取舍

本轮最主要的风险有三个：

### 13.1 provider 会乱猜 `age_group`

缓解方式：

- prompt 明确要求“无明确线索就返回 `null`”
- 服务层严格归一，只接受受限枚举

### 13.2 非人物术语被错误标成有 `age_group`

缓解方式：

- 服务层用 `category` 做最后闸门
- 非 `character` 一律强制 `null`

### 13.3 字段存在但 translation 不真正消费

本轮已经明确避免这个问题：

- `age_group` 会进入 translation glossary prompt
- `glossary_snapshot_id` 对 `age_group` 变化敏感

这样新增字段才不只是“看起来结构化”，而是真正进入主链路。

## 14. 最终结论

本轮 `P1.2` 第二刀采用下面这组收口：

- `age_group` 作为 glossary 主链路的结构化字段落地
- 值模型限定为 `child / teen / adult / elderly / null`
- 仅 `category == "character"` 生效
- 只接受明确年龄段线索，不做宽松推断
- extract 提供初值，finalize 保留最终确认权
- draft / candidate / entry / inspect / translation snapshot / translation prompt 全链路感知 `age_group`
- 不做历史回填，不做年龄层后处理，不扩其他 inspect 面

这能以最小复杂度把人物年龄层信息从自由文本提升为可靠结构，同时保持和现有 `gender` 设计几乎完全对称，降低后续维护成本。
