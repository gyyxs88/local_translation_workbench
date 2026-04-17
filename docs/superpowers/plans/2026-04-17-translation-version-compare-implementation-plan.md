# Translation Inspect Version Compare Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `inspect.translation` 增加“当前 active version vs 指定历史正式版本”的单段 compare 能力，让人工排查时能直接看到文本和关键元数据的变化摘要。

**Architecture:** 保持现有 `inspect.translation` action 不变，在 `TranslationService.inspect()` 上增加单段定位和 `compare_version_id` 两组可选参数。普通项目模式继续返回整项目 `translations + versions`；单段 compare 模式只返回一个 segment，并在当前 translation 行上追加 `compare` 字段，同时复用现有 version payload 与 provenance 组装逻辑。

**Tech Stack:** Python 3、SQLAlchemy ORM、pytest、PowerShell CLI

---

## 文件结构

- Modify: `app/services/translation_service.py`
  责任：为 `inspect(...)` 增加单段模式、compare 模式、参数校验、目标 segment 解析与 compare payload 组装。
- Modify: `app/repositories/translations.py`
  责任：补正式版本按 `version_id` 读取 helper，供 compare 目标解析使用。
- Modify: `app/action_router.py`
  责任：为 `inspect.translation` 透传 `segment_id / chapter_index / segment_index / compare_version_id`。
- Modify: `tests/test_translation_stage.py`
  责任：补 service compare 成功、错误语义、单段模式与 CLI compare 覆盖。
- Modify: `README.md`
  责任：补 `inspect.translation` 的单段 compare 用法和参数说明。
- Modify: `docs/roadmap.md`
  责任：把 `P1.3` 第二刀的当前状态写入路线图。
- Modify: `CHANGELOG.md`
  责任：记录 translation inspect version compare 已落地。

---

### Task 1: 先用红测锁定单段 compare 的成功路径

**Files:**
- Modify: `tests/test_translation_stage.py`
- Modify: `app/repositories/translations.py`
- Modify: `app/services/translation_service.py`
- Test: `tests/test_translation_stage.py`

- [ ] **Step 1: 先写 compare 成功和单段 inspect 收窄的红测**

```python
def test_translation_inspect_compare_returns_active_and_base_versions_for_single_segment(
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

    service = TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=FakeProvider(),
    )
    service.run(
        request_id=request_id_factory("translation-compare-base"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-compare-base",
    )
    service.run(
        request_id=request_id_factory("translation-compare-current"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-compare-current",
    )

    first_segment = db_session.execute(
        select(ChapterSegment.id)
        .where(ChapterSegment.project_id == project_id)
        .order_by(ChapterSegment.id.asc())
    ).scalars().first()
    assert first_segment is not None

    translation = db_session.execute(
        select(SegmentTranslation)
        .where(
            SegmentTranslation.project_id == project_id,
            SegmentTranslation.segment_id == first_segment,
        )
    ).scalar_one()
    versions = db_session.execute(
        select(SegmentTranslationVersion)
        .where(SegmentTranslationVersion.segment_translation_id == translation.id)
        .order_by(SegmentTranslationVersion.version_index.asc())
    ).scalars().all()

    payload = TranslationService(db_session, base_data_dir=project_workspace).inspect(
        project_id=project_id,
        segment_id=first_segment,
        compare_version_id=int(versions[0].id),
    )

    assert len(payload["translations"]) == 1
    assert len(payload["versions"]) == 2
    row = payload["translations"][0]
    assert row["segment_id"] == first_segment
    assert row["active_version_id"] == translation.active_version_id
    assert row["compare"]["base_version"]["id"] == int(versions[0].id)
    assert row["compare"]["current_version"]["id"] == int(versions[1].id)
    assert row["compare"]["changed"] is True
    assert row["compare"]["summary"]["translated_text_changed"] is True
    assert row["compare"]["summary"]["source_hash_changed"] is False
    assert row["compare"]["summary"]["glossary_snapshot_changed"] is False
    assert row["compare"]["summary"]["model_profile_changed"] is True
    assert row["compare"]["summary"]["model_name_changed"] is True
    assert row["compare"]["summary"]["status_changed"] is False
    assert row["provenance"] is not None


def test_translation_inspect_single_segment_without_compare_limits_versions_to_target_segment(
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

    service = TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=FakeProvider(),
    )
    service.run(
        request_id=request_id_factory("translation-single-segment-a"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 2},
        model_profile_id="profile-single-segment-a",
    )
    service.run(
        request_id=request_id_factory("translation-single-segment-b"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-single-segment-b",
    )

    payload = TranslationService(db_session, base_data_dir=project_workspace).inspect(
        project_id=project_id,
        chapter_index=1,
        segment_index=1,
    )

    row = payload["translations"][0]
    target_translation_id = db_session.execute(
        select(SegmentTranslation.id)
        .where(
            SegmentTranslation.project_id == project_id,
            SegmentTranslation.segment_id == row["segment_id"],
        )
    ).scalar_one()

    assert len(payload["translations"]) == 1
    assert row["segment_index"] == 1
    assert all(version["segment_translation_id"] == int(target_translation_id) for version in payload["versions"])
    assert all(version["version_index"] in {1, 2} for version in payload["versions"])
    assert "compare" not in row
```

