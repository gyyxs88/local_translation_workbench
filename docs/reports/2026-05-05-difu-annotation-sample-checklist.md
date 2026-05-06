# 《地府叫我小先生》文化典故与民俗语注释层抽样清单

- 项目：`project_id=31`
- 范围：前 10 万字所在章节，当前抽样覆盖第 1、6、7、17、36、51、64、69、70 章
- 目标：把不适合硬塞进译文正文的文化信息放入 annotation 层，保持英文正文流畅，同时让读者能理解民俗、典故和术法背景。

## 抽样清单

| 优先级 | 章 | source_anchor | 建议 annotation_type | 说明 | 建议处理 |
| --- | --- | --- | --- | --- | --- |
| P0 | 1 | 南茅北马 | folklore | 民间法脉南北对举，直译难解释。 | 首次出现加注释。 |
| P0 | 1 | 出马弟子 / 出马仙 | folklore | 东北出马仙体系核心概念，后文高频。 | 建立 locked annotation，解释 spirit-medium/chuma 背景。 |
| P0 | 1 | 四梁八柱 | folklore | 体系内组织结构，英文术语本身不能说明功能。 | 注释解释四梁、八柱和仙家分工。 |
| P0 | 64 | 法不传六耳 | idiom | 字面译法会误导，实际含义是秘传不可外泄。 | 注释解释“第三双耳朵/外人不得听”。 |
| P0 | 51 | 九字真言 / 临兵斗者，皆阵列前行 | religious_text | 道教口诀和日本误抄流变是信息点。 | 注释说明原句、误抄版本和常见误解。 |
| P1 | 51 | 《抱朴子内篇》 | text_reference | 道教经典，译文保留书名但读者未必知道来源。 | 首次出现加简短说明。 |
| P1 | 69 | 风萧萧兮易水寒 | literary_allusion | 荆轲刺秦典故，用来渲染悲壮。 | 注释解释典故来源和语气功能。 |
| P1 | 36 | 人皮灯笼 | folklore_object | 恐怖民俗物件，可能涉及地方传说/禁忌。 | 若译文未解释，导出章节注释。 |
| P1 | 7 | 冤魂骨 | folklore_object | 小说设定物件，但承接黄巢、厉鬼、永不超生等文化恐怖语义。 | 注释解释为本书设定，不强行当真实民俗。 |
| P1 | 7 | 黄巢 / 刘伯温 / 首阳碑 | historical_allusion | 历史人物与民间传说混用，英文读者缺上下文。 | 若同段导出，至少抽一个合并注释。 |
| P1 | 70 | 九窍玉 | burial_custom | 与人体九窍、尸玉、厌胜/丧葬想象相关。 | 注释说明“封九窍”的文化背景，避免正文过度解释。 |
| P2 | 55 | 紫河车 | medical_folklore | 胎盘药名/民俗禁忌，已有译文 `zi-he-che—her placenta`。 | 若正文已解释，可低优先级；保持候选。 |
| P2 | 48 | 千里冰封、万里雪飘 | literary_echo | 毛诗语感，若译文只是自然描写会损失互文。 | 面向普通读者可不注；面向文化版可注。 |
| P2 | 70 | 黑云压城 | idiom | 面相语境中借用成语，正文自然化即可。 | 仅在后续样本发现误解时注释。 |

## 执行方式

推荐先用抽样章节跑候选抽取，再由 agent/人工筛选：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run.ps1 `
  -Action annotation.extract `
  -ProjectId 31 `
  -ScopeType chapter_list `
  -ScopeChapters "1,7,36,51,64,69,70"
```

筛选原则：

- `P0` 候选优先 approve，并在解释稳定后 lock。
- 对同一概念只保留一个 `canonical_key`，例如 `folklore:出马仙`、`idiom:法不传六耳`。
- 已经在正文自然解释清楚的项目不强制导出注释，避免读者被过度打断。
- 注释不改 `SegmentTranslationVersion.translated_text`，不替代 glossary 译名约束；它只服务导出阅读辅助。
