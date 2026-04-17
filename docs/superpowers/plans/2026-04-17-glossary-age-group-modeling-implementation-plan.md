# Glossary Age Group 结构化建模 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 glossary 主链路增加结构化 `age_group`，把人物年龄层信息从 `note` / provider 自由文本提升为可空受限字段，并贯通到 draft/candidate/entry、inspect 输出，以及 translation 的 glossary prompt 与 snapshot。

**Architecture:** 先在 glossary 三层存储结构上补齐 `age_group`；随后在 `GlossaryService` 中增加统一的 `age_group` 归一逻辑，让 extract 提供初值、finalize 保留最终确认权，并严格限制为 `child / teen / adult / elderly / null`；最后把 `age_group` 接进 `inspect.glossary`、`glossary.inspect_pipeline`、translation prompt 格式化和 `glossary_snapshot_id` 计算，并用定点测试锁死保守判定行为。

**Tech Stack:** Python 3、SQLAlchemy ORM、Alembic、pytest、CLI action router

---

## 文件结构

- Create: `migrations/versions/0019_glossary_age_group_modeling.py`
  责任：给 glossary draft/candidate/entry 表增加 `age_group`。
- Modify: `app/db/models.py`
  责任：为 `GlossaryEntry`、`GlossaryCandidate`、`GlossaryDraftCandidate` 增加 `age_group` 字段定义。
- Modify: `app/repositories/glossary.py`
  责任：扩展 `create_entry(...)`、`create_candidate(...)`、`create_draft_candidate(...)` 和 inspect helper，让 `age_group` 可写可读。
- Modify: `app/services/glossary_service.py`
  责任：增加 `GlossaryExtraction.age_group`、`_normalize_age_group(...)`、extract/finalize prompt 与 payload 透传、`inspect.glossary` 返回增强。
- Modify: `app/services/glossary_pipeline_service.py`
  责任：extract 时把 `age_group` 写入 draft candidate evidence 链路，并纳入 normalize 去重 key。
- Modify: `app/services/translation_service.py`
  责任：把 `age_group` 纳入 glossary prompt 注入与 snapshot 计算。
- Modify: `app/services/translation_pipeline_service.py`
  责任：保持多 workflow translation 的 glossary prompt 注入与 snapshot 计算和单服务路径一致。
- Modify: `tests/test_glossary_stage.py`
  责任：补 schema、extract 归一、finalize 落库、inspect/pipeline 返回的 `age_group` 回归。
- Modify: `tests/test_translation_stage.py`
  责任：补 translation glossary prompt 与 snapshot 对 `age_group` 的联动测试。
- Modify: `README.md`
  责任：更新 glossary 字段说明、`inspect.glossary` 返回口径、translation glossary 注入行为。
- Modify: `docs/roadmap.md`
  责任：把 `P1.2` 第二刀落地状态同步到路线图。
- Modify: `CHANGELOG.md`
  责任：记录 glossary `age_group` 建模与回归基线更新。

---

### Task 1: 为 glossary 三层存储增加 `age_group`

**Files:**
- Create: `migrations/versions/0019_glossary_age_group_modeling.py`
- Modify: `app/db/models.py`
- Modify: `app/repositories/glossary.py`
- Modify: `tests/test_glossary_stage.py`
- Test: `tests/test_glossary_stage.py`

- [ ] **Step 1: 先在 `tests/test_glossary_stage.py` 写 schema 红测**

```python
from sqlalchemy import inspect


def test_glossary_schema_includes_age_group_columns(db_session) -> None:
    inspector = inspect(db_session.get_bind())

    draft_columns = {
        column["name"]: column
        for column in inspector.get_columns("ltw_glossary_draft_candidates")
    }
    candidate_columns = {
        column["name"]: column
        for column in inspector.get_columns("ltw_glossary_candidates")
    }
    entry_columns = {
        column["name"]: column
        for column in inspector.get_columns("ltw_glossary_entries")
    }

    assert "age_group" in draft_columns
    assert draft_columns["age_group"]["nullable"] is True

    assert "age_group" in candidate_columns
    assert candidate_columns["age_group"]["nullable"] is True

    assert "age_group" in entry_columns
    assert entry_columns["age_group"]["nullable"] is True
```

