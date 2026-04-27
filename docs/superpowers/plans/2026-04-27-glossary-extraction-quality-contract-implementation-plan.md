# Glossary Extraction Quality Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 glossary extraction 按章节显式返回 `terms_found` 或 `no_new_terms`，并在提取时带入当前章节命中的已有术语，随后用硬质检和风险触发型 LLM 质检守住一致性。

**Architecture:** 在现有 `GlossaryService -> GlossaryWorkflowDomainService` 链路内扩展，不新增 workflow step。新增两个小服务分别负责已有术语上下文和抽取质量判断，`GlossaryPromptService` 只负责 prompt 与 JSON 契约解析，workflow domain 负责把章节级结果写入 step payload。

**Tech Stack:** Python 3.12、SQLAlchemy ORM、pytest、json_repair、现有 Provider 抽象、现有 MySQL 测试夹具。

---

## File Map

- Modify: `app/services/glossary_types.py`
  - 保留 `GlossaryExtraction`。
  - 新增 `MatchedExistingGlossaryTerm`、`GlossaryExtractionEnvelope`、`GlossaryExtractionQualityIssue`、`GlossaryChapterExtractionResult`、`GlossaryLlmQualityReview`。
- Create: `app/services/glossary_existing_term_context_service.py`
  - 读取当前有效 glossary entries。
  - 用 `TranslationAssetsService.build_prompt_glossary_entries` 做章节标题加正文的本地命中过滤。
  - 输出当前章节实际命中的已有术语。
- Create: `app/services/glossary_extraction_quality_service.py`
  - 执行常驻硬质检。
  - 过滤重复已有术语、正文不存在的候选、结构壳候选。
  - 标记 `suspicious_empty`、`relation_risk`、`duplicate_existing`、`source_not_in_chapter`、`too_many_candidates`。
- Modify: `app/services/glossary_prompt_service.py`
  - 抽取 prompt 改为 envelope-only 输出。
  - 解析结果改为 `GlossaryExtractionEnvelope`。
  - JSON repair prompt 也要求 envelope。
  - 新增风险型 LLM 质检 prompt、质检响应 parser、定向补提取 prompt。
- Modify: `app/services/glossary_service.py`
  - `_extract_terms` 返回 `GlossaryExtractionEnvelope`。
  - 增加 `matched_existing_terms`、`risk_signals`、`previous_extraction` 参数。
  - 解析 repair 成功时标记 `repaired=True`。
  - 新增 `_review_extraction_quality`，只在 workflow domain 判定有风险时调用。
- Modify: `app/services/glossary_workflow_domain_service.py`
  - 每章先构建已命中术语上下文。
  - 每章抽取后执行硬质检。
  - 只对通过质检的新增术语创建 draft candidate。
  - 对风险章节最多执行 1 轮 LLM 质检加定向补提取。
  - step output payload 暴露 `chapter_results`、状态计数、`quality_issues`、`token_usage`。
- Modify: `tests/test_glossary_stage.py`
  - 把 extractor fake 输出升级为显式 envelope。
  - 保留 finalize / relation / scope review 现有 JSON 格式。
  - 增加 workflow 级 payload 和调用次数断言。
- Create: `tests/test_glossary_extraction_contract.py`
  - 覆盖 parser、上下文匹配、硬质检、风险型 LLM 质检最小闭环。
- Modify: `README.md`
  - 更新 glossary 联动说明，写明空结果必须是显式 `no_new_terms`。

## Contract Rules

标准 extractor 输出只允许对象 envelope：

```json
{
  "extraction_status": "terms_found",
  "terms": [
    {
      "source_term": "时羽",
      "translated_term": "Shi Yu",
      "category": "character",
      "note": null,
      "gender": "female",
      "age_group": null,
      "term_group_key": "char_shiyu",
      "relation_role": "canonical"
    }
  ],
  "reason": "发现新增主要人物。"
}
```

无新增术语必须是：

```json
{
  "extraction_status": "no_new_terms",
  "terms": [],
  "reason": "本章只出现已知人物和普通叙事，没有新增专名或固定称谓。"
}
```

以下响应必须报 `ToolError(code="provider_error")`，不能被当成成功空结果：

```text
空字符串
null
[]
{}
{"terms":[]}
```

## Status Semantics

- `terms_found`：至少有一个新增候选进入后续 normalize / relation / scope / finalize。
- `no_new_terms`：模型明确判断无新增术语，章节成功，不创建 draft candidate。
- `suspicious_empty`：模型返回 `no_new_terms`，硬质检发现风险，触发 LLM 质检或记录风险。
- `skipped`：provider 失败、JSON 修复失败、格式仍不合法、或定向补提取仍失败。

## Tasks

### Task 1: Parser Contract Failing Tests

**Files:**
- Create: `tests/test_glossary_extraction_contract.py`
- Modify: none
- Test: `tests/test_glossary_extraction_contract.py`

- [ ] **Step 1: Write parser tests for explicit envelope success and ambiguous empty failure**

Create `tests/test_glossary_extraction_contract.py` with this initial content:

```python
from __future__ import annotations

import json

import pytest

from tools.local_translation_workbench.app.errors import ToolError
from tools.local_translation_workbench.app.services.glossary_prompt_service import GlossaryPromptService


def test_parse_terms_found_envelope() -> None:
    service = GlossaryPromptService()

    parsed = service.parse_extraction_response(
        json.dumps(
            {
                "extraction_status": "terms_found",
                "terms": [
                    {
                        "source_term": "时羽",
                        "translated_term": "Shi Yu",
                        "category": "character",
                        "note": "新登场人物",
                        "gender": "female",
                        "age_group": None,
                        "term_group_key": "char_shiyu",
                        "relation_role": "canonical",
                    }
                ],
                "reason": "发现新增主要人物。",
            },
            ensure_ascii=False,
        )
    )

    assert parsed.extraction_status == "terms_found"
    assert parsed.reason == "发现新增主要人物。"
    assert parsed.repaired is False
    assert len(parsed.terms) == 1
    assert parsed.terms[0].source_term == "时羽"
    assert parsed.terms[0].suggested_term == "Shi Yu"
    assert parsed.terms[0].gender == "female"


def test_parse_no_new_terms_envelope() -> None:
    service = GlossaryPromptService()

    parsed = service.parse_extraction_response(
        json.dumps(
            {
                "extraction_status": "no_new_terms",
                "terms": [],
                "reason": "本章没有新增专名。",
            },
            ensure_ascii=False,
        )
    )

    assert parsed.extraction_status == "no_new_terms"
    assert parsed.terms == []
    assert parsed.reason == "本章没有新增专名。"


@pytest.mark.parametrize("content", ["", "null", "[]", "{}", '{"terms":[]}'])
def test_parse_rejects_ambiguous_empty_outputs(content: str) -> None:
    service = GlossaryPromptService()

    with pytest.raises(ToolError, match="extraction_status"):
        service.parse_extraction_response(content)


def test_parse_rejects_no_new_terms_with_non_empty_terms() -> None:
    service = GlossaryPromptService()

    with pytest.raises(ToolError, match="no_new_terms"):
        service.parse_extraction_response(
            json.dumps(
                {
                    "extraction_status": "no_new_terms",
                    "terms": [
                        {
                            "source_term": "时羽",
                            "translated_term": "Shi Yu",
                            "category": "character",
                        }
                    ],
                    "reason": "冲突输出。",
                },
                ensure_ascii=False,
            )
        )


def test_parse_rejects_terms_found_with_empty_terms() -> None:
    service = GlossaryPromptService()

    with pytest.raises(ToolError, match="terms_found"):
        service.parse_extraction_response(
            json.dumps(
                {
                    "extraction_status": "terms_found",
                    "terms": [],
                    "reason": "冲突输出。",
                },
                ensure_ascii=False,
            )
        )
```

