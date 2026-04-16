# Glossary Gender 结构化建模 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 glossary 主链路增加结构化 `gender`，把人物性别信息从 `note` 提升为可空受限字段，并贯通到 draft/candidate/entry、inspect 输出，以及 translation 的 glossary prompt 与 snapshot。

**Architecture:** 先在 glossary 三层存储结构上补齐 `gender`，并顺手让 `GlossaryCandidate` 与 `GlossaryEntry/GlossaryDraftCandidate` 的字段对齐；随后在 `GlossaryService` 中增加统一的 `gender` 归一逻辑，让 extract 提供初值、finalize 保留最终确认权；最后把 `gender` 接进 `inspect.glossary`、`glossary.inspect_pipeline`、translation prompt 格式化和 `glossary_snapshot_id` 计算，并用定点测试锁死行为。

**Tech Stack:** Python 3、SQLAlchemy ORM、Alembic、pytest、CLI action router

---

## 文件结构

- Create: `migrations/versions/0018_glossary_gender_modeling.py`
  责任：给 glossary draft/candidate/entry 表增加 `gender`，并给 glossary candidate 表补 `category/note`。
- Modify: `app/db/models.py`
  责任：为 `GlossaryEntry`、`GlossaryCandidate`、`GlossaryDraftCandidate` 增加新字段定义。
- Modify: `app/repositories/glossary.py`
  责任：扩展 `create_entry(...)`、`create_candidate(...)`、`create_draft_candidate(...)` 和 inspect helper，让新字段可写可读。
- Modify: `app/services/glossary_service.py`
  责任：增加 `GlossaryExtraction.gender`、`_normalize_gender(...)`、extract/finalize prompt 与 payload 透传、`inspect.glossary` 返回增强。
- Modify: `app/services/glossary_pipeline_service.py`
  责任：extract 时把 `gender` 写入 draft candidate evidence 链路。
- Modify: `app/services/translation_service.py`
  责任：把 `gender` 纳入 glossary prompt 注入与 snapshot 计算。
- Modify: `app/services/translation_pipeline_service.py`
  责任：保持多 workflow translation 的 glossary prompt 注入与 snapshot 计算和单服务路径一致。
- Modify: `tests/test_glossary_stage.py`
  责任：补 schema、extract 归一、finalize 落库、inspect/pipeline/CLI 返回的 `gender` 回归。
- Modify: `tests/test_translation_stage.py`
  责任：补 translation glossary prompt 与 snapshot 对 `gender` 的联动测试。
- Modify: `README.md`
  责任：更新 glossary 字段说明、`inspect.glossary` 返回口径、translation glossary 注入行为。
- Modify: `docs/roadmap.md`
  责任：把 `P1.2` 第一刀落地状态同步到路线图。
- Modify: `CHANGELOG.md`
  责任：记录 glossary gender 建模与回归基线更新。

---

### Task 1: 为 glossary 三层存储增加 `gender`，并补齐 candidate 的 `category/note`

**Files:**
- Create: `migrations/versions/0018_glossary_gender_modeling.py`
- Modify: `app/db/models.py`
- Modify: `app/repositories/glossary.py`
- Modify: `tests/test_glossary_stage.py`
- Test: `tests/test_glossary_stage.py`

- [ ] **Step 1: 先在 `tests/test_glossary_stage.py` 写 schema 红测**

```python
from sqlalchemy import inspect


def test_glossary_schema_includes_gender_columns(db_session) -> None:
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

    assert "gender" in draft_columns
    assert draft_columns["gender"]["nullable"] is True

    assert "category" in candidate_columns
    assert "note" in candidate_columns
    assert "gender" in candidate_columns
    assert candidate_columns["note"]["nullable"] is True
    assert candidate_columns["gender"]["nullable"] is True

    assert "gender" in entry_columns
    assert entry_columns["gender"]["nullable"] is True
```

