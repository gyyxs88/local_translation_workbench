# Segment 分片语义设计

## 1. 背景

当前仓库里的 `chapter / segment` 实际语义并不完全一致：

- `chapter` 已经明确是逻辑章节
- `segment` 在数据模型、translation、review、export、inspect 中承担的是运行单元
- 但当前 `chaptering` 实现仍然是一章只创建一个 `segment`

这会导致两个问题：

1. `segment` 这个词在语义上看起来像“章内正文段落”，但真实作用更接近“LLM 执行单元”
2. 当单章内容过长时，当前实现只能把整章正文直接送进 translation workflow，容易带来：
- 单次请求体过大
- 模型输出速度下降
- 幻觉风险上升
- 失败补跑粒度过粗

因此这轮不再把 `segment` 定义成“文学结构段落”，而是正式收口为：

**`segment = 章节内翻译分片`**

也就是：

- `chapter` 负责表达逻辑章节边界
- `segment` 负责表达 LLM 的稳定执行边界、补跑边界和 inspect 边界

## 2. 本轮目标

本轮只解决一件事：

**把 `segment` 的定义、切分策略和下游语义统一收口为“翻译分片”。**

具体目标有四个：

1. 明确 `chapter` 和 `segment` 的最终语义
2. 定义 v1 分片规则：什么时候拆、按什么边界切、目标大小是多少
3. 明确 translation / review / export / inspect 如何消费分片
4. 明确本轮范围只做稳定、固定规则分片，不引入动态模型感知切分

## 3. 非目标

本轮明确不做下面这些事：

- 不把 `segment` 定义成自然段
- 不做“按不同 provider/profile/tokenizer 动态切分”
- 不在 v1 引入双层结构，例如 `chapter -> segment -> runtime chunk`
- 不重做 glossary schema
- 不做旧项目数据回填兼容
- 不要求保留“一章一个 segment”的旧语义

仓库当前规则已经明确：

- 不需要向后兼容

所以这轮设计直接按目标语义收口，不为旧实现保留过渡包袱。

## 4. 方案选择

本轮评估三个方向：

### 4.1 方案 A：`segment = 自然段`

做法：

- `chaptering` 按自然段拆分
- 每个自然段直接变成一个 `segment`

优点：

- 实现直观
- 肉眼容易理解

缺点：

- 自然段不等于好的 LLM 执行单元
- 对短对话、留白句、连续动作句会过碎
- 容易让 translation prompt 失去足够上下文
- 会把 `segment` 的语义锁死在文学结构，而不是运行结构

### 4.2 方案 B：`segment = 翻译分片`

做法：

- 先按章节读取正文
- 当章节长度低于阈值时，整章只保留 1 个 `segment`
- 当章节过长时，按稳定规则拆成多个 `segment`
- 切分优先参考自然段，但自然段只是边界依据，不是 `segment` 定义

优点：

- 语义和系统真实用途一致
- 能同时服务 translation、失败补跑、inspect、review、export
- 能避免“整章过长”与“逐自然段过碎”两个极端

缺点：

- `chaptering` 逻辑会变复杂
- 需要同步刷新测试基线和下游计数口径

### 4.3 方案 C：运行时动态分片

做法：

- 数据库只保留章级单元
- translation 时按当前模型上下文窗口临时切分

优点：

- 最贴近模型限制

缺点：

- 分片不稳定
- inspect / rerun / review / export 都会变复杂
- 当前仓库的运行记录模型会被削弱

### 4.4 结论

本轮采用：

**方案 B：`segment = 翻译分片`。**

原因很直接：

- 这和当前系统中 `segment` 的真实职责最一致
- 它能在不推翻现有 schema 的前提下解决“整章过长”的问题
- 它比“自然段即 segment”更稳，也比“运行时动态切分”更容易落地和观察

## 5. 语义定义

### 5.1 `chapter`

`chapter` 的语义保持不变：

- 表达逻辑章节边界
- 由源文档中的章节标题或章节切分规则产生
- 是导出展示和章节级 inspect 的主容器

### 5.2 `segment`

`segment` 的语义正式定义为：

**章节内翻译分片。**

它是下面四件事的统一边界：

- translation 执行边界
- 失败重跑边界
- inspect 单元边界
- review / export 的内部聚合边界

因此：

- `segment_index` 表示“本章第几个翻译分片”
- 不表示“第几个自然段”
- 不要求和文学段落一一对应

## 6. 分片规则

### 6.1 总体规则

每章正文先作为一个候选整体。

然后按下面规则处理：

1. 如果章节正文长度不超过 `target_chars`，则整章生成一个 `segment`
2. 如果超过 `target_chars`，开始按稳定边界向多个 `segment` 拆分
3. 任一 `segment` 不能超过 `hard_max_chars`
4. 切分优先保持语义完整，而不是追求平均长度

### 6.2 v1 阈值

v1 不引入 tokenizer 感知逻辑，直接使用字符数近似。

默认值：

- `target_chars = 2500`
- `hard_max_chars = 4000`

含义如下：

- `target_chars`
  - 期望单个分片尽量落在这个量级附近
- `hard_max_chars`
  - 单个分片的硬上限，不能超过

选择字符数而不是 token 的原因：

- 规则稳定
- 实现成本低
- 不依赖 provider/tokenizer
- 更适合先把分片语义和主流程收口

后续如果真的出现模型差异需求，再在此基础上扩展为 profile-aware 阈值。

### 6.3 一级边界：自然段

v1 的默认切分边界是自然段。

规则如下：

- 先把章节正文按空行归并成自然段块
- 尽量按自然段块向 `segment` 中累加
- 当继续累加会明显超过 `target_chars` 时，优先在当前自然段边界处截断