- [ ] **Step 2: Run parser tests and verify they fail**

Run from `D:\Project\NovelT`:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_glossary_extraction_contract.py -q
```

Expected: FAIL because `parse_extraction_response` currently returns `list[GlossaryExtraction]` and accepts ambiguous empty outputs.

- [ ] **Step 3: Commit failing tests**

```powershell
git add tests/test_glossary_extraction_contract.py
git commit -m "test: define glossary extraction envelope contract"
```

### Task 2: Envelope Types And Parser Implementation

**Files:**
- Modify: `app/services/glossary_types.py`
- Modify: `app/services/glossary_prompt_service.py`
- Test: `tests/test_glossary_extraction_contract.py`

- [ ] **Step 1: Add extraction contract dataclasses**

Append these dataclasses to `app/services/glossary_types.py` after `GlossaryExtraction`:

```python

@dataclass(frozen=True)
class MatchedExistingGlossaryTerm:
    source_term: str
    target_term: str
    category: str
    note: str | None
    gender: str | None
    age_group: str | None
    term_group_key: str
    relation_role: str
    scope_level: str
    scope_chapter_id: int | None


@dataclass(frozen=True)
class GlossaryExtractionEnvelope:
    extraction_status: str
    terms: list[GlossaryExtraction]
    reason: str | None
    repaired: bool = False


@dataclass(frozen=True)
class GlossaryExtractionQualityIssue:
    issue_type: str
    severity: str
    message: str
    source_term: str | None = None
    source_evidence: str | None = None
    suggested_action: str | None = None

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "issue_type": self.issue_type,
            "severity": self.severity,
            "message": self.message,
        }
        if self.source_term is not None:
            payload["source_term"] = self.source_term
        if self.source_evidence is not None:
            payload["source_evidence"] = self.source_evidence
        if self.suggested_action is not None:
            payload["suggested_action"] = self.suggested_action
        return payload


@dataclass(frozen=True)
class GlossaryChapterExtractionResult:
    chapter_id: int
    chapter_index: int
    chapter_title: str
    status: str
    terms: list[GlossaryExtraction]
    matched_existing_terms: list[MatchedExistingGlossaryTerm]
    reason: str | None
    quality_issues: list[GlossaryExtractionQualityIssue]
    llm_quality_review: dict[str, object] | None = None

    def as_payload(self) -> dict[str, object]:
        return {
            "chapter_id": self.chapter_id,
            "chapter_index": self.chapter_index,
            "chapter_title": self.chapter_title,
            "status": self.status,
            "term_count": len(self.terms),
            "matched_existing_term_count": len(self.matched_existing_terms),
            "reason": self.reason,
            "quality_issues": [issue.as_payload() for issue in self.quality_issues],
            "llm_quality_review": self.llm_quality_review,
        }


@dataclass(frozen=True)
class GlossaryLlmQualityReview:
    passed: bool
    issues: list[GlossaryExtractionQualityIssue]

    def as_payload(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "issues": [issue.as_payload() for issue in self.issues],
        }
```

- [ ] **Step 2: Update imports in `glossary_prompt_service.py`**

Change the existing import:

```python
from .glossary_types import GlossaryExtraction
```

to:

```python
from .glossary_types import GlossaryExtraction, GlossaryExtractionEnvelope, GlossaryExtractionQualityIssue, GlossaryLlmQualityReview
```

- [ ] **Step 3: Replace `parse_extraction_response` with envelope parser**

Replace the current `parse_extraction_response` method in `app/services/glossary_prompt_service.py` with:

```python
    def parse_extraction_response(self, content: str) -> GlossaryExtractionEnvelope:
        normalized = self.strip_code_fence(content).strip()
        if normalized == "":
            raise ToolError(
                code="provider_error",
                message="术语提取返回格式错误：必须返回包含 extraction_status 的 JSON 对象。",
                status=502,
            )
        try:
            payload = self.load_json_payload(normalized)
        except json.JSONDecodeError as exc:
            raise ToolError(
                code="provider_error",
                message=f"术语提取返回了无效 JSON：{exc}",
                status=502,
            ) from exc

        if not isinstance(payload, dict):
            raise ToolError(
                code="provider_error",
                message="术语提取返回格式错误：必须返回包含 extraction_status 的 JSON 对象。",
                status=502,
            )

        extraction_status = self.normalize_text(payload.get("extraction_status"))
        if extraction_status not in {"terms_found", "no_new_terms"}:
            raise ToolError(
                code="provider_error",
                message="术语提取返回格式错误：extraction_status 必须是 terms_found 或 no_new_terms。",
                status=502,
            )

        raw_terms = payload.get("terms")
        if not isinstance(raw_terms, list):
            raise ToolError(
                code="provider_error",
                message="术语提取返回格式错误：terms 必须是数组。",
                status=502,
            )

        results = self._parse_extraction_terms(raw_terms)
        if extraction_status == "terms_found" and not results:
            raise ToolError(
                code="provider_error",
                message="术语提取返回格式错误：terms_found 必须包含至少一个有效术语。",
                status=502,
            )
        if extraction_status == "no_new_terms" and results:
            raise ToolError(
                code="provider_error",
                message="术语提取返回格式错误：no_new_terms 必须搭配空 terms 数组。",
                status=502,
            )
        return GlossaryExtractionEnvelope(
            extraction_status=extraction_status,
            terms=results,
            reason=self.normalize_optional_text(payload.get("reason")),
        )
```

- [ ] **Step 4: Extract existing term parsing into helper**

Insert this helper directly below `parse_extraction_response`:

```python
    def _parse_extraction_terms(self, raw_terms: list[object]) -> list[GlossaryExtraction]:
        results: list[GlossaryExtraction] = []
        seen_terms: set[str] = set()
        for item in raw_terms:
            if not isinstance(item, dict):
                continue
            source_term = self.normalize_text(item.get("source_term"))
            suggested_term = self.normalize_text(
                item.get("translated_term") or item.get("target_term") or item.get("suggested_term")
            )
            if source_term == "" or suggested_term == "":
                continue
            if source_term in seen_terms:
                continue
            category = self.normalize_text(item.get("category")) or "term"
            note = self.normalize_optional_text(item.get("note"))
            gender = self.normalize_gender(category=category, gender=item.get("gender"))
            age_group = self.normalize_age_group(category=category, age_group=item.get("age_group"))
            term_group_key = self.normalize_text(item.get("term_group_key")) or source_term
            relation_role = self.normalize_text(item.get("relation_role")) or "independent"
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
            seen_terms.add(source_term)
        return results
```

- [ ] **Step 5: Update JSON repair prompt contract**

In `build_extraction_json_repair_prompt`, replace the sentence that says `格式为 {"terms": [...]}` with:

```python
            "输出必须是合法 JSON，格式为 {\"extraction_status\":\"terms_found\",\"terms\":[...],\"reason\":\"...\"} 或 {\"extraction_status\":\"no_new_terms\",\"terms\":[],\"reason\":\"...\"}，不要 Markdown，不要解释。\n\n"
```

- [ ] **Step 6: Run parser tests and verify they pass**

Run from `D:\Project\NovelT`:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_glossary_extraction_contract.py -q
```

Expected: PASS for parser tests.

- [ ] **Step 7: Commit parser implementation**

```powershell
git add app/services/glossary_types.py app/services/glossary_prompt_service.py tests/test_glossary_extraction_contract.py
git commit -m "feat: enforce glossary extraction envelope"
```