- [ ] **Step 2: 跑 schema 红测，确认字段还不存在**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_glossary_stage.py -k "glossary_schema_includes_age_group_columns" -q`

Expected: FAIL，断言提示 `age_group` 字段缺失。

- [ ] **Step 3: 新增 Alembic migration，补 glossary 三层字段**

```python
"""add glossary age group modeling"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0019_glossary_age_group_modeling"
down_revision = "0018_glossary_gender_modeling"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ltw_glossary_draft_candidates",
        sa.Column("age_group", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "ltw_glossary_candidates",
        sa.Column("age_group", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "ltw_glossary_entries",
        sa.Column("age_group", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ltw_glossary_entries", "age_group")
    op.drop_column("ltw_glossary_candidates", "age_group")
    op.drop_column("ltw_glossary_draft_candidates", "age_group")
```

- [ ] **Step 4: 在模型和 repository 上接住新字段**

```python
class GlossaryEntry(Base):
    __tablename__ = "ltw_glossary_entries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_translation_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_term: Mapped[str] = mapped_column(String(255), nullable=False)
    target_term: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="entity", server_default="entity")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(32), nullable=True)
    age_group: Mapped[str | None] = mapped_column(String(32), nullable=True)
```

```python
class GlossaryCandidate(Base):
    __tablename__ = "ltw_glossary_candidates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_translation_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chapter_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_term: Mapped[str] = mapped_column(String(255), nullable=False)
    suggested_term: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="entity", server_default="entity")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(32), nullable=True)
    age_group: Mapped[str | None] = mapped_column(String(32), nullable=True)
```

```python
class GlossaryDraftCandidate(Base):
    __tablename__ = "ltw_glossary_draft_candidates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_run_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_translation_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chapter_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_term: Mapped[str] = mapped_column(String(255), nullable=False)
    suggested_term: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    gender: Mapped[str | None] = mapped_column(String(32), nullable=True)
    age_group: Mapped[str | None] = mapped_column(String(32), nullable=True)
```

```python
def create_candidate(
    self,
    *,
    project_id: int,
    chapter_id: int,
    source_term: str,
    suggested_term: str,
    category: str = "entity",
    note: str | None = None,
    gender: str | None = None,
    age_group: str | None = None,
    status: str = "pending",
    term_group_key: str | None = None,
    relation_role: str = "independent",
    scope_level: str | None = None,
    scope_chapter_id: int | None = None,
    workflow_run_id: int | None = None,
) -> GlossaryCandidate:
    candidate = GlossaryCandidate(
        project_id=project_id,
        chapter_id=chapter_id,
        source_term=source_term,
        suggested_term=suggested_term,
        category=category,
        note=note,
        gender=gender,
        age_group=age_group,
        status=status,
        term_group_key=term_group_key or source_term,
        relation_role=relation_role,
        scope_level=normalized_scope_level,
        scope_chapter_id=normalized_scope_chapter_id,
        workflow_run_id=workflow_run_id,
    )
```

- [ ] **Step 5: 重新跑 schema 测试，确认 migration、模型和 repository 同步生效**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_glossary_stage.py -k "glossary_schema_includes_age_group_columns or create_candidate_review_rejects_cross_workflow_run" -q`

Expected: PASS，输出 `2 passed`。

- [ ] **Step 6: 提交 Task 1**

```bash
git add migrations/versions/0019_glossary_age_group_modeling.py app/db/models.py app/repositories/glossary.py tests/test_glossary_stage.py
git commit -m "feat: add glossary age group storage fields"
```

### Task 2: 在 `GlossaryService` 中实现 `age_group` 归一、extract 解析和 finalize 落库

**Files:**
- Modify: `app/services/glossary_service.py`
- Modify: `app/services/glossary_pipeline_service.py`
- Modify: `tests/test_glossary_stage.py`
- Test: `tests/test_glossary_stage.py`

- [ ] **Step 1: 先写 extract/finalize 红测**

```python
def test_glossary_extract_normalizes_character_age_group(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    provider = FakeGlossaryProvider(
        outputs=[
            json.dumps(
                {
                    "terms": [
                        {
                            "source_term": "林溪",
                            "translated_term": "Lin Xi",
                            "category": "character",
                            "gender": "female",
                            "age_group": " Teen ",
                            "note": "Character name",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            '{"decisions":[]}',
            '{"items":[]}',
            '{"items":[]}',
            '{"terms":[]}',
        ]
    )

    GlossaryService(db_session, provider=provider).run(
        request_id=request_id_factory("glossary-age-group-normalize"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-glossary-age-group",
    )

    draft = db_session.execute(
        select(GlossaryDraftCandidate).where(GlossaryDraftCandidate.project_id == project_id)
    ).scalar_one()

    assert draft.age_group == "teen"
```

```python
def test_glossary_extract_clears_age_group_for_non_character_terms(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    provider = FakeGlossaryProvider(
        outputs=[
            json.dumps(
                {
                    "terms": [
                        {
                            "source_term": "深蓝公寓",
                            "translated_term": "Deep Blue Apartments",
                            "category": "location",
                            "age_group": "adult",
                            "note": "Apartment building",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            '{"decisions":[]}',
            '{"items":[]}',
            '{"items":[]}',
            '{"terms":[]}',
        ]
    )

    GlossaryService(db_session, provider=provider).run(
        request_id=request_id_factory("glossary-age-group-non-character"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-glossary-age-group",
    )

    draft = db_session.execute(
        select(GlossaryDraftCandidate).where(GlossaryDraftCandidate.project_id == project_id)
    ).scalar_one()

    assert draft.category == "location"
    assert draft.age_group is None
```

```python
def test_glossary_finalize_persists_age_group_to_candidate_and_entry(db_session) -> None:
    project = TranslationProject(
        request_id="glossary-finalize-age-group-project",
        project_key="glossary-finalize-age-group-project",
        source_path="source.txt",
        source_language="zh",
        target_language="en",
        status="created",
    )
    db_session.add(project)
    db_session.flush()
    chapter = Chapter(
        project_id=project.id,
        chapter_index=1,
        chapter_title="第1章",
        source_path="chapter-1.txt",
        normalized_path="chapter-1.txt",
        stage_status="ready",
    )
    db_session.add(chapter)
    db_session.flush()

    workflow_run = WorkflowRun(
        workflow_key="glossary_single_llm_v1",
        project_id=project.id,
        stage="glossary",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":1}',
        request_id="glossary-finalize-age-group-run",
        status="running",
        summary=None,
    )
    db_session.add(workflow_run)
    db_session.flush()
    step_run = WorkflowStepRun(
        workflow_run_id=workflow_run.id,
        step_key="finalize",
        action="glossary.finalize",
        llm_role="terminologist",
        model_profile_id="profile-glossary",
        status="completed",
        input_ref="workflow:1",
        output_payload=None,
        summary=None,
    )
    db_session.add(step_run)
    db_session.flush()

    repository = GlossaryRepository(db_session)
    repository.create_draft_candidate(
        workflow_run_id=workflow_run.id,
        project_id=project.id,
        chapter_id=chapter.id,
        source_term="林溪",
        suggested_term="Lin Xi",
        category="character",
        gender="female",
        age_group="teen",
        term_group_key="character-linxi",
        relation_role="canonical",
        scope_level="chapter_term",
        scope_chapter_id=chapter.id,
        evidence_payload={"note": "Character name", "age_group": "teen"},
    )

    result = GlossaryService(db_session).finalize_from_workflow(
        workflow_run_id=workflow_run.id,
        workflow_step_run_id=step_run.id,
        project_id=project.id,
        model_name="profile-glossary",
    )

    entry = db_session.execute(select(GlossaryEntry).where(GlossaryEntry.project_id == project.id)).scalar_one()
    candidate = db_session.execute(
        select(GlossaryCandidate).where(GlossaryCandidate.project_id == project.id)
    ).scalar_one()

    assert result.candidate_count == 1
    assert entry.age_group == "teen"
    assert candidate.age_group == "teen"
```

- [ ] **Step 2: 跑红测，确认 `age_group` 归一和落库逻辑还不存在**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_glossary_stage.py::test_glossary_extract_normalizes_character_age_group tests\test_glossary_stage.py::test_glossary_extract_clears_age_group_for_non_character_terms tests\test_glossary_stage.py::test_glossary_finalize_persists_age_group_to_candidate_and_entry -q`

Expected: FAIL，断言提示 `GlossaryDraftCandidate` / `GlossaryCandidate` / `GlossaryEntry` 没有正确存 `age_group`，或 parse/finalize 逻辑没有透传该字段。

- [ ] **Step 3: 在 `GlossaryService` 里加入 `age_group` 值模型与归一逻辑**

```python
@dataclass(frozen=True)
class GlossaryExtraction:
    source_term: str
    suggested_term: str
    category: str
    note: str | None
    term_group_key: str
    relation_role: str
    gender: str | None
    age_group: str | None
```

```python
def _normalize_age_group(self, *, category: str, age_group: object) -> str | None:
    normalized_category = self._normalize_text(category) or "term"
    if normalized_category != "character":
        return None
    normalized_age_group = self._normalize_optional_text(age_group)
    if normalized_age_group is None:
        return None
    canonical = normalized_age_group.strip().lower()
    if canonical in {"child", "teen", "adult", "elderly"}:
        return canonical
    return None
```

```python
category = self._normalize_text(item.get("category")) or "term"
note = self._normalize_optional_text(item.get("note"))
gender = self._normalize_gender(category=category, gender=item.get("gender"))
age_group = self._normalize_age_group(category=category, age_group=item.get("age_group"))
term_group_key = self._normalize_text(item.get("term_group_key")) or source_term
relation_role = self._normalize_text(item.get("relation_role")) or "independent"
results.append(
    GlossaryExtraction(
        source_term=source_term,
        suggested_term=suggested_term,
        category=category,
        note=note,
        term_group_key=term_group_key,
        relation_role=relation_role,
        gender=gender,
        age_group=age_group,
    )
)
```

- [ ] **Step 4: 让 extract/finalize prompt 和 payload 都透传 `age_group`**

```python
"每个术语对象字段：source_term, translated_term, category, note, term_group_key, relation_role, gender, age_group。\n"
"age_group 仅在 category=character 且正文或术语里有明确年龄段线索时填写 child/teen/adult/elderly，否则返回 null。\n"
"不要根据先生、小姐、哥、姐、阿姨等敬称猜测年龄层。\n"
```

```python
evidence_payload={
    "workflow_step_run_id": workflow_step_run_id,
    "chapter_id": chapter.id,
    "chapter_index": chapter.chapter_index,
    "chapter_title": chapter.chapter_title,
    "note": item.note,
    "gender": item.gender,
    "age_group": item.age_group,
}
```

```python
finalized_terms.append(
    {
        "draft_candidate_id": item.id,
        "chapter_id": item.chapter_id,
        "source_term": item.source_term,
        "target_term": item.suggested_term,
        "category": item.category,
        "note": evidence_payload.get("note"),
        "gender": self._normalize_gender(
            category=item.category,
            gender=evidence_payload.get("gender"),
        ),
        "age_group": self._normalize_age_group(
            category=item.category,
            age_group=evidence_payload.get("age_group"),
        ),
        "term_group_key": str(relation_review.get("term_group_key") or item.term_group_key),
        "relation_role": str(relation_review.get("relation_role") or item.relation_role),
        "scope_level": scope_level,
        "scope_chapter_id": scope_chapter_id,
    }
)
```

```python
hydrated_terms.append(
    {
        "draft_candidate_id": matched_draft.id,
        "chapter_id": matched_draft.chapter_id,
        "source_term": str(term.get("source_term") or matched_draft.source_term),
        "target_term": str(term.get("target_term") or term.get("suggested_term") or matched_draft.suggested_term),
        "category": str(term.get("category") or matched_draft.category),
        "note": term.get("note", evidence_payload.get("note")),
        "gender": self._normalize_gender(
            category=str(term.get("category") or matched_draft.category),
            gender=term.get("gender", matched_draft.gender),
        ),
        "age_group": self._normalize_age_group(
            category=str(term.get("category") or matched_draft.category),
            age_group=term.get("age_group", matched_draft.age_group),
        ),
        "term_group_key": str(term.get("term_group_key") or relation_review.get("term_group_key") or matched_draft.term_group_key),
        "relation_role": str(term.get("relation_role") or relation_review.get("relation_role") or matched_draft.relation_role),
        "scope_level": scope_level,
        "scope_chapter_id": scope_chapter_id,
    }
)
```

- [ ] **Step 5: 在 pipeline 去重、finalize 落库与 inspect 输出里接住 `age_group`**

```python
unique_terms = {
    (
        item.chapter_id,
        item.source_term,
        item.suggested_term,
        item.category,
        item.gender,
        item.age_group,
        item.term_group_key,
        item.relation_role,
    )
    for item in draft_items
}
```

```python
self.glossary.create_entry(
    project_id=project_id,
    source_term=str(item["source_term"]),
    target_term=str(item["target_term"]),
    category=str(item["category"]),
    note=self._normalize_optional_text(item.get("note")),
    gender=self._normalize_gender(category=str(item["category"]), gender=item.get("gender")),
    age_group=self._normalize_age_group(category=str(item["category"]), age_group=item.get("age_group")),
    locked=0,
    term_group_key=str(item["term_group_key"]),
    relation_role=str(item["relation_role"]),
    scope_level=scope_level,
    scope_chapter_id=int(scope_chapter_id) if scope_chapter_id is not None else None,
)
```

```python
self.glossary.create_candidate(
    project_id=project_id,
    chapter_id=int(item["chapter_id"]),
    source_term=str(item["source_term"]),
    suggested_term=str(item["target_term"]),
    category=str(item["category"]),
    note=self._normalize_optional_text(item.get("note")),
    gender=self._normalize_gender(category=str(item["category"]), gender=item.get("gender")),
    age_group=self._normalize_age_group(category=str(item["category"]), age_group=item.get("age_group")),
    status="pending",
    term_group_key=str(item["term_group_key"]),
    relation_role=str(item["relation_role"]),
    scope_level=scope_level,
    scope_chapter_id=int(scope_chapter_id) if scope_chapter_id is not None else None,
    workflow_run_id=workflow_run_id,
)
```

- [ ] **Step 6: 重新跑定点测试，确认 extract 归一与 finalize 落库通过**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_glossary_stage.py::test_glossary_extract_normalizes_character_age_group tests\test_glossary_stage.py::test_glossary_extract_clears_age_group_for_non_character_terms tests\test_glossary_stage.py::test_glossary_finalize_persists_age_group_to_candidate_and_entry -q`

Expected: PASS，输出 `3 passed`。

- [ ] **Step 7: 提交 Task 2**

```bash
git add app/services/glossary_service.py app/services/glossary_pipeline_service.py tests/test_glossary_stage.py
git commit -m "feat: normalize glossary age group through finalize"
```

### Task 3: 增强 `inspect.glossary` / `glossary.inspect_pipeline`，并把 `age_group` 接进 translation prompt 与 snapshot

**Files:**
- Modify: `app/repositories/glossary.py`
- Modify: `app/services/glossary_service.py`
- Modify: `app/services/translation_service.py`
- Modify: `app/services/translation_pipeline_service.py`
- Modify: `tests/test_glossary_stage.py`
- Modify: `tests/test_translation_stage.py`
- Test: `tests/test_glossary_stage.py`
- Test: `tests/test_translation_stage.py`

- [ ] **Step 1: 先写 inspect 和 translation 联动红测**

```python
def test_glossary_inspect_returns_age_group_for_entries_candidates_and_pipeline(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    provider = FakeGlossaryProvider(
        outputs=[
            json.dumps(
                {
                    "terms": [
                        {
                            "source_term": "林溪",
                            "translated_term": "Lin Xi",
                            "category": "character",
                            "gender": "female",
                            "age_group": "teen",
                            "note": "Character name",
                            "term_group_key": "character-linxi",
                            "relation_role": "canonical",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            '{"decisions":[]}',
            '{"items":[]}',
            '{"items":[]}',
            '{"terms":[]}',
        ]
    )

    result = GlossaryService(db_session, provider=provider).run(
        request_id=request_id_factory("glossary-inspect-age-group"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-glossary-age-group",
    )

    workflow_run = db_session.execute(
        select(WorkflowRun)
        .where(WorkflowRun.project_id == project_id, WorkflowRun.stage == "glossary")
        .order_by(WorkflowRun.id.desc())
    ).scalar_one()

    data = GlossaryService(db_session, provider=provider).inspect(project_id=project_id)
    pipeline = GlossaryPipelineService(db_session, provider=provider).inspect_pipeline(
        workflow_run_id=workflow_run.id
    )

    assert result.candidate_count == 1
    assert data["entries"][0]["age_group"] == "teen"
    assert data["candidates"][0]["age_group"] == "teen"
    assert pipeline["draft_candidates"][0]["age_group"] == "teen"
```

```python
def test_translation_glossary_prompt_and_snapshot_include_age_group(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
        source_text="第1章 开始\n林溪背着书包走进深蓝公寓。",
    )

    synopsis = db_session.execute(
        select(ProjectSynopsis).where(ProjectSynopsis.project_id == project_id)
    ).scalar_one()
    synopsis.source_synopsis_text = "已有 source synopsis"
    synopsis.source_synopsis_status = "ready"
    synopsis.source_synopsis_origin = "generated"
    synopsis.source_synopsis_hash = hashlib.sha256("已有 source synopsis".encode("utf-8")).hexdigest()
    synopsis.source_synopsis_model_profile_id = "profile-synopsis-source"
    synopsis.source_synopsis_provider_name = "fake_provider"
    synopsis.source_synopsis_model_name = "profile-synopsis-source"
    synopsis.target_synopsis_text = "已有 target synopsis"
    synopsis.target_synopsis_status = "ready"
    synopsis.target_synopsis_origin = "translated"
    synopsis.target_synopsis_hash = hashlib.sha256("已有 target synopsis".encode("utf-8")).hexdigest()
    synopsis.target_synopsis_model_profile_id = "profile-synopsis-target"
    synopsis.target_synopsis_provider_name = "fake_provider"
    synopsis.target_synopsis_model_name = "profile-synopsis-target"

    db_session.add_all(
        [
            GlossaryEntry(
                project_id=project_id,
                source_term="林溪",
                target_term="Lin Xi",
                category="character",
                note="Character name",
                gender="female",
                age_group="teen",
                status="active",
                locked=0,
                term_group_key="character-linxi",
                relation_role="canonical",
            ),
            GlossaryEntry(
                project_id=project_id,
                source_term="深蓝公寓",
                target_term="Deep Blue Apartments",
                category="location",
                note="Apartment building",
                gender=None,
                age_group=None,
                status="active",
                locked=0,
                term_group_key="location-deep-blue-apartments",
                relation_role="independent",
            ),
        ]
    )
    db_session.commit()

    provider = FakeProvider()
    TranslationService(db_session, base_data_dir=project_workspace, provider=provider).run(
        request_id=request_id_factory("translation-age-group-snapshot"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-translation-age-group",
    )

    version = db_session.execute(
        select(SegmentTranslationVersion)
        .where(SegmentTranslationVersion.project_id == project_id)
        .order_by(SegmentTranslationVersion.id.asc())
    ).scalar_one()

    assert "age_group: teen" in str(provider.calls[0]["prompt"])
    assert "age_group: None" not in str(provider.calls[0]["prompt"])

    payload_with_age_group = json.dumps(
        [
            {
                "source_term": "林溪",
                "target_term": "Lin Xi",
                "category": "character",
                "note": "Character name",
                "gender": "female",
                "age_group": "teen",
                "status": "active",
                "locked": 0,
                "term_group_key": "character-linxi",
                "relation_role": "canonical",
            },
            {
                "source_term": "深蓝公寓",
                "target_term": "Deep Blue Apartments",
                "category": "location",
                "note": "Apartment building",
                "gender": None,
                "age_group": None,
                "status": "active",
                "locked": 0,
                "term_group_key": "location-deep-blue-apartments",
                "relation_role": "independent",
            },
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    expected_snapshot_id = hashlib.sha256(payload_with_age_group.encode("utf-8")).hexdigest()

    assert version.glossary_snapshot_id == expected_snapshot_id
```

- [ ] **Step 2: 跑红测，确认 inspect 与 translation 还没接住 `age_group`**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_glossary_stage.py::test_glossary_inspect_returns_age_group_for_entries_candidates_and_pipeline tests\test_translation_stage.py::test_translation_glossary_prompt_and_snapshot_include_age_group -q`

Expected: FAIL，断言提示 `inspect.glossary` / `inspect_pipeline` 没有 `age_group`，或者 `glossary_snapshot_id` 仍按旧 payload 计算。

- [ ] **Step 3: 在 repository inspect helper 与 `GlossaryService.inspect()` 中返回新字段**

```python
def inspect_draft_candidates(self, workflow_run_id: int) -> list[dict[str, object]]:
    return [
        {
            "id": candidate.id,
            "workflow_run_id": candidate.workflow_run_id,
            "project_id": candidate.project_id,
            "chapter_id": candidate.chapter_id,
            "source_term": candidate.source_term,
            "suggested_term": candidate.suggested_term,
            "category": candidate.category,
            "gender": candidate.gender,
            "age_group": candidate.age_group,
            "scope_level": candidate.scope_level,
            "scope_chapter_id": candidate.scope_chapter_id,
            "evidence_payload": candidate.evidence_payload,
            "status": candidate.status,
            "term_group_key": candidate.term_group_key,
            "relation_role": candidate.relation_role,
        }
        for candidate in self.session.execute(statement).scalars().all()
    ]
```

```python
entries = [
    {
        "id": entry.id,
        "project_id": entry.project_id,
        "source_term": entry.source_term,
        "target_term": entry.target_term,
        "category": entry.category,
        "gender": entry.gender,
        "age_group": entry.age_group,
        "status": entry.status,
        "locked": entry.locked,
        "term_group_key": entry.term_group_key,
        "relation_role": entry.relation_role,
    }
    for entry in self.glossary.list_entries(project_id)
]
candidates = [
    {
        "id": candidate.id,
        "project_id": candidate.project_id,
        "chapter_id": candidate.chapter_id,
        "source_term": candidate.source_term,
        "suggested_term": candidate.suggested_term,
        "category": candidate.category,
        "note": candidate.note,
        "gender": candidate.gender,
        "age_group": candidate.age_group,
        "status": candidate.status,
        "term_group_key": candidate.term_group_key,
        "relation_role": candidate.relation_role,
    }
    for candidate in self.glossary.list_candidates(project_id)
]
```

- [ ] **Step 4: 在单/多 translation 路径里统一注入 `age_group`**

```python
def _format_glossary_entry(self, entry: GlossaryEntry) -> str:
    note_suffix = f" | note: {entry.note}" if entry.note else ""
    category_suffix = f" | category: {entry.category}" if entry.category else ""
    gender_suffix = f" | gender: {entry.gender}" if entry.gender else ""
    age_group_suffix = f" | age_group: {entry.age_group}" if entry.age_group else ""
    return (
        f"- {entry.source_term} => {entry.target_term}"
        f" | role: {entry.relation_role}"
        f" | group: {entry.term_group_key}"
        f"{category_suffix}{gender_suffix}{age_group_suffix}{note_suffix}"
    )
```

```python
payload = json.dumps(
    [
        {
            "source_term": entry.source_term,
            "target_term": entry.target_term,
            "category": entry.category,
            "note": entry.note,
            "gender": entry.gender,
            "age_group": entry.age_group,
            "status": entry.status,
            "locked": entry.locked,
            "term_group_key": entry.term_group_key,
            "relation_role": entry.relation_role,
        }
        for entry in sorted(glossary_entries, key=lambda item: item.source_term)
    ],
    ensure_ascii=False,
    sort_keys=True,
)
```

- [ ] **Step 5: 重新跑定点测试，确认 inspect 与 translation 联动通过**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_glossary_stage.py::test_glossary_inspect_returns_age_group_for_entries_candidates_and_pipeline tests\test_translation_stage.py::test_translation_glossary_prompt_and_snapshot_include_age_group -q`

Expected: PASS，输出 `2 passed`。

- [ ] **Step 6: 提交 Task 3**

```bash
git add app/repositories/glossary.py app/services/glossary_service.py app/services/translation_service.py app/services/translation_pipeline_service.py tests/test_glossary_stage.py tests/test_translation_stage.py
git commit -m "feat: expose glossary age group in inspect and translation"
```

### Task 4: 更新文档并完成目标回归与全量回归

**Files:**
- Modify: `README.md`
- Modify: `docs/roadmap.md`
- Modify: `CHANGELOG.md`
- Test: `tests/test_glossary_stage.py`
- Test: `tests/test_translation_stage.py`

- [ ] **Step 1: 先补文档变更**

```md
- 抽取 prompt 要求模型直接返回 JSON，当前收口字段对齐生产侧常见口径：`source_term / translated_term / category / note / gender / age_group / term_group_key / relation_role`
- 本地正式术语表当前保存为 `source_term / target_term / category / note / gender / age_group / term_group_key / relation_role`
- `age_group` 当前只对 `category=character` 生效，取值为 `child / teen / adult / elderly / null`
- `inspect.glossary` 现在会返回 `entries[*].age_group`，以及 `candidates[*].age_group`
- `glossary.inspect_pipeline` 的 draft candidate 也会返回 `age_group`
- `translation` 的 glossary prompt 会在 `age_group` 非空时注入 `| age_group: ...`
- `glossary_snapshot_id` 现在会感知 `age_group` 变化
```

- [ ] **Step 2: 跑 glossary/translation 目标回归**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_glossary_stage.py tests\test_translation_stage.py -q`

Expected: PASS，输出通过数高于当前 `51 passed` 的子集基线，并且没有失败。

- [ ] **Step 3: 跑完整回归**

Run: `$env:LTW_TEST_DATABASE_URL='mysql+pymysql://abner:NsS4IhrMBSBVO46cIqbsTAlJTERsKeJ0@192.168.31.212:3307/abner_ltw_test'; D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests -q`

Expected: PASS，完整回归全部通过；如果基线从 `224` 增长，需把新数字同步回 README / roadmap / changelog。

- [ ] **Step 4: 提交 Task 4**

```bash
git add README.md docs/roadmap.md CHANGELOG.md tests/test_glossary_stage.py tests/test_translation_stage.py
git commit -m "docs: record glossary age group modeling rollout"
```

## 自检记录

- 规格覆盖：Task 1 对应 spec 的数据模型变更；Task 2 对应 extract/finalize/归一逻辑；Task 3 对应 inspect 与 translation 联动；Task 4 对应文档和完整回归，没有遗漏 spec 中的核心要求。
- 完整性扫描：计划里没有未完成留白；每个代码步骤都给了明确片段和命令。
- 命名一致性：全程统一使用 `age_group`、`GlossaryExtraction.age_group`、`_normalize_age_group(...)`、`glossary_snapshot_id` 这些名称，没有前后漂移。