这里强调：

- 自然段是切分依据
- 不是 `segment` 的定义

### 6.4 二级边界：句级切分

如果某一个自然段本身就已经超过 `hard_max_chars`，则不能整段塞进单一分片。

此时退化为句级切分：

- 优先按 `。！？；` 等句末标点切
- 保持切分后每片尽量接近 `target_chars`
- 仍然不能超过 `hard_max_chars`

如果句级切分后仍然超上限，再允许做最小必要的硬截断，但这属于异常兜底路径，不作为常态。

### 6.5 合并短段

连续的短自然段允许合并到同一个分片。

目的：

- 避免“每个短段都变成单独请求”
- 避免对话或碎句段落过度离散
- 让 translation 看到足够上下文

v1 的原则是：

- 只要合并后仍不超过 `target_chars`
- 且不会突破 `hard_max_chars`
- 就允许把多个连续短段合并成一个 `segment`

### 6.6 不进入普通翻译分片的内容

下面这些内容不作为普通正文分片的一部分：

- 已被 chaptering 抽出的显式 synopsis
- 纯章节标题行
- 仅承担结构作用的空白分隔行

其中：

- synopsis 继续走现有 synopsis 逻辑
- 标题继续挂在 chapter 元数据上
- 正文分片只负责真正要进入 translation 的正文内容

## 7. 下游语义

### 7.1 translation

translation 继续按 `segment` 执行，但此时 `segment` 表示翻译分片，而不是整章。

这样做的直接效果：

- 过长章节会被拆成多个稳定请求
- `failed_only / missing_only / stale_only` 的粒度会更细
- 多 LLM workflow 的并发粒度也会更合理

translation prompt 不需要知道“这个分片原本由几个自然段构成”，只需要知道：

- 当前 chapter
- 当前 segment
- 当前 source_text
- 当前命中的 glossary

### 7.2 review

review 继续按 `segment` 检查。

这意味着：

- 更细粒度地定位缺译、空译和异常结果
- review run summary 里的来源快照也会变得更细

但在章节级 inspect 和导出结果里，仍然以 chapter 为上层容器展示。

### 7.3 export

export 时按：

- `chapter_index`
- `segment_index`

排序回拼。

用户看到的仍然是章节级输出，而不是“导出出 N 个分片”。

也就是说：

- 分片是内部执行结构
- 章节是最终消费结构

### 7.4 inspect

inspect 语义保持分层：

- `inspect.chapter / inspect.chapters`
  - 继续站在章节视角
- `inspect.segment`
  - 明确查看某个翻译分片
- `inspect.translation`
  - 继续围绕分片对应的正式译文版本展开

这套语义在“segment = 翻译分片”后反而会更一致。

## 8. 实现边界

### 8.1 schema

本轮不要求先改 schema。

原因：

- 现有 `ChapterSegment` 已经有 `segment_index`
- 现有 translation / review / export 都已经按 segment 主循环组织
- 当前主要缺的是 chaptering 产出多个 segment 的能力

### 8.2 chaptering

本轮的主改动点在 `ChapteringService`：

- 从“每章只创建一个 segment”
- 改为“每章根据分片规则创建 1..N 个 segments”

每个 `segment` 继续拥有：

- `segment_index`
- `source_text_path`
- `translation_status`
- `review_status`

其中 `source_text_path` 指向该翻译分片自己的正文文件。

### 8.3 配置策略

v1 先采用固定规则和固定阈值：

- 不做 per-profile 配置
- 不做 per-provider 配置
- 不做运行时动态 token 估算

如果后续真实联调证明有必要，再把阈值提升为配置项。

## 9. 风险与处理

### 9.1 过度碎片化

风险：

- 如果切得太碎，translation 会丢上下文

处理：

- 默认先看整章长度
- 短章不拆
- 连续短段允许合并
- 只有超过阈值才拆

### 9.2 大段落异常超长

风险：

- 某些源文里存在极长自然段

处理：

- 超过 `hard_max_chars` 时退化到句级切分
- 再不行才兜底硬截断

### 9.3 章节级计数口径变化

风险：

- 现有测试和摘要默认近似“一章一个 segment”

处理：

- 统一把 segment_count 解释为“翻译分片数”
- 相关测试基线同步刷新
- 文档和 inspect 返回口径同步更新

### 9.4 导出回拼顺序错误

风险：

- 多分片章节如果排序不稳，导出正文会乱序

处理：

- export 明确只按 `chapter_index + segment_index` 排序回拼
- 增加专项测试覆盖

## 10. 测试方案

本轮至少覆盖下面八类测试：

1. 短章节不会被拆分
2. 长章节会被拆成多个分片
3. 连续短自然段会被合并，而不是机械一段一片
4. 超长自然段会退化到句级切分
5. 每个 segment 的 `segment_index` 在章内稳定递增
6. translation 能对多分片章节正确生成多个正式版本
7. `failed_only / missing_only` 能在多分片场景下按分片粒度补跑
8. export 能按章节回拼出正确顺序的正文

验证顺序建议：

1. 先补 chaptering 相关单测
2. 再补 translation/review/export 联动单测
3. 最后跑全量 `pytest`

## 11. 完成标准

本轮完成后，需要满足下面这些条件：

1. `segment` 在代码、测试、文档中的语义统一为“翻译分片”
2. 短章节默认仍然只有 1 个 segment
3. 长章节会按稳定规则切成多个 segments
4. translation / review / export / inspect 都能正确消费多分片章节
5. 导出结果仍然保持章节级阅读体验，而不是泄露内部运行分片结构

如果以上五点都满足，就可以认为这轮“segment 语义收口”完成。