### Task 3: Existing Term Context Service

**Files:**
- Create: `app/services/glossary_existing_term_context_service.py`
- Modify: `tests/test_glossary_extraction_contract.py`
- Test: `tests/test_glossary_extraction_contract.py`

- [ ] **Step 1: Add a failing test for chapter-local matched existing terms**

Append this test to `tests/test_glossary_extraction_contract.py`:

```python
from pathlib import Path

from tools.local_translation_workbench.app.db.models import Chapter, TranslationProject
from tools.local_translation_workbench.app.repositories.glossary import GlossaryRepository
from tools.local_translation_workbench.app.services.glossary_existing_term_context_service import (
    GlossaryExistingTermContextService,
)


def test_existing_term_context_only_returns_terms_matched_in_current_chapter(db_session, tmp_path: Path) -> None:
    project = TranslationProject(
        request_id="glossary-context-project-request",
        project_key="glossary-context-project",
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
        chapter_title="第1章 林溪的来信",
        source_path=str(tmp_path / "chapter-source.txt"),
        normalized_path=str(tmp_path / "chapter-normalized.txt"),
        stage_status="ready",
    )
    db_session.add(chapter)
    db_session.flush()

    repository = GlossaryRepository(db_session)
    repository.create_entry(
        project_id=project.id,
        source_term="林溪",
        target_term="Lin Xi",
        category="character",
        term_group_key="char_linxi",
        relation_role="canonical",
        scope_level="project_term",
    )
    repository.create_entry(
        project_id=project.id,
        source_term="深蓝公寓",
        target_term="Deep Blue Apartments",
        category="location",
        term_group_key="loc_deep_blue",
        relation_role="canonical",
        scope_level="project_term",
    )
    repository.create_entry(
        project_id=project.id,
        source_term="溪溪",
        target_term="Xixi",
        category="character",
        term_group_key="char_linxi",
        relation_role="alias",
        scope_level="chapter_term",
        scope_chapter_id=chapter.id,
    )

    matched = GlossaryExistingTermContextService(repository).list_matched_terms_for_chapter(
        project_id=project.id,
        chapter_id=chapter.id,
        chapter_title=chapter.chapter_title,
        chapter_text="溪溪把信交给林溪。",
    )

    assert [item.source_term for item in matched] == ["溪溪", "林溪"]
    assert {item.term_group_key for item in matched} == {"char_linxi"}
```

- [ ] **Step 2: Run the context test and verify it fails**

Run from `D:\Project\NovelT`:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_glossary_extraction_contract.py::test_existing_term_context_only_returns_terms_matched_in_current_chapter -q
```

Expected: FAIL with import error for `GlossaryExistingTermContextService`.

- [ ] **Step 3: Implement the context service**

Create `app/services/glossary_existing_term_context_service.py`:

```python
from __future__ import annotations

from ..repositories.glossary import GlossaryRepository
from .glossary_types import MatchedExistingGlossaryTerm
from .translation_assets_service import TranslationAssetsService


class GlossaryExistingTermContextService:
    def __init__(
        self,
        glossary: GlossaryRepository,
        *,
        translation_assets: TranslationAssetsService | None = None,
    ) -> None:
        self.glossary = glossary
        self.translation_assets = translation_assets or TranslationAssetsService()

    def list_matched_terms_for_chapter(
        self,
        *,
        project_id: int,
        chapter_id: int,
        chapter_title: str,
        chapter_text: str,
    ) -> list[MatchedExistingGlossaryTerm]:
        active_entries = self.glossary.list_active_entries_for_matching(
            project_id,
            scope_level="chapter_term",
            scope_chapter_id=chapter_id,
            include_project_scope=True,
        )
        matched_entries = self.translation_assets.build_prompt_glossary_entries(
            glossary_entries=active_entries,
            source_text=f"{chapter_title}\n{chapter_text}",
        )
        return [
            MatchedExistingGlossaryTerm(
                source_term=str(entry.source_term),
                target_term=str(entry.target_term),
                category=str(entry.category),
                note=entry.note,
                gender=entry.gender,
                age_group=entry.age_group,
                term_group_key=str(entry.term_group_key),
                relation_role=str(entry.relation_role),
                scope_level=str(entry.scope_level),
                scope_chapter_id=entry.scope_chapter_id,
            )
            for entry in sorted(
                matched_entries,
                key=lambda item: (
                    str(item.scope_level),
                    int(item.scope_chapter_id or 0),
                    str(item.term_group_key),
                    str(item.relation_role),
                    str(item.source_term),
                ),
            )
        ]
```

- [ ] **Step 4: Run the context test and verify it passes**

Run from `D:\Project\NovelT`:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_glossary_extraction_contract.py::test_existing_term_context_only_returns_terms_matched_in_current_chapter -q
```

Expected: PASS.

- [ ] **Step 5: Commit context service**

```powershell
git add app/services/glossary_existing_term_context_service.py tests/test_glossary_extraction_contract.py
git commit -m "feat: match existing glossary terms per chapter"
```

### Task 4: Extraction Prompt Context And Risk Signals

**Files:**
- Modify: `app/services/glossary_prompt_service.py`
- Modify: `tests/test_glossary_extraction_contract.py`
- Test: `tests/test_glossary_extraction_contract.py`

- [ ] **Step 1: Add failing prompt test**

Append this test to `tests/test_glossary_extraction_contract.py`:

```python
from tools.local_translation_workbench.app.services.glossary_types import MatchedExistingGlossaryTerm


def test_extraction_prompt_includes_matched_existing_terms_and_requires_explicit_empty() -> None:
    service = GlossaryPromptService()

    prompt = service.build_extraction_prompt(
        chapter_text="溪溪把信交给林溪。",
        chapter_index=1,
        chapter_title="第1章 林溪的来信",
        source_language="zh",
        target_language="en",
        matched_existing_terms=[
            MatchedExistingGlossaryTerm(
                source_term="林溪",
                target_term="Lin Xi",
                category="character",
                note=None,
                gender="female",
                age_group=None,
                term_group_key="char_linxi",
                relation_role="canonical",
                scope_level="project_term",
                scope_chapter_id=None,
            )
        ],
        risk_signals=["possible_alias_without_group"],
        previous_extraction=None,
    )

    assert '"source_term": "林溪"' in prompt
    assert '"target_term": "Lin Xi"' in prompt
    assert "已有术语的译名和关系组必须沿用" in prompt
    assert "完全相同的已有 source_term 不要作为新增术语重复输出" in prompt
    assert '"extraction_status": "no_new_terms"' in prompt
    assert "不能返回空字符串、null、空数组或只有 terms 的对象" in prompt
    assert "possible_alias_without_group" in prompt
```

- [ ] **Step 2: Run prompt test and verify it fails**

