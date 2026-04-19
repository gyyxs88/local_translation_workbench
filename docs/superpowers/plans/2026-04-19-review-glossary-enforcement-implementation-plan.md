# Review 阶段术语遵守检查 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `review` 阶段新增首版 glossary 术语遵守检查，只报告“原文分片命中了 `source_term`，但当前生效译文里未出现约定 `target_term`”这一类高置信问题。

**Architecture:** 先在 `tests/test_review_export.py` 增加可控夹具和失败测试，再在 `ReviewService` 里扩展一条新的规则审校路径。实现分两步推进：第一步先让 `review` 能产出新的 `glossary_term_missing` issue；第二步再把规则收口为“只检查当前分片真实命中的 glossary entry，并使用宽松文本匹配”。

**Tech Stack:** Python 3.11、SQLAlchemy ORM、pytest、PowerShell、仓库根目录虚拟环境 `..\..\.venv\Scripts\python.exe`

---

## File Structure

- Modify: `app/services/review_service.py`
  - 扩展 `ReviewService`，新增 glossary 术语缺失规则、宽松文本匹配和 issue 构建逻辑。
- Modify: `tests/test_review_export.py`
  - 增加可控的 glossary review 测试夹具、首版失败测试和现有断言更新。
- Modify: `README.md`
  - 补充 `review` 当前真实会检查 glossary 约束的说明，避免文档落后于实现。

### Task 1: 让 review 能报告 glossary target 缺失

**Files:**
- Modify: `tests/test_review_export.py`
- Modify: `app/services/review_service.py`

- [ ] **Step 1: 在 `tests/test_review_export.py` 写失败测试和可控夹具**

```python
class StaticTranslationProvider:
    def __init__(self, *, translated_text: str) -> None:
        self.translated_text = translated_text

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        return TextGenerationResult(
            content=self.translated_text,
            provider_name="static_translation_provider",
            model_name=model_name,
        )


def _prepare_project_for_glossary_review(
    *,
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
    source_text: str,
    translated_text: str,
    glossary_terms: list[tuple[str, str]],
) -> int:
    source_file = project_workspace / "review-glossary-source.txt"
    source_file.write_text(source_text, encoding="utf-8")

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("review-glossary-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("review-glossary-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    glossary_service = GlossaryService(db_session)
    for source_term, target_term in glossary_terms:
        glossary_service.seed_locked_entry(
            project_id=project.id,
            source_term=source_term,
            target_term=target_term,
        )

    TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=StaticTranslationProvider(translated_text=translated_text),
    ).run(
        request_id=request_id_factory("review-glossary-translation"),
        project_id=project.id,
        scope={"type": "all"},
        model_profile_id="profile-review-glossary",
    )
    return project.id


def test_review_reports_glossary_term_missing_when_translation_omits_required_target_term(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_for_glossary_review(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
        source_text="第1章 相遇\n程风到了。",
        translated_text="He arrived.",
        glossary_terms=[("程风", "Cheng Feng")],
    )

    result = ReviewService(db_session).run(
        request_id=request_id_factory("review-glossary-missing"),
        project_id=project_id,
        scope={"type": "all"},
    )

    issues = db_session.execute(
        select(ReviewIssue).where(ReviewIssue.review_run_id == result.run_id)
    ).scalars().all()

    assert result.issue_count == 1
    assert len(issues) == 1
    assert issues[0].issue_type == "glossary_term_missing"
    assert issues[0].severity == "medium"
    assert "程风" in issues[0].message
    assert "Cheng Feng" in issues[0].message
```

- [ ] **Step 2: 跑定向测试，确认当前 review 还不会报 glossary 术语缺失**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_review_export.py::test_review_reports_glossary_term_missing_when_translation_omits_required_target_term -v`

Expected: `FAILED`，失败信息包含 `assert 0 == 1`

- [ ] **Step 3: 在 `app/services/review_service.py` 写最小实现，让 review 先能报新 issue**

```python
from ..repositories.glossary import GlossaryRepository
```

```python
class ReviewService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.reviews = ReviewRepository(session)
        self.translation_source = TranslationSourceSnapshotService()
        self.glossary = GlossaryRepository(session)
