# 《江湖邪医》前 5 万字真实联调报告

## 结论

- 本次真实联调已完成 `project.create -> chaptering -> glossary -> translation -> review -> export` 全链路。
- 覆盖范围为第 1 章到第 18 章，按去空白字符累计 50,317 字，满足“前 5 万字章节”要求。
- 项目 ID：`16`，项目 key：`prj_e98ccfc9fe91`。
- 主 LLM 使用 `gpt-5.5`，实际可用 profile 为 `gpt_5_5_kxaug`。
- 副 LLM 使用 `deepseek-v4-pro`，profile 为 `deepseek_v4_pro`；小请求健康检查正常，术语抽取分支正常，但翻译草稿大请求分支持续返回无可用通道。
- 最终 18 章、36 个 segment 均已翻译、审校并导出。
- 计数规则已明确：中日韩文本按去空白字符数统计；英文等非中日韩译文按单词数统计。
- 代码层已补一处 provider 可重试错误识别，并新增回归测试；完整 pytest 已通过。

## 测试配置

- 源文件：`novels/江湖邪医/江湖邪医.txt`
- 目标语言：英文
- Python 虚拟环境：`D:\Project\NovelT\.venv\Scripts\python.exe`
- 业务数据库：使用当前环境变量 `LTW_DATABASE_URL`
- 测试数据库：已确认存在 `LTW_TEST_DATABASE_URL`
- 主模型 profile：`gpt_5_5_kxaug`
- 主模型名称：`gpt-5.5`
- 副模型 profile：`deepseek_v4_pro`
- 副模型名称：`deepseek-v4-pro`
- 术语 workflow：`glossary_gpt55_kxaug_deepseek_v4_20260428`
- 翻译 workflow：`translation_gpt55_kxaug_deepseek_v4_20260428`
- 凭证处理：DeepSeek key 仅注入运行环境，报告和代码均不记录明文密钥。

## 覆盖范围

按章节完整覆盖到第 18 章：

| 章节 | 标题 | 本章去空白字符数 | 累计 |
| --- | --- | ---: | ---: |
| 1 | 第1章　邪医，欧少邪 | 2,676 | 2,676 |
| 2 | 第2章　似曾相识 | 2,750 | 5,426 |
| 3 | 第3章　救人 | 2,767 | 8,193 |
| 4 | 第4章　逃出碧泉殿 | 2,852 | 11,045 |
| 5 | 第5章　寒疾 | 2,782 | 13,827 |
| 6 | 第6章　凰影金针 | 2,768 | 16,595 |
| 7 | 第7章　无耻 | 2,843 | 19,438 |
| 8 | 第8章　天元斩魔剑术 | 2,910 | 22,348 |
| 9 | 第9章　盟主府 | 2,638 | 24,986 |
| 10 | 第10章　治寒疾 | 2,892 | 27,878 |
| 11 | 第11章　正与魔 | 2,807 | 30,685 |
| 12 | 第12章　何谓江湖 | 2,807 | 33,492 |
| 13 | 第13章　幕后黑手 | 2,781 | 36,273 |
| 14 | 第14章　小小天机阁 | 2,869 | 39,142 |
| 15 | 第15章　杀无赦 | 2,809 | 41,951 |
| 16 | 第16章　山寨 | 2,736 | 44,687 |
| 17 | 第17章　战穷王侠 | 2,916 | 47,603 |
| 18 | 第18章　盟主府遭袭 | 2,714 | 50,317 |

## 阶段结果

### 项目与分章

- `project.create` 成功。
- `chaptering` 成功：全书识别 73 章、145 个 segment。
- 简介抽取成功：原文简介 40 个非空白字符，英文译文简介 39 个单词。

### 术语阶段

首次尝试一次性跑第 1-18 章时，GPT 抽取分支长时间未返回；停止该 run 后改为 3 章一组执行，全部成功。

| 范围 | candidate_count | 状态 |
| --- | ---: | --- |
| 1-3 | 36 | completed |
| 4-6 | 32 | completed |
| 7-9 | 45 | completed |
| 10-12 | 40 | completed |
| 13-15 | 34 | completed |
| 16-18 | 35 | completed |

- 术语候选合计：222
- 最终 active 术语条目：110
- DeepSeek 术语抽取分支：6/6 成功
- 术语阶段测量 token 合计：173,463

### 翻译阶段

第 1-18 章分 6 批翻译，每批 3 章、6 个 segment。stage 层全部成功，累计生成 36 个 active translation version。

| 范围 | translated_segments | active_version_count | workflow 状态 |
| --- | ---: | ---: | --- |
| 1-3 | 6 | 6 | insufficient_evidence |
| 4-6 | 6 | 6 | insufficient_evidence |
| 7-9 | 6 | 6 | insufficient_evidence |
| 10-12 | 6 | 6 | insufficient_evidence |
| 13-15 | 6 | 6 | insufficient_evidence |
| 16-18 | 6 | 6 | insufficient_evidence |

说明：每个翻译 workflow 中，GPT 主草稿、GPT review、GPT rewrite、finalize 均成功；DeepSeek `generate_secondary` 分支均失败，因此 workflow 级别标记为 `insufficient_evidence`，但 stage 层在已有 GPT 证据下完成并产出正式译文。

- 翻译 stage 测量 token 合计：398,250
- 翻译 stage 测量调用数：108
- DeepSeek 翻译分支失败错误核心信息：`No available channel for model deepseek-v4-pro under group codex-pro (distributor)`

### 审校阶段

审校采用 `hybrid`，最大重写轮数 `2`。6 批全部完成，36/36 个 segment 均通过审校，无需人工返修。