Run from `D:\Project\NovelT`:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_glossary_extraction_contract.py::test_extraction_prompt_includes_matched_existing_terms_and_requires_explicit_empty -q
```

Expected: FAIL because `build_extraction_prompt` has no context arguments.

- [ ] **Step 3: Update prompt imports**

Add `MatchedExistingGlossaryTerm` to the `glossary_prompt_service.py` import from `glossary_types`:

```python
from .glossary_types import (
    GlossaryExtraction,
    GlossaryExtractionEnvelope,
    GlossaryExtractionQualityIssue,
    GlossaryLlmQualityReview,
    MatchedExistingGlossaryTerm,
)
```

- [ ] **Step 4: Replace `build_extraction_prompt` signature and body**

Replace `build_extraction_prompt` with:

```python
    def build_extraction_prompt(
        self,
        *,
        chapter_text: str,
        chapter_index: int,
        chapter_title: str,
        source_language: str,
        target_language: str,
        matched_existing_terms: list[MatchedExistingGlossaryTerm],
        risk_signals: list[str],
        previous_extraction: dict[str, object] | None,
    ) -> str:
        existing_terms_payload = [
            {
                "source_term": item.source_term,
                "target_term": item.target_term,
                "category": item.category,
                "note": item.note,
                "gender": item.gender,
                "age_group": item.age_group,
                "term_group_key": item.term_group_key,
                "relation_role": item.relation_role,
                "scope_level": item.scope_level,
                "scope_chapter_id": item.scope_chapter_id,
            }
            for item in matched_existing_terms
        ]
        output_contract = {
            "extraction_status": "terms_found",
            "terms": [
                {
                    "source_term": "时羽",
                    "translated_term": "Shi Yu",
                    "category": "character",
                    "note": None,
                    "gender": "female",
                    "age_group": None,
                    "term_group_key": "char_shiyu",
                    "relation_role": "canonical",
                }
            ],
            "reason": "发现新增主要人物。",
        }
        empty_contract = {
            "extraction_status": "no_new_terms",
            "terms": [],
            "reason": "本章只出现已知人物和普通叙事，没有新增专名或固定称谓。",
        }
        prompt = (
            "你是小说翻译平台的术语抽取器。请只根据给定章节正文，提取后续翻译需要保持一致的新增术语。\n"
            f"源语言: {source_language}\n"
            f"目标语言: {target_language}\n"
            f"章节号: {chapter_index}\n"
            f"章节标题: {chapter_title}\n"
            "优先提取：人名、地名、组织/势力、专有物件、固定称谓、世界观术语、俚语/梗。\n"
            "不要输出普通代词、泛化名词、完整句子或解释性段落。\n"
            "已有术语的译名和关系组必须沿用。\n"
            "完全相同的已有 source_term 不要作为新增术语重复输出。\n"
            "如果章节中出现已有实体的新别名、称号、变体，可以作为新增术语输出，并绑定已有 term_group_key。\n"
            "如果你认为没有新增术语，必须明确返回 no_new_terms，不能返回空字符串、null、空数组或只有 terms 的对象。\n"
            "请直接返回 JSON，不要 Markdown，不要额外说明。\n"
            "每个术语对象字段：source_term, translated_term, category, note, term_group_key, relation_role, gender, age_group。\n"
            "category 推荐使用 character/location/organization/item/title/slang/term/other。\n"
            "relation_role 仅允许 canonical/alias/title/variant/independent。\n"
            "gender 仅在 category=character 且正文有明确线索时填写 female/male/nonbinary，否则返回 null。\n"
            "age_group 仅在 category=character 且正文或术语里有明确年龄段线索时填写 child/teen/adult/elderly，否则返回 null。\n"
            "不要根据先生、小姐、哥、姐、阿姨等敬称猜测年龄层。\n"
            "translated_term 必须给出建议译名；note 可为空。\n\n"
            f"已有且命中本章的术语：\n{json.dumps(existing_terms_payload, ensure_ascii=False, indent=2)}\n\n"
            f"风险信号：\n{json.dumps(risk_signals, ensure_ascii=False, indent=2)}\n\n"
            f"上一轮抽取结果：\n{json.dumps(previous_extraction, ensure_ascii=False, indent=2) if previous_extraction is not None else 'null'}\n\n"
            f"有新增术语时返回示例：\n{json.dumps(output_contract, ensure_ascii=False, indent=2)}\n\n"
            f"无新增术语时返回示例：\n{json.dumps(empty_contract, ensure_ascii=False, indent=2)}\n\n"
            "待提取章节正文：\n"
            f"{chapter_text}"
        )
        return prompt
```

- [ ] **Step 5: Run prompt test and verify it passes**

Run from `D:\Project\NovelT`:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_glossary_extraction_contract.py::test_extraction_prompt_includes_matched_existing_terms_and_requires_explicit_empty -q
```

Expected: PASS.

- [ ] **Step 6: Commit prompt context**

```powershell
git add app/services/glossary_prompt_service.py tests/test_glossary_extraction_contract.py
git commit -m "feat: include matched glossary context in extraction prompt"
```

### Task 5: Hard Quality Service

**Files:**
- Create: `app/services/glossary_extraction_quality_service.py`
- Modify: `tests/test_glossary_extraction_contract.py`
- Test: `tests/test_glossary_extraction_contract.py`

- [ ] **Step 1: Add failing quality tests**

Append these tests to `tests/test_glossary_extraction_contract.py`:

```python
from tools.local_translation_workbench.app.services.glossary_extraction_quality_service import (
    GlossaryExtractionQualityService,
)
from tools.local_translation_workbench.app.services.glossary_types import (
    GlossaryExtraction,
    GlossaryExtractionEnvelope,
)


def test_quality_filters_duplicate_existing_terms() -> None:
    service = GlossaryExtractionQualityService()
    matched = [
        MatchedExistingGlossaryTerm(
            source_term="林溪",
            target_term="Lin Xi",
            category="character",
            note=None,
            gender="female",
            age_group=None,
            term_group_key="char_linxi",
            relation_role="canonical",
            scope_level="project_term",
            scope_chapter_id=None,
        )
    ]
    envelope = GlossaryExtractionEnvelope(
        extraction_status="terms_found",
        terms=[
            GlossaryExtraction(
                source_term="林溪",
                suggested_term="Lin Xi",
                category="character",
                note=None,
                term_group_key="char_linxi",
                relation_role="canonical",
                gender="female",
                age_group=None,
            )
        ],
        reason="模型重复输出已有术语。",
    )

    result = service.evaluate(
        chapter_id=10,
        chapter_index=1,
        chapter_title="第1章",
        chapter_text="林溪打开窗。",
        envelope=envelope,
        matched_existing_terms=matched,
    )

    assert result.status == "no_new_terms"
    assert result.terms == []
    assert [issue.issue_type for issue in result.quality_issues] == ["duplicate_existing"]


def test_quality_marks_suspicious_empty_when_name_like_terms_exist() -> None:
    service = GlossaryExtractionQualityService()
    envelope = GlossaryExtractionEnvelope(
        extraction_status="no_new_terms",
        terms=[],
        reason="没有新增术语。",
    )

    result = service.evaluate(
        chapter_id=10,
        chapter_index=1,
        chapter_title="第1章",
        chapter_text="时羽小姐推开门。望月同学站在走廊尽头。",
        envelope=envelope,
        matched_existing_terms=[],
    )

    assert result.status == "suspicious_empty"
    assert any(issue.issue_type == "suspicious_empty" for issue in result.quality_issues)


def test_quality_filters_terms_not_present_in_chapter() -> None:
    service = GlossaryExtractionQualityService()
    envelope = GlossaryExtractionEnvelope(
        extraction_status="terms_found",
        terms=[
            GlossaryExtraction(
                source_term="不存在的人名",
                suggested_term="Missing Name",
                category="character",
                note=None,
                term_group_key="char_missing",
                relation_role="canonical",
                gender=None,
                age_group=None,
            )
        ],
        reason="模型幻觉。",
    )

    result = service.evaluate(
        chapter_id=10,
        chapter_index=1,
        chapter_title="第1章",
        chapter_text="林溪打开窗。",
        envelope=envelope,
        matched_existing_terms=[],
    )

    assert result.status == "skipped"
    assert result.terms == []
    assert any(issue.issue_type == "source_not_in_chapter" for issue in result.quality_issues)
```

- [ ] **Step 2: Run quality tests and verify they fail**

