# 灵境行者前 5 万字完整测试报告

## 结论

本次按用户指定配置完成了《灵境行者》前 5 万字范围的真实链路测试，范围为 `chapter_index=1..14`，累计 50,639 个中文计数字符、29 个翻译分片。

最终状态：

- provider/profile 健康检查通过：主 LLM `gpt_5_5_aicodelink` 可用，副 LLM `deepseek_v4_pro` 可用。
- `chaptering / glossary / translation / review / export` 全链路完成。
- 前 5 万字范围 29/29 分片已翻译，29/29 分片已审校通过。
- 最新导出已生成 2 个产物：`manifest.json` 与 `export.md`。
- 最新完整回归通过：`358 passed in 340.70s (0:05:40)`。

## 测试范围

- 日期：2026-04-28
- 工具目录：`D:\Project\NovelT\tools\local_translation_workbench`
- 小说：`D:\Project\NovelT\tools\local_translation_workbench\novels\灵境行者\灵境行者.txt`
- 业务项目 ID：`17`
- 项目 key：`prj_b88b60f569da`
- 源语言：中文
- 目标语言：英文
- 主 LLM：`gpt_5_5_aicodelink`，provider=`aicodelink`，model=`gpt-5.5`
- 副 LLM：`deepseek_v4_pro`，provider=`deepseek`，model=`deepseek-v4-pro`
- 路由 preset：`lingjing_gpt55_aicodelink_deepseek_20260428`
- glossary workflow：`glossary_multi_llm_v1`
- translation workflow：`translation_multi_llm_v1`

## 前 5 万字章节范围

范围按源文件顺序截取，不按自然章号重新排序。源文件首章为 `第100章 上门`，且 `第10章` 出现在 `第109章` 之后。

| chapter_index | 字数 | 累计字数 | 标题 |
| --- | ---: | ---: | --- |
| 1 | 2,895 | 2,895 | 第100章 上门 |
| 2 | 3,757 | 6,652 | 第101章 元始天尊意外身亡 |
| 3 | 3,213 | 9,865 | 第102章 联系邪恶职业 |
| 4 | 3,547 | 13,412 | 第103章 弹指杀敌 |
| 5 | 2,862 | 16,274 | 第104章 兵佣 |
| 6 | 3,463 | 19,737 | 第105章 交易 |
| 7 | 3,176 | 22,913 | 第106章 松海第三小学 |
| 8 | 3,429 | 26,342 | 第107章 寻宝本能 |
| 9 | 4,120 | 30,462 | 第108章 大眼瞪小眼 |
| 10 | 3,264 | 33,726 | 第109章 绝境？ |
| 11 | 4,405 | 38,131 | 第10章 S级试炼灵境 |
| 12 | 3,383 | 41,514 | 第110章 行动失败 |
| 13 | 4,334 | 45,848 | 第111章 午夜的音频 |
| 14 | 4,791 | 50,639 | 第112章 坑爹道具 |

## 阶段结果

### chaptering

- 创建项目：`project_id=17`，`project_key=prj_b88b60f569da`
- 切章结果：242 章、541 个分片
- 前 5 万字范围：14 章、29 个分片
- 源文件未提供显式简介，后续 translation 阶段触发自动 synopsis 生成。

### glossary

运行范围为 `chapter_index=1..14`，每 2 章一个批次。

| 范围 | 耗时秒 | 候选数 |
| --- | ---: | ---: |
| 1-2 | 423.266 | 55 |
| 3-4 | 452.532 | 41 |
| 5-6 | 323.235 | 31 |
| 7-8 | 366.632 | 31 |
| 9-10 | 281.244 | 40 |
| 11-12 | 619.330 | 90 |
| 13-14 | 458.908 | 58 |

汇总：

- glossary 候选合计：346
- 当前项目正式 glossary entries：134
- 未触发 provider fallback。

### translation

首次 translation 触发 synopsis 自动生成时发现超时问题，修复后从 translation 阶段恢复运行。

| 范围 | 耗时秒 | 翻译分片 |
| --- | ---: | ---: |
| 1-2 | 225.043 | 4 |
| 3-4 | 279.833 | 4 |
| 5-6 | 199.902 | 4 |
| 7-8 | 207.553 | 4 |
| 9-10 | 206.483 | 4 |
| 11-12 | 179.389 | 4 |
| 13-14 | 149.536 | 5 |

汇总：

- 29/29 分片已翻译。
- source synopsis：`ready`，`origin=generated`，长度 1,004 characters。
- target synopsis：`ready`，`origin=translated`，长度 773 words。

### review

初次 review 后，`chapter_index=3, segment_index=1` 被标记为 `needs_revision`。原因是审校模型识别到“一个小目标”译为 `A small target` 会丢失“一亿元”的金额梗义。

已补跑 `chapter_index=3..4`，将 `max_rewrite_rounds` 提高到 4，最终该分片通过审校，active version 从 `143` 更新为 `163`，导出译文包含：

```text
A small target—one hundred million. What do you think?
```

最终审校汇总：

- 29/29 分片 `reviewed`
- 0 个 `needs_revision`
- 0 个 `pending_review`

关键 review 运行记录：