| 范围 | issue_count | passed_segments | rewrite_segments | 状态 |
| --- | ---: | ---: | ---: | --- |
| 1-3 | 7 | 6 | 3 | completed |
| 4-6 | 15 | 6 | 4 | completed |
| 7-9 | 13 | 6 | 3 | completed |
| 10-12 | 13 | 6 | 5 | completed |
| 13-15 | 20 | 6 | 5 | completed |
| 16-18 | 19 | 6 | 4 | completed |

- 审校问题合计：87
- 自动重写 segment 合计：24
- `needs_revision_segment_count`：0
- 审校 stage 测量 token 合计：370,066
- 审校 stage 测量调用数：84

### 导出阶段

- `export` 成功。
- export run ID：`7`
- 导出章节数：18
- 导出 segment 来源：36 个 segment、36 个 version。
- 导出产物数：2
- manifest：`data/projects/prj_e98ccfc9fe91/exports/run_9d1eef916ecd/manifest.json`
- Markdown：`data/projects/prj_e98ccfc9fe91/exports/run_9d1eef916ecd/export.md`
- `export.md` 文件大小：382,776 字节，4,469 行。
- manifest 中导出的原文正文：50,187 个非空白字符。
- manifest 中导出的英文译文正文：36,182 个单词。

## 发现的问题与处理

### 1. PowerShell 传递 workflow JSON 时剥离双引号

- 现象：`workflow.create` 返回 `definition_json 不是有效的 JSON`。
- 判断：Windows PowerShell 将复杂 JSON 作为原生命令参数传递时，实际 argv 中 JSON 双引号被剥离。
- 处理：使用 `temp/ltw_test_setup.py` 直接调用 action router 创建 workflow，绕过 CLI 参数转义问题。
- 后续建议：为 `workflow.create` 增加 `definition_json_file` 或 stdin 输入方式。

### 2. AICodeLink 上 `gpt-5.5` 不可用

- 现象：既有 `gpt_5_5_aicodelink` 健康检查失败。
- 错误：provider 返回 `model_not_found`，提示当前分组无 `gpt-5.5` 可用通道。
- 处理：新增并验证 `gpt_5_5_kxaug`，本次主 LLM 仍使用 `gpt-5.5`。

### 3. 大范围术语抽取可观测性不足

- 现象：一次性跑第 1-18 章 glossary 时，DeepSeek 分支已完成，但 GPT extractor 长时间未返回。
- 处理：停止该 run，标记为失败并释放 lease，改为每 3 章一批后全部成功。
- 风险：当前并行 tolerant group 在 quorum 达标后仍会等待慢分支，遇到慢请求时整体耗时和可观测性不够友好。
- 后续建议：workflow group 达到 quorum 后支持提前推进，或至少输出分支级心跳。

### 4. DeepSeek 翻译草稿大请求持续失败

- 现象：DeepSeek 健康检查通过，术语抽取分支也通过，但翻译 `generate_secondary` 分支 6/6 失败。
- 错误：`No available channel for model deepseek-v4-pro under group codex-pro (distributor)`。
- 判断：该 provider 对小请求可用，但对本批翻译草稿请求在网关层持续无法分配通道。
- 已修复：将 `no available channel` 纳入 OpenAI-compatible provider 的可重试错误识别。
- 新增测试：`test_openai_compatible_provider_retries_no_available_channel`。
- 结果：重试逻辑可覆盖瞬时无通道，但本次真实翻译请求中 DeepSeek 连续失败，重试后仍无法产出副草稿。

### 5. 临时清理脚本中的中文诊断入库乱码

- 现象：一次 inline PowerShell -> Python 清理诊断时，中文说明进入数据库后显示为问号。
- 影响：仅影响一次被中止 stage run 的诊断说明，不影响正文、术语、译文和导出产物。
- 后续建议：涉及中文 payload 的临时脚本统一使用 UTF-8 文件执行，避免经 PowerShell 管道传递。

## 代码变更

- `app/providers/openai_compatible.py`
  - 将 `no available channel` 纳入 provider 错误重试判断。
- `tests/test_openai_compatible_provider.py`
  - 新增 `No available channel` 先失败、第二次成功的重试回归测试。
- `app/text_counting.py`
  - 新增统一文本计数规则：中日韩按去空白字符数，非中日韩按单词数。
- synopsis summary 相关服务
  - 将 `length` 从简单 `len()` 调整为统一计数规则，并补充 `length_unit`。

## 验证记录

- DeepSeek profile 健康检查：通过，`deepseek-v4-pro`，延迟约 1.8 秒。
- GPT profile 健康检查：通过，`gpt-5.5`，延迟约 1.8 秒。
- provider 定向测试：此前已通过 `tests/test_openai_compatible_provider.py`，4 passed。
- 文本计数定向测试：`tests/test_text_counting.py`，4 passed。
- 完整 pytest：`346 passed in 511.93s (0:08:31)`。
- `git diff --check`：通过，仅提示既有 Windows 行尾转换 warning，无空白错误。

## 总体评价

本次测试完成了用户要求的前 5 万字章节全流程输出。系统在主 GPT 通道可用时能够完成术语、翻译、审校、重写和导出；审校阶段发现并自动修正了大量术语一致性和译文质量问题。

主要短板集中在 provider 层和长任务可观测性：DeepSeek 小请求可用但大翻译请求不稳定，workflow 对慢分支的等待策略也会放大该类问题。短期可继续用 GPT 主线完成生产输出；中期应优化副模型失败降级、quorum 提前推进和 CLI JSON 输入方式。
