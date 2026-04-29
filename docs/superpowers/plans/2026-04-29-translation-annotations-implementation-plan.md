# Translation Annotations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 local_translation_workbench 增加独立翻译注释层，用于俚语、文化梗和专有词说明，并在导出中以章节注释区呈现。

**Architecture:** 新增 `ltw_annotations` 与 `ltw_annotation_occurrences` 两张表，注释定义按 `project_id + canonical_key` 保持项目级一致性，出现位置绑定到 chapter/segment/version。抽取流程由 `AnnotationService` 读取 active translation、glossary、review issue 与已有注释，经 LLM JSON 候选合并为 candidate/approved 注释；导出流程只读取 approved 注释，写入 manifest 与章节尾部注释区，不改写 `SegmentTranslationVersion.translated_text`。

**Tech Stack:** Python 3.12、SQLAlchemy ORM、Alembic、Pytest、现有 Provider `generate_text` 接口、PowerShell CLI。

**Execution Status:** 已实现并验证，聚焦回归 `37 passed`，全量回归 `366 passed`。

---

## 文件结构

- Create: `migrations/versions/0023_translation_annotations.py`
  - 创建 `ltw_annotations`、`ltw_annotation_occurrences`，含唯一约束和必要索引。
- Modify: `app/db/models.py`
  - 添加 `Annotation`、`AnnotationOccurrence` ORM 模型。
- Create: `app/repositories/annotations.py`
  - 封装注释定义与出现位置的查找、创建、更新、审批和导出查询。
- Create: `app/services/annotation_prompt_service.py`
  - 构建 LLM 抽取 prompt，解析 JSON envelope，标准化候选字段。
- Create: `app/services/annotation_service.py`
  - 实现 `extract`、`inspect`、`approve`、`reject`。
- Create: `app/action_handlers/annotation_handlers.py`
  - 暴露 `annotation.extract`、`annotation.inspect`、`annotation.approve`、`annotation.reject`。
- Modify: `app/action_handlers/__init__.py`
  - 注册 annotation handlers。
- Modify: `app/cli.py`
  - 帮助文本加入 annotation actions；参数映射加入 annotation 常用参数。
- Modify: `app/services/export_service.py`
  - 查询 approved 注释，manifest 增加 `annotations`，Markdown 每章译文后增加 `#### 注释`。
- Modify: `README.md`
  - 中文说明新增 annotation actions 和导出行为。
- Test: `tests/test_annotation_service.py`
  - 覆盖 prompt parse、抽取合并、一致性、locked、审批和 inspect。
- Test: `tests/test_annotation_export.py`
  - 覆盖 manifest 与 Markdown 注释导出，不污染译文正文。
- Modify: `tests/test_cli_smoke.py` 或 `tests/test_action_router_dispatch.py`
  - 覆盖 action 注册与 CLI 帮助文本。

## Task 1: 数据模型与迁移

**Files:**
- Create: `migrations/versions/0023_translation_annotations.py`
- Modify: `app/db/models.py`
- Test: `tests/test_annotation_service.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_annotation_service.py` 添加：

```python
from sqlalchemy import select

from tools.local_translation_workbench.app.db.models import Annotation, AnnotationOccurrence


def test_annotation_schema_enforces_project_canonical_key_uniqueness(db_session):
    first = Annotation(
        project_id=1,
        source_anchor="一个小目标",
        target_anchor="one hundred million",
        annotation_type="idiom",
        canonical_key="idiom:一个小目标",
        explanation="A Chinese internet meme referring to one hundred million yuan.",
        status="candidate",
        locked=0,
        source="llm_annotation",
    )
    second = Annotation(
        project_id=1,
        source_anchor="一个小目标",
        target_anchor="one hundred million yuan",
        annotation_type="idiom",
        canonical_key="idiom:一个小目标",
        explanation="Conflicting explanation.",
        status="candidate",
        locked=0,
        source="llm_annotation",
    )
    db_session.add(first)
    db_session.flush()
    db_session.add(second)

    with pytest.raises(Exception):
        db_session.flush()


def test_annotation_occurrence_schema_enforces_version_anchor_uniqueness(db_session):
    annotation = Annotation(
        project_id=1,
        source_anchor="一个小目标",
        target_anchor="one hundred million",
        annotation_type="idiom",
        canonical_key="idiom:一个小目标",
        explanation="A Chinese internet meme referring to one hundred million yuan.",
        status="approved",
        locked=0,
        source="manual",
    )
    db_session.add(annotation)
    db_session.flush()
    first = AnnotationOccurrence(
        annotation_id=annotation.id,
        project_id=1,
        chapter_id=10,
        segment_id=20,
        version_id=30,
        source_anchor="一个小目标",
        target_anchor="one hundred million",
        display_order=1,
    )
    second = AnnotationOccurrence(
        annotation_id=annotation.id,
        project_id=1,
        chapter_id=10,
        segment_id=20,
        version_id=30,
        source_anchor="一个小目标",
        target_anchor="one hundred million",
        display_order=2,
    )
    db_session.add(first)
    db_session.flush()
    db_session.add(second)

    with pytest.raises(Exception):
        db_session.flush()
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_annotation_service.py -q
```

