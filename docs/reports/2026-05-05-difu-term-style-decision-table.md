# 《地府叫我小先生》术语与称谓风格决策表

- 项目：`project_id=31`
- 来源：`2026-05-05-difu-translation-sample-review.md`、`2026-05-05-difu-glossary-term-missing-analysis.md`、`inspect.glossary`
- 目标：把抽样复核发现的术语/称谓风险收成明确决策，避免 hard review 的 exact 规则牵着译文走，也避免人物称谓和民俗术语在全书漂移。

## 使用规则

- `强制术语`：进入 glossary，可在人工确认后锁定；review 可按 canonical target 检查。
- `软术语`：保留 glossary 作为提示，不做 exact target 强制；允许语境化自然译法。
- `注释优先`：不强迫译文解释，进入 annotation 抽样清单；导出时用章节注释补文化背景。
- `称谓组`：同一人物/身份的多个中文称呼必须共享 `term_group_key`，但英文可按语境使用 title、alias 或叙述性称谓。

## 决策表

| 类型 | 源项 | 当前/建议译法 | 决策 | 说明 |
| --- | --- | --- | --- | --- |
| 地名 | 北国十万大山 | the Hundred-Thousand Mountains of the North | 强制术语 | 第1章样本已稳定；全书地名应固定。 |
| 地名 | 北国 | the Northern Realm | 软术语 | 单独出现时可按上下文译为 northern lands / the North；不应强制所有 `北国` 都 exact 命中。 |
| 人物 | 华九难 | Hua Jiunan | 强制术语 | 主角名，必须固定。 |
| 称谓 | 小先生 | Young Sir | 称谓组 | 当前 glossary 为 `Young Sir`；标题语境可另行评估书名译法，但正文称谓先固定。 |
| 人物 | 陈大计 | Chen Daji | 强制术语 | 主配角名，必须固定。 |
| 人物 | 虎娃 | Huwa | 强制术语 | 昵称式姓名，沿用拼音。 |
| 人物 | 聋婆婆 | Granny Deaf | 称谓组 | 样本与 glossary 均偏向 `Granny Deaf`；`Deaf Granny` 作为历史变体应逐步收敛。 |
| 人物 | 李大爷 | Old Master Li | 称谓组 | 样本使用自然；保持 `Old Master Li`。 |
| 人物 | 麻衣姥姥 | Granny Maiyi | 称谓组 | 保留音译加亲属称谓，避免变成纯解释性 `Hemp-Robed Granny`。 |
| 职务 | 周所长 | Director Zhou | 称谓组 | 当前 glossary 为 `Director Zhou`；样本中 `Station Chief Zhou` 可读但需收敛。 |
| 职务 | 赵干部 | Cadre Zhao | 称谓组 | 第17章样本可接受；保留时代政治语气。 |
| 民俗体系 | 出马仙 | Chuma Immortals | 强制术语 | 作为东北民俗体系核心概念保留拼音；首次出现应配注释。 |
| 民俗体系 | 四梁八柱 | Four Beams and Eight Pillars | 强制术语 + 注释 | 术语固定，但含义需要注释解释。 |
| 民俗体系 | 清风堂/扫/看/串等堂口 | Qingfeng Hall / Sweeping Hall / Watching Hall / Linking Hall | 软术语 | 单字 `扫/看/串` 已证明误报严重；仅在明确堂口语境下使用。 |
| 鬼怪 | 厉鬼 | vengeful ghost | 软术语 | 普通概念词允许 ferocious ghost / vengeful spirit 等自然变体；不做 exact 强制。 |
| 鬼怪 | 脏东西 | filthy things | 软术语 | 可按语气译为 unclean things / filthy things / evil things；不做 exact 强制。 |
| 术法 | 邪术 | evil arts | 软术语 | 可按上下文译为 wicked art / evil art / dark technique。 |
| 物件 | 冤魂骨 | Vengeful Spirit Bone | 强制术语 | 第7章 rewrite 样本可接受；作为关键物件固定。 |
| 鬼怪/人物 | 雪尸 | Snow Corpse | 强制术语 | 关键实体，固定译名。 |
| 物件 | 九窍玉 | Nine-Orifice Jade | 强制术语 | 第70章样本稳定；固定。 |
| 物件 | 人皮灯笼 | Human-Skin Lantern | 强制术语 + 注释 | 恐怖民俗物件，固定译名并进入注释抽样。 |
| 道教文本 | 《抱朴子内篇》 | Inner Chapters of Baopuzi | 强制术语 + 注释 | 书名固定；首次出现建议注释。 |
| 口诀 | 九字真言 | Nine-Word Mantra | 强制术语 + 注释 | 固定译名；涉及误抄流变，注释优先。 |
| 成语/典故 | 法不传六耳 | The Dharma is not passed to six ears | 注释优先 | 直译会让英文读者困惑；正文可自然化，注释解释“秘传不可外泄”。 |
| 典故 | 风萧萧兮易水寒 | The wind whistles, the waters of Yi are cold | 注释优先 | 典故气氛重要，建议导出注释补荆轲语境。 |

## 后续执行建议

- 下一轮 glossary 人工维护时，优先锁定 `强制术语` 中的人名、地名、关键物件。
- `软术语` 不应触发 hard review 的 exact target 缺失；如需检查，只检查明显漏译或语义反向。
- `注释优先` 项进入 `2026-05-05-difu-annotation-sample-checklist.md`，用 annotation 层解释，不污染正文译文。
