# Translation Inspect Timeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `inspect.translation` 增加“当前 active version 来源链时间线”能力，让人工查看时能直接看到 selected draft、selected draft reviews 和 finalize 提交事件，不再手工拼 provenance 与 review 记录。

**Architecture:** 保持现有 `inspect.translation` action、参数和表结构不变，只在 `TranslationService.inspect()` 的 row payload 上新增 `timeline`。timeline 只围绕当前 active version 的 provenance 组装，事件范围固定为 `draft_created / review_created / finalize_committed`，并与现有 `provenance`、`compare` 并存。由于当前 timeline 依赖表没有独立 `created_at`，本轮 `occurred_at` 统一返回 `null`，排序改用稳定事件顺序而不伪造时间。实现上优先复用现有 active version、draft、review、step run 查询逻辑，在 `translation_service.py` 内部增加 shared history loader 和 timeline builder，避免引入新 service 或多余 repository 改造。

**Tech Stack:** Python 3、SQLAlchemy ORM、pytest、PowerShell CLI

---

## 文件结构

- Modify: `app/services/translation_service.py`
  责任：在 `inspect(...)`、`_inspect_project_translations(...)` 和 `_build_translation_row_payload(...)` 上新增 `timeline` 组装；增加 translation history loader、timeline builder、稳定事件排序和 step model name 解析 helper。
- Modify: `tests/test_translation_stage.py`
  责任：补 single workflow timeline、multi workflow timeline、legacy 空 timeline、step run 缺失退化、compare 共存、pending row 空 timeline 覆盖。
- Modify: `README.md`
  责任：补 `inspect.translation` 当前 active version 时间线能力说明。
- Modify: `docs/roadmap.md`
  责任：把 `P1.3` 第三刀 timeline 当前状态写入路线图。
- Modify: `CHANGELOG.md`
  责任：记录 translation inspect timeline 已落地。

---

### Task 1: 先用红测锁定单段与项目级 inspect 的基础时间线输出

**Files:**
- Modify: `tests/test_translation_stage.py`
- Modify: `app/services/translation_service.py`
- Test: `tests/test_translation_stage.py`

- [ ] **Step 1: 先写 pending row 与 single workflow timeline 的红测**

```python
def test_inspect_translation_includes_untranslated_segments(
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

    provider = FakeProvider()
    TranslationService(db_session, base_data_dir=project_workspace, provider=provider).run(
        request_id=request_id_factory("translation-partial"),
        project_id=project_id,
        scope={"type": "chapter_list", "chapters": [1]},
        model_profile_id="profile-inspect",
    )

    data = TranslationService(db_session, base_data_dir=project_workspace).inspect(project_id=project_id)
    pending_rows = [item for item in data["translations"] if item["chapter_index"] == 2]

    assert len(pending_rows) == 1
    assert pending_rows[0]["active_version_id"] is None
    assert pending_rows[0]["timeline"] == []


def test_translation_inspect_single_workflow_timeline_includes_draft_and_finalize_events(
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

    provider = FakeProvider(outputs=["源简介内容", "目标简介内容", "Single workflow draft"])
    TranslationService(db_session, base_data_dir=project_workspace, provider=provider).run(
        request_id=request_id_factory("translation-timeline-single"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-timeline-single",
    )

    payload = TranslationService(db_session, base_data_dir=project_workspace).inspect(project_id=project_id)
    row = next(item for item in payload["translations"] if item["chapter_index"] == 1)

    assert [event["type"] for event in row["timeline"]] == [
        "draft_created",
        "finalize_committed",
    ]
    assert row["timeline"][0]["payload"]["draft_role"] == "primary"
    assert row["timeline"][1]["payload"]["translation_version_id"] == row["active_version_id"]
```