Expected: FAIL，原因是 `Annotation` 与 `AnnotationOccurrence` 未定义。

- [ ] **Step 3: 实现模型与迁移**

在 `app/db/models.py` 中添加两个模型：

```python
class Annotation(Base):
    __tablename__ = "ltw_annotations"
    __table_args__ = (UniqueConstraint("project_id", "canonical_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("ltw_translation_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_anchor: Mapped[str] = mapped_column(String(255), nullable=False)
    target_anchor: Mapped[str] = mapped_column(String(255), nullable=False)
    annotation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_key: Mapped[str] = mapped_column(String(320), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="candidate", server_default="candidate")
    locked: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="llm_annotation", server_default="llm_annotation")
    conflict_with_annotation_id: Mapped[int | None] = mapped_column(ForeignKey("ltw_annotations.id", ondelete="SET NULL"), nullable=True, index=True)
    evidence_payload: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, server_default=text("CURRENT_TIMESTAMP"), server_onupdate=FetchedValue())
```

并添加 `AnnotationOccurrence`，字段与设计文档一致，唯一约束为 `annotation_id, version_id, source_anchor, target_anchor`。

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_annotation_service.py::test_annotation_schema_enforces_project_canonical_key_uniqueness tools/local_translation_workbench/tests/test_annotation_service.py::test_annotation_occurrence_schema_enforces_version_anchor_uniqueness -q
```

Expected: PASS。

## Task 2: Prompt 解析与候选标准化

**Files:**
- Create: `app/services/annotation_prompt_service.py`
- Test: `tests/test_annotation_service.py`

- [ ] **Step 1: 写失败测试**

```python
from tools.local_translation_workbench.app.services.annotation_prompt_service import AnnotationPromptService


def test_annotation_prompt_service_parses_json_candidates():
    service = AnnotationPromptService()
    envelope = service.parse_extraction_response(
        '{"annotations":[{"source_anchor":"一个小目标","target_anchor":"one hundred million","annotation_type":"idiom","explanation":"A Chinese internet meme referring to one hundred million yuan."}]}'
    )

    assert envelope[0]["canonical_key"] == "idiom:一个小目标"
    assert envelope[0]["status"] == "candidate"
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_annotation_service.py::test_annotation_prompt_service_parses_json_candidates -q
```

Expected: FAIL，原因是 `AnnotationPromptService` 不存在。

- [ ] **Step 3: 实现 PromptService**

实现 `parse_extraction_response()`：

```python
payload = json.loads(content.strip())
items = payload.get("annotations")
if not isinstance(items, list):
    raise ToolError(code="provider_error", message="annotation.extract 必须返回 annotations 数组。", status=502)
```

对每个候选标准化：

```python
source_anchor = self.normalize_text(item.get("source_anchor"))
target_anchor = self.normalize_text(item.get("target_anchor"))
annotation_type = self.normalize_type(item.get("annotation_type"))
explanation = self.normalize_text(item.get("explanation"))
canonical_key = self.normalize_text(item.get("canonical_key")) or f"{annotation_type}:{source_anchor}"
```

缺少 `source_anchor`、`target_anchor`、`explanation` 时跳过候选并记录 skipped count。

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_annotation_service.py::test_annotation_prompt_service_parses_json_candidates -q
```

Expected: PASS。

## Task 3: 仓储与一致性合并

**Files:**
- Create: `app/repositories/annotations.py`
- Create/Modify: `app/services/annotation_service.py`
- Test: `tests/test_annotation_service.py`

- [ ] **Step 1: 写失败测试**

