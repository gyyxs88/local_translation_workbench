# Translation Inspect Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `inspect.translation` 增加当前 `active version` 的 provenance 链路，让返回结果能够解释“这条正式译文来自哪次 finalize、选中了哪条 draft、这条 draft 收到过哪些 review 结论”，同时保持现有 inspect 结构兼容。

**Architecture:** 在 `ltw_segment_translation_versions` 上新增 provenance 三元组字段，finalize 落正式版本时把 `workflow_run / finalize step / selected draft` 一次性写入；`TranslationService.inspect()` 继续保留现有 `translations + versions` 结构，只给 `translations[*]` 增加 `provenance` 字段，并对旧数据与未翻译段落稳定返回 `null`。

**Tech Stack:** Python 3、SQLAlchemy ORM、Alembic、pytest

---

## 文件结构

- Create: `migrations/versions/0017_translation_version_provenance.py`
  责任：给 `ltw_segment_translation_versions` 增加 provenance 三元组字段、索引和外键。
- Modify: `app/db/models.py`
  责任：为 `SegmentTranslationVersion` 增加 provenance 字段定义。
- Modify: `app/repositories/translations.py`
  责任：扩展 `create_version(...)`，让正式版本写入 provenance 指针。
- Modify: `app/services/translation_pipeline_service.py`
  责任：在 finalize job 中把 selected draft 的 provenance 元信息带到正式版本落库。
- Modify: `app/services/translation_service.py`
  责任：批量加载 finalize step、selected draft、selected draft reviews，并把 `provenance` 填到 `inspect.translation` 的 `translations[*]` 上。
- Modify: `tests/test_translation_stage.py`
  责任：补 schema、single workflow provenance、multi workflow provenance、legacy/null fallback 回归。
- Modify: `README.md`
  责任：补 `inspect.translation` 对 provenance 的说明。
- Modify: `CHANGELOG.md`
  责任：记录 translation inspect provenance 已落地。
- Modify: `docs/roadmap.md`
  责任：把 `P1.3` 第一刀的当前状态写进路线图。

---

### Task 1: 增加正式译文版本的 provenance 字段

**Files:**
- Create: `migrations/versions/0017_translation_version_provenance.py`
- Modify: `app/db/models.py`
- Modify: `app/repositories/translations.py`
- Test: `tests/test_translation_stage.py`

- [ ] **Step 1: 在测试文件里先写 schema 红测**

```python
def test_translation_schema_includes_version_provenance_columns(db_session) -> None:
    inspector = inspect(db_session.get_bind())
    columns = {
        column["name"]: column
        for column in inspector.get_columns("ltw_segment_translation_versions")
    }

    assert "origin_workflow_run_id" in columns
    assert "origin_step_run_id" in columns
    assert "origin_draft_version_id" in columns
    assert columns["origin_workflow_run_id"]["nullable"] is True
    assert columns["origin_step_run_id"]["nullable"] is True
    assert columns["origin_draft_version_id"]["nullable"] is True
```