Run from `D:\Project\NovelT`:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_glossary_extraction_contract.py::test_quality_filters_duplicate_existing_terms tools/local_translation_workbench/tests/test_glossary_extraction_contract.py::test_quality_marks_suspicious_empty_when_name_like_terms_exist tools/local_translation_workbench/tests/test_glossary_extraction_contract.py::test_quality_filters_terms_not_present_in_chapter -q
```

Expected: FAIL with import error for `GlossaryExtractionQualityService`.

- [ ] **Step 3: Implement quality service**

Create `app/services/glossary_extraction_quality_service.py`:

```python
from __future__ import annotations

import re

from .glossary_types import (
    GlossaryChapterExtractionResult,
    GlossaryExtraction,
    GlossaryExtractionEnvelope,
    GlossaryExtractionQualityIssue,
    MatchedExistingGlossaryTerm,
)


class GlossaryExtractionQualityService:
    _structure_scaffold_pattern = re.compile(r"^第[0-9零一二三四五六七八九十百千万两]+[章节卷部篇集话回]$")
    _name_like_pattern = re.compile(r"[一-龥]{2,4}(?:小姐|同学|老师|前辈|殿下|大人|阁下)")

    def evaluate(
        self,
        *,
        chapter_id: int,
        chapter_index: int,
        chapter_title: str,
        chapter_text: str,
        envelope: GlossaryExtractionEnvelope,
        matched_existing_terms: list[MatchedExistingGlossaryTerm],
    ) -> GlossaryChapterExtractionResult:
        combined_text = f"{chapter_title}\n{chapter_text}"
        issues: list[GlossaryExtractionQualityIssue] = []
        accepted_terms: list[GlossaryExtraction] = []
        existing_by_source = {item.source_term: item for item in matched_existing_terms}

        for term in envelope.terms:
            if term.source_term in existing_by_source:
                issues.append(
                    GlossaryExtractionQualityIssue(
                        issue_type="duplicate_existing",
                        severity="low",
                        message="候选与当前章节命中的已有术语完全重复，已过滤。",
                        source_term=term.source_term,
                    )
                )
                continue
            if self._structure_scaffold_pattern.fullmatch(term.source_term.strip()):
                issues.append(
                    GlossaryExtractionQualityIssue(
                        issue_type="structure_scaffold",
                        severity="low",
                        message="候选是章节结构壳，已过滤。",
                        source_term=term.source_term,
                    )
                )
                continue
            if term.source_term not in combined_text:
                issues.append(
                    GlossaryExtractionQualityIssue(
                        issue_type="source_not_in_chapter",
                        severity="high",
                        message="候选 source_term 未出现在章节标题或正文中，已过滤。",
                        source_term=term.source_term,
                        suggested_action="skip_candidate",
                    )
                )
                continue
            relation_issue = self._build_relation_issue(term=term, matched_existing_terms=matched_existing_terms)
            if relation_issue is not None:
                issues.append(relation_issue)
            accepted_terms.append(term)

        if len(envelope.terms) > 40:
            issues.append(
                GlossaryExtractionQualityIssue(
                    issue_type="too_many_candidates",
                    severity="medium",
                    message="单章候选数量异常偏多，需要质检确认。",
                    suggested_action="llm_quality_review",
                )
            )

        status = self._resolve_status(
            envelope=envelope,
            accepted_terms=accepted_terms,
            issues=issues,
            combined_text=combined_text,
        )
        return GlossaryChapterExtractionResult(
            chapter_id=chapter_id,
            chapter_index=chapter_index,
            chapter_title=chapter_title,
            status=status,
            terms=accepted_terms,
            matched_existing_terms=matched_existing_terms,
            reason=envelope.reason,
            quality_issues=issues,
        )

    def should_run_llm_quality_review(self, result: GlossaryChapterExtractionResult) -> bool:
        if result.status == "suspicious_empty":
            return True
        return any(issue.severity in {"medium", "high"} for issue in result.quality_issues)

    def _resolve_status(
        self,
        *,
        envelope: GlossaryExtractionEnvelope,
        accepted_terms: list[GlossaryExtraction],
        issues: list[GlossaryExtractionQualityIssue],
        combined_text: str,
    ) -> str:
        if accepted_terms:
            return "terms_found"
        if any(issue.issue_type == "source_not_in_chapter" and issue.severity == "high" for issue in issues):
            return "skipped"
        if envelope.extraction_status == "no_new_terms":
            if self._is_suspicious_empty(combined_text=combined_text):
                issues.append(
                    GlossaryExtractionQualityIssue(
                        issue_type="suspicious_empty",
                        severity="medium",
                        message="章节存在疑似专名形态，但抽取结果为 no_new_terms。",
                        suggested_action="targeted_reextract",
                    )
                )
                return "suspicious_empty"
            return "no_new_terms"
        return "no_new_terms"

    def _is_suspicious_empty(self, *, combined_text: str) -> bool:
        if len(combined_text) >= 1200:
            return True
        return len(self._name_like_pattern.findall(combined_text)) >= 2

    def _build_relation_issue(
        self,
        *,
        term: GlossaryExtraction,
        matched_existing_terms: list[MatchedExistingGlossaryTerm],
    ) -> GlossaryExtractionQualityIssue | None:
        if term.term_group_key != term.source_term:
            return None
        for existing in matched_existing_terms:
            if existing.category != term.category:
                continue
            if term.source_term in existing.source_term or existing.source_term in term.source_term:
                return GlossaryExtractionQualityIssue(
                    issue_type="relation_risk",
                    severity="medium",
                    message="候选疑似已有实体的别名或变体，但没有绑定已有 term_group_key。",
                    source_term=term.source_term,
                    suggested_action="llm_quality_review",
                )
        return None
```

- [ ] **Step 4: Run quality tests and verify they pass**

Run from `D:\Project\NovelT`:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_glossary_extraction_contract.py::test_quality_filters_duplicate_existing_terms tools/local_translation_workbench/tests/test_glossary_extraction_contract.py::test_quality_marks_suspicious_empty_when_name_like_terms_exist tools/local_translation_workbench/tests/test_glossary_extraction_contract.py::test_quality_filters_terms_not_present_in_chapter -q
```

Expected: PASS.

- [ ] **Step 5: Commit quality service**

```powershell
git add app/services/glossary_extraction_quality_service.py tests/test_glossary_extraction_contract.py
git commit -m "feat: add glossary extraction hard quality checks"
```

### Task 6: Workflow Integration Without LLM Quality Review

**Files:**
- Modify: `app/services/glossary_service.py`
- Modify: `app/services/glossary_workflow_domain_service.py`
- Modify: `tests/test_glossary_stage.py`
- Test: `tests/test_glossary_stage.py`

- [ ] **Step 1: Update fake extractor outputs in tests**

In `tests/test_glossary_stage.py`, add this helper near `FakeGlossaryProvider`:

```python
def _extraction_payload(terms: list[dict[str, object]], reason: str = "fake extraction") -> str:
    return json.dumps(
        {
            "extraction_status": "terms_found" if terms else "no_new_terms",
            "terms": terms,
            "reason": reason,
        },
        ensure_ascii=False,
    )
```

Change `FakeGlossaryProvider.generate_text` default content from:

```python
        content = self.outputs.pop(0) if self.outputs else '{"terms":[]}'
```

to:

```python
        content = self.outputs.pop(0) if self.outputs else _extraction_payload([], "fake default no new terms")
```

Then update extractor outputs only. For example, change an extractor output shaped as:

```python
json.dumps(
    {
        "terms": [
            {
                "source_term": "傅慕宁",
                "translated_term": "Fu Muning",
                "category": "character",
                "note": "Character name",
            }
        ]
    },
    ensure_ascii=False,
)
```

