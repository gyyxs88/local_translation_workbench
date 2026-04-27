# Glossary Extraction Quality Contract Design

## 目标

让术语提取从“模型吐出若干候选”升级为有明确契约的章节级流程：

- 提取时带入当前章节命中的已有术语，保证译名和关系组一致。
- 允许章节无新增术语，但必须显式返回 `no_new_terms`，不能用空值、空字符串、`null` 或无语义的空数组表达。
- 用硬质检常驻兜底，LLM 质检只在风险信号出现时触发，最多 1 轮定向补提取。

这次设计只约束 glossary extraction 链路，不改变 translation/review/export 的主流程。

## 核心决策

### 1. 已有术语只注入当前章节命中项

提取前本地扫描当前章节标题和正文，匹配当前有效术语表：

```json
{
  "matched_existing_terms": [
    {
      "source_term": "林溪",
      "target_term": "Lin Xi",
      "category": "character",
      "term_group_key": "char_linxi",
      "relation_role": "canonical"
    }
  ]
}
```

不把全项目术语表全部塞进 prompt。这样可以控制 token，并避免模型围绕无关术语发挥。

Extractor prompt 必须明确：

- 已有术语的译名和关系组必须沿用。
- 完全相同的已有 `source_term` 不应作为新增术语重复输出。
- 如果章节中出现已有实体的新别名、称号、变体，可以作为新增术语输出，并绑定已有 `term_group_key`。
- 如果发现模型想改已有术语译名，不允许直接修改，后续记录为一致性风险。

### 2. 空结果必须显式表达

新的 extractor 标准输出是对象，不再接受裸数组作为规范输出：

```json
{
  "extraction_status": "terms_found",
  "terms": [
    {
      "source_term": "时羽",
      "translated_term": "Shi Yu",
      "category": "character",
      "note": null,
      "gender": "female",
      "age_group": null,
      "term_group_key": "char_shiyu",
      "relation_role": "canonical"
    }
  ],
  "reason": "发现新增主要人物。"
}
```

无新增术语时必须返回：

```json
{
  "extraction_status": "no_new_terms",
  "terms": [],
  "reason": "本章只出现已知人物和普通叙事，没有新增专名或固定称谓。"
}
```

以下都不是合法的“无新增术语”：

- 空字符串
- `null`
- `[]`
- `{}`
- `{"terms":[]}` 但没有 `extraction_status`

这些输出会进入 JSON 修复或格式错误处理；不能静默当成正常空结果。

### 3. 空结果分三类状态

章节级提取结果需要进入 workflow step output payload：

- `terms_found`：有新增候选，进入后续 normalize/review/finalize。
- `no_new_terms`：模型明确判断无新增术语，不创建 draft candidate，但记录章节结果。
- `suspicious_empty`：模型声称无新增术语，但硬质检发现风险，需要 LLM 质检或定向补提取。
- `skipped`：模型调用失败、JSON 修复失败、格式仍不合法、或补提取仍失败。

其中 `no_new_terms` 是成功状态，不等于失败，也不应造成 stage failed。

## 组件设计

### GlossaryExistingTermContextService

职责：

- 读取当前有效 glossary entries。
- 对章节标题和正文做本地匹配。
- 输出 `matched_existing_terms`，只保留当前章节真实命中的条目。

它只负责上下文，不创建候选，也不调用 LLM。

### GlossaryExtractionPromptService 扩展

在现有 `GlossaryPromptService.build_extraction_prompt` 上扩展参数：

- `matched_existing_terms`
- `risk_signals`

prompt 需要明确输出 envelope：

- `extraction_status`
- `terms`
- `reason`

解析时产出一个结构化对象，而不是只返回 `list[GlossaryExtraction]`。

### GlossaryExtractionQualityService

硬质检常驻，规则包括：