- [ ] **Step 2: 跑红测，确认当前 inspect 还不支持 compare 和单段 versions 收窄**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_stage.py::test_translation_inspect_compare_returns_active_and_base_versions_for_single_segment tests\test_translation_stage.py::test_translation_inspect_single_segment_without_compare_limits_versions_to_target_segment -q`

Expected: FAIL，至少一条会因为 `TranslationService.inspect()` 不接受 `segment_id` / `compare_version_id`，或因为单段模式仍返回整项目 versions 而失败。

- [ ] **Step 3: 在 repository 加按主键读取正式版本 helper**

```python
def get_version_by_id(self, version_id: int) -> SegmentTranslationVersion | None:
    return self.session.get(SegmentTranslationVersion, version_id)
```

- [ ] **Step 4: 在 `TranslationService.inspect()` 上增加单段模式和 compare payload 组装**

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

    chapter, segment, translation, version = self._resolve_single_translation_row(
        project_id=project_id,
        segment_id=segment_id,
        chapter_index=chapter_index,
        segment_index=segment_index,
    )
    active_versions = [] if version is None else [version]
    provenance_by_version_id = self._build_translation_provenance_map(active_versions=active_versions)
    compare_payload = None
    if compare_version_id is not None:
        compare_payload = self._build_translation_compare_payload(
            project_id=project_id,
            translation=translation,
            current_version=version,
            compare_version_id=compare_version_id,
        )

    row = self._build_translation_row_payload(
        project_id=project_id,
        chapter=chapter,
        segment=segment,
        segment_translation=translation,
        version=version,
        provenance_by_version_id=provenance_by_version_id,
    )
    if compare_payload is not None:
        row["compare"] = compare_payload

    version_rows = (
        []
        if translation is None
        else [
            self._build_translation_version_payload(item)
            for item in self.translations.list_versions_for_translation(int(translation.id))
        ]
    )
    return {"translations": [row], "versions": version_rows}
```

```python
def _inspect_project_translations(self, *, project_id: int) -> dict[str, list[dict[str, object]]]:
    statement = (
        select(Chapter, ChapterSegment, SegmentTranslation, SegmentTranslationVersion)
        .join(ChapterSegment, ChapterSegment.chapter_id == Chapter.id)
        .outerjoin(
            SegmentTranslation,
            SegmentTranslation.segment_id == ChapterSegment.id,
        )
        .outerjoin(SegmentTranslationVersion, SegmentTranslationVersion.id == SegmentTranslation.active_version_id)
        .where(
            Chapter.project_id == project_id,
            ChapterSegment.project_id == project_id,
        )
        .where((SegmentTranslation.project_id == project_id) | (SegmentTranslation.project_id.is_(None)))
        .order_by(Chapter.chapter_index.asc(), ChapterSegment.segment_index.asc())
    )
    rows = self.session.execute(statement).all()
    active_versions = [version for *_, version in rows if version is not None]
    provenance_by_version_id = self._build_translation_provenance_map(active_versions=active_versions)
    return {
        "translations": [
            self._build_translation_row_payload(
                project_id=project_id,
                chapter=chapter,
                segment=segment,
                segment_translation=translation,
                version=version,
                provenance_by_version_id=provenance_by_version_id,
            )
            for chapter, segment, translation, version in rows
        ],
        "versions": [
            self._build_translation_version_payload(version)
            for version in self.translations.list_segment_translation_versions(project_id)
        ],
    }


def _build_translation_version_payload(self, version: SegmentTranslationVersion) -> dict[str, object]:
    return {
        "id": int(version.id),
        "project_id": int(version.project_id),
        "segment_translation_id": int(version.segment_translation_id),
        "version_index": int(version.version_index),
        "source_hash": str(version.source_hash),
        "glossary_snapshot_id": str(version.glossary_snapshot_id),
        "provider_name": str(version.provider_name),
        "model_profile_id": str(version.model_profile_id),
        "model_name": str(version.model_name),
        "source_text": str(version.source_text),
        "translated_text": str(version.translated_text),
        "translated_text_path": str(version.translated_text_path),
        "status": str(version.status),
    }


def _build_translation_row_payload(
    self,
    *,
    project_id: int,
    chapter: Chapter,
    segment: ChapterSegment,
    segment_translation: SegmentTranslation | None,
    version: SegmentTranslationVersion | None,
    provenance_by_version_id: dict[int, dict[str, object]],
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
    }
```