- [ ] **Step 2: 跑这两条测试，确认当前实现还没有 timeline**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_stage.py -k "untranslated_segments or single_workflow_timeline" -q`

Expected: FAIL，报错要么是 `KeyError: 'timeline'`，要么是 timeline 断言失败；不能直接绿。

- [ ] **Step 3: 先把 inspect row 的 timeline plumbing 接起来，并实现最小 single timeline**

```python
def inspect(
    self,
    *,
    project_id: int,
    segment_id: int | None = None,
    chapter_index: int | None = None,
    segment_index: int | None = None,
    compare_version_id: int | None = None,
) -> dict[str, list[dict[str, object]]]:
    self._validate_inspect_translation_locator(
        segment_id=segment_id,
        chapter_index=chapter_index,
        segment_index=segment_index,
        compare_version_id=compare_version_id,
    )
    if segment_id is None and chapter_index is None and segment_index is None:
        return self._inspect_project_translations(project_id=project_id)

    chapter, segment, segment_translation, version = self._resolve_single_translation_row(
        project_id=project_id,
        segment_id=segment_id,
        chapter_index=chapter_index,
        segment_index=segment_index,
    )
    active_versions = [] if version is None else [version]
    provenance_by_version_id = self._build_translation_provenance_map(active_versions=active_versions)
    timeline_by_version_id = self._build_translation_timeline_map(active_versions=active_versions)
    translation_row = self._build_translation_row_payload(
        project_id=project_id,
        chapter=chapter,
        segment=segment,
        segment_translation=segment_translation,
        version=version,
        provenance_by_version_id=provenance_by_version_id,
        timeline_by_version_id=timeline_by_version_id,
    )
    if compare_version_id is not None:
        translation_row["compare"] = self._build_translation_compare_payload(
            project_id=project_id,
            translation=segment_translation,
            current_version=version,
            compare_version_id=compare_version_id,
        )
    versions = []
    if segment_translation is not None:
        versions = [
            self._build_translation_version_list_payload(item)
            for item in self.translations.list_versions_for_translation(int(segment_translation.id))
        ]
    return {"translations": [translation_row], "versions": versions}


def _build_translation_row_payload(
    self,
    *,
    project_id: int,
    chapter: Chapter,
    segment: ChapterSegment,
    segment_translation: SegmentTranslation | None,
    version: SegmentTranslationVersion | None,
    provenance_by_version_id: dict[int, dict[str, object]],
    timeline_by_version_id: dict[int, list[dict[str, object]]],
) -> dict[str, object]:
    return {
        "project_id": project_id,
        "chapter_id": int(chapter.id),
        "chapter_index": int(chapter.chapter_index),
        "chapter_title": str(chapter.chapter_title),
        "segment_id": int(segment.id),
        "segment_index": int(segment.segment_index),
        "translation_status": str(segment.translation_status),
        "review_status": str(segment.review_status),
        "active_version_id": (
            None
            if segment_translation is None or segment_translation.active_version_id is None
            else int(segment_translation.active_version_id)
        ),
        "version": None if version is None else self._build_translation_version_payload(version),
        "provenance": None if version is None else provenance_by_version_id.get(int(version.id)),
        "timeline": [] if version is None else list(timeline_by_version_id.get(int(version.id), [])),
    }


def _build_translation_timeline_map(
    self,
    *,
    active_versions: list[SegmentTranslationVersion],
) -> dict[int, list[dict[str, object]]]:
    timeline_by_version_id: dict[int, list[dict[str, object]]] = {}
    for version in active_versions:
        if version.origin_draft_version_id is None:
            continue
        draft = self.session.get(TranslationDraftVersion, int(version.origin_draft_version_id))
        if draft is None:
            timeline_by_version_id[int(version.id)] = [self._build_finalize_timeline_event(version=version, step=None)]
            continue
        timeline_by_version_id[int(version.id)] = [
            self._build_draft_timeline_event(draft=draft, step=self.session.get(WorkflowStepRun, int(draft.step_run_id))),
            self._build_finalize_timeline_event(
                version=version,
                step=None if version.origin_step_run_id is None else self.session.get(WorkflowStepRun, int(version.origin_step_run_id)),
            ),
        ]
    return timeline_by_version_id
```

- [ ] **Step 4: 重新跑 Task 1 的目标测试，确认基础 timeline 已经落出来**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_stage.py -k "untranslated_segments or single_workflow_timeline" -q`

Expected: PASS，输出 `2 passed`。

- [ ] **Step 5: Commit**

```bash
git add tests/test_translation_stage.py app/services/translation_service.py
git commit -m "feat: add basic translation inspect timeline"
```

---

### Task 2: 补齐 multi workflow review 事件与 compare 共存路径

