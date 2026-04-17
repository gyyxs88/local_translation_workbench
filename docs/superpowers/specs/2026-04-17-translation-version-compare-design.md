# Translation Inspect Version Compare 设计

## 1. 背景

当前 `inspect.translation` 已经具备两类能力：

- 返回整项目的 `translations` 与历史 `versions`
- 对每个 segment 当前 `active version` 返回 provenance

这解决了“当前结果从哪来”的第一层问题，但还缺少 `P1.3` 第二刀最核心的一类观察面：

- 当前 active version 和某个历史正式版本到底差了什么
- 这次 rerun / reroute / glossary 变化后，文本有没有变
- 模型、快照、状态这些关键元数据有没有一起变化

现在如果想回答这些问题，只能人工从 `versions[]` 里翻两条记录自己比，既慢也容易漏看。

路线图里 `P1.3 历史版本与可追踪性增强` 的下一刀，目标不是一次性做任意双边 compare 或完整时间线，而是先把最常见的排查动作补齐：

- 以当前 active version 为基准
- 对比一条显式指定的历史正式版本
- 直接返回结构化变化摘要

## 2. 本轮目标

本轮目标只有四个：

1. 让 `inspect.translation` 支持“当前 active version vs 指定历史正式版本”的 compare
2. compare 模式只针对单个 segment，避免跨段歧义
3. 先返回“文本前后 + 元数据变化摘要”，不做细粒度 diff
4. 保持普通 `inspect.translation` 项目级查看能力不变，不新增新的 inspect action

## 3. 非目标

本轮明确不做下面这些事情：

- 不支持任意两个 version 自由 compare
- 不新增 `inspect.translation_compare`
- 不做逐词、逐句或行级文本 diff
- 不做 provenance diff
- 不做 chapter 级或 project 级聚合 compare
- 不扩 `inspect.segment`、`inspect.chapter`、`inspect.chapters`
- 不修改任何 translation 版本表结构

## 4. 方案选择

本轮评估三种方向：

### 4.1 方案 A：整项目返回里混入 compare 结果

做法：

- 仍只传 `project_id`
- 额外传 `compare_version_id`
- 让命中的那一条 `translations[*]` 带 compare，其余段落照常返回

优点：

- 表面上改动最小

缺点：

- `compare_version_id` 天然只对应一个 segment
- 整项目返回里只有一条记录带 compare，语义很别扭
- 调用方还得自己定位到底哪一行才是 compare 目标

### 4.2 方案 B：在 `inspect.translation` 上增加单段 compare 模式

做法：

- `inspect.translation` 保持原 action 不变
- 增加单段定位参数
- compare 只允许在单段模式下启用
- compare 目标用 `compare_version_id` 显式指定

优点：

- 语义直接
- 不需要新 action
- 最贴合当前人工排查场景

缺点：

- 需要给 `inspect.translation` 增加一套可选参数约束

### 4.3 方案 C：新增独立 compare action

做法：

- 单独新增 `inspect.translation_compare`
- 把 compare 逻辑全部挪到新 action

优点：

- 接口很纯

缺点：

- 动作面会再扩一条
- 当前这一刀的收益不值得引入新 action

### 4.4 结论

本轮采用：

**方案 B：在现有 `inspect.translation` 上增加单段 compare 模式。**

原因很直接：

- 当前最常见的问题是“这条当前译文和某个旧版到底差了什么”
- compare 目标天然是单段
- 复用现有 `inspect.translation`，比新开 action 更轻也更顺

## 5. 查询模式与参数约束

### 5.1 普通模式

只传：

- `project_id`

保持现有行为：

- 返回整项目 `translations`
- 返回整项目 `versions`
- 不返回 `compare`

### 5.2 单段模式

在 `project_id` 之外，允许任选一套单段定位方式：

- `segment_id`
- `chapter_index + segment_index`

单段模式返回约束：

- `translations` 只返回 1 条
- `versions` 只返回当前 segment 对应的正式版本列表
- 如果没有传 `compare_version_id`，则不返回 `compare`

### 5.3 compare 模式

compare 模式必须同时满足：

- 已启用单段定位
- 传入 `compare_version_id`

允许的组合只有：

- `project_id + segment_id + compare_version_id`
- `project_id + chapter_index + segment_index + compare_version_id`

不允许的情况：

- 只传 `project_id + compare_version_id`
- 只传 `chapter_index` 或只传 `segment_index`
- 同时混用 `segment_id` 和 `chapter_index + segment_index`

### 5.4 `compare_version_id` 的语义

`compare_version_id` 表示：