```python
def _build_translation_compare_payload(
    self,
    *,
    project_id: int,
    translation: SegmentTranslation | None,
    current_version: SegmentTranslationVersion | None,
    compare_version_id: int,
) -> dict[str, object]:
    if translation is None or current_version is None or translation.active_version_id is None:
        raise ToolError(code="not_found", message="当前段落没有 active version，无法执行 compare。", status=404)
    if int(current_version.id) == compare_version_id:
        raise ToolError(code="invalid_arguments", message="compare_version_id 不能指向当前 active version。", status=400)

    base_version = self.translations.get_version_by_id(compare_version_id)
    if (
        base_version is None
        or int(base_version.project_id) != project_id
        or int(base_version.segment_translation_id) != int(translation.id)
    ):
        raise ToolError(code="not_found", message=f"找不到可比较的历史正式版本 {compare_version_id}。", status=404)

    summary = {
        "translated_text_changed": str(base_version.translated_text) != str(current_version.translated_text),
        "source_hash_changed": str(base_version.source_hash) != str(current_version.source_hash),
        "glossary_snapshot_changed": str(base_version.glossary_snapshot_id) != str(current_version.glossary_snapshot_id),
        "model_profile_changed": str(base_version.model_profile_id) != str(current_version.model_profile_id),
        "model_name_changed": str(base_version.model_name) != str(current_version.model_name),
        "status_changed": str(base_version.status) != str(current_version.status),
    }
    return {
        "base_version": self._build_translation_version_payload(base_version),
        "current_version": self._build_translation_version_payload(current_version),
        "changed": any(summary.values()),
        "summary": summary,
    }
```