**Files:**
- Modify: `tests/test_translation_stage.py`
- Modify: `app/services/translation_service.py`
- Test: `tests/test_translation_stage.py`

- [ ] **Step 1: 写 multi workflow timeline 和 compare 共存的红测**

```python
def test_translation_inspect_multi_workflow_timeline_includes_selected_draft_reviews(
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
        request_id=request_id_factory("translation-timeline-multi"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-timeline-multi",
        workflow_key="translation_multi_llm_v1",
    )

    active_version = db_session.execute(
        select(SegmentTranslationVersion)
        .where(SegmentTranslationVersion.project_id == project_id)
        .order_by(SegmentTranslationVersion.id.asc())
    ).scalar_one()
    selected_draft_id = active_version.origin_draft_version_id
    assert selected_draft_id is not None

    review_step = WorkflowStepRun(
        workflow_run_id=active_version.origin_workflow_run_id,
        step_key="review_drafts",
        action="translation.review_draft",
        llm_role="reviewer",
        model_profile_id="profile-review-selected",
        provider_name="fake",
        provider_model_name="model-review-selected",
        status="completed",
        output_payload={"actual_model_name": "model-review-selected"},
        summary=json.dumps({"provider_model_name": "model-review-selected"}, ensure_ascii=False),
    )
    db_session.add(review_step)
    db_session.flush()
    db_session.add(
        TranslationDraftReview(
            draft_version_id=int(selected_draft_id),
            step_run_id=int(review_step.id),
            review_type="quality",
            decision="keep",
            score=0.98,
            reason_codes=["faithful"],
            structured_payload={"issues": []},
        )
    )
    db_session.commit()

    payload = TranslationService(db_session, base_data_dir=project_workspace).inspect(project_id=project_id)
    row = next(item for item in payload["translations"] if item["chapter_index"] == 1)

    assert [event["type"] for event in row["timeline"]] == [
        "draft_created",
        "review_created",
        "finalize_committed",
    ]
    assert row["timeline"][0]["occurred_at"] is None
    assert row["timeline"][0]["payload"]["draft_role"] == "rewrite"
    assert row["timeline"][1]["payload"]["decision"] == "keep"


def test_translation_inspect_compare_mode_still_returns_timeline(
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

    service = TranslationService(db_session, base_data_dir=project_workspace, provider=FakeProvider())
    service.run(
        request_id=request_id_factory("translation-timeline-compare-base"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-timeline-compare-base",
    )
    service.run(
        request_id=request_id_factory("translation-timeline-compare-current"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-timeline-compare-current",
    )

    first_segment = db_session.execute(
        select(ChapterSegment.id)
        .where(ChapterSegment.project_id == project_id)
        .order_by(ChapterSegment.id.asc())
    ).scalars().first()
    translation = db_session.execute(
        select(SegmentTranslation)
        .where(
            SegmentTranslation.project_id == project_id,
            SegmentTranslation.segment_id == first_segment,
        )
    ).scalar_one()
    base_version = db_session.execute(
        select(SegmentTranslationVersion.id)
        .where(SegmentTranslationVersion.segment_translation_id == translation.id)
        .order_by(SegmentTranslationVersion.version_index.asc())
    ).scalars().first()

    payload = TranslationService(db_session, base_data_dir=project_workspace).inspect(
        project_id=project_id,
        segment_id=int(first_segment),
        compare_version_id=int(base_version),
    )

    row = payload["translations"][0]
    assert row["compare"]["changed"] is True
    assert [event["type"] for event in row["timeline"]] == [
        "draft_created",
        "finalize_committed",
    ]
```