| 范围 | 耗时秒 | issue_count | 通过分片 | 需修订分片 | 重写分片 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1-2 | 124.721 | 5 | 4 | 0 | 3 |
| 3-4 初次 | 379.912 | 9 | 3 | 1 | 3 |
| 3-4 补跑 | 111.466 | 4 | 4 | 0 | 2 |
| 5-6 | 131.287 | 11 | 4 | 0 | 3 |
| 7-8 | 94.345 | 4 | 4 | 0 | 2 |
| 9-10 | 189.511 | 14 | 4 | 0 | 4 |
| 11-12 | 210.957 | 7 | 4 | 0 | 4 |
| 13-14 | 245.675 | 12 | 5 | 0 | 4 |

### export

补跑审校后重新导出，避免旧导出引用已被替换的 `needs_revision` 版本。

最新导出：

- export run id：`9`
- artifact_count：2
- manifest：`D:\Project\NovelT\tools\local_translation_workbench\data\projects\prj_b88b60f569da\exports\run_ca8e02eefb53\manifest.json`
- markdown：`D:\Project\NovelT\tools\local_translation_workbench\data\projects\prj_b88b60f569da\exports\run_ca8e02eefb53\export.md`
- manifest 中 translation_source 覆盖 29 个分片、29 个 active version。
- `export.md` 已确认包含修正后的 `A small target—one hundred million`。

## 发现并修复的问题

### 1. 粘连章节标题无法切分

现象：源文件里大量章节标题形如：

```text
(本章完)第101章 元始天尊意外身亡
```

旧实现只识别行首 `第N章`，因此会把多章正文合并到前一章。

处理：

- 新增单测 `test_chaptering_service_splits_inline_end_marker_and_next_heading`。
- 在 `ChapteringService` 中补充“本章完后紧跟章节标题”的边界标准化。
- 验证：新增用例红绿通过，`tests/test_chaptering_stage.py` 通过 16 个测试。

### 2. 无显式简介时自动 synopsis 输入过大

现象：源文件无显式简介，translation 前会自动生成 source synopsis。旧实现把整本 300 万字级正文直接塞给模型，导致 provider 调用 60 秒超时，translation 还未进入正文分片就失败。

处理：

- 新增单测 `test_generated_source_synopsis_uses_bounded_source_excerpt`。
- 自动生成 source synopsis 时改为只使用正文前 12,000 字符样本。
- prompt 文案从“整部作品正文”改为“作品正文样本”，避免误导。
- 验证：新增用例红绿通过，`tests/test_synopsis_flow.py` 通过 9 个测试。

### 3. 审校发现真实译文质量问题

现象：第 3 章第 1 分片中，“一个小目标”初译为 `A small target`。审校模型判断该译法未表达“一亿元”的梗义，保留为 `needs_revision`。

处理：

- 补跑第 3-4 章 hybrid review。
- 将 `max_rewrite_rounds` 从 2 提高到 4。
- 最终 active version 更新为 `163`，译文修为 `A small target—one hundred million`。
- 验证：分片状态变为 `reviewed`，最新 export 使用 version `163`。

### 4. 测试过程中的操作注意

- PowerShell 调用原生命令传 JSON 时会剥离双引号，`profile.route_set` 的 `bindings_json` 需要先压缩 JSON，再将 `"` 转义为 `\"`。
- 从 `temp/` 启动临时 runner 时，需显式把工具根目录加入 `sys.path`，否则会出现 `ModuleNotFoundError: No module named 'app'`。

## 验证记录

已执行并通过：

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_chaptering_stage.py -q
# 16 passed
```

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_synopsis_flow.py -q
# 9 passed
```

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests -q
# 358 passed in 340.70s (0:05:40)
```

## 产物与日志

- 最新测试报告：`D:\Project\NovelT\tools\local_translation_workbench\docs\reports\2026-04-28-lingjing-5w-full-test.md`
- 最新导出 manifest：`D:\Project\NovelT\tools\local_translation_workbench\data\projects\prj_b88b60f569da\exports\run_ca8e02eefb53\manifest.json`
- 最新导出 markdown：`D:\Project\NovelT\tools\local_translation_workbench\data\projects\prj_b88b60f569da\exports\run_ca8e02eefb53\export.md`
- glossary 初始真实运行日志：`D:\Project\NovelT\tools\local_translation_workbench\temp\lingjing-5w-20260428\real-run.jsonl`
- translation/review/export 恢复运行日志：`D:\Project\NovelT\tools\local_translation_workbench\temp\lingjing-5w-20260428\real-run-v2.jsonl`
- review 补跑日志：`D:\Project\NovelT\tools\local_translation_workbench\temp\lingjing-5w-20260428\review-v3-03-04.log`
- export 补跑日志：`D:\Project\NovelT\tools\local_translation_workbench\temp\lingjing-5w-20260428\export-v3-01-14.log`
- 最终 pytest 日志：`D:\Project\NovelT\tools\local_translation_workbench\temp\lingjing-5w-20260428\pytest-final.log`

## 剩余风险

- 本次“前 5 万字”按源文件顺序截取。源文件章节顺序本身存在 `第10章` 插入到 `第109章` 之后的情况，本次没有擅自重排。
- 自动生成 synopsis 现在取前 12,000 字符样本，可以避免超时，但它不是整书全量摘要；如果后续需要长篇全局简介，建议单独做分块摘要合并。
- 本次质量判断以工具内 hard check、LLM hybrid review 与抽样确认导出为主，没有做人工逐句文学审校。