- `extraction_status` 必须是 `terms_found` 或 `no_new_terms`。
- `terms_found` 时 `terms` 可以非空；如果为空，转为格式风险。
- `no_new_terms` 时 `terms` 必须为空。
- 新候选 `source_term` 必须出现在章节标题或正文中。
- 新候选与 `matched_existing_terms.source_term` 完全相同则过滤为重复，不创建 draft。
- 新候选如果像同一实体别名但没有绑定已有 `term_group_key`，标记 `relation_risk`。
- `gender / age_group` 继续执行现有收口，不允许根据敬称乱猜。
- 结构壳和泛词继续过滤。

风险信号包括：

- 章节较长但 `no_new_terms`。
- 章节出现多个疑似专名形态但 `no_new_terms`。
- JSON 发生过修复。
- 候选数量异常多。
- 与已有术语译名或关系组冲突。

### 风险触发型 LLM 质检

LLM 质检只在硬质检发现风险时触发，不默认每章运行。

LLM 质检输出示例：

```json
{
  "passed": false,
  "issues": [
    {
      "issue_type": "suspicious_empty",
      "severity": "medium",
      "message": "章节中出现疑似新人物“时羽”，但提取结果为 no_new_terms。",
      "source_evidence": "时羽同学的眼睛又大又水灵",
      "suggested_action": "targeted_reextract"
    }
  ]
}
```

只允许 1 轮定向补提取。补提取仍失败或仍可疑时，章节状态为 `skipped` 或 `suspicious_empty`，不继续无限重试。

## 数据流

1. 解析章节标题和正文。
2. 本地匹配已有术语，生成 `matched_existing_terms`。
3. 本地生成轻量 `risk_signals`，例如章节长度、疑似专名数量。
4. 调用 extractor，要求返回 envelope。
5. 解析 JSON；如果解析失败，先执行现有 JSON repair。
6. 硬质检输出章节级状态和问题。
7. 正常 `terms_found` 创建 draft candidates。
8. 正常 `no_new_terms` 不创建候选，但写入 step payload。
9. 风险状态触发 LLM 质检，必要时做 1 轮定向补提取。
10. step output payload 汇总：
    - `chapter_results`
    - `draft_candidate_count`
    - `no_new_terms_count`
    - `suspicious_empty_count`
    - `skipped_chapter_count`
    - `quality_issues`
    - `token_usage`

## 错误处理

- Provider 调用失败：章节记为 `skipped`，记录 code/message，不让整批章节直接失败。
- JSON 无法解析：先 repair；repair 后仍失败则 `skipped`。
- JSON 合法但缺少 `extraction_status`：格式错误；不把 `{"terms":[]}` 当成正常空结果。
- `no_new_terms` 但带了非空 `terms`：格式错误或修正为 `terms_found` 需经质检确认，不能静默吞掉。
- 已有术语重复输出：过滤，不创建 draft candidate，同时计入 `duplicate_existing_count`。

## 测试计划

新增或调整测试：

- 提取 prompt 包含当前章节命中的已有术语，不包含未命中的全局术语。
- 已有术语完全重复输出时不会创建 draft candidate。
- 新别名输出时继承已有 `term_group_key`。
- `{"extraction_status":"no_new_terms","terms":[]}` 被视为成功且不创建候选。
- `[]`、`null`、`{"terms":[]}` 缺少 status 时不视为正常空结果。
- 长章节或疑似专名章节返回 `no_new_terms` 时标记 `suspicious_empty`。
- 风险触发时最多 1 轮定向补提取。
- workflow step payload 暴露 `chapter_results / no_new_terms_count / suspicious_empty_count / quality_issues`。

## 非目标

- 不在本次引入全项目术语表大上下文注入。
- 不让 LLM 质检默认每章都跑。
- 不在 extraction 阶段直接修改已有正式术语。
- 不让 glossary 阶段因为单章无新增术语失败。

## 自检

- 无占位符或未定字段。
- `no_new_terms` 被明确为成功状态，不是空值。
- 设计保持单一焦点：只改 glossary extraction 的上下文、一致性和质量契约。
- 风险 LLM 只按条件触发，避免重新膨胀 glossary 链路。