- [ ] **Step 2: 跑这两条测试，确认当前实现还没把 review 事件与 compare 共存补齐**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_stage.py -k "multi_workflow_timeline or compare_mode_still_returns_timeline" -q`

Expected: FAIL。multi workflow 测试至少会因为 timeline 里缺 review 事件或 draft 角色不对而失败；compare 共存测试如果 timeline 丢失也应该失败。

- [ ] **Step 3: 把 selected draft reviews 和 step run 元数据补进 timeline builder**

```python
def _build_translation_timeline_map(
    self,
    *,
    active_versions: list[SegmentTranslationVersion],
) -> dict[int, list[dict[str, object]]]:
    context = self._load_translation_history_context(active_versions=active_versions)
    timeline_by_version_id: dict[int, list[dict[str, object]]] = {}

    for version in context["tracked_versions"]:
        events: list[dict[str, object]] = []
        draft = context["draft_rows"].get(int(version.origin_draft_version_id))
        if draft is not None:
            draft_step = context["step_rows"].get(int(draft.step_run_id))
            events.append(self._build_draft_timeline_event(draft=draft, step=draft_step))
            for review in context["reviews_by_draft"].get(int(draft.id), []):
                review_step = context["step_rows"].get(int(review.step_run_id))
                events.append(self._build_review_timeline_event(review=review, step=review_step))

        finalize_step = None
        if version.origin_step_run_id is not None:
            finalize_step = context["step_rows"].get(int(version.origin_step_run_id))
        events.append(self._build_finalize_timeline_event(version=version, step=finalize_step))
        timeline_by_version_id[int(version.id)] = self._sort_translation_timeline(events)

    return timeline_by_version_id


def _load_translation_history_context(
    self,
    *,
    active_versions: list[SegmentTranslationVersion],
) -> dict[str, object]:
    tracked_versions = [version for version in active_versions if version.origin_draft_version_id is not None]
    draft_ids = sorted({int(version.origin_draft_version_id) for version in tracked_versions})
    draft_rows = {
        int(row.id): row
        for row in self.session.execute(
            select(TranslationDraftVersion).where(TranslationDraftVersion.id.in_(draft_ids))
        ).scalars().all()
    }
    review_rows = self.session.execute(
        select(TranslationDraftReview)
        .where(TranslationDraftReview.draft_version_id.in_(draft_ids))
        .order_by(TranslationDraftReview.created_at.asc(), TranslationDraftReview.id.asc())
    ).scalars().all()
    reviews_by_draft: dict[int, list[TranslationDraftReview]] = {}
    for review in review_rows:
        reviews_by_draft.setdefault(int(review.draft_version_id), []).append(review)

    step_ids = sorted(
        {
            int(step_id)
            for step_id in (
                [version.origin_step_run_id for version in tracked_versions]
                + [draft.step_run_id for draft in draft_rows.values()]
                + [review.step_run_id for review in review_rows]
            )
            if step_id is not None
        }
    )
    step_rows = {
        int(row.id): row
        for row in self.session.execute(
            select(WorkflowStepRun).where(WorkflowStepRun.id.in_(step_ids))
        ).scalars().all()
    }
    return {
        "tracked_versions": tracked_versions,
        "draft_rows": draft_rows,
        "reviews_by_draft": reviews_by_draft,
        "step_rows": step_rows,
    }


def _resolve_timeline_step_model_name(self, *, step: WorkflowStepRun | None, fallback_model_name: str | None) -> str | None:
    if step is not None and isinstance(step.output_payload, dict):
        actual_model_name = step.output_payload.get("actual_model_name")
        if isinstance(actual_model_name, str) and actual_model_name.strip() != "":
            return actual_model_name
    if step is not None and isinstance(step.summary, str) and step.summary.strip() != "":
        try:
            summary_payload = json.loads(step.summary)
        except json.JSONDecodeError:
            summary_payload = {}
        provider_model_name = summary_payload.get("provider_model_name")
        if isinstance(provider_model_name, str) and provider_model_name.strip() != "":
            return provider_model_name
    return fallback_model_name


def _sort_translation_timeline(self, events: list[dict[str, object]]) -> list[dict[str, object]]:
    priority = {
        "draft_created": 0,
        "review_created": 1,
        "finalize_committed": 2,
    }
    def build_tie_breaker(item: dict[str, object]) -> int:
        payload = item.get("payload")
        if not isinstance(payload, dict):
            return 0
        if item["type"] == "draft_created":
            return int(payload.get("draft_version_id") or 0)
        if item["type"] == "review_created":
            return int(payload.get("review_id") or 0)
        if item["type"] == "finalize_committed":
            return int(payload.get("translation_version_id") or 0)
        return 0
    return sorted(
        events,
        key=lambda item: (
            int(priority.get(str(item["type"]), 99)),
            int(build_tie_breaker(item)),
        ),
    )
