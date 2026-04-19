# Review 阶段术语遵守检查设计

## 1. 背景

当前仓库里的 `review` 阶段仍然是轻量规则审校。

截至现在，`ReviewService` 只会报告下面三类问题：

- 没有可用生效译文
- 译文为空
- 译文与原文完全一致

这能支撑最基础的闭环，但还不能回答一个更贴近真实使用的问题：

**如果原文分片里已经命中了 glossary 术语，当前生效译文是否真的遵守了 glossary 约定的译法。**

由于这类检查很容易误报，本轮不追求“抓全所有术语问题”，而是优先落一条高置信、低误伤的规则。

## 2. 本轮目标

本轮只做一件事：

**在 `review` 阶段新增首版 glossary 术语遵守检查。**

首版规则收口为：

- 只检查当前分片原文里真实命中的 glossary `source_term`
- 如果译文里没有出现对应的 `target_term`，则报告 issue
- 匹配使用宽松文本规则，降低大小写、空格和常见标点带来的误报

## 3. 非目标

本轮明确不做下面这些事：

- 不引入 LLM 审校
- 不判断“译文是否优美”或“语气是否合适”
- 不检查 glossary 同组 alias / canonical / title / variant 是否可以互相放行
- 不检查“同一 source_term 在原文出现多次，译文是否出现相同次数”
- 不引入词形还原、同义词扩展、模糊语义匹配
- 不修改数据库 schema
- 不新增 `segment_id` 到 `ReviewIssue`

也就是说，这轮只做一条保守规则：

**`source_term` 命中，但 `target_term` 缺失。**

## 4. 方案比较

### 4.1 方案 A：在 `review` 自己重写 glossary 命中规则

做法：

- `review` 自己遍历 glossary entries
- 自己实现一套 source term 命中逻辑
- 再检查 `target_term` 是否出现在译文里

优点：

- `review` 模块表面上更独立

缺点：

- 很容易和 `translation` 生成 prompt 时的术语命中范围漂移
- 以后会出现“translation 认为命中了，review 却不这么看”的不一致

### 4.2 方案 B：复用 `translation` 当前的 glossary 命中逻辑

做法：

- `review` 直接复用 `TranslationAssetsService.build_prompt_glossary_entries(...)`
- 先得到“当前分片原文里真实命中的 glossary entries”
- 再对这些 entries 检查译文是否包含对应 `target_term`

优点：

- 和真实 translation prompt 的 glossary 注入范围保持一致
- 首版误报最低
- 不需要维护两套不同的 source term 命中语义

缺点：

- `review` 会依赖 `TranslationAssetsService`

### 4.3 方案 C：直接做 group-aware 宽松审校

做法：

- 只要同组术语中的任一 `target_term` 出现在译文里，就算通过

优点：

- 理论上覆盖更多真实写法

缺点：

- 边界会立刻复杂化
- 和当前“保守、高置信优先”的目标冲突
- 很容易把首版做成“看起来很聪明、实际不好解释”

### 4.4 结论

本轮采用：

**方案 B：复用 `translation` 的 glossary 命中逻辑。**

原因：

- 这和当前真正参与翻译 prompt 构造的 glossary 语义一致
- 能最大限度降低首版误报
- 不会让 `review` 额外发明一套新规则

## 5. 规则定义

### 5.1 检查对象

每个待审分片需要先拿到：

- 当前分片原文 `source_text`
- 当前 active version 的 `translated_text`
- 当前项目下有效 glossary entries

然后用现有 `TranslationAssetsService.build_prompt_glossary_entries(...)` 计算出：

- 当前分片原文里真实命中的 glossary entries

只有这些命中的 entries 才进入审校检查。

### 5.2 缺失判定

对每个命中的 glossary entry：

- 读取 `source_term`
- 读取 `target_term`
- 检查译文里是否包含对应 `target_term`

如果译文里找不到对应 `target_term`，则生成一条 review issue。

### 5.3 重复命中口径

如果同一个 `source_term` 在原文分片里出现多次，首版口径如下：

- **只要译文里出现过一次对应 `target_term`，就视为通过**

本轮不检查原文和译文的出现次数是否大致对应。

这样做的原因是：

- 首版优先减少误报
- 计数一致性检查会明显增加复杂度
- 对真实译文来说，重复命中的呈现方式不一定和原文一一对齐

## 6. 文本匹配规则

### 6.1 采用宽松文本匹配

首版不做严格精确匹配，而是采用宽松文本匹配。

原因：

- 英文译文里常见大小写变化
- 术语前后容易带引号、逗号、句点、括号
- 如果要求逐字符完全一致，误报率会很高

### 6.2 规范化规则

在比较 `target_term` 是否出现在 `translated_text` 中之前，双方先做统一规范化。

规范化至少包括：

- 全部转小写
- 去掉中英文空白字符
- 去掉常见中英文标点