```python
from tools.local_translation_workbench.app.services.annotation_service import AnnotationService


def test_annotation_service_reuses_existing_approved_annotation(db_session):
    service = AnnotationService(db_session)
    existing = service.repository.create_annotation(
        project_id=1,
        source_anchor="一个小目标",
        target_anchor="one hundred million",
        annotation_type="idiom",
        canonical_key="idiom:一个小目标",
        explanation="A Chinese internet meme referring to one hundred million yuan.",
        status="approved",
        locked=0,
        source="manual",
        evidence_payload=None,
    )
    merged = service.merge_candidate(
        project_id=1,
        candidate={
            "source_anchor": "一个小目标",
            "target_anchor": "one hundred million",
            "annotation_type": "idiom",
            "canonical_key": "idiom:一个小目标",
            "explanation": "A Chinese internet meme referring to one hundred million yuan.",
            "status": "candidate",
            "source": "llm_annotation",
            "evidence_payload": {},
        },
    )

    assert merged.id == existing.id
    assert merged.status == "approved"
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_annotation_service.py::test_annotation_service_reuses_existing_approved_annotation -q
```

Expected: FAIL，原因是 `AnnotationService` 或仓储方法不存在。

- [ ] **Step 3: 实现仓储与合并**

`AnnotationRepository` 提供：

```python
get_by_canonical_key(project_id, canonical_key)
create_annotation(...)
update_annotation(...)
create_or_update_occurrence(...)
list_annotations(project_id, status=None)
list_export_annotations(project_id, chapter_ids)
approve(annotation_id)
reject(annotation_id)
```

`AnnotationService.merge_candidate()` 规则：

```python
existing = repository.get_by_canonical_key(project_id, canonical_key)
if existing is None:
    return repository.create_annotation(...)
if existing.status == "approved" or int(existing.locked):
    return existing
if existing.explanation.strip() != candidate["explanation"].strip():
    return repository.create_annotation(..., canonical_key=f"{canonical_key}#conflict:{uuid4().hex[:8]}", conflict_with_annotation_id=existing.id)
return repository.update_annotation(existing, candidate)
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_annotation_service.py::test_annotation_service_reuses_existing_approved_annotation -q
```

Expected: PASS。

## Task 4: 抽取、审批、inspect 与 CLI 动作

**Files:**
- Modify: `app/services/annotation_service.py`
- Create: `app/action_handlers/annotation_handlers.py`
- Modify: `app/action_handlers/__init__.py`
- Modify: `app/cli.py`
- Test: `tests/test_annotation_service.py`
- Test: `tests/test_action_router_dispatch.py`

- [ ] **Step 1: 写失败测试**

```python
def test_annotation_approve_changes_status_and_lock(db_session):
    service = AnnotationService(db_session)
    annotation = service.repository.create_annotation(
        project_id=1,
        source_anchor="一个小目标",
        target_anchor="one hundred million",
        annotation_type="idiom",
        canonical_key="idiom:一个小目标",
        explanation="A Chinese internet meme referring to one hundred million yuan.",
        status="candidate",
        locked=0,
        source="llm_annotation",
        evidence_payload=None,
    )

    result = service.approve(annotation_id=annotation.id, locked=True)

    assert result["status"] == "approved"
    assert result["locked"] == 1
```

另在 dispatch 测试中断言：

```python
from tools.local_translation_workbench.app.action_handlers import ACTION_HANDLERS


def test_annotation_actions_are_registered():
    assert "annotation.extract" in ACTION_HANDLERS
    assert "annotation.inspect" in ACTION_HANDLERS
    assert "annotation.approve" in ACTION_HANDLERS
    assert "annotation.reject" in ACTION_HANDLERS
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_annotation_service.py::test_annotation_approve_changes_status_and_lock tools/local_translation_workbench/tests/test_action_router_dispatch.py::test_annotation_actions_are_registered -q
```

Expected: FAIL，原因是审批方法和 action 注册不存在。

- [ ] **Step 3: 实现服务与动作**

`annotation.extract` 读取参数：

```python
project_id = int(support._require_argument(arguments, "project_id"))
request_id = support._require_argument(arguments, "request_id")
model_profile_id = arguments.get("model_profile_id", "default")
scope = ScopeService().build_scope(...)
```

通过 `build_provider_from_profile()` 得到 provider，调用：

```python
AnnotationService(session, provider=resolved.provider).extract(
    request_id=request_id,
    project_id=project_id,
    scope=scope,
    model_profile_id=resolved.profile_key,
    provider_model_name=resolved.model_name,
)
```