to:

```python
_extraction_payload(
    [
        {
            "source_term": "傅慕宁",
            "translated_term": "Fu Muning",
            "category": "character",
            "note": "Character name",
        }
    ],
    "发现新增人物。",
)
```

Keep relation review responses as `{"items":[]}` and finalize responses as `{"terms":[]}` because those parsers are separate.

- [ ] **Step 2: Add workflow payload test for no_new_terms**

Append this test to `tests/test_glossary_stage.py`:

```python
def test_glossary_extract_records_explicit_no_new_terms_payload(
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
            _extraction_payload([], "本章没有新增术语。"),
            '{"items":[]}',
            '{"items":[]}',
            '{"terms":[]}',
        ]
    )

    result = GlossaryService(db_session, provider=provider).run(
        request_id=request_id_factory("glossary-no-new-terms"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-glossary-no-new-terms",
    )

    extract_step = db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.action == "glossary.extract")
    ).scalar_one()

    assert result.candidate_count == 0
    assert extract_step.output_payload["draft_candidate_count"] == 0
    assert extract_step.output_payload["no_new_terms_count"] == 1
    assert extract_step.output_payload["suspicious_empty_count"] == 0
    assert extract_step.output_payload["skipped_chapter_count"] == 0
    assert extract_step.output_payload["chapter_results"][0]["status"] == "no_new_terms"
```

- [ ] **Step 3: Run updated workflow tests and verify failure**

Run from `D:\Project\NovelT`:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_glossary_stage.py::test_glossary_extract_records_explicit_no_new_terms_payload -q
```

Expected: FAIL because `extract_draft_candidates` has no `chapter_results` counters and `_extract_terms` still returns a list.

- [ ] **Step 4: Update `GlossaryService._extract_terms` signature**

In `app/services/glossary_service.py`, change the import:

```python
from .glossary_types import GlossaryExtraction
```

to:

```python
from dataclasses import replace

from .glossary_types import GlossaryExtraction, GlossaryExtractionEnvelope, MatchedExistingGlossaryTerm
```

Then replace `_extract_terms` signature with:

```python
    def _extract_terms(
        self,
        *,
        chapter_text: str,
        chapter_index: int,
        chapter_title: str,
        source_language: str,
        target_language: str,
        model_name: str,
        matched_existing_terms: list[MatchedExistingGlossaryTerm],
        risk_signals: list[str],
        previous_extraction: dict[str, object] | None = None,
    ) -> GlossaryExtractionEnvelope:
```

- [ ] **Step 5: Update `_extract_terms` prompt call and repair return**

Inside `_extract_terms`, update `build_extraction_prompt` call to pass:

```python
            matched_existing_terms=matched_existing_terms,
            risk_signals=risk_signals,
            previous_extraction=previous_extraction,
```

Then change the repair parse branch from:

```python
                return self.prompts.parse_extraction_response(repair_response.content)
```

to:

```python
                return replace(self.prompts.parse_extraction_response(repair_response.content), repaired=True)
```

- [ ] **Step 6: Integrate context and quality services in workflow domain**

In `app/services/glossary_workflow_domain_service.py`, add imports:

```python
from .glossary_existing_term_context_service import GlossaryExistingTermContextService
from .glossary_extraction_quality_service import GlossaryExtractionQualityService
from .glossary_types import GlossaryChapterExtractionResult
```

In `__init__`, add:

```python
        self.existing_term_context = GlossaryExistingTermContextService(self.glossary)
        self.extraction_quality = GlossaryExtractionQualityService()
```

At the start of `extract_draft_candidates`, after `created = 0`, add:

```python
        chapter_results: list[GlossaryChapterExtractionResult] = []
        quality_issues: list[dict[str, object]] = []
```

Replace the per-chapter extraction body with:

```python
            matched_existing_terms = self.existing_term_context.list_matched_terms_for_chapter(
                project_id=project_id,
                chapter_id=chapter.id,
                chapter_title=chapter.chapter_title,
                chapter_text=chapter_text,
            )
            try:
                extraction = self.glossary_service._extract_terms(
                    chapter_text=chapter_text,
                    chapter_index=chapter.chapter_index,
                    chapter_title=chapter.chapter_title,
                    source_language=project.source_language,
                    target_language=project.target_language,
                    model_name=actual_model_name,
                    matched_existing_terms=matched_existing_terms,
                    risk_signals=[],
                )
            except ToolError as exc:
                skipped_chapters.append(
                    {
                        "chapter_id": chapter.id,
                        "chapter_index": chapter.chapter_index,
                        "chapter_title": chapter.chapter_title,
                        "code": exc.code,
                        "message": exc.message,
                    }
                )
                continue
            quality_result = self.extraction_quality.evaluate(
                chapter_id=chapter.id,
                chapter_index=chapter.chapter_index,
                chapter_title=chapter.chapter_title,
                chapter_text=chapter_text,
                envelope=extraction,
                matched_existing_terms=matched_existing_terms,
            )
            chapter_results.append(quality_result)
            quality_issues.extend(
                issue.as_payload() | {
                    "chapter_id": chapter.id,
                    "chapter_index": chapter.chapter_index,
                }
                for issue in quality_result.quality_issues
            )
            decided_terms = self.glossary_service._decide_terms(
                project=project,
                chapter=chapter,
                extracted_terms=quality_result.terms,
                model_name=actual_model_name,
            )
```

Keep the existing draft creation loop after `decided_terms`.

- [ ] **Step 7: Add payload counters**

At the end of `extract_draft_candidates`, replace payload assembly with:

```python
        status_counts: dict[str, int] = {
            "terms_found": 0,
            "no_new_terms": 0,
            "suspicious_empty": 0,
            "skipped": len(skipped_chapters),
        }
        for result in chapter_results:
            status_counts[result.status] = status_counts.get(result.status, 0) + 1
        payload: dict[str, object] = {
            "draft_candidate_count": created,
            "chapter_results": [result.as_payload() for result in chapter_results],
            "terms_found_count": status_counts.get("terms_found", 0),
            "no_new_terms_count": status_counts.get("no_new_terms", 0),
            "suspicious_empty_count": status_counts.get("suspicious_empty", 0),
            "skipped_chapter_count": status_counts.get("skipped", 0),
            "quality_issues": quality_issues,
        }
        if skipped_chapters:
            payload["skipped_chapters"] = skipped_chapters
        return payload | self.glossary_service.build_generation_metadata()
```

- [ ] **Step 8: Run no_new_terms workflow test and verify it passes**

Run from `D:\Project\NovelT`:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_glossary_stage.py::test_glossary_extract_records_explicit_no_new_terms_payload -q
```

Expected: PASS.

- [ ] **Step 9: Run glossary stage regression and fix remaining extractor fixture outputs**