- [ ] **Step 5: 重新跑定点测试，确认 compare 成功路径和单段 versions 收窄通过**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_stage.py::test_translation_inspect_compare_returns_active_and_base_versions_for_single_segment tests\test_translation_stage.py::test_translation_inspect_single_segment_without_compare_limits_versions_to_target_segment -q`

Expected: PASS，输出 `2 passed`。

- [ ] **Step 6: 提交 Task 1**

```bash
git add app/repositories/translations.py app/services/translation_service.py tests/test_translation_stage.py
git commit -m "feat: add translation inspect version compare"
```

### Task 2: 收紧 compare 参数校验和 `not_found` / `invalid_arguments` 语义

**Files:**
- Modify: `tests/test_translation_stage.py`
- Modify: `app/services/translation_service.py`
- Test: `tests/test_translation_stage.py`

- [ ] **Step 1: 先写 compare 错误语义红测**

```python
def test_translation_inspect_compare_requires_single_segment_locator(
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
    service = TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=FakeProvider(),
    )
    service.run(
        request_id=request_id_factory("translation-compare-missing-locator"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-compare-missing-locator",
    )
    base_version_id = db_session.execute(
        select(SegmentTranslationVersion.id)
        .where(SegmentTranslationVersion.project_id == project_id)
        .order_by(SegmentTranslationVersion.id.asc())
    ).scalars().first()
    assert base_version_id is not None

    with pytest.raises(ToolError) as exc:
        TranslationService(db_session, base_data_dir=project_workspace).inspect(
            project_id=project_id,
            compare_version_id=int(base_version_id),
        )

    assert exc.value.code == "invalid_arguments"
    assert "compare_version_id" in exc.value.message


def test_translation_inspect_compare_rejects_cross_segment_base_version(
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
    service = TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=FakeProvider(),
    )
    service.run(
        request_id=request_id_factory("translation-compare-cross-segment"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 2},
        model_profile_id="profile-compare-cross-segment",
    )
    first_segment, second_segment = db_session.execute(
        select(ChapterSegment.id)
        .where(ChapterSegment.project_id == project_id)
        .order_by(ChapterSegment.id.asc())
    ).scalars().all()
    other_version_id = db_session.execute(
        select(SegmentTranslationVersion.id)
        .join(SegmentTranslation, SegmentTranslation.id == SegmentTranslationVersion.segment_translation_id)
        .where(
            SegmentTranslation.project_id == project_id,
            SegmentTranslation.segment_id == second_segment,
        )
    ).scalars().first()
    assert other_version_id is not None

    with pytest.raises(ToolError) as exc:
        TranslationService(db_session, base_data_dir=project_workspace).inspect(
            project_id=project_id,
            segment_id=first_segment,
            compare_version_id=int(other_version_id),
        )

    assert exc.value.code == "not_found"
    assert str(other_version_id) in exc.value.message


def test_translation_inspect_compare_requires_active_version(
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
    service = TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=FakeProvider(),
    )
    service.run(
        request_id=request_id_factory("translation-compare-no-active-initial"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-compare-no-active-initial",
    )

    first_segment = db_session.execute(
        select(ChapterSegment.id)
        .where(ChapterSegment.project_id == project_id)
        .order_by(ChapterSegment.id.asc())
    ).scalars().first()
    assert first_segment is not None
    base_version_id = db_session.execute(
        select(SegmentTranslationVersion.id)
        .join(SegmentTranslation, SegmentTranslation.id == SegmentTranslationVersion.segment_translation_id)
        .where(
            SegmentTranslation.project_id == project_id,
            SegmentTranslation.segment_id == first_segment,
        )
        .order_by(SegmentTranslationVersion.id.asc())
    ).scalars().first()
    assert base_version_id is not None

    db_session.execute(
        update(SegmentTranslation)
        .where(
            SegmentTranslation.project_id == project_id,
            SegmentTranslation.segment_id == first_segment,
        )
        .values(active_version_id=None)
    )
    db_session.commit()

    with pytest.raises(ToolError) as exc:
        TranslationService(db_session, base_data_dir=project_workspace).inspect(
            project_id=project_id,
            segment_id=int(first_segment),
            compare_version_id=int(base_version_id),
        )

    assert exc.value.code == "not_found"
    assert "active version" in exc.value.message
```

- [ ] **Step 2: 跑错误语义红测，确认校验还不完整**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_stage.py::test_translation_inspect_compare_requires_single_segment_locator tests\test_translation_stage.py::test_translation_inspect_compare_rejects_cross_segment_base_version tests\test_translation_stage.py::test_translation_inspect_compare_requires_active_version -q`

Expected: FAIL，至少一条会因为当前还没统一 `invalid_arguments / not_found` 语义，或没有 active version 时仍软退化而失败。

- [ ] **Step 3: 在 `TranslationService` 中补参数校验和目标段落解析 helper**

```python
def _validate_inspect_translation_locator(
    self,
    *,
    segment_id: int | None,
    chapter_index: int | None,
    segment_index: int | None,
    compare_version_id: int | None,
) -> None:
    if segment_id is not None and (chapter_index is not None or segment_index is not None):
        raise ToolError(
            code="invalid_arguments",
            message="inspect.translation 不能同时提供 segment_id 与 chapter_index/segment_index。",
            status=400,
        )
    if compare_version_id is not None and segment_id is None and chapter_index is None and segment_index is None:
        raise ToolError(
            code="invalid_arguments",
            message="inspect.translation 使用 compare_version_id 时必须先定位到单个 segment。",
            status=400,
        )
    if segment_id is None and (chapter_index is None) != (segment_index is None):
        raise ToolError(
            code="invalid_arguments",
            message="inspect.translation 使用章节定位时必须同时提供 chapter_index 和 segment_index。",
            status=400,
        )


def _resolve_single_translation_row(
    self,
    *,
    project_id: int,
    segment_id: int | None,
    chapter_index: int | None,
    segment_index: int | None,
) -> tuple[Chapter, ChapterSegment, SegmentTranslation | None, SegmentTranslationVersion | None]:
    statement = (
        select(Chapter, ChapterSegment, SegmentTranslation, SegmentTranslationVersion)
        .join(ChapterSegment, ChapterSegment.chapter_id == Chapter.id)
        .outerjoin(
            SegmentTranslation,
            and_(
                SegmentTranslation.segment_id == ChapterSegment.id,
                SegmentTranslation.project_id == project_id,
            ),
        )
        .outerjoin(SegmentTranslationVersion, SegmentTranslationVersion.id == SegmentTranslation.active_version_id)
        .where(Chapter.project_id == project_id, ChapterSegment.project_id == project_id)
    )
    if segment_id is not None:
        statement = statement.where(ChapterSegment.id == segment_id)
    else:
        statement = statement.where(
            Chapter.chapter_index == chapter_index,
            ChapterSegment.segment_index == segment_index,
        )
    row = self.session.execute(statement).one_or_none()
    if row is None:
        raise ToolError(code="not_found", message="找不到目标段落。", status=404)
    return row
```

- [ ] **Step 4: 重新跑错误语义测试，确认 compare 校验口径稳定**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_stage.py::test_translation_inspect_compare_requires_single_segment_locator tests\test_translation_stage.py::test_translation_inspect_compare_rejects_cross_segment_base_version tests\test_translation_stage.py::test_translation_inspect_compare_requires_active_version -q`

Expected: PASS，输出 `3 passed`。

- [ ] **Step 5: 提交 Task 2**

```bash
git add app/services/translation_service.py tests/test_translation_stage.py
git commit -m "feat: tighten translation inspect compare validation"
```

### Task 3: 打通 CLI 参数透传，并补 inspect.translation 的 CLI compare 回归

**Files:**
- Modify: `app/action_router.py`
- Modify: `tests/test_translation_stage.py`
- Test: `tests/test_translation_stage.py`

- [ ] **Step 1: 先写 CLI compare 成功和参数错误红测**

```python
def test_inspect_translation_cli_supports_compare_mode(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    capsys,
    monkeypatch,
) -> None:
    monkeypatch.setenv("LTW_DATABASE_URL", database_url)
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    service = TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=FakeProvider(),
    )
    service.run(
        request_id=request_id_factory("translation-cli-compare-a"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-cli-compare-a",
    )
    service.run(
        request_id=request_id_factory("translation-cli-compare-b"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-cli-compare-b",
    )

    first_segment = db_session.execute(
        select(ChapterSegment.id)
        .where(ChapterSegment.project_id == project_id)
        .order_by(ChapterSegment.id.asc())
    ).scalars().first()
    assert first_segment is not None
    base_version_id = db_session.execute(
        select(SegmentTranslationVersion.id)
        .join(SegmentTranslation, SegmentTranslation.id == SegmentTranslationVersion.segment_translation_id)
        .where(
            SegmentTranslation.project_id == project_id,
            SegmentTranslation.segment_id == first_segment,
        )
        .order_by(SegmentTranslationVersion.version_index.asc())
    ).scalars().first()
    assert base_version_id is not None

    exit_code = main(
        [
            "-Action",
            "inspect.translation",
            "-ProjectId",
            str(project_id),
            "-SegmentId",
            str(first_segment),
            "-CompareVersionId",
            str(base_version_id),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["action"] == "inspect.translation"
    assert len(payload["data"]["translations"]) == 1
    assert payload["data"]["translations"][0]["compare"]["base_version"]["id"] == int(base_version_id)


def test_inspect_translation_cli_rejects_compare_without_locator(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    capsys,
    monkeypatch,
) -> None:
    monkeypatch.setenv("LTW_DATABASE_URL", database_url)
    project_id = _prepare_project_with_chapters(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    service = TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=FakeProvider(),
    )
    service.run(
        request_id=request_id_factory("translation-cli-compare-missing-locator"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-cli-compare-missing-locator",
    )
    base_version_id = db_session.execute(
        select(SegmentTranslationVersion.id)
        .where(SegmentTranslationVersion.project_id == project_id)
        .order_by(SegmentTranslationVersion.id.asc())
    ).scalars().first()
    assert base_version_id is not None

    exit_code = main(
        [
            "-Action",
            "inspect.translation",
            "-ProjectId",
            str(project_id),
            "-CompareVersionId",
            str(base_version_id),
        ]
    )
    payload = json.loads(capsys.readouterr().err)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_arguments"
    assert "compare_version_id" in payload["error"]["message"]
```

- [ ] **Step 2: 跑 CLI 红测，确认 action_router 还没有透传 compare 参数**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_stage.py::test_inspect_translation_cli_supports_compare_mode tests\test_translation_stage.py::test_inspect_translation_cli_rejects_compare_without_locator -q`

Expected: FAIL，至少一条会因为 `inspect.translation` 还没读取 `SegmentId` / `CompareVersionId` 而失败。

- [ ] **Step 3: 在 action_router 上透传新参数**

```python
def _handle_inspect_translation(arguments: dict[str, str]) -> dict[str, Any]:
    project_id = int(_require_argument(arguments, "project_id"))
    config = load_config()
    session_factory = get_session_factory(_require_database_url(config.database_url))
    session = session_factory()
    try:
        project = ProjectRepository(session).get_by_id(project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        data = TranslationService(session, base_data_dir=config.data_dir).inspect(
            project_id=project_id,
            segment_id=_parse_optional_int(arguments.get("segment_id")),
            chapter_index=_parse_optional_int(arguments.get("chapter_index")),
            segment_index=_parse_optional_int(arguments.get("segment_index")),
            compare_version_id=_parse_optional_int(arguments.get("compare_version_id")),
        )
        return {"ok": True, "action": "inspect.translation", "data": data}
    finally:
        session.close()
```

- [ ] **Step 4: 重新跑 CLI 定点测试，确认 compare 参数已经打通**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_stage.py::test_inspect_translation_cli_supports_compare_mode tests\test_translation_stage.py::test_inspect_translation_cli_rejects_compare_without_locator -q`

Expected: PASS，输出 `2 passed`。

- [ ] **Step 5: 提交 Task 3**

```bash
git add app/action_router.py tests/test_translation_stage.py
git commit -m "feat: wire inspect translation compare args"
```

### Task 4: 更新文档并完成目标回归与完整回归

**Files:**
- Modify: `README.md`
- Modify: `docs/roadmap.md`
- Modify: `CHANGELOG.md`
- Test: `tests/test_translation_stage.py`
- Test: `tests/test_review_export.py`

- [ ] **Step 1: 先补文档变更**

```md
### `inspect.translation`

查看翻译版本、当前激活版本、当前 `active version` 的 provenance，以及单段 compare 结果。

当前 compare 规则：

- 普通模式只需 `project_id`
- 单段模式可传 `segment_id`，或同时传 `chapter_index + segment_index`
- compare 模式需要在单段模式下额外传 `compare_version_id`
- compare 会返回当前 active version 与指定历史正式版本的变化摘要
- 当前 compare 摘要只覆盖：
  - `translated_text_changed`
  - `source_hash_changed`
  - `glossary_snapshot_changed`
  - `model_profile_changed`
  - `model_name_changed`
  - `status_changed`
```

```md
- 已完成第二刀：`inspect.translation` 已支持“当前 active version vs 指定历史正式版本”的单段 compare，可直接查看文本和关键元数据变化摘要。
```

```md
- `inspect.translation` 已支持单段 compare 模式，可在当前 active version 与指定历史正式版本之间返回结构化变化摘要。
- 项目文档已同步到 translation inspect version compare 落地后的真实状态。
```

- [ ] **Step 2: 跑 translation 目标回归**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_stage.py -k "inspect_translation or inspect_translation_cli" -q`

Expected: PASS，输出通过数高于当前 `4` 条 inspect 相关测试基线，并且没有失败。

- [ ] **Step 3: 跑包含 review/export 的 inspect 冒烟回归**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_review_export.py::test_review_and_export_inspect_actions_report_runs_and_artifacts -q`

Expected: PASS，输出 `1 passed`，证明普通 `inspect.translation` 项目模式没有被 compare 改坏。

- [ ] **Step 4: 跑完整回归**

Run: `$env:LTW_TEST_DATABASE_URL='mysql+pymysql://abner:NsS4IhrMBSBVO46cIqbsTAlJTERsKeJ0@192.168.31.212:3307/abner_ltw_test'; D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests -q`

Expected: PASS，完整回归全部通过；如果基线从 `230 passed` 增长，需把新数字同步回 README / roadmap / changelog。

- [ ] **Step 5: 提交 Task 4**

```bash
git add README.md docs/roadmap.md CHANGELOG.md tests/test_translation_stage.py tests/test_review_export.py
git commit -m "docs: record translation version compare rollout"
```

## 自检记录

- 规格覆盖：Task 1 对应单段 compare 成功路径与 `compare` 结构；Task 2 对应 `invalid_arguments / not_found` 错误语义；Task 3 对应 CLI 参数透传；Task 4 对应文档和完整回归，没有遗漏 spec 中的核心要求。
- 占位符扫描：计划里没有 `TBD`、`TODO`、`稍后实现` 之类留白；每个代码步骤都给了明确片段和命令。
- 命名一致性：全程统一使用 `compare_version_id`、`invalid_arguments`、`_build_translation_compare_payload(...)`、`_validate_inspect_translation_locator(...)`、`inspect.translation`，没有再出现之前 spec 里的 `validation_error` 旧口径。