标点范围首版覆盖常见集合即可，例如：

- `, . ! ? ; :`
- `，。！？；：`
- `' " “ ” ‘ ’`
- `() [] {}`
- `（）【】《》`

规范化后的判断方式仍然是：

- **包含关系判断**

即：

- 规范化后的 `translated_text`
- 是否包含规范化后的 `target_term`

### 6.3 本轮不做的匹配增强

本轮明确不做：

- 词形变化识别
- 复数/单复数兼容
- 连字符和特殊拼写变体的语义归一
- 同义词容忍
- 同组 alias / canonical 互认

如果后续需要更强能力，再单独开一轮设计。

## 7. Issue 设计

### 7.1 新 issue_type

新增 review issue 类型：

- `glossary_term_missing`

语义是：

- 原文分片命中了 glossary `source_term`
- 当前 active 译文里没有找到对应 `target_term`

### 7.2 severity

首版严重级别固定为：

- `medium`

原因：

- 这类问题比“缺失译文”轻
- 但又明显比普通风格问题更确定

### 7.3 message

由于当前 `ReviewIssue` 没有 `segment_id` 字段，首版不改 schema，直接在 `message` 里写清楚定位信息。

message 需要至少包含：

- `chapter_index`
- `segment_index`
- `source_term`
- `target_term`

建议形态：

- `第1章第2分片命中了术语“程风”，但译文里未发现约定译法“Cheng Feng”。`

## 8. 实现边界

### 8.1 不改 schema

本轮不新增或修改数据库字段。

原因：

- 当前需求只是新增一种规则 issue
- `ReviewIssue` 现有字段已足以表达问题类型、严重级别和文本消息
- 首版先验证规则价值，再决定是否需要 schema 强化

### 8.2 复用现有服务

实现上新增的主要逻辑应该尽量收在 `ReviewService` 内部，但 glossary 命中范围要复用现有 `TranslationAssetsService`。

推荐做法：

- `ReviewService` 增加 `translation_assets` 依赖
- 新增一个内部方法，专门构建 glossary 术语缺失 issue
- `_build_issue(...)` 从“单一规则判断”扩展为“按顺序执行多个高置信规则”

### 8.3 规则执行顺序

推荐顺序如下：

1. 无 active version -> `missing_translation`
2. active version 译文为空 -> `missing_translation`
3. 译文与原文完全一致 -> `unchanged_translation`
4. glossary 术语遵守检查 -> `glossary_term_missing`

首版约束：

- 每个分片最多返回一条 review issue

也就是说，如果分片已经落入前面更明确的问题类型，本轮不再继续叠加 glossary issue。

这样可以保持首版输出简单、稳定、可解释。

## 9. 测试方案

本轮至少新增三组测试。

### 9.1 命中 source_term 但缺失 target_term

场景：

- 原文分片里命中了 glossary `source_term`
- 当前 active version 译文里没有对应 `target_term`

预期：

- review 生成一条 `glossary_term_missing`
- `severity = medium`

### 9.2 大小写或标点差异不应误报

场景：

- 原文命中了 glossary `source_term`
- 译文里出现了本质相同的 `target_term`
- 但大小写、引号、逗号、句点或空格与 glossary 保存值不同

预期：

- review 不应生成 `glossary_term_missing`

### 9.3 当前分片未命中 source_term 不应报错

场景：

- glossary 里有术语
- 但当前分片原文并未命中该 `source_term`

预期：

- review 不应因为这个 glossary entry 报 issue

### 9.4 回归要求

除新增定向测试外，仍需要跑完整 `pytest` 回归，确保：

- 现有 `review / export / inspect.review` 行为不被破坏
- 新增 issue_type 不会影响已有 summary 和导出流程

## 10. 风险与处理

### 10.1 误报风险

风险：

- 英文译文里存在大小写、引号、标点等格式差异

处理：

- 首版使用宽松文本匹配

### 10.2 与 translation 语义漂移

风险：

- `review` 如果自己实现 glossary 命中逻辑，容易和 translation 真实 prompt 注入范围不一致

处理：

- 直接复用 `TranslationAssetsService.build_prompt_glossary_entries(...)`

### 10.3 一次报太多问题

风险：

- 一个分片同时命中多条规则时，输出会过乱

处理：

- 首版保持“每分片最多一条 issue”
- 优先保留更明确的基础错误类型

## 11. 完成标准

本轮完成后，需要满足下面这些条件：

1. `review` 能识别“原文命中了术语，但译文里没出现约定译法”的高置信问题
2. 新 issue 使用统一类型 `glossary_term_missing`
3. 大小写、空格和常见标点差异不会造成明显误报
4. 未命中 source term 的 glossary 项不会参与当前分片审校
5. 全量测试继续通过

如果以上五点都满足，就可以认为这轮 `review` 的 glossary 首版约束检查已经落地。