```

- [ ] **Step 4: 重新跑 Task 2 的目标测试，确认 multi workflow review 事件和 compare 共存都稳定**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_stage.py -k "multi_workflow_timeline or compare_mode_still_returns_timeline" -q`

Expected: PASS，输出 `2 passed`。

- [ ] **Step 5: Commit**

```bash
git add tests/test_translation_stage.py app/services/translation_service.py
git commit -m "feat: add translation inspect review timeline events"
```

---

### Task 3: 补 legacy 与 step run 缺失退化，让 timeline 只保留可信事件

**Files:**
- Modify: `tests/test_translation_stage.py`
- Modify: `app/services/translation_service.py`
- Test: `tests/test_translation_stage.py`

- [ ] **Step 1: 写 legacy 空 timeline 和 step run 缺失退化的红测**

```python
def test_translation_inspect_returns_empty_timeline_for_legacy_active_version(
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
        request_id=request_id_factory("translation-timeline-legacy"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-timeline-legacy",
    )

    active_version_id = db_session.execute(
        select(SegmentTranslation.active_version_id)
        .where(SegmentTranslation.project_id == project_id)
        .order_by(SegmentTranslation.id.asc())
    ).scalars().first()

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

    payload = TranslationService(db_session, base_data_dir=project_workspace).inspect(project_id=project_id)
    row = next(item for item in payload["translations"] if item["chapter_index"] == 1)
    assert row["timeline"] == []


def test_translation_inspect_timeline_keeps_finalize_event_when_step_run_is_missing(
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
        provider=FakeProvider(outputs=["源简介内容", "目标简介内容", "Single workflow draft"]),
    ).run(
        request_id=request_id_factory("translation-timeline-missing-step"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-timeline-missing-step",
    )

    active_version = db_session.execute(
        select(SegmentTranslationVersion)
        .where(SegmentTranslationVersion.project_id == project_id)
        .order_by(SegmentTranslationVersion.id.asc())
    ).scalar_one()
    assert active_version.origin_step_run_id is not None

    db_session.execute(
        delete(WorkflowStepRun).where(WorkflowStepRun.id == active_version.origin_step_run_id)
    )
    db_session.commit()

    payload = TranslationService(db_session, base_data_dir=project_workspace).inspect(project_id=project_id)
    row = next(item for item in payload["translations"] if item["chapter_index"] == 1)
    finalize_event = next(event for event in row["timeline"] if event["type"] == "finalize_committed")

    assert finalize_event["step_run_id"] is None
    assert finalize_event["step_key"] is None
    assert finalize_event["action"] is None
```

- [ ] **Step 2: 跑这两条测试，确认当前实现还没完整处理退化语义**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_stage.py -k "legacy_active_version or missing_step" -q`

Expected: FAIL。至少一条会因为 timeline 没有退化成 spec 规定的稳定输出而失败。

- [ ] **Step 3: 把 timeline builder 收口成“尽量保留可信事件”的退化规则**

```python
def _build_translation_timeline_map(
    self,
    *,
    active_versions: list[SegmentTranslationVersion],
) -> dict[int, list[dict[str, object]]]:
    context = self._load_translation_history_context(active_versions=active_versions)
    timeline_by_version_id: dict[int, list[dict[str, object]]] = {}

    for version in active_versions:
        if version.origin_draft_version_id is None:
            continue

        events: list[dict[str, object]] = []
        draft = context["draft_rows"].get(int(version.origin_draft_version_id))
        if draft is not None:
            draft_step = context["step_rows"].get(int(draft.step_run_id))
            events.append(self._build_draft_timeline_event(draft=draft, step=draft_step))
            for review in context["reviews_by_draft"].get(int(draft.id), []):
                review_step = context["step_rows"].get(int(review.step_run_id))
                events.append(self._build_review_timeline_event(review=review, step=review_step))

        finalize_step = None
        if version.origin_step_run_id is not None:
            finalize_step = context["step_rows"].get(int(version.origin_step_run_id))
        events.append(self._build_finalize_timeline_event(version=version, step=finalize_step))
        timeline_by_version_id[int(version.id)] = self._sort_translation_timeline(events)

    return timeline_by_version_id