`annotation.inspect` 返回 annotations 与 occurrences；`annotation.approve` 和 `annotation.reject` 按 `annotation_id` 更新状态。

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_annotation_service.py::test_annotation_approve_changes_status_and_lock tools/local_translation_workbench/tests/test_action_router_dispatch.py::test_annotation_actions_are_registered -q
```

Expected: PASS。

## Task 5: 导出 manifest 与章节注释区

**Files:**
- Modify: `app/services/export_service.py`
- Test: `tests/test_annotation_export.py`

- [ ] **Step 1: 写失败测试**

```python
def test_export_includes_approved_annotations_without_changing_translation_text(db_session, project_workspace, request_id_factory):
    project_id = prepare_project_with_one_active_translation(db_session, project_workspace, request_id_factory)
    service = AnnotationService(db_session)
    annotation = service.repository.create_annotation(
        project_id=project_id,
        source_anchor="一个小目标",
        target_anchor="one hundred million",
        annotation_type="idiom",
        canonical_key="idiom:一个小目标",
        explanation="A Chinese internet meme referring to one hundred million yuan.",
        status="approved",
        locked=1,
        source="manual",
        evidence_payload=None,
    )
    service.repository.create_or_update_occurrence(
        annotation_id=annotation.id,
        project_id=project_id,
        chapter_id=1,
        segment_id=1,
        version_id=1,
        source_anchor="一个小目标",
        target_anchor="one hundred million",
        display_order=1,
    )

    result = ExportService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("annotation-export"),
        project_id=project_id,
        scope={"type": "all"},
    )
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    export_text = Path(result.manifest_path).with_name("export.md").read_text(encoding="utf-8")

    assert manifest["annotations"][0]["canonical_key"] == "idiom:一个小目标"
    assert "#### 注释" in export_text
    assert "[1] 一个小目标 / one hundred million" in export_text
    assert "one hundred million[1]" not in export_text
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_annotation_export.py::test_export_includes_approved_annotations_without_changing_translation_text -q
```

Expected: FAIL，原因是导出没有 annotations。

- [ ] **Step 3: 实现导出**

在 `ExportService.__init__()` 增加 `AnnotationRepository`。在 `run()` 中按本次 `chapter_ids` 查询 approved 注释：

```python
annotations = self.annotations.list_export_annotations(project_id=project_id, chapter_ids=chapter_ids)
```

manifest 增加：

```python
"annotations": annotations,
```

调用 `_render_export_markdown()` 时传入 annotations，并在每章译文 fenced block 后追加：

```python
chapter_annotations = annotations_by_chapter.get(int(item["chapter_id"]), [])
if chapter_annotations:
    lines.append("#### 注释")
    for index, annotation in enumerate(chapter_annotations, start=1):
        lines.append(f"- [{index}] {annotation['source_anchor']} / {annotation['target_anchor']}：{annotation['explanation']}")
    lines.append("")
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_annotation_export.py::test_export_includes_approved_annotations_without_changing_translation_text -q
```

Expected: PASS。

## Task 6: 文档、回归与收尾

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-04-29-translation-annotations-design.md`
- Test: full test suite

- [ ] **Step 1: 更新文档**

`README.md` 的 action 列表加入：

```markdown
- `annotation.extract` / `annotation.inspect` / `annotation.approve` / `annotation.reject`
```

新增说明：

```markdown
### annotation 注释层

annotation 用于保存俚语、文化梗和专有词解释。注释不写入译文正文，不改变 glossary 译名约束；导出时只读取 approved 注释，在每章译文后生成独立 `#### 注释` 区，并在 `manifest.json` 写入结构化 `annotations`。
```

- [ ] **Step 2: 扫描未完成标记**

Run:

```powershell
$patterns = @('TB'+'D', 'TO'+'DO', 'implement'+' later', 'fill'+' in', ([char]21344 + [char]20301))
Select-String -Path docs/superpowers/plans/2026-04-29-translation-annotations-implementation-plan.md,docs/superpowers/specs/2026-04-29-translation-annotations-design.md,README.md -Pattern $patterns
```

Expected: no output。

- [ ] **Step 3: 跑全量测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests -q
```

Expected: 全部 PASS。

- [ ] **Step 4: 检查工作区**

Run:

```powershell
git diff --check
git status -sb
```

Expected: `git diff --check` no output；`git status -sb` 只显示本功能相关文件。

## 自检

- 设计目标覆盖：独立存储由 Task 1/3 完成；一致性由 Task 3 完成；自动候选和人工状态由 Task 2/4 完成；导出 manifest 与章节注释由 Task 5 完成；文档由 Task 6 完成。
- 未完成标记扫描：本文未使用待补充标记。
- 类型一致性：`Annotation`、`AnnotationOccurrence`、`AnnotationRepository`、`AnnotationService`、`AnnotationPromptService` 名称在所有任务中保持一致。