- [ ] **Step 2: 跑 schema 红测，确认字段还不存在**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_glossary_stage.py -k "glossary_schema_includes_gender_columns" -q`

Expected: FAIL，断言提示 `gender` / `category` / `note` 字段缺失。

- [ ] **Step 3: 新增 Alembic migration，补 glossary 三层字段**

```python
"""add glossary gender modeling"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0018_glossary_gender_modeling"
down_revision = "0017_translation_version_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ltw_glossary_draft_candidates",
        sa.Column("gender", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "ltw_glossary_candidates",
        sa.Column("category", sa.String(length=64), nullable=False, server_default="entity"),
    )
    op.add_column(
        "ltw_glossary_candidates",
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.add_column(
        "ltw_glossary_candidates",
        sa.Column("gender", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "ltw_glossary_entries",
        sa.Column("gender", sa.String(length=32), nullable=True),
    )

    op.alter_column("ltw_glossary_candidates", "category", server_default=None)


def downgrade() -> None:
    op.drop_column("ltw_glossary_entries", "gender")
    op.drop_column("ltw_glossary_candidates", "gender")
    op.drop_column("ltw_glossary_candidates", "note")
    op.drop_column("ltw_glossary_candidates", "category")
    op.drop_column("ltw_glossary_draft_candidates", "gender")
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
        status=status,
        term_group_key=term_group_key or source_term,
        relation_role=relation_role,
        scope_level=normalized_scope_level,
        scope_chapter_id=normalized_scope_chapter_id,
        workflow_run_id=workflow_run_id,
    )
```

- [ ] **Step 5: 重新跑 schema 测试，确认 migration、模型和 repository 同步生效**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_glossary_stage.py -k "glossary_schema_includes_gender_columns or glossary_candidate_creation_rejects_mismatched_project_chapter" -q`

Expected: PASS，输出 `2 passed`。

- [ ] **Step 6: 提交 Task 1**

```bash
git add migrations/versions/0018_glossary_gender_modeling.py app/db/models.py app/repositories/glossary.py tests/test_glossary_stage.py
git commit -m "feat: add glossary gender storage fields"
```

### Task 2: 在 `GlossaryService` 中实现 `gender` 归一、extract 解析和 finalize 落库

**Files:**
- Modify: `app/services/glossary_service.py`
- Modify: `app/services/glossary_pipeline_service.py`
- Modify: `tests/test_glossary_stage.py`
- Test: `tests/test_glossary_stage.py`

- [ ] **Step 1: 先写 extract/finalize 红测**

```python
def test_glossary_extract_normalizes_character_gender(
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
                            "source_term": "傅慕宁",
                            "translated_term": "Fu Muning",
                            "category": "character",
                            "gender": " Female ",
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
        request_id=request_id_factory("glossary-gender-normalize"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-glossary-gender",
    )

    draft = db_session.execute(
        select(GlossaryDraftCandidate).where(GlossaryDraftCandidate.project_id == project_id)
    ).scalar_one()

    assert draft.gender == "female"
```

```python
def test_glossary_extract_clears_gender_for_non_character_terms(
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
                            "gender": "male",
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
        request_id=request_id_factory("glossary-gender-non-character"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-glossary-gender",
    )

    draft = db_session.execute(
        select(GlossaryDraftCandidate).where(GlossaryDraftCandidate.project_id == project_id)
    ).scalar_one()

    assert draft.category == "location"
    assert draft.gender is None
```

```python
def test_glossary_finalize_persists_gender_to_candidate_and_entry(db_session) -> None:
    project = TranslationProject(
        request_id="glossary-finalize-gender-project",
        project_key="glossary-finalize-gender-project",
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
        request_id="glossary-finalize-gender-run",
        status="running",
        summary=None,
    )
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
    db_session.add_all([workflow_run, step_run])
    db_session.flush()

    repository = GlossaryRepository(db_session)
    repository.create_draft_candidate(
        workflow_run_id=workflow_run.id,
        project_id=project.id,
        chapter_id=chapter.id,
        source_term="傅慕宁",
        suggested_term="Fu Muning",
        category="character",
        gender="female",
        term_group_key="character-fu-muning",
        relation_role="canonical",
        scope_level="chapter_term",
        scope_chapter_id=chapter.id,
        evidence_payload={"note": "Character name"},
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
    assert entry.gender == "female"
    assert candidate.category == "character"
    assert candidate.note == "Character name"
    assert candidate.gender == "female"
```

- [ ] **Step 2: 跑红测，确认 `gender` 归一和落库逻辑还不存在**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_glossary_stage.py::test_glossary_extract_normalizes_character_gender tests\test_glossary_stage.py::test_glossary_extract_clears_gender_for_non_character_terms tests\test_glossary_stage.py::test_glossary_finalize_persists_gender_to_candidate_and_entry -q`

Expected: FAIL，断言提示 `GlossaryDraftCandidate` / `GlossaryCandidate` / `GlossaryEntry` 没有正确存 `gender`，或 `create_candidate(...)` 不接受 `category/note/gender`。

- [ ] **Step 3: 在 `GlossaryService` 里加入 `gender` 值模型与归一逻辑**

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
```

```python
def _normalize_gender(self, *, category: str, gender: object) -> str | None:
    normalized_category = self._normalize_text(category) or "term"
    if normalized_category != "character":
        return None
    normalized_gender = self._normalize_optional_text(gender)
    if normalized_gender is None:
        return None
    canonical = normalized_gender.strip().lower()
    if canonical in {"female", "male", "nonbinary"}:
        return canonical
    return None
```

```python
category = self._normalize_text(item.get("category")) or "term"
note = self._normalize_optional_text(item.get("note"))
gender = self._normalize_gender(category=category, gender=item.get("gender"))
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
    )
)
```

- [ ] **Step 4: 让 extract/finalize prompt 和 payload 都透传 `gender`**

```python
"每个术语对象字段：source_term, translated_term, category, note, term_group_key, relation_role, gender。\n"
"gender 仅在 category=character 且正文有明确线索时填写 female/male/nonbinary，否则返回 null。\n"
```

```python
evidence_payload={
    "workflow_step_run_id": workflow_step_run_id,
    "chapter_id": chapter.id,
    "chapter_index": chapter.chapter_index,
    "chapter_title": chapter.chapter_title,
    "note": item.note,
    "gender": item.gender,
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
            gender=term.get("gender", evidence_payload.get("gender")),
        ),
        "term_group_key": str(term.get("term_group_key") or relation_review.get("term_group_key") or matched_draft.term_group_key),
        "relation_role": str(term.get("relation_role") or relation_review.get("relation_role") or matched_draft.relation_role),
        "scope_level": scope_level,
        "scope_chapter_id": scope_chapter_id,
    }
)
```

- [ ] **Step 5: 在 finalize 落库与 inspect 输出里接住 `gender`**

```python
if entry is None:
    self.glossary.create_entry(
        project_id=project_id,
        source_term=str(item["source_term"]),
        target_term=str(item["target_term"]),
        category=str(item["category"]),
        note=self._normalize_optional_text(item.get("note")),
        gender=self._normalize_gender(category=str(item["category"]), gender=item.get("gender")),
        locked=0,
        term_group_key=str(item["term_group_key"]),
        relation_role=str(item["relation_role"]),
        scope_level=scope_level,
        scope_chapter_id=int(scope_chapter_id) if scope_chapter_id is not None else None,
    )
elif entry.locked == 0:
    entry.target_term = str(item["target_term"])
    entry.category = str(item["category"])
    entry.note = self._normalize_optional_text(item.get("note"))
    entry.gender = self._normalize_gender(category=entry.category, gender=item.get("gender"))
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
    status="pending",
    term_group_key=str(item["term_group_key"]),
    relation_role=str(item["relation_role"]),
    scope_level=scope_level,
    scope_chapter_id=int(scope_chapter_id) if scope_chapter_id is not None else None,
    workflow_run_id=workflow_run_id,
)
```

- [ ] **Step 6: 重新跑定点测试，确认 extract 归一与 finalize 落库通过**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_glossary_stage.py::test_glossary_extract_normalizes_character_gender tests\test_glossary_stage.py::test_glossary_extract_clears_gender_for_non_character_terms tests\test_glossary_stage.py::test_glossary_finalize_persists_gender_to_candidate_and_entry -q`

Expected: PASS，输出 `3 passed`。

- [ ] **Step 7: 提交 Task 2**

```bash
git add app/services/glossary_service.py app/services/glossary_pipeline_service.py tests/test_glossary_stage.py
git commit -m "feat: normalize glossary gender through finalize"
```

### Task 3: 增强 `inspect.glossary` / `glossary.inspect_pipeline`，并把 `gender` 接进 translation prompt 与 snapshot

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
def test_glossary_inspect_returns_gender_for_entries_candidates_and_pipeline(
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
                            "source_term": "傅慕宁",
                            "translated_term": "Fu Muning",
                            "category": "character",
                            "gender": "female",
                            "note": "Character name",
                            "term_group_key": "character-fu-muning",
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
        request_id=request_id_factory("glossary-inspect-gender"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-glossary-gender",
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
    assert data["entries"][0]["gender"] == "female"
    assert data["candidates"][0]["category"] == "character"
    assert data["candidates"][0]["note"] == "Character name"
    assert data["candidates"][0]["gender"] == "female"
    assert pipeline["draft_candidates"][0]["gender"] == "female"
```

```python
def test_translation_glossary_prompt_and_snapshot_include_gender(
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
        source_text="第1章 开始\n傅慕宁走进深蓝公寓。",
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
                source_term="傅慕宁",
                target_term="Fu Muning",
                category="character",
                note="Character name",
                gender="female",
                status="active",
                locked=0,
                term_group_key="character-fu-muning",
                relation_role="canonical",
            ),
            GlossaryEntry(
                project_id=project_id,
                source_term="深蓝公寓",
                target_term="Deep Blue Apartments",
                category="location",
                note="Apartment building",
                gender=None,
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
        request_id=request_id_factory("translation-gender-snapshot"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-translation-gender",
    )

    version = db_session.execute(
        select(SegmentTranslationVersion)
        .where(SegmentTranslationVersion.project_id == project_id)
        .order_by(SegmentTranslationVersion.id.asc())
    ).scalar_one()

    assert "gender: female" in str(provider.calls[0]["prompt"])
    assert "深蓝公寓 => Deep Blue Apartments" in str(provider.calls[0]["prompt"])
    assert "gender: None" not in str(provider.calls[0]["prompt"])

    payload_with_gender = json.dumps(
        [
            {
                "source_term": "傅慕宁",
                "target_term": "Fu Muning",
                "category": "character",
                "note": "Character name",
                "gender": "female",
                "status": "active",
                "locked": 0,
                "term_group_key": "character-fu-muning",
                "relation_role": "canonical",
            },
            {
                "source_term": "深蓝公寓",
                "target_term": "Deep Blue Apartments",
                "category": "location",
                "note": "Apartment building",
                "gender": None,
                "status": "active",
                "locked": 0,
                "term_group_key": "location-deep-blue-apartments",
                "relation_role": "independent",
            },
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    expected_snapshot_id = hashlib.sha256(payload_with_gender.encode("utf-8")).hexdigest()

    assert version.glossary_snapshot_id == expected_snapshot_id
```

- [ ] **Step 2: 跑红测，确认 inspect 与 translation 还没接住 `gender`**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_glossary_stage.py::test_glossary_inspect_returns_gender_for_entries_candidates_and_pipeline tests\test_translation_stage.py::test_translation_glossary_prompt_and_snapshot_include_gender -q`

Expected: FAIL，断言提示 `inspect.glossary` / `inspect_pipeline` 没有 `gender`，或者 `glossary_snapshot_id` 仍按旧 payload 计算。

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
        "status": candidate.status,
        "term_group_key": candidate.term_group_key,
        "relation_role": candidate.relation_role,
    }
    for candidate in self.glossary.list_candidates(project_id)
]
```

- [ ] **Step 4: 在单/多 translation 路径里统一注入 `gender`**

```python
def _format_glossary_entry(self, entry: GlossaryEntry) -> str:
    note_suffix = f" | note: {entry.note}" if entry.note else ""
    category_suffix = f" | category: {entry.category}" if entry.category else ""
    gender_suffix = f" | gender: {entry.gender}" if entry.gender else ""
    return (
        f"- {entry.source_term} => {entry.target_term}"
        f" | role: {entry.relation_role}"
        f" | group: {entry.term_group_key}"
        f"{category_suffix}{gender_suffix}{note_suffix}"
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

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_glossary_stage.py::test_glossary_inspect_returns_gender_for_entries_candidates_and_pipeline tests\test_translation_stage.py::test_translation_glossary_prompt_and_snapshot_include_gender -q`

Expected: PASS，输出 `2 passed`。

- [ ] **Step 6: 提交 Task 3**

```bash
git add app/repositories/glossary.py app/services/glossary_service.py app/services/translation_service.py app/services/translation_pipeline_service.py tests/test_glossary_stage.py tests/test_translation_stage.py
git commit -m "feat: expose glossary gender in inspect and translation"
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
- 本地正式术语表当前保存为 `source_term / target_term / category / note / gender / term_group_key / relation_role`
- `gender` 当前只对 `category=character` 生效，取值为 `female / male / nonbinary / null`
- `inspect.glossary` 现在会返回 `entries[*].gender`，以及 `candidates[*].category / note / gender`
- `translation` 的 glossary prompt 会在 `gender` 非空时注入 `| gender: ...`
- `glossary_snapshot_id` 现在会感知 `gender`
```

- [ ] **Step 2: 跑 glossary/translation 目标回归**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_glossary_stage.py tests\test_translation_stage.py -q`

Expected: PASS，输出的通过数高于当前新增测试前的基线，并且没有失败。

- [ ] **Step 3: 跑完整回归**

Run: `$env:LTW_TEST_DATABASE_URL='mysql+pymysql://abner:NsS4IhrMBSBVO46cIqbsTAlJTERsKeJ0@192.168.31.212:3307/abner_ltw_test'; D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests -q`

Expected: PASS，完整回归全部通过；如果基线从 `218` 增长，需把新数字同步回 README / roadmap / changelog。

- [ ] **Step 4: 提交 Task 4**

```bash
git add README.md docs/roadmap.md CHANGELOG.md tests/test_glossary_stage.py tests/test_translation_stage.py
git commit -m "docs: record glossary gender modeling rollout"
```

## 自检记录

- 规格覆盖：Task 1 对应 spec 的数据模型变更；Task 2 对应 extract/finalize/归一逻辑；Task 3 对应 inspect 与 translation 联动；Task 4 对应文档和完整回归，没有遗漏 spec 中的核心要求。
- 占位扫描：计划里没有 `TBD`、`TODO`、`implement later` 这类占位语；每个代码步骤都给了明确片段和命令。
- 命名一致性：全程统一使用 `gender`、`GlossaryExtraction.gender`、`_normalize_gender(...)`、`glossary_snapshot_id` 这些名称，没有前后漂移。