- 当前 segment 对应的 `segment_translation` 下
- 一条明确存在的
- 当前 active version 之前的历史正式版本

设计约束：

- 不接受跨 project 的 version
- 不接受跨 segment 的 version
- 不接受当前 active version 自己作为 compare 目标

本轮选择 `compare_version_id` 而不是 `compare_version_index`，原因是：

- `version_index` 只在单个 `segment_translation` 内唯一
- 离开具体 segment 很容易歧义
- 用主键更适合作为 inspect compare 的硬指针

## 6. 错误语义

本轮统一两类错误：

### 6.1 `invalid_arguments`

用于参数组合本身不合法，例如：

- 传了 `compare_version_id`，但没有单段定位
- 单段定位参数不完整
- 同时混用了两套单段定位方式
- `compare_version_id` 指向当前 active version 自己

### 6.2 `not_found`

用于 compare 对象本身不成立，例如：

- 当前 project 下找不到目标 segment
- 当前 segment 没有 active version
- `compare_version_id` 不存在
- `compare_version_id` 不属于当前 project
- `compare_version_id` 不属于当前 segment 的 `segment_translation`

这里不做 `compare = null` 这种模糊降级，原因很简单：

- compare 模式是显式请求
- 一旦 compare 对象不成立，就应该让调用方马上知道

## 7. 返回结构设计

本轮 compare 模式仍然沿用 `translations + versions` 主体结构，但范围已经收成单段。

示意结构如下：

```json
{
  "translations": [
    {
      "segment_id": 12,
      "active_version_id": 34,
      "version": {
        "id": 34,
        "version_index": 3,
        "source_hash": "....",
        "glossary_snapshot_id": "....",
        "provider_name": "provider",
        "model_profile_id": "profile-current",
        "model_name": "model-current",
        "source_text": "...",
        "translated_text": "...",
        "translated_text_path": "...",
        "status": "completed"
      },
      "provenance": {
        "finalize_step": {
          "step_run_id": 88,
          "step_key": "finalize_segments",
          "action": "translation.finalize"
        },
        "selected_draft": {
          "id": 144,
          "workflow_run_id": 66,
          "step_run_id": 87,
          "draft_role": "rewrite",
          "parent_draft_id": 138,
          "provider_name": "provider",
          "model_profile_id": "profile-current",
          "model_name": "model-current",
          "translated_text_path": "...",
          "status": "completed",
          "evidence_payload": {},
          "reviews": []
        }
      },
      "compare": {
        "base_version": {
          "id": 22,
          "version_index": 1,
          "source_hash": "....",
          "glossary_snapshot_id": "....",
          "provider_name": "provider",
          "model_profile_id": "profile-old",
          "model_name": "model-old",
          "source_text": "...",
          "translated_text": "...",
          "translated_text_path": "...",
          "status": "completed"
        },
        "current_version": {
          "id": 34,
          "version_index": 3,
          "source_hash": "....",
          "glossary_snapshot_id": "....",
          "provider_name": "provider",
          "model_profile_id": "profile-current",
          "model_name": "model-current",
          "source_text": "...",
          "translated_text": "...",
          "translated_text_path": "...",
          "status": "completed"
        },
        "changed": true,
        "summary": {
          "translated_text_changed": true,
          "source_hash_changed": false,
          "glossary_snapshot_changed": true,
          "model_profile_changed": true,
          "model_name_changed": false,
          "status_changed": false
        }
      }
    }
  ],
  "versions": [
    {
      "id": 22,
      "segment_translation_id": 5,
      "version_index": 1,
      "source_hash": "....",
      "glossary_snapshot_id": "....",
      "provider_name": "provider",
      "model_profile_id": "profile-old",
      "model_name": "model-old",
      "source_text": "...",
      "translated_text": "...",
      "translated_text_path": "...",
      "status": "completed"
    },
    {
      "id": 34,
      "segment_translation_id": 5,
      "version_index": 3,
      "source_hash": "....",
      "glossary_snapshot_id": "....",
      "provider_name": "provider",
      "model_profile_id": "profile-current",
      "model_name": "model-current",
      "source_text": "...",
      "translated_text": "...",
      "translated_text_path": "...",
      "status": "completed"
    }
  ]
}
```

约束如下：

- `compare` 只在 compare 模式下返回
- `compare` 挂在当前 translation 行上，不新增顶层 compare 块
- `base_version` 与 `current_version` 直接复用现有 `version` 结构
- 当前 translation 行已有的 `version` 与 `provenance` 结构不改
- `versions` 在单段模式下收成当前 segment 的正式版本列表