```

```python
    def _build_issue(
        self,
        *,
        chapter: Chapter,
        segment: ChapterSegment,
        source_text: str,
        version: SegmentTranslationVersion | None,
    ) -> dict[str, object] | None:
        if version is None:
            return {
                "project_id": chapter.project_id,
                "chapter_id": chapter.id,
                "issue_type": "missing_translation",
                "severity": "high",
                "message": f"第{chapter.chapter_index}章第{segment.segment_index}段没有可用的生效译文。",
                "status": "open",
            }

        translated_text = version.translated_text.strip()
        if translated_text == "":
            return {
                "project_id": chapter.project_id,
                "chapter_id": chapter.id,
                "issue_type": "missing_translation",
                "severity": "high",
                "message": f"第{chapter.chapter_index}章第{segment.segment_index}段的译文为空。",
                "status": "open",
            }

        if translated_text == source_text.strip():
            return {
                "project_id": chapter.project_id,
                "chapter_id": chapter.id,
                "issue_type": "unchanged_translation",
                "severity": "medium",
                "message": f"第{chapter.chapter_index}章第{segment.segment_index}段的译文与原文一致。",
                "status": "open",
            }

        glossary_entries = self.glossary.list_active_entries_for_matching(
            chapter.project_id,
            scope_level="chapter_term",
            scope_chapter_id=chapter.id,
            include_project_scope=True,
        )
        for entry in glossary_entries:
            target_term = str(entry.target_term).strip()
            if target_term == "":
                continue
            if target_term not in translated_text:
                return {
                    "project_id": chapter.project_id,
                    "chapter_id": chapter.id,
                    "issue_type": "glossary_term_missing",
                    "severity": "medium",
                    "message": (
                        f"第{chapter.chapter_index}章第{segment.segment_index}分片命中了术语"
                        f"“{entry.source_term}”，但译文里未发现约定译法“{entry.target_term}”。"
                    ),
                    "status": "open",
                }

        return None
```

- [ ] **Step 4: 重跑定向测试，确认新 issue 已经能被写出来**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_review_export.py::test_review_reports_glossary_term_missing_when_translation_omits_required_target_term -v`

Expected: `PASSED`

- [ ] **Step 5: 提交这一批最小可用改动**

```bash
git add tests/test_review_export.py app/services/review_service.py
git commit -m "feat: detect missing glossary targets during review"
```

### Task 2: 把规则收口为“只检查命中的术语 + 宽松文本匹配”

**Files:**
- Modify: `tests/test_review_export.py`
- Modify: `app/services/review_service.py`

- [ ] **Step 1: 在 `tests/test_review_export.py` 继续补两组失败测试**

```python
def test_review_allows_glossary_target_when_only_case_or_punctuation_differs(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_for_glossary_review(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
        source_text="第1章 相遇\n程风到了。",
        translated_text="“CHENG FENG,” arrived.",
        glossary_terms=[("程风", "Cheng Feng")],
    )

    result = ReviewService(db_session).run(
        request_id=request_id_factory("review-glossary-punctuation"),
        project_id=project_id,
        scope={"type": "all"},
    )

    issues = db_session.execute(
        select(ReviewIssue).where(ReviewIssue.review_run_id == result.run_id)
    ).scalars().all()

    assert result.issue_count == 0
    assert issues == []


def test_review_ignores_glossary_entries_not_hit_by_current_segment(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_for_glossary_review(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
        source_text="第1章 相遇\n他到了。",
        translated_text="He arrived.",
        glossary_terms=[("程风", "Cheng Feng")],
    )

    result = ReviewService(db_session).run(
        request_id=request_id_factory("review-glossary-no-hit"),
        project_id=project_id,
        scope={"type": "all"},
    )

    issues = db_session.execute(
        select(ReviewIssue).where(ReviewIssue.review_run_id == result.run_id)
    ).scalars().all()

    assert result.issue_count == 0
    assert issues == []
```

- [ ] **Step 2: 跑这两组定向测试，确认当前最小实现会误报**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_review_export.py -k "glossary_target_when_only_case_or_punctuation_differs or glossary_entries_not_hit_by_current_segment" -v`

Expected: 至少 1 个 `FAILED`，失败信息包含 `assert 1 == 0`

- [ ] **Step 3: 在 `app/services/review_service.py` 收口为真实命中 + 宽松匹配**

```python
from .translation_assets_service import TranslationAssetsService
```

```python
class ReviewService:
    GLOSSARY_TEXT_TRANSLATION_TABLE = str.maketrans(
        "",
        "",
        " \t\r\n,.;:!?，。！？；：'\"“”‘’()[]{}（）【】《》",
    )

    def __init__(self, session: Session) -> None:
        self.session = session
        self.reviews = ReviewRepository(session)
        self.translation_source = TranslationSourceSnapshotService()
        self.glossary = GlossaryRepository(session)
        self.translation_assets = TranslationAssetsService()