- [ ] **Step 2: 跑 schema 红测，确认字段还不存在**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_stage.py -k "translation_schema_includes_version_provenance_columns" -q`

Expected: FAIL，断言提示 `origin_workflow_run_id` / `origin_step_run_id` / `origin_draft_version_id` 不存在。

- [ ] **Step 3: 新增 Alembic migration，给正式版本表加 provenance 三元组**

```python
"""add translation version provenance"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0017_translation_version_provenance"
down_revision = "0016_provider_health_fallback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ltw_segment_translation_versions",
        sa.Column("origin_workflow_run_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "ltw_segment_translation_versions",
        sa.Column("origin_step_run_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "ltw_segment_translation_versions",
        sa.Column("origin_draft_version_id", sa.Integer(), nullable=True),
    )

    op.create_index(
        "ix_ltw_segment_translation_versions_origin_workflow_run_id",
        "ltw_segment_translation_versions",
        ["origin_workflow_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_ltw_segment_translation_versions_origin_step_run_id",
        "ltw_segment_translation_versions",
        ["origin_step_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_ltw_segment_translation_versions_origin_draft_version_id",
        "ltw_segment_translation_versions",
        ["origin_draft_version_id"],
        unique=False,
    )

    op.create_foreign_key(
        "fk_stv_origin_workflow_run",
        "ltw_segment_translation_versions",
        "ltw_workflow_runs",
        ["origin_workflow_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_stv_origin_step_run",
        "ltw_segment_translation_versions",
        "ltw_workflow_step_runs",
        ["origin_step_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_stv_origin_draft_version",
        "ltw_segment_translation_versions",
        "ltw_translation_draft_versions",
        ["origin_draft_version_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_stv_origin_draft_version", "ltw_segment_translation_versions", type_="foreignkey")
    op.drop_constraint("fk_stv_origin_step_run", "ltw_segment_translation_versions", type_="foreignkey")
    op.drop_constraint("fk_stv_origin_workflow_run", "ltw_segment_translation_versions", type_="foreignkey")

    op.drop_index("ix_ltw_segment_translation_versions_origin_draft_version_id", table_name="ltw_segment_translation_versions")
    op.drop_index("ix_ltw_segment_translation_versions_origin_step_run_id", table_name="ltw_segment_translation_versions")
    op.drop_index("ix_ltw_segment_translation_versions_origin_workflow_run_id", table_name="ltw_segment_translation_versions")

    op.drop_column("ltw_segment_translation_versions", "origin_draft_version_id")
    op.drop_column("ltw_segment_translation_versions", "origin_step_run_id")
    op.drop_column("ltw_segment_translation_versions", "origin_workflow_run_id")
```

- [ ] **Step 4: 在模型和 repository 上接住新字段**

```python
class SegmentTranslationVersion(Base):
    __tablename__ = "ltw_segment_translation_versions"
    __table_args__ = (UniqueConstraint("segment_translation_id", "version_index"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_translation_projects.id", name="fk_stv_project", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    segment_translation_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_segment_translations.id", name="fk_stv_translation", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    origin_workflow_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ltw_workflow_runs.id", name="fk_stv_origin_workflow_run", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    origin_step_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ltw_workflow_step_runs.id", name="fk_stv_origin_step_run", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    origin_draft_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("ltw_translation_draft_versions.id", name="fk_stv_origin_draft_version", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
```

```python
def create_version(
    self,
    *,
    project_id: int,
    segment_translation_id: int,
    version_index: int,
    source_hash: str,
    glossary_snapshot_id: str,
    provider_name: str,
    model_profile_id: str,
    model_name: str,
    source_text: str,
    translated_text: str,
    translated_text_path: str,
    origin_workflow_run_id: int | None = None,
    origin_step_run_id: int | None = None,
    origin_draft_version_id: int | None = None,
    status: str = "completed",
) -> SegmentTranslationVersion:
    version = SegmentTranslationVersion(
        project_id=project_id,
        segment_translation_id=segment_translation_id,
        version_index=version_index,
        source_hash=source_hash,
        glossary_snapshot_id=glossary_snapshot_id,
        provider_name=provider_name,
        model_profile_id=model_profile_id,
        model_name=model_name,
        source_text=source_text,
        translated_text=translated_text,
        translated_text_path=translated_text_path,
        origin_workflow_run_id=origin_workflow_run_id,
        origin_step_run_id=origin_step_run_id,
        origin_draft_version_id=origin_draft_version_id,
        status=status,
    )
```

- [ ] **Step 5: 重新跑 schema 测试，确认 migration 和模型同步生效**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_stage.py -k "translation_schema_includes_version_provenance_columns or translation_schema_uses_unbounded_text_for_output_path" -q`

Expected: PASS，输出 `2 passed`。

- [ ] **Step 6: 提交 Task 1**

```bash
git add migrations/versions/0017_translation_version_provenance.py app/db/models.py app/repositories/translations.py tests/test_translation_stage.py
git commit -m "feat: add translation version provenance columns"
```

### Task 2: 在 finalize 时持久化 provenance，并让 single workflow 的 inspect 先跑通

**Files:**
- Modify: `app/services/translation_pipeline_service.py`
- Modify: `app/services/translation_service.py`
- Modify: `tests/test_translation_stage.py`
- Test: `tests/test_translation_stage.py`

- [ ] **Step 1: 先写 single workflow provenance 红测**

```python
def test_translation_inspect_includes_single_llm_active_version_provenance(
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

    provider = FakeProvider(
        outputs=[
            "源简介内容",
            "目标简介内容",
            "Single workflow draft",
        ]
    )
    TranslationService(db_session, base_data_dir=project_workspace, provider=provider).run(
        request_id=request_id_factory("translation-provenance-single"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-single-provenance",
    )

    data = TranslationService(db_session, base_data_dir=project_workspace).inspect(project_id=project_id)
    translated_row = next(item for item in data["translations"] if item["chapter_index"] == 1)
    version = db_session.execute(
        select(SegmentTranslationVersion).where(SegmentTranslationVersion.id == translated_row["active_version_id"])
    ).scalar_one()

    assert version.origin_workflow_run_id is not None
    assert version.origin_step_run_id is not None
    assert version.origin_draft_version_id is not None
    assert translated_row["provenance"]["finalize_step"]["step_key"] == "finalize_segments"
    assert translated_row["provenance"]["selected_draft"]["draft_role"] == "primary"
    assert translated_row["provenance"]["selected_draft"]["reviews"] == []
```

- [ ] **Step 2: 跑 red test，确认当前 finalize 还没有把 provenance 写进去**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_stage.py -k "single_llm_active_version_provenance" -q`

Expected: FAIL，断言提示 `origin_step_run_id` 为 `None` 或 `translated_row["provenance"]` 为 `None`。

- [ ] **Step 3: 在 finalize job 里把 selected draft 的 provenance 元信息一起传下去**

```python
def _build_finalize_segment_job(
    self,
    *,
    project_id: int,
    workflow_step_run_id: int,
    translation_root: Path,
    segment_id: int,
    segment_map: dict[int, tuple[Chapter, ChapterSegment]],
    selected: Any,
) -> dict[str, object]:
    chapter, segment = segment_map[segment_id]
    return {
        "project_id": project_id,
        "workflow_step_run_id": workflow_step_run_id,
        "translation_root": str(translation_root),
        "segment_id": segment_id,
        "chapter_index": int(chapter.chapter_index),
        "source_text_path": str(segment.source_text_path),
        "selected_draft": {
            "id": int(selected.id),
            "workflow_run_id": int(selected.workflow_run_id),
            "step_run_id": int(selected.step_run_id),
            "parent_draft_id": None if selected.parent_draft_id is None else int(selected.parent_draft_id),
            "draft_role": str(selected.draft_role),
            "source_hash": str(selected.source_hash),
            "glossary_snapshot_id": str(selected.glossary_snapshot_id),
            "provider_name": str(selected.provider_name),
            "model_profile_id": str(selected.model_profile_id),
            "model_name": str(selected.model_name),
            "translated_text": str(selected.translated_text),
            "translated_text_path": str(selected.translated_text_path),
            "status": str(selected.status),
            "evidence_payload": selected.evidence_payload,
            "fallback_depth": int(((selected.evidence_payload or {}).get("fallback_depth")) or 0),
        },
    }
```

```python
version = self.translations.create_version(
    project_id=int(job["project_id"]),
    segment_translation_id=translation.id,
    version_index=next_version_index,
    source_hash=str(selected_draft["source_hash"]),
    glossary_snapshot_id=str(selected_draft["glossary_snapshot_id"]),
    provider_name=str(selected_draft["provider_name"]),
    model_profile_id=str(selected_draft["model_profile_id"]),
    model_name=str(selected_draft["model_name"]),
    source_text=Path(str(job["source_text_path"])).read_text(encoding="utf-8"),
    translated_text=translated_text,
    translated_text_path=str(version_path),
    origin_workflow_run_id=int(selected_draft["workflow_run_id"]),
    origin_step_run_id=int(job["workflow_step_run_id"]),
    origin_draft_version_id=int(selected_draft["id"]),
    status="completed",
)
```

- [ ] **Step 4: 在 `inspect.translation` 里组装 single workflow 可用的 provenance**

```python
from ..db.models import (
    Chapter,
    ChapterSegment,
    ExportRun,
    GlossaryEntry,
    ReviewRun,
    SegmentTranslation,
    SegmentTranslationVersion,
    StageRun,
    TranslationDraftReview,
    TranslationDraftVersion,
    TranslationProject,
    WorkflowStepRun,
)
```

```python
def _build_translation_provenance_map(
    self,
    *,
    active_versions: list[SegmentTranslationVersion],
) -> dict[int, dict[str, object]]:
    tracked_versions = [
        version
        for version in active_versions
        if version.origin_step_run_id is not None and version.origin_draft_version_id is not None
    ]
    if not tracked_versions:
        return {}

    step_ids = sorted({int(version.origin_step_run_id) for version in tracked_versions})
    draft_ids = sorted({int(version.origin_draft_version_id) for version in tracked_versions})

    step_rows = {
        row.id: row
        for row in self.session.execute(
            select(WorkflowStepRun).where(WorkflowStepRun.id.in_(step_ids))
        ).scalars().all()
    }
    draft_rows = {
        row.id: row
        for row in self.session.execute(
            select(TranslationDraftVersion).where(TranslationDraftVersion.id.in_(draft_ids))
        ).scalars().all()
    }
    review_rows = self.session.execute(
        select(TranslationDraftReview)
        .where(TranslationDraftReview.draft_version_id.in_(draft_ids))
        .order_by(TranslationDraftReview.id.asc())
    ).scalars().all()

    reviews_by_draft: dict[int, list[TranslationDraftReview]] = {}
    for review in review_rows:
        reviews_by_draft.setdefault(int(review.draft_version_id), []).append(review)

    payload: dict[int, dict[str, object]] = {}
    for version in tracked_versions:
        step = step_rows.get(int(version.origin_step_run_id))
        draft = draft_rows.get(int(version.origin_draft_version_id))
        if step is None or draft is None:
            continue
        payload[int(version.id)] = {
            "finalize_step": {
                "step_run_id": int(step.id),
                "step_key": str(step.step_key),
                "action": str(step.action),
            },
            "selected_draft": {
                "id": int(draft.id),
                "workflow_run_id": int(draft.workflow_run_id),
                "step_run_id": int(draft.step_run_id),
                "draft_role": str(draft.draft_role),
                "parent_draft_id": None if draft.parent_draft_id is None else int(draft.parent_draft_id),
                "provider_name": str(draft.provider_name),
                "model_profile_id": str(draft.model_profile_id),
                "model_name": str(draft.model_name),
                "translated_text_path": str(draft.translated_text_path),
                "status": str(draft.status),
                "evidence_payload": draft.evidence_payload,
                "reviews": [
                    {
                        "id": int(review.id),
                        "step_run_id": int(review.step_run_id),
                        "review_type": str(review.review_type),
                        "decision": str(review.decision),
                        "score": review.score,
                        "reason_codes": review.reason_codes,
                        "structured_payload": review.structured_payload,
                    }
                    for review in reviews_by_draft.get(int(draft.id), [])
                ],
            },
        }
    return payload
```

```python
active_versions = [version for *_, version in rows if version is not None]
provenance_by_version_id = self._build_translation_provenance_map(active_versions=active_versions)

translations = [
    {
        "project_id": project_id,
        "chapter_id": chapter.id,
        "chapter_index": chapter.chapter_index,
        "chapter_title": chapter.chapter_title,
        "segment_id": segment.id,
        "segment_index": segment.segment_index,
        "translation_status": segment.translation_status,
        "review_status": segment.review_status,
        "active_version_id": None if segment_translation is None else segment_translation.active_version_id,
        "version": None if version is None else { ... },
        "provenance": None if version is None else provenance_by_version_id.get(int(version.id)),
    }
    for chapter, segment, segment_translation, version in rows
]
```

- [ ] **Step 5: 重新跑 single workflow provenance 测试**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_stage.py -k "single_llm_active_version_provenance" -q`

Expected: PASS，输出 `1 passed`。

- [ ] **Step 6: 提交 Task 2**

```bash
git add app/services/translation_pipeline_service.py app/services/translation_service.py tests/test_translation_stage.py
git commit -m "feat: persist translation provenance on finalize"
```

### Task 3: 覆盖 multi workflow 的 rewrite provenance 与 null fallback

**Files:**
- Modify: `tests/test_translation_stage.py`
- Modify: `app/services/translation_service.py`
- Test: `tests/test_translation_stage.py`

- [ ] **Step 1: 增加 multi workflow provenance 与 legacy/null fallback 红测**

```python
def test_translation_inspect_includes_multi_llm_rewrite_provenance(
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
    segment_id = db_session.execute(
        select(ChapterSegment.id)
        .where(ChapterSegment.project_id == project_id)
        .order_by(ChapterSegment.id.asc())
    ).scalars().first()
    assert segment_id is not None

    provider = FakeProvider(
        outputs=[
            "源简介内容",
            "目标简介内容",
            "Primary draft",
            "Secondary draft",
            json.dumps(
                {
                    "reviews": [
                        {
                            "segment_id": segment_id,
                            "draft_role": "primary",
                            "decision": "keep",
                            "score": 0.91,
                            "reason_codes": ["faithful"],
                            "issues": [],
                        },
                        {
                            "segment_id": segment_id,
                            "draft_role": "secondary",
                            "decision": "revise",
                            "score": 0.64,
                            "reason_codes": ["wording"],
                            "issues": ["措辞偏硬"],
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "drafts": [
                        {
                            "segment_id": segment_id,
                            "translated_text": "Rewrite draft",
                            "parent_draft_role": "primary",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
        ]
    )

    TranslationService(db_session, base_data_dir=project_workspace, provider=provider).run(
        request_id=request_id_factory("translation-provenance-multi"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-multi-provenance",
        workflow_key="translation_multi_llm_v1",
    )

    data = TranslationService(db_session, base_data_dir=project_workspace).inspect(project_id=project_id)
    translated_row = next(item for item in data["translations"] if item["chapter_index"] == 1)

    assert translated_row["version"]["translated_text"] == "Rewrite draft"
    assert translated_row["provenance"]["selected_draft"]["draft_role"] == "rewrite"
    assert translated_row["provenance"]["selected_draft"]["parent_draft_id"] is not None
    assert translated_row["provenance"]["selected_draft"]["reviews"] == []
```

```python
def test_translation_inspect_returns_null_provenance_for_legacy_active_version(
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

    TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=FakeProvider(outputs=["源简介内容", "目标简介内容", "Legacy draft"]),
    ).run(
        request_id=request_id_factory("translation-provenance-legacy"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-legacy-provenance",
    )

    active_version_id = db_session.execute(
        select(SegmentTranslation.active_version_id)
        .where(SegmentTranslation.project_id == project_id)
        .order_by(SegmentTranslation.id.asc())
    ).scalars().first()
    assert active_version_id is not None

    db_session.execute(
        update(SegmentTranslationVersion)
        .where(SegmentTranslationVersion.id == active_version_id)
        .values(
            origin_workflow_run_id=None,
            origin_step_run_id=None,
            origin_draft_version_id=None,
        )
    )
    db_session.commit()

    data = TranslationService(db_session, base_data_dir=project_workspace).inspect(project_id=project_id)
    translated_row = next(item for item in data["translations"] if item["chapter_index"] == 1)

    assert translated_row["active_version_id"] == active_version_id
    assert translated_row["provenance"] is None
```

并把现有未翻译段落测试补一条断言：

```python
assert pending_rows[0]["provenance"] is None
```

- [ ] **Step 2: 先跑这组红测**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_stage.py -k "multi_llm_rewrite_provenance or legacy_active_version or inspect_translation_includes_untranslated_segments" -q`

Expected: FAIL，至少一条会因为 `provenance` 结构缺字段或 legacy null fallback 不稳定而失败。

- [ ] **Step 3: 收紧 provenance 组装规则，保证 rewrite 和 null fallback 都稳定**

```python
def _build_translation_provenance_map(
    self,
    *,
    active_versions: list[SegmentTranslationVersion],
) -> dict[int, dict[str, object]]:
    tracked_versions = [
        version
        for version in active_versions
        if version.origin_step_run_id is not None and version.origin_draft_version_id is not None
    ]
    if not tracked_versions:
        return {}

    step_ids = sorted({int(version.origin_step_run_id) for version in tracked_versions})
    draft_ids = sorted({int(version.origin_draft_version_id) for version in tracked_versions})
    step_rows = {row.id: row for row in ...}
    draft_rows = {row.id: row for row in ...}
    review_rows = ...

    payload: dict[int, dict[str, object]] = {}
    for version in tracked_versions:
        step = step_rows.get(int(version.origin_step_run_id))
        draft = draft_rows.get(int(version.origin_draft_version_id))
        if step is None or draft is None:
            continue

        payload[int(version.id)] = {
            "finalize_step": {
                "step_run_id": int(step.id),
                "step_key": str(step.step_key),
                "action": str(step.action),
            },
            "selected_draft": {
                "id": int(draft.id),
                "workflow_run_id": int(draft.workflow_run_id),
                "step_run_id": int(draft.step_run_id),
                "draft_role": str(draft.draft_role),
                "parent_draft_id": None if draft.parent_draft_id is None else int(draft.parent_draft_id),
                "provider_name": str(draft.provider_name),
                "model_profile_id": str(draft.model_profile_id),
                "model_name": str(draft.model_name),
                "translated_text_path": str(draft.translated_text_path),
                "status": str(draft.status),
                "evidence_payload": draft.evidence_payload,
                "reviews": [
                    {
                        "id": int(review.id),
                        "step_run_id": int(review.step_run_id),
                        "review_type": str(review.review_type),
                        "decision": str(review.decision),
                        "score": review.score,
                        "reason_codes": review.reason_codes,
                        "structured_payload": review.structured_payload,
                    }
                    for review in reviews_by_draft.get(int(draft.id), [])
                ],
            },
        }
    return payload
```

这一步的验收点只有两个：

- 选中 rewrite draft 时，`parent_draft_id` 保留下来，`reviews` 稳定是空数组
- provenance 指针丢失时，`provenance` 稳定退化为 `null`

- [ ] **Step 4: 重新跑这组测试**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_stage.py -k "multi_llm_rewrite_provenance or legacy_active_version or inspect_translation_includes_untranslated_segments" -q`

Expected: PASS，输出 `3 passed`。

- [ ] **Step 5: 提交 Task 3**

```bash
git add app/services/translation_service.py tests/test_translation_stage.py
git commit -m "feat: expose translation inspect provenance"
```

### Task 4: 同步文档并完成全量验证

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/roadmap.md`
- Test: `tests/test_translation_stage.py`
- Test: `tests/test_translation_workflow_actions.py`
- Test: `tests`

- [ ] **Step 1: 更新 README、CHANGELOG 和 roadmap**

```md
### `inspect.translation`

查看翻译版本、当前激活版本，以及当前 active version 的 provenance。
当前 provenance 会解释：

- 这条正式译文来自哪次 `translation.finalize`
- finalize 最终选中了哪条 draft
- 这条 selected draft 收到过哪些 review 结论

必填参数只有：

- `project_id`
```

```md
## [Unreleased]

### 新增

- `inspect.translation` 已支持当前 active version 的 provenance 输出，能够显示 finalize step、selected draft 与 selected draft reviews。

### 变更

- translation 正式译文版本已补充 provenance 指针，便于后续历史追踪与问题排查。
```

```md
### 4.3 历史版本与可追踪性增强

范围：

- 已完成第一刀：`inspect.translation` 已支持 current active version 的 provenance，可直接查看 finalize step、selected draft 与 selected draft reviews。
- 后续继续补 translation/review/export 的更完整历史查看能力。
- 增加版本切换、对比、问题来源追踪所需的 inspect 能力。
```

- [ ] **Step 2: 跑 translation 相关回归**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_stage.py tests\test_translation_workflow_actions.py -q`

Expected: PASS，输出 `42 passed`。

- [ ] **Step 3: 跑完整回归**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests -q`

Expected: PASS，输出 `212 passed`。

- [ ] **Step 4: 提交 Task 4**

```bash
git add README.md CHANGELOG.md docs/roadmap.md
git commit -m "docs: record translation inspect provenance"
```

## Self-Review

- Spec 覆盖检查：
  - provenance 三元组落库：Task 1
  - finalize 写入 provenance：Task 2
  - `inspect.translation` 返回 `provenance`：Task 2
  - multi workflow rewrite provenance：Task 3
  - old data / untranslated null fallback：Task 3
  - 文档与完整回归：Task 4
- 占位符检查：全文没有 `TODO`、`TBD`、`待定` 这类占位语句。
- 类型一致性检查：
  - provenance 字段名统一为 `origin_workflow_run_id` / `origin_step_run_id` / `origin_draft_version_id`
  - inspect 返回统一使用 `provenance -> finalize_step / selected_draft / reviews`
  - 所有任务都沿用同一组 helper 和字段命名，没有前后漂移。