def _build_finalize_timeline_event(
    self,
    *,
    version: SegmentTranslationVersion,
    step: WorkflowStepRun | None,
) -> dict[str, object]:
    return {
        "type": "finalize_committed",
        "occurred_at": None,
        "step_run_id": None if version.origin_step_run_id is None else int(version.origin_step_run_id),
        "step_key": None if step is None else str(step.step_key),
        "action": None if step is None else str(step.action),
        "model_profile_id": str(version.model_profile_id),
        "model_name": str(version.model_name),
        "payload": {
            "translation_version_id": int(version.id),
            "version_index": int(version.version_index),
            "status": str(version.status),
        },
    }
```

- [ ] **Step 4: 重新跑 Task 3 的目标测试，确认 legacy 与 step run 缺失路径稳定**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_stage.py -k "legacy_active_version or missing_step" -q`

Expected: PASS，输出 `2 passed`。

- [ ] **Step 5: Commit**

```bash
git add tests/test_translation_stage.py app/services/translation_service.py
git commit -m "feat: harden translation inspect timeline fallback"
```

---

### Task 4: 跑回归并同步 README、路线图和变更记录

**Files:**
- Modify: `README.md`
- Modify: `docs/roadmap.md`
- Modify: `CHANGELOG.md`
- Test: `tests/test_translation_stage.py`

- [ ] **Step 1: 先补 README 的 inspect.translation 时间线说明**

```md
`inspect.translation` 现在除 `version / provenance / compare` 外，还会在每条 `translations[*]` 上返回 `timeline`。

- `timeline` 只解释当前 active version 的来源链
- 当前事件类型固定为：
  - `draft_created`
  - `review_created`
  - `finalize_committed`
- 没有 active version 或 provenance 缺失时，`timeline` 返回空数组 `[]`
```

- [ ] **Step 2: 更新路线图和 CHANGELOG**

```md
### 4.3 历史版本与可追踪性增强

- 已完成第三刀：`inspect.translation` 已支持当前 active version 的来源链 timeline，可直接查看 selected draft、selected draft reviews 与 finalize 提交事件。
```

```md
## Unreleased

- `inspect.translation` 新增当前 active version 来源链 `timeline`，事件覆盖 `draft_created / review_created / finalize_committed`。
```

- [ ] **Step 3: 先跑 timeline 目标回归**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_stage.py -k "timeline or provenance or compare" -q`

Expected: PASS，输出通过数大于当前 timeline 新增用例数；不能有失败。

- [ ] **Step 4: 再跑 review/export 冒烟，确认 inspect.translation 没把外围 inspect 打坏**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_review_export.py::test_cli_inspect_translation_review_export -q`

Expected: PASS，输出 `1 passed`。

- [ ] **Step 5: 跑完整回归并刷新文档基线**

Run: `$env:LTW_TEST_DATABASE_URL='mysql+pymysql://abner:NsS4IhrMBSBVO46cIqbsTAlJTERsKeJ0@192.168.31.212:3307/abner_ltw_test'; D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests -q`

Expected: PASS，完整套件全绿；把 README / roadmap / changelog 里的回归基线更新成最新真实通过数。

- [ ] **Step 6: Commit**

```bash
git add README.md docs/roadmap.md CHANGELOG.md tests/test_translation_stage.py app/services/translation_service.py
git commit -m "docs: record translation inspect timeline rollout"
```

---

## 自检清单

- [ ] spec 覆盖检查：timeline 范围只覆盖当前 active version 来源链，没有把 full timeline、review/export 时间线或 `active_version_switched` 偷渡进来。
- [ ] 时间语义检查：`occurred_at` 当前实现统一为 `null`，不要再次引用不存在的 `created_at` 字段。
- [ ] 命名一致性检查：统一使用 `timeline`、`draft_created`、`review_created`、`finalize_committed`、`compare` 这些已经定稿的名字。
- [ ] 退化语义检查：`provenance` 仍然保持“缺链即空”，`timeline` 保持“尽量保留可信事件”，两者不能写反。
- [ ] 回归命令检查：所有 pytest 命令都可直接从当前仓库根目录执行，且完整回归显式注入 `LTW_TEST_DATABASE_URL`。