```

```python
    def _build_issue(
        self,
        *,
        chapter: Chapter,
        segment: ChapterSegment,
        source_text: str,
        version: SegmentTranslationVersion | None,
    ) -> dict[str, object] | None:
        if version is None:
            return {
                "project_id": chapter.project_id,
                "chapter_id": chapter.id,
                "issue_type": "missing_translation",
                "severity": "high",
                "message": f"第{chapter.chapter_index}章第{segment.segment_index}段没有可用的生效译文。",
                "status": "open",
            }

        translated_text = version.translated_text.strip()
        if translated_text == "":
            return {
                "project_id": chapter.project_id,
                "chapter_id": chapter.id,
                "issue_type": "missing_translation",
                "severity": "high",
                "message": f"第{chapter.chapter_index}章第{segment.segment_index}段的译文为空。",
                "status": "open",
            }

        if translated_text == source_text.strip():
            return {
                "project_id": chapter.project_id,
                "chapter_id": chapter.id,
                "issue_type": "unchanged_translation",
                "severity": "medium",
                "message": f"第{chapter.chapter_index}章第{segment.segment_index}段的译文与原文一致。",
                "status": "open",
            }

        glossary_entries = self.glossary.list_active_entries_for_matching(
            chapter.project_id,
            scope_level="chapter_term",
            scope_chapter_id=chapter.id,
            include_project_scope=True,
        )
        matched_entries = self.translation_assets.build_prompt_glossary_entries(
            glossary_entries=glossary_entries,
            source_text=source_text,
        )
        normalized_translation = self._normalize_glossary_text(translated_text)

        for entry in matched_entries:
            normalized_target = self._normalize_glossary_text(str(entry.target_term))
            if normalized_target == "":
                continue
            if normalized_target not in normalized_translation:
                return {
                    "project_id": chapter.project_id,
                    "chapter_id": chapter.id,
                    "issue_type": "glossary_term_missing",
                    "severity": "medium",
                    "message": (
                        f"第{chapter.chapter_index}章第{segment.segment_index}分片命中了术语"
                        f"“{entry.source_term}”，但译文里未发现约定译法“{entry.target_term}”。"
                    ),
                    "status": "open",
                }

        return None

    def _normalize_glossary_text(self, value: str) -> str:
        return value.lower().translate(self.GLOSSARY_TEXT_TRANSLATION_TABLE)
```

- [ ] **Step 4: 重跑这两组定向测试，确认误报被收掉**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_review_export.py -k "glossary_target_when_only_case_or_punctuation_differs or glossary_entries_not_hit_by_current_segment" -v`

Expected: 两个测试全部 `PASSED`

- [ ] **Step 5: 提交规则收口改动**

```bash
git add tests/test_review_export.py app/services/review_service.py
git commit -m "refactor: align review glossary checks with prompt matching"
```

### Task 3: 收口现有测试和 README 说明

**Files:**
- Modify: `tests/test_review_export.py`
- Modify: `README.md`

- [ ] **Step 1: 更新现有 review 测试断言，允许新 issue_type**

```python
def test_review_creates_structured_issues_for_current_translations(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_current_translations(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    result = ReviewService(db_session).run(
        request_id=request_id_factory("review-run"),
        project_id=project_id,
        scope={"type": "all"},
    )

    assert result.issue_count >= 1

    runs = db_session.execute(
        select(ReviewRun).where(ReviewRun.project_id == project_id)
    ).scalars().all()
    issues = db_session.execute(
        select(ReviewIssue).where(ReviewIssue.project_id == project_id)
    ).scalars().all()

    assert len(runs) == 1
    assert len(issues) >= 1
    assert {issue.issue_type for issue in issues} <= {
        "missing_translation",
        "unchanged_translation",
        "glossary_term_missing",
    }
    assert all(issue.status == "open" for issue in issues)
```

- [ ] **Step 2: 在 `README.md` 增加 review 当前真实规则范围说明**

```markdown
- `review` 当前仍然是规则审校，不走 LLM；除缺失译文、空译文、原文未翻外，现阶段还会检查“原文分片命中了 glossary `source_term`，但当前生效译文里未出现约定 `target_term`”这一类高置信术语问题。
```

推荐把这条补在 glossary / translation 联动段落之后，避免 `review` 的真实能力只存在于代码和测试里。

- [ ] **Step 3: 跑本轮重点回归组合**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_review_export.py -v`

Expected: `PASSED`，且新增 glossary review 测试与原有 review/export 测试全部通过

- [ ] **Step 4: 跑完整回归**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests -q`

Expected: 输出形态为 `... passed`，退出码为 `0`

- [ ] **Step 5: 提交 README 和最终验证结果**

```bash
git add tests/test_review_export.py README.md
git commit -m "docs: describe glossary enforcement in review"
```

## Self-Review

- spec 的核心约束都已经映射到任务：
  - 新 issue_type `glossary_term_missing` 在 Task 1
  - “只检查命中的 `source_term`”在 Task 2
  - 宽松文本匹配在 Task 2
  - 不改 schema 在整份计划中都成立
  - README 文档收口和完整回归在 Task 3
- 没有留下需要后续补细节的空白说明。
- 后续任务引用的名称已经前后一致：`StaticTranslationProvider`、`_prepare_project_for_glossary_review`、`glossary_term_missing`、`_normalize_glossary_text`、`TranslationAssetsService.build_prompt_glossary_entries(...)`。