Run from `D:\Project\NovelT`:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_glossary_stage.py -q
```

Expected: PASS. If failures mention missing `extraction_status`, update only the extractor fake output consumed by `glossary.extract` to `_extraction_payload(...)`.

- [ ] **Step 10: Commit workflow integration**

```powershell
git add app/services/glossary_service.py app/services/glossary_workflow_domain_service.py tests/test_glossary_stage.py
git commit -m "feat: record chapter-level glossary extraction results"
```

### Task 7: Risk-Triggered LLM Quality Review And Targeted Re-Extraction

**Files:**
- Modify: `app/services/glossary_prompt_service.py`
- Modify: `app/services/glossary_service.py`
- Modify: `app/services/glossary_workflow_domain_service.py`
- Modify: `tests/test_glossary_stage.py`
- Test: `tests/test_glossary_stage.py`

- [ ] **Step 1: Add failing test for one targeted re-extraction**

Append this test to `tests/test_glossary_stage.py`:

```python
def test_glossary_suspicious_empty_triggers_one_targeted_reextract(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    source_file = project_workspace / "glossary-risk-source.txt"
    source_file.write_text(
        "第1章 走廊\n时羽小姐推开门。望月同学站在走廊尽头。",
        encoding="utf-8",
    )
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("glossary-risk-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )
    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("glossary-risk-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )
    provider = FakeGlossaryProvider(
        outputs=[
            _extraction_payload([], "没有新增术语。"),
            json.dumps(
                {
                    "passed": False,
                    "issues": [
                        {
                            "issue_type": "suspicious_empty",
                            "severity": "medium",
                            "message": "章节中出现疑似新人物。",
                            "source_evidence": "时羽小姐推开门。",
                            "suggested_action": "targeted_reextract",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            _extraction_payload(
                [
                    {
                        "source_term": "时羽",
                        "translated_term": "Shi Yu",
                        "category": "character",
                        "term_group_key": "char_shiyu",
                        "relation_role": "canonical",
                        "gender": "female",
                    }
                ],
                "定向补提取发现新增人物。",
            ),
            '{"items":[]}',
            '{"items":[]}',
            '{"terms":[]}',
        ]
    )

    result = GlossaryService(db_session, provider=provider).run(
        request_id=request_id_factory("glossary-risk-run"),
        project_id=project.id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-glossary-risk",
    )

    extract_step = db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.action == "glossary.extract")
    ).scalar_one()

    assert result.candidate_count == 1
    assert extract_step.output_payload["chapter_results"][0]["status"] == "terms_found"
    assert extract_step.output_payload["chapter_results"][0]["llm_quality_review"]["passed"] is False
    assert len([call for call in provider.calls if "术语抽取器" in str(call["prompt"])]) == 2
```

- [ ] **Step 2: Run targeted re-extraction test and verify it fails**

Run from `D:\Project\NovelT`:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_glossary_stage.py::test_glossary_suspicious_empty_triggers_one_targeted_reextract -q
```

Expected: FAIL because no LLM quality review or re-extraction path exists.

- [ ] **Step 3: Add LLM quality parser and prompt methods**

In `app/services/glossary_prompt_service.py`, add these methods after `build_extraction_json_repair_prompt`:

```python
    def build_extraction_quality_review_prompt(
        self,
        *,
        chapter_text: str,
        chapter_index: int,
        chapter_title: str,
        extraction_payload: dict[str, object],
        quality_issues: list[dict[str, object]],
    ) -> str:
        return (
            "你是小说术语抽取质检器。请判断当前章节的术语抽取结果是否可信。\n"
            "只返回 JSON，不要 Markdown，不要解释。\n"
            "格式：{\"passed\":true,\"issues\":[]} 或 {\"passed\":false,\"issues\":[{\"issue_type\":\"suspicious_empty\",\"severity\":\"medium\",\"message\":\"...\",\"source_evidence\":\"...\",\"suggested_action\":\"targeted_reextract\"}]}\n"
            "只有发现确实需要重新抽取时，suggested_action 才能是 targeted_reextract。\n\n"
            f"章节号: {chapter_index}\n"
            f"章节标题: {chapter_title}\n"
            f"硬质检问题：\n{json.dumps(quality_issues, ensure_ascii=False, indent=2)}\n\n"
            f"当前抽取结果：\n{json.dumps(extraction_payload, ensure_ascii=False, indent=2)}\n\n"
            "章节正文：\n"
            f"{chapter_text}"
        )

    def parse_extraction_quality_review_response(self, content: str) -> GlossaryLlmQualityReview:
        normalized = self.strip_code_fence(content).strip()
        if normalized == "":
            return GlossaryLlmQualityReview(passed=False, issues=[])
        try:
            payload = self.load_json_payload(normalized)
        except json.JSONDecodeError:
            return GlossaryLlmQualityReview(passed=False, issues=[])
        if not isinstance(payload, dict):
            return GlossaryLlmQualityReview(passed=False, issues=[])
        raw_issues = payload.get("issues", [])
        issues: list[GlossaryExtractionQualityIssue] = []
        if isinstance(raw_issues, list):
            for item in raw_issues:
                if not isinstance(item, dict):
                    continue
                issues.append(
                    GlossaryExtractionQualityIssue(
                        issue_type=self.normalize_text(item.get("issue_type")) or "llm_quality_issue",
                        severity=self.normalize_text(item.get("severity")) or "medium",
                        message=self.normalize_text(item.get("message")) or "LLM 质检发现风险。",
                        source_term=self.normalize_optional_text(item.get("source_term")),
                        source_evidence=self.normalize_optional_text(item.get("source_evidence")),
                        suggested_action=self.normalize_optional_text(item.get("suggested_action")),
                    )
                )
        return GlossaryLlmQualityReview(
            passed=bool(payload.get("passed")) and not issues,
            issues=issues,
        )
```

- [ ] **Step 4: Add service method for LLM quality review**

In `app/services/glossary_service.py`, add `GlossaryLlmQualityReview` to the type import and insert this method below `_extract_terms`:

```python
    def _review_extraction_quality(
        self,
        *,
        chapter_text: str,
        chapter_index: int,
        chapter_title: str,
        extraction_payload: dict[str, object],
        quality_issues: list[dict[str, object]],
        model_name: str,
    ) -> GlossaryLlmQualityReview:
        if self.provider is None:
            raise ToolError(code="invalid_arguments", message="缺少术语质检 provider。", status=400)
        prompt = self.prompts.build_extraction_quality_review_prompt(
            chapter_text=chapter_text,
            chapter_index=chapter_index,
            chapter_title=chapter_title,
            extraction_payload=extraction_payload,
            quality_issues=quality_issues,
        )
        response = self.provider.generate_text(
            prompt=prompt,
            model_name=model_name,
            timeout_seconds=60,
        )
        self._generation_results.append(response)
        return self.prompts.parse_extraction_quality_review_response(response.content)
```

- [ ] **Step 5: Add one-round re-extraction logic in workflow domain**

In `extract_draft_candidates`, after initial `quality_result = self.extraction_quality.evaluate(...)`, insert:

```python
            if self.extraction_quality.should_run_llm_quality_review(quality_result):
                llm_review = self.glossary_service._review_extraction_quality(
                    chapter_text=chapter_text,
                    chapter_index=chapter.chapter_index,
                    chapter_title=chapter.chapter_title,
                    extraction_payload=quality_result.as_payload(),
                    quality_issues=[issue.as_payload() for issue in quality_result.quality_issues],
                    model_name=actual_model_name,
                )
                if any(issue.suggested_action == "targeted_reextract" for issue in llm_review.issues):
                    risk_signals = [
                        issue.issue_type
                        for issue in quality_result.quality_issues + llm_review.issues
                    ]
                    retry_extraction = self.glossary_service._extract_terms(
                        chapter_text=chapter_text,
                        chapter_index=chapter.chapter_index,
                        chapter_title=chapter.chapter_title,
                        source_language=project.source_language,
                        target_language=project.target_language,
                        model_name=actual_model_name,
                        matched_existing_terms=matched_existing_terms,
                        risk_signals=risk_signals,
                        previous_extraction=quality_result.as_payload(),
                    )
                    quality_result = self.extraction_quality.evaluate(
                        chapter_id=chapter.id,
                        chapter_index=chapter.chapter_index,
                        chapter_title=chapter.chapter_title,
                        chapter_text=chapter_text,
                        envelope=retry_extraction,
                        matched_existing_terms=matched_existing_terms,
                    )
                quality_result = GlossaryChapterExtractionResult(
                    chapter_id=quality_result.chapter_id,
                    chapter_index=quality_result.chapter_index,
                    chapter_title=quality_result.chapter_title,
                    status=quality_result.status,
                    terms=quality_result.terms,
                    matched_existing_terms=quality_result.matched_existing_terms,
                    reason=quality_result.reason,
                    quality_issues=quality_result.quality_issues,
                    llm_quality_review=llm_review.as_payload(),
                )
```

This inserts exactly one re-extraction attempt because there is no loop.

- [ ] **Step 6: Run targeted re-extraction test and verify it passes**

Run from `D:\Project\NovelT`:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_glossary_stage.py::test_glossary_suspicious_empty_triggers_one_targeted_reextract -q
```

Expected: PASS.

- [ ] **Step 7: Commit risk-triggered LLM quality review**

```powershell
git add app/services/glossary_prompt_service.py app/services/glossary_service.py app/services/glossary_workflow_domain_service.py tests/test_glossary_stage.py
git commit -m "feat: add risk-triggered glossary extraction quality review"
```

### Task 8: Existing Term Consistency Regression

**Files:**
- Modify: `tests/test_glossary_stage.py`
- Test: `tests/test_glossary_stage.py`

- [ ] **Step 1: Add regression test for matched existing term prompt and duplicate filtering**

Append this test to `tests/test_glossary_stage.py`:

```python
def test_glossary_extraction_uses_matched_existing_terms_and_filters_duplicates(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    source_file = project_workspace / "glossary-existing-context-source.txt"
    source_file.write_text(
        "第1章 林溪的信\n溪溪把信交给林溪。",
        encoding="utf-8",
    )
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("glossary-existing-context-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )
    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("glossary-existing-context-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )
    chapter = db_session.execute(
        select(Chapter).where(Chapter.project_id == project.id)
    ).scalar_one()
    repository = GlossaryRepository(db_session)
    repository.create_entry(
        project_id=project.id,
        source_term="林溪",
        target_term="Lin Xi",
        category="character",
        term_group_key="char_linxi",
        relation_role="canonical",
        scope_level="project_term",
    )
    provider = FakeGlossaryProvider(
        outputs=[
            _extraction_payload(
                [
                    {
                        "source_term": "林溪",
                        "translated_term": "Lin Xi",
                        "category": "character",
                        "term_group_key": "char_linxi",
                        "relation_role": "canonical",
                    },
                    {
                        "source_term": "溪溪",
                        "translated_term": "Xixi",
                        "category": "character",
                        "term_group_key": "char_linxi",
                        "relation_role": "alias",
                    },
                ],
                "发现已有人物别名。",
            ),
            json.dumps(
                {
                    "decisions": [
                        {
                            "source_term": "溪溪",
                            "keep": True,
                            "term_group_key": "char_linxi",
                            "relation_role": "alias",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            '{"items":[]}',
            '{"items":[]}',
            '{"terms":[]}',
        ]
    )

    result = GlossaryService(db_session, provider=provider).run(
        request_id=request_id_factory("glossary-existing-context-run"),
        project_id=project.id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-glossary-existing-context",
    )
    extract_step = db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.action == "glossary.extract")
    ).scalar_one()

    assert result.candidate_count == 1
    assert '"source_term": "林溪"' in provider.calls[0]["prompt"]
    assert '"target_term": "Lin Xi"' in provider.calls[0]["prompt"]
    assert extract_step.output_payload["quality_issues"][0]["issue_type"] == "duplicate_existing"
    assert db_session.execute(
        select(GlossaryDraftCandidate).where(
            GlossaryDraftCandidate.project_id == project.id,
            GlossaryDraftCandidate.chapter_id == chapter.id,
        )
    ).scalar_one().source_term == "溪溪"
```

- [ ] **Step 2: Run consistency regression and verify it passes**

Run from `D:\Project\NovelT`:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_glossary_stage.py::test_glossary_extraction_uses_matched_existing_terms_and_filters_duplicates -q
```

Expected: PASS.

- [ ] **Step 3: Commit consistency regression**

```powershell
git add tests/test_glossary_stage.py
git commit -m "test: cover glossary extraction existing term consistency"
```

### Task 9: Documentation And Full Verification

**Files:**
- Modify: `README.md`
- Test: `tests/test_glossary_extraction_contract.py`
- Test: `tests/test_glossary_stage.py`

- [ ] **Step 1: Update README glossary section**

In `README.md`, replace this bullet:

```markdown
- 抽取 prompt 要求模型直接返回 JSON，当前收口字段对齐生产侧常见口径：`source_term / translated_term / category / note / gender / age_group / term_group_key / relation_role`。
```

with:

```markdown
- 抽取 prompt 要求模型直接返回 JSON envelope：有新增术语时返回 `{"extraction_status":"terms_found","terms":[...]}`；无新增术语时必须返回 `{"extraction_status":"no_new_terms","terms":[],"reason":"..."}`，不能用空字符串、`null`、空数组或缺少 status 的 `{"terms":[]}` 表示空结果。
```

Add this bullet after it:

```markdown
- 术语抽取会先注入当前章节标题和正文真实命中的已有术语，用于保持译名和 `term_group_key / relation_role` 一致；未命中当前章节的全局术语不会进入 extractor prompt。
```

- [ ] **Step 2: Run contract tests**

Run from `D:\Project\NovelT`:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_glossary_extraction_contract.py -q
```

Expected: all tests in `test_glossary_extraction_contract.py` PASS.

- [ ] **Step 3: Run glossary stage tests**

Run from `D:\Project\NovelT`:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_glossary_stage.py -q
```

Expected: all tests in `test_glossary_stage.py` PASS.

- [ ] **Step 4: Run full regression**

Run from `D:\Project\NovelT`:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests -q
```

Expected: all local translation workbench tests PASS.

- [ ] **Step 5: Inspect final git diff**

Run from `D:\Project\NovelT\tools\local_translation_workbench`:

```powershell
git status --short
git diff --stat
```

Expected: only files listed in this plan are modified.

- [ ] **Step 6: Commit documentation and verification adjustments**

```powershell
git add README.md tests/test_glossary_extraction_contract.py tests/test_glossary_stage.py
git commit -m "docs: document glossary extraction quality contract"
```

## Acceptance Checklist

- `parse_extraction_response` rejects ambiguous empty outputs.
- `no_new_terms` is a successful chapter state and does not create draft candidates.
- Existing terms injected into extraction prompt are limited to current chapter matches.
- Exact duplicate existing terms are filtered before draft candidate creation.
- New aliases can reuse an existing `term_group_key`.
- Risky empty extraction can trigger exactly one LLM quality review and one targeted re-extraction.
- Workflow extract step payload includes `chapter_results`, `draft_candidate_count`, `no_new_terms_count`, `suspicious_empty_count`, `skipped_chapter_count`, `quality_issues`, and `token_usage` when provider usage exists.
- Full test suite passes from `D:\Project\NovelT`.

## Self-Review

- Spec coverage: matched existing terms, explicit `no_new_terms`, hard quality, risk-triggered LLM quality, one re-extraction cap, payload counters, and documentation are covered by Tasks 1 through 9.
- Placeholder scan: this plan contains concrete file paths, command lines, expected outputs, and code snippets for each code-changing step.
- Type consistency: all later tasks use the dataclasses defined in Task 2; workflow integration consumes `GlossaryExtractionEnvelope` and produces `GlossaryChapterExtractionResult`.