## 8. 变化摘要设计

本轮 `compare.summary` 只收下面六个布尔字段：

- `translated_text_changed`
- `source_hash_changed`
- `glossary_snapshot_changed`
- `model_profile_changed`
- `model_name_changed`
- `status_changed`

此外增加一个总开关：

- `changed`

判定规则：

- 只要 `summary` 中任意一个字段为 `true`，`changed = true`
- 否则 `changed = false`

### 8.1 为什么包含 `source_hash_changed`

它可以直接回答：

- 这次变化是不是源文变了
- 这次 rerun 是“同源文重跑”，还是“源文更新后的重跑”

这对历史排查很有价值。

### 8.2 为什么先不做 `provider_name_changed`

当前第一刀里：

- `model_profile_id`
- `model_name`

已经能覆盖更有判断价值的模型变化观察面。

`provider_name` 这轮先继续保留在 version 本体里，不单独出 compare 标志，避免摘要字段膨胀。

## 9. 查询与组装策略

`TranslationService.inspect()` 的实现建议遵循下面的边界：

1. 先按参数判断是：
   - 项目模式
   - 单段模式
   - compare 模式
2. 项目模式保持现有查询逻辑
3. 单段模式先解析出唯一目标 segment，再只查询这一条 translation 和它的正式 versions
4. compare 模式下：
   - 先确认当前 segment 存在 active version
   - 再确认 `compare_version_id` 命中当前 segment 的历史正式版本
   - 构建 `base_version / current_version / summary / changed`
5. provenance 仍只构建当前 active version，不为 `base_version` 额外补 provenance

我建议把 compare 逻辑收成独立 helper，例如：

- `_resolve_translation_inspect_target(...)`
- `_build_translation_compare_payload(...)`

这样可以让普通 inspect 路径和 compare 路径保持清晰分层。

## 10. 实现触点

本轮预计只需要改动下面这些位置：

- `app/action_router.py`
  - `inspect.translation` 增加可选参数解析：
    - `segment_id`
    - `chapter_index`
    - `segment_index`
    - `compare_version_id`
- `app/services/translation_service.py`
  - `inspect(...)` 增加单段模式与 compare 模式
  - compare 组装逻辑
- `app/repositories/translations.py`
  - 补充按 version_id 读取正式版本或按 translation 读取正式版本的 helper
- `tests/test_translation_stage.py`
  - 补 compare 模式成功、错误语义、普通模式不回归
- `README.md`
- `docs/roadmap.md`
- `CHANGELOG.md`

本轮不需要 migration。

## 11. 风险点

### 11.1 compare 目标跨 segment

如果只校验 `compare_version_id` 是否存在，而不校验它是否属于当前 segment，就会把 compare 做成伪结果。

要求：

- 必须校验 `segment_translation_id` 一致

### 11.2 单段模式误伤普通模式

如果在 `inspect.translation` 里直接改现有查询，而没有把项目模式和单段模式明确分开，容易把原来整项目返回行为改坏。

要求：

- 项目模式保留原逻辑
- 单段模式单独走分支

### 11.3 compare 与无 active version 的段落混用

普通单段 inspect 可以容忍没有 active version；但 compare 模式不应该继续软退化。

要求：

- compare 模式下没有 active version 就直接 `not_found`

## 12. 测试边界

本轮至少覆盖下面五组测试：

1. 普通模式不变
   - 只传 `project_id`
   - 仍返回整项目 `translations + versions`
   - 不带 `compare`

2. 单段 compare 成功
   - `project_id + segment_id + compare_version_id`
   - 返回 1 条 translation
   - `compare.base_version / current_version / summary / changed` 正常存在

3. compare 目标跨 segment
   - `compare_version_id` 指向别的 segment 的正式版本
   - 直接报 `not_found`

4. compare 模式缺单段定位
   - 只传 `project_id + compare_version_id`
   - 直接报 `invalid_arguments`

5. 当前 segment 没有 active version
   - 即使 `compare_version_id` 合法
   - 也直接报 `not_found`

如果实现时顺手补一组附加测试，我建议优先补：

- `compare_version_id == active_version_id` 返回 `invalid_arguments`

## 13. 完成后的效果

本轮完成后，`inspect.translation` 至少要能直接回答：

- 当前这条正式译文和指定历史版相比，文本有没有变
- 这次变化是不是伴随着源文变化
- glossary snapshot、profile、model、status 有没有一起变化

人工复核和问题排查时，不需要再从 `versions[]` 里手工摘两条记录自己对比。
