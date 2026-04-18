# P1.2 / P1.3 尾项收口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不新增 schema 的前提下，完成 `P1.2` 的 glossary 关系组观察面与 translation 注入校准，并完成 `P1.3` 的历史版本切换、review/export 版本来源快照与相关 inspect 收口。

**Architecture:** 这轮实现分成三条紧耦合但可独立回归的子线：第一条是 glossary 读模型，新增关系组服务并把正式视角与 pipeline 视角都收成稳定返回；第二条是 translation inspect/history 读模型，在现有 `TranslationInspectionService` 上补 `version_id` 和“当前选中版本”语义；第三条是 review/export 的轻量 translation source 快照，把 run 来源信息写入 summary 并在 inspect 顶层透出。整体都走“新增小服务 + 薄改入口 service”的方式，避免把已有大文件继续撑大。

**Tech Stack:** Python 3、SQLAlchemy ORM、pytest、PowerShell CLI

---

## 文件结构

- Create: `app/services/glossary_relation_group_service.py`
  责任：把 glossary entries 或 finalized terms 聚合成 `relation_groups` / `finalized_relation_groups`，统一一致性告警规则和角色分布计算。
- Create: `app/services/translation_source_snapshot_service.py`
  责任：从 review/export 的 segment rows 构建轻量 `translation_source` 快照，统一 version 元信息裁剪口径。
- Modify: `app/services/glossary_service.py`
  责任：`inspect()` 追加 `relation_groups`，并复用新关系组服务。
- Modify: `app/services/glossary_pipeline_service.py`
  责任：`inspect_pipeline()` 追加 `finalized_terms / finalized_relation_groups`，同时从 finalize step payload 读取真实 finalized 结果。
- Modify: `app/services/translation_assets_service.py`
  责任：把 glossary prompt 注入改成组感知渲染，锁稳定排序和“只注入正文命中项”规则。
- Modify: `app/services/translation_inspection_service.py`
  责任：新增 `version_id` 支持，让 `version / provenance / timeline / compare` 全部围绕当前选中版本工作。
- Modify: `app/services/translation_service.py`
  责任：透传 `version_id` 给 inspection service，保持薄入口一致。
- Modify: `app/action_router.py`
  责任：为 `inspect.translation` 透传 `version_id`。
- Modify: `app/services/review_service.py`
  责任：run summary 写入 `translation_source`，inspect 顶层透出 `translation_source`。
- Modify: `app/services/export_service.py`
  责任：run summary 写入 `translation_source`，inspect 顶层透出 `translation_source`。
- Modify: `tests/test_glossary_stage.py`
  责任：锁 glossary relation groups、pipeline finalized 视角和 inspect 行为。
- Modify: `tests/test_translation_assets_service.py`
  责任：锁 group block 排序和 prompt 注入不扩写规则。
- Modify: `tests/test_translation_inspection_service.py`
  责任：锁 `TranslationService.inspect()` 的委托参数更新，以及 `TranslationInspectionService` 的 locator 校验。
- Modify: `tests/test_translation_stage.py`
  责任：锁 `version_id` 历史版本切换、compare 语义、CLI 参数透传和实际 inspect 输出。
- Modify: `tests/test_review_export.py`
  责任：锁 review/export translation source summary 与 inspect 顶层透出。
- Modify: `README.md`
  责任：更新 glossary/translation/review/export inspect 的新能力说明。
- Modify: `docs/roadmap.md`
  责任：把 `P1.2 / P1.3` 尾项标为完成，并补当前完成口径。
- Modify: `CHANGELOG.md`
  责任：记录本轮落地内容和最新测试基线。

---

### Task 1: 先补 glossary 关系组读模型，并让 `inspect.glossary` 直接返回 `relation_groups`

**Files:**
- Create: `app/services/glossary_relation_group_service.py`
- Modify: `app/services/glossary_service.py`
- Modify: `tests/test_glossary_stage.py`
- Test: `tests/test_glossary_stage.py`

- [ ] **Step 1: 先写 `inspect.glossary` 关系组红测**

```python
def test_inspect_glossary_returns_relation_groups_with_consistency_warnings(
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

    glossary = GlossaryService(db_session, provider=FakeGlossaryProvider())
    glossary.seed_locked_entry(project_id=project_id, source_term="林溪", target_term="Lin Xi")
    glossary.seed_locked_entry(project_id=project_id, source_term="小溪", target_term="Little Xi")

    entry_canonical = glossary.get_entry(project_id=project_id, source_term="林溪")
    entry_alias = glossary.get_entry(project_id=project_id, source_term="小溪")
    entry_canonical.category = "character"
    entry_alias.category = "character"
    entry_canonical.gender = "female"
    entry_alias.gender = "male"
    entry_canonical.age_group = "teen"
    entry_alias.age_group = "teen"
    entry_canonical.term_group_key = "char_linxi"
    entry_alias.term_group_key = "char_linxi"
    entry_canonical.relation_role = "canonical"
    entry_alias.relation_role = "alias"
    db_session.commit()

    payload = glossary.inspect(project_id=project_id)

    assert "relation_groups" in payload
    assert len(payload["relation_groups"]) == 1
    group = payload["relation_groups"][0]
    assert group["term_group_key"] == "char_linxi"
    assert group["member_count"] == 2
    assert group["role_distribution"] == {"canonical": 1, "alias": 1}
    assert group["consistency"]["category_consistent"] is True
    assert group["consistency"]["gender_consistent"] is False
    assert group["consistency"]["age_group_consistent"] is True
    assert group["consistency"]["warnings"] == ["gender_conflict"]
    assert [item["source_term"] for item in group["members"]] == ["林溪", "小溪"]


def test_inspect_glossary_skips_single_independent_group_noise(
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

    glossary = GlossaryService(db_session, provider=FakeGlossaryProvider())
    glossary.seed_locked_entry(project_id=project_id, source_term="青石镇", target_term="Qingshi Town")

    payload = glossary.inspect(project_id=project_id)

    assert payload["relation_groups"] == []
```

- [ ] **Step 2: 跑红测，确认当前 `inspect.glossary` 还没有 `relation_groups`**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_glossary_stage.py -k "relation_groups_with_consistency_warnings or skips_single_independent_group_noise" -q`

Expected: FAIL，至少一条因为 `payload["relation_groups"]` 不存在而失败。

- [ ] **Step 3: 新建关系组服务并接到 `GlossaryService.inspect()`**

```python
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable


class GlossaryRelationGroupService:
    ROLE_PRIORITY = {
        "canonical": 0,
        "alias": 1,
        "title": 2,
        "variant": 3,
        "independent": 4,
    }

    def build_relation_groups(self, *, items: Iterable[object], member_id_field: str) -> list[dict[str, object]]:
        grouped: dict[str, list[object]] = defaultdict(list)
        for item in items:
            group_key = str(getattr(item, "term_group_key", "") or "")
            if group_key == "":
                continue
            grouped[group_key].append(item)

        relation_groups: list[dict[str, object]] = []
        for group_key, members in sorted(grouped.items()):
            if len(members) == 1 and str(getattr(members[0], "relation_role", "independent")) == "independent":
                continue
            relation_groups.append(self._build_group_payload(group_key=group_key, members=members, member_id_field=member_id_field))
        return relation_groups
```

```python
class GlossaryService:
    def __init__(self, session: Session, *, provider: Provider | None = None) -> None:
        self.session = session
        self.provider = provider
        self.glossary = GlossaryRepository(session)
        self._generation_results: list[TextGenerationResult] = []
        self.project_staleness = ProjectStalenessService(session)
        self.relation_groups = GlossaryRelationGroupService()

    def inspect(self, *, project_id: int) -> dict[str, list[dict[str, object]]]:
        entry_rows = self.glossary.list_entries(project_id)
        candidate_rows = self.glossary.list_candidates(project_id)
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
            for entry in entry_rows
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
            for candidate in candidate_rows
        ]
        return {
            "entries": entries,
            "candidates": candidates,
            "relation_groups": self.relation_groups.build_relation_groups(
                items=entry_rows,
                member_id_field="entry_id",
            ),
        }
```

- [ ] **Step 4: 重新跑定点测试，确认 `inspect.glossary` 已稳定返回关系组**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_glossary_stage.py -k "relation_groups_with_consistency_warnings or skips_single_independent_group_noise" -q`

Expected: PASS，输出 `2 passed`。

- [ ] **Step 5: Commit**

```bash
git add app/services/glossary_relation_group_service.py app/services/glossary_service.py tests/test_glossary_stage.py
git commit -m "feat: add glossary relation groups inspect view"
```

---

### Task 2: 补 `glossary.inspect_pipeline` 的 finalized 视角，并复用同一套关系组逻辑

**Files:**
- Modify: `app/services/glossary_pipeline_service.py`
- Modify: `app/services/glossary_service.py`
- Modify: `tests/test_glossary_stage.py`
- Test: `tests/test_glossary_stage.py`

- [ ] **Step 1: 先写 finalized 视角红测**

```python
def test_glossary_inspect_pipeline_returns_finalized_terms_and_relation_groups_after_finalize(
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

    provider = FakeGlossaryProvider()
    result = GlossaryService(db_session, provider=provider).run(
        request_id=request_id_factory("glossary-pipeline-finalized"),
        project_id=project_id,
        scope={"type": "all"},
        model_profile_id="profile-glossary-finalized",
        workflow_key="glossary_single_llm_v1",
    )
    assert result.candidate_count >= 1

    workflow_run_id = db_session.execute(
        select(WorkflowRun.id)
        .where(WorkflowRun.project_id == project_id, WorkflowRun.stage == "glossary")
        .order_by(WorkflowRun.id.desc())
    ).scalars().first()
    assert workflow_run_id is not None

    payload = GlossaryPipelineService(db_session, provider=provider).inspect_pipeline(workflow_run_id=int(workflow_run_id))

    assert payload["finalized_terms"]
    assert payload["finalized_relation_groups"] == []
    assert all("target_term" in item for item in payload["finalized_terms"])
```

- [ ] **Step 2: 跑红测，确认当前 `inspect_pipeline()` 还没有 finalized 视角**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_glossary_stage.py -k "finalized_terms_and_relation_groups_after_finalize" -q`

Expected: FAIL，至少一条因为 `finalized_terms` / `finalized_relation_groups` 不存在而失败。

- [ ] **Step 3: 让 finalize step 把真实 `finalized_terms` 带进 payload，并让 inspect 从 payload 读**

```python
class GlossaryService:
    def build_finalized_terms_preview(self, *, workflow_run_id: int) -> list[dict[str, object]]:
        step = self.session.execute(
            select(WorkflowStepRun)
            .where(
                WorkflowStepRun.workflow_run_id == workflow_run_id,
                WorkflowStepRun.step_key == "finalize",
            )
            .order_by(WorkflowStepRun.id.desc())
        ).scalars().first()
        if step is None or not isinstance(step.output_payload, dict):
            return []
        finalized_terms = step.output_payload.get("finalized_terms")
        if not isinstance(finalized_terms, list):
            return []
        return [item for item in finalized_terms if isinstance(item, dict)]
```

```python
class GlossaryPipelineService:
    def inspect_pipeline(self, *, workflow_run_id: int) -> dict[str, object]:
        finalized_terms = self.glossary_service.build_finalized_terms_preview(workflow_run_id=workflow_run_id)
        return {
            "draft_candidates": self.glossary.inspect_draft_candidates(workflow_run_id=workflow_run_id),
            "reviews": self.glossary.inspect_candidate_reviews(workflow_run_id=workflow_run_id),
            "finalized_terms": finalized_terms,
            "finalized_relation_groups": self.glossary_service.relation_groups.build_relation_groups(
                items=[SimpleNamespace(id=index + 1, **item) for index, item in enumerate(finalized_terms)],
                member_id_field="draft_candidate_id",
            ),
        }
```

- [ ] **Step 4: 重新跑定点测试，确认 pipeline inspect 已能直接看 finalized 视角**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_glossary_stage.py -k "finalized_terms_and_relation_groups_after_finalize" -q`

Expected: PASS，输出 `1 passed`。

- [ ] **Step 5: Commit**

```bash
git add app/services/glossary_pipeline_service.py app/services/glossary_service.py tests/test_glossary_stage.py
git commit -m "feat: add finalized glossary pipeline inspect view"
```

---

### Task 3: 校准 translation glossary 注入，让 prompt 渲染变成组感知输出

**Files:**
- Modify: `app/services/translation_assets_service.py`
- Modify: `tests/test_translation_assets_service.py`
- Test: `tests/test_translation_assets_service.py`

- [ ] **Step 1: 先写 prompt 分组与不扩写规则红测**

```python
def test_translation_assets_service_renders_group_blocks_in_match_order() -> None:
    service = TranslationAssetsService()
    glossary_entries = [
        SimpleNamespace(
            source_term="林溪",
            target_term="Lin Xi",
            category="character",
            note=None,
            gender="female",
            age_group="teen",
            status="active",
            locked=0,
            term_group_key="char_linxi",
            relation_role="canonical",
        ),
        SimpleNamespace(
            source_term="小溪",
            target_term="Little Xi",
            category="character",
            note=None,
            gender="female",
            age_group="teen",
            status="active",
            locked=0,
            term_group_key="char_linxi",
            relation_role="alias",
        ),
        SimpleNamespace(
            source_term="秦大人",
            target_term="Lord Qin",
            category="character",
            note=None,
            gender=None,
            age_group=None,
            status="active",
            locked=0,
            term_group_key="title_lord_qin",
            relation_role="title",
        ),
    ]

    prompt = service.build_translation_prompt(
        source_language="zh",
        target_language="en",
        chapter_index=1,
        segment_index=1,
        source_text="小溪向秦大人行礼，林溪没有说话。",
        glossary_entries=service.build_prompt_glossary_entries(
            glossary_entries=glossary_entries,
            source_text="小溪向秦大人行礼，林溪没有说话。",
        ),
    )

    assert "[group char_linxi]" in prompt
    assert "[group title_lord_qin]" in prompt
    assert prompt.index("[group char_linxi]") < prompt.index("[group title_lord_qin]")
    assert prompt.index("- 林溪 => Lin Xi") < prompt.index("- 小溪 => Little Xi")


def test_translation_assets_service_does_not_inject_unmatched_canonical_from_same_group() -> None:
    service = TranslationAssetsService()
    glossary_entries = [
        SimpleNamespace(
            source_term="林溪",
            target_term="Lin Xi",
            category="character",
            note=None,
            gender="female",
            age_group="teen",
            status="active",
            locked=0,
            term_group_key="char_linxi",
            relation_role="canonical",
        ),
        SimpleNamespace(
            source_term="小溪",
            target_term="Little Xi",
            category="character",
            note=None,
            gender="female",
            age_group="teen",
            status="active",
            locked=0,
            term_group_key="char_linxi",
            relation_role="alias",
        ),
    ]

    selected = service.build_prompt_glossary_entries(
        glossary_entries=glossary_entries,
        source_text="小溪笑了。",
    )

    assert [item.source_term for item in selected] == ["小溪"]
```

- [ ] **Step 2: 跑红测，确认当前 prompt 还是平铺的**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_assets_service.py -k "renders_group_blocks_in_match_order or does_not_inject_unmatched_canonical_from_same_group" -q`

Expected: FAIL，第一条至少会因为 prompt 中没有 `[group char_linxi]` 这样的分组块而失败。

- [ ] **Step 3: 在 `TranslationAssetsService` 上补组感知渲染**

```python
class TranslationAssetsService:
    ROLE_PRIORITY = {
        "canonical": 0,
        "alias": 1,
        "title": 2,
        "variant": 3,
        "independent": 4,
    }

    def build_translation_prompt(
        self,
        *,
        source_language: str,
        target_language: str,
        chapter_index: int,
        segment_index: int,
        source_text: str,
        glossary_entries: list[object],
    ) -> str:
        prompt = (
            f"你是一个翻译引擎。请翻译正文，把{source_language}文本翻译成{target_language}。\n"
            f"章节: {chapter_index}\n"
            f"段落: {segment_index}\n"
            "只返回译文，不要解释。\n"
            "如果正文命中了术语表中的 source_term，译文必须优先使用该条目的 target_term。\n"
            "同组命中的多条表面形式必须分别按各自 source_term 对应 target_term 翻译，不能互换。\n"
            "不要把当前命中的 alias/title 改写成同组 canonical，反之亦然。"
        )
        if glossary_entries:
            prompt += "\n术语表：\n" + self._render_glossary_groups(glossary_entries)
        return f"{prompt}\n\n{source_text}"

    def _render_glossary_groups(self, glossary_entries: list[object]) -> str:
        groups: dict[str, list[object]] = {}
        for entry in glossary_entries:
            groups.setdefault(str(entry.term_group_key), []).append(entry)
        lines: list[str] = []
        for group_key, entries in groups.items():
            lines.append(f"[group {group_key}]")
            for entry in sorted(
                entries,
                key=lambda item: (
                    int(self.ROLE_PRIORITY.get(str(item.relation_role), 99)),
                    str(item.source_term),
                ),
            ):
                lines.append(self._format_glossary_entry(entry))
            lines.append("")
        return "\n".join(lines).strip()
```

- [ ] **Step 4: 重新跑定点测试，确认 prompt 渲染已稳定收口**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_assets_service.py -k "renders_group_blocks_in_match_order or does_not_inject_unmatched_canonical_from_same_group" -q`

Expected: PASS，输出 `2 passed`。

- [ ] **Step 5: Commit**

```bash
git add app/services/translation_assets_service.py tests/test_translation_assets_service.py
git commit -m "feat: group glossary prompt injection by relation group"
```

---

### Task 4: 打通 `inspect.translation version_id`，让 inspect / provenance / timeline / compare 全部围绕当前选中版本

**Files:**
- Modify: `app/services/translation_inspection_service.py`
- Modify: `app/services/translation_service.py`
- Modify: `app/action_router.py`
- Modify: `tests/test_translation_inspection_service.py`
- Modify: `tests/test_translation_stage.py`
- Test: `tests/test_translation_inspection_service.py`
- Test: `tests/test_translation_stage.py`

- [ ] **Step 1: 先写委托更新和 `version_id` 校验红测**

```python
def test_translation_service_inspect_delegates_version_id_to_inspection_service(
    db_session,
    project_workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.local_translation_workbench.app.services.translation_inspection_service import (
        TranslationInspectionService,
    )

    captured: dict[str, object] = {}

    def fake_inspect(self, **kwargs):
        captured.update(kwargs)
        return {"translations": [], "versions": []}

    monkeypatch.setattr(TranslationInspectionService, "inspect", fake_inspect)

    service = TranslationService(db_session, base_data_dir=project_workspace, provider=None)
    payload = service.inspect(
        project_id=11,
        segment_id=22,
        chapter_index=None,
        segment_index=None,
        version_id=44,
        compare_version_id=33,
    )

    assert payload == {"translations": [], "versions": []}
    assert captured["version_id"] == 44
    assert captured["compare_version_id"] == 33


def test_translation_inspection_service_rejects_version_id_without_locator(db_session) -> None:
    from tools.local_translation_workbench.app.errors import ToolError
    from tools.local_translation_workbench.app.services.translation_inspection_service import (
        TranslationInspectionService,
    )

    service = TranslationInspectionService(db_session)
    with pytest.raises(ToolError, match="version_id"):
        service.inspect(project_id=7, version_id=9)
```

- [ ] **Step 2: 再写历史版本切换和 compare 语义红测**

```python
def test_inspect_translation_can_select_historical_version_by_version_id(
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
        request_id=request_id_factory("translation-version-select-a"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-version-select-a",
    )
    service.run(
        request_id=request_id_factory("translation-version-select-b"),
        project_id=project_id,
        scope={"type": "chapter_range", "start": 1, "end": 1},
        model_profile_id="profile-version-select-b",
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
    versions = db_session.execute(
        select(SegmentTranslationVersion)
        .where(SegmentTranslationVersion.segment_translation_id == translation.id)
        .order_by(SegmentTranslationVersion.version_index.asc())
    ).scalars().all()

    payload = TranslationService(db_session, base_data_dir=project_workspace).inspect(
        project_id=project_id,
        segment_id=int(first_segment),
        version_id=int(versions[0].id),
        compare_version_id=int(versions[1].id),
    )

    row = payload["translations"][0]
    assert row["active_version_id"] == int(versions[1].id)
    assert row["inspected_version_id"] == int(versions[0].id)
    assert row["inspected_version_is_active"] is False
    assert row["version"]["id"] == int(versions[0].id)
    assert row["compare"]["current_version"]["id"] == int(versions[0].id)
    assert row["compare"]["base_version"]["id"] == int(versions[1].id)
```

- [ ] **Step 3: 跑红测，确认当前 inspection 还不支持 `version_id`**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_inspection_service.py tests\test_translation_stage.py -k "version_id or historical_version_by_version_id" -q`

Expected: FAIL，至少一条会因为 `inspect()` 还不接受 `version_id` 或 compare 仍绑在 active version 上而失败。

- [ ] **Step 4: 在 inspection service、translation 薄入口和 CLI 里同时打通 `version_id`**

```python
class TranslationService:
    def inspect(
        self,
        *,
        project_id: int,
        segment_id: int | None = None,
        chapter_index: int | None = None,
        segment_index: int | None = None,
        version_id: int | None = None,
        compare_version_id: int | None = None,
    ) -> dict[str, list[dict[str, object]]]:
        return TranslationInspectionService(self.session).inspect(
            project_id=project_id,
            segment_id=segment_id,
            chapter_index=chapter_index,
            segment_index=segment_index,
            version_id=version_id,
            compare_version_id=compare_version_id,
        )
```

```python
class TranslationInspectionService:
    def inspect(
        self,
        *,
        project_id: int,
        segment_id: int | None = None,
        chapter_index: int | None = None,
        segment_index: int | None = None,
        version_id: int | None = None,
        compare_version_id: int | None = None,
    ) -> dict[str, list[dict[str, object]]]:
        self._validate_inspect_translation_locator(
            segment_id=segment_id,
            chapter_index=chapter_index,
            segment_index=segment_index,
            version_id=version_id,
            compare_version_id=compare_version_id,
        )
        if segment_id is None and chapter_index is None and segment_index is None:
            return self._inspect_project_translations(project_id=project_id)

        chapter, segment, translation, active_version = self._resolve_single_translation_row(
            project_id=project_id,
            segment_id=segment_id,
            chapter_index=chapter_index,
            segment_index=segment_index,
        )
        inspected_version = self._resolve_inspected_version(
            project_id=project_id,
            translation=translation,
            active_version=active_version,
            version_id=version_id,
        )
        active_versions = [] if inspected_version is None else [inspected_version]
        provenance_by_version_id = self._build_translation_provenance_map(active_versions=active_versions)
        timeline_by_version_id = self._build_translation_timeline_map(active_versions=active_versions)
        row = self._build_translation_row_payload(
            project_id=project_id,
            chapter=chapter,
            segment=segment,
            segment_translation=translation,
            version=inspected_version,
            active_version=active_version,
            provenance_by_version_id=provenance_by_version_id,
            timeline_by_version_id=timeline_by_version_id,
        )
        if compare_version_id is not None:
            row["compare"] = self._build_translation_compare_payload(
                project_id=project_id,
                translation=translation,
                current_version=inspected_version,
                compare_version_id=compare_version_id,
            )
        versions = (
            []
            if translation is None
            else [
                self._build_translation_version_list_payload(item)
                for item in self.translations.list_versions_for_translation(int(translation.id))
            ]
        )
        return {"translations": [row], "versions": versions}
```

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
        version_id=_parse_optional_int(arguments.get("version_id")),
        compare_version_id=_parse_optional_int(arguments.get("compare_version_id")),
    )
        return {"ok": True, "action": "inspect.translation", "data": data}
    finally:
        session.close()
```

- [ ] **Step 5: 重新跑定点测试，确认历史版本切换和 compare 语义都已收口**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_inspection_service.py tests\test_translation_stage.py -k "version_id or historical_version_by_version_id or inspect_translation_cli" -q`

Expected: PASS，输出通过数大于等于新增用例数，并且没有 `invalid_arguments` 误判。

- [ ] **Step 6: Commit**

```bash
git add app/services/translation_inspection_service.py app/services/translation_service.py app/action_router.py tests/test_translation_inspection_service.py tests/test_translation_stage.py
git commit -m "feat: add translation inspect version selection"
```

---

### Task 5: 给 review/export 落 `translation_source` 快照，并在 inspect 顶层直接透出

**Files:**
- Create: `app/services/translation_source_snapshot_service.py`
- Modify: `app/services/review_service.py`
- Modify: `app/services/export_service.py`
- Modify: `tests/test_review_export.py`
- Test: `tests/test_review_export.py`

- [ ] **Step 1: 先写 review/export summary 与 inspect 的红测**

```python
def test_review_run_summary_contains_translation_source_snapshot(
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
        request_id=request_id_factory("review-source-snapshot"),
        project_id=project_id,
        scope={"type": "all"},
    )

    run = db_session.execute(
        select(ReviewRun).where(ReviewRun.id == result.run_id)
    ).scalar_one()
    summary = json.loads(run.summary)

    assert "translation_source" in summary
    assert summary["translation_source"]["segment_count"] >= 1
    assert summary["translation_source"]["version_count"] >= 1
    assert "translated_text" not in json.dumps(summary["translation_source"], ensure_ascii=False)


def test_review_and_export_inspect_expose_translation_source_at_top_level(
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

    ReviewService(db_session).run(
        request_id=request_id_factory("review-inspect-source"),
        project_id=project_id,
        scope={"type": "chapter_list", "chapters": [1]},
    )
    ExportService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("export-inspect-source"),
        project_id=project_id,
        scope={"type": "chapter_list", "chapters": [1]},
    )

    review_payload = ReviewService(db_session).inspect(project_id=project_id)
    export_payload = ExportService(db_session, base_data_dir=project_workspace).inspect(project_id=project_id)

    assert review_payload["runs"][0]["translation_source"]["segment_count"] >= 1
    assert export_payload["runs"][0]["translation_source"]["segment_count"] >= 1
    assert "translated_text" not in json.dumps(review_payload["runs"][0]["translation_source"], ensure_ascii=False)
    assert "translated_text" not in json.dumps(export_payload["runs"][0]["translation_source"], ensure_ascii=False)
```

- [ ] **Step 2: 跑红测，确认当前 summary 和 inspect 还没有 `translation_source`**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_review_export.py -k "translation_source_snapshot or expose_translation_source_at_top_level" -q`

Expected: FAIL，至少一条因为 `translation_source` 字段不存在而失败。

- [ ] **Step 3: 新建 snapshot service，并接入 review/export**

```python
from __future__ import annotations

from typing import Iterable


class TranslationSourceSnapshotService:
    def build_snapshot(
        self,
        *,
        rows: Iterable[tuple[object, object, object | None, object | None]],
    ) -> dict[str, object]:
        items = list(rows)
        version_ids = sorted(
            {
                int(version.id)
                for _, _, _, version in items
                if version is not None
            }
        )
        return {
            "segment_count": len(items),
            "version_count": len(version_ids),
            "version_ids": version_ids,
            "segments": [
                {
                    "segment_id": int(segment.id),
                    "chapter_id": int(chapter.id),
                    "chapter_index": int(chapter.chapter_index),
                    "segment_index": int(segment.segment_index),
                    "translation_status": str(segment.translation_status),
                    "review_status": str(segment.review_status),
                    "version": None
                    if version is None
                    else {
                        "id": int(version.id),
                        "version_index": int(version.version_index),
                        "provider_name": str(version.provider_name),
                        "model_profile_id": str(version.model_profile_id),
                        "model_name": str(version.model_name),
                        "status": str(version.status),
                        "source_hash": str(version.source_hash),
                        "glossary_snapshot_id": str(version.glossary_snapshot_id),
                    },
                }
                for chapter, segment, _, version in items
            ],
        }
```

```python
class ReviewService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.reviews = ReviewRepository(session)
        self.translation_source = TranslationSourceSnapshotService()

    def run(
        self,
        *,
        request_id: str,
        project_id: int,
        scope: dict[str, object],
        heartbeat: Callable[[], None] | None = None,
    ) -> ReviewResult:
        rows = self._resolve_segment_rows(project_id=project_id, scope=scope)
        review_run = self.reviews.create_run(
            project_id=project_id,
            scope_type=str(scope["type"]),
            scope_value=json.dumps(scope, ensure_ascii=False),
            status="completed",
            summary=json.dumps(
                {
                    "request_id": request_id,
                    "issue_count": len(issues),
                    "segment_count": len(rows),
                    "translation_source": self.translation_source.build_snapshot(rows=rows),
                },
                ensure_ascii=False,
            ),
        )

    def inspect(self, *, project_id: int) -> dict[str, list[dict[str, object]]]:
        runs.append(
            {
                "id": review_run.id,
                "project_id": review_run.project_id,
                "scope_type": review_run.scope_type,
                "scope_value": self._decode_summary(review_run.scope_value),
                "status": review_run.status,
                "summary": summary,
                "translation_source": None if not isinstance(summary, dict) else summary.get("translation_source"),
                "issue_count": len(issues_for_run),
            }
        )
```

```python
class ExportService:
    def __init__(self, session: Session, *, base_data_dir: Path) -> None:
        self.session = session
        self.base_data_dir = Path(base_data_dir)
        self.exports = ExportRepository(session)
        self.glossary = GlossaryRepository(session)
        self.reviews = ReviewRepository(session)
        self.synopses = ProjectSynopsisRepository(session)
        self.translations = TranslationRepository(session)
        self.translation_source = TranslationSourceSnapshotService()

    def run(
        self,
        *,
        request_id: str,
        project_id: int,
        scope: dict[str, object],
        heartbeat: Callable[[], None] | None = None,
    ) -> ExportResult:
        rows = self._resolve_segment_rows(project_id=project_id, scope=scope)
        translation_source = self.translation_source.build_snapshot(rows=rows)
        export_run = self.exports.create_run(
            project_id=project_id,
            scope_type=str(scope["type"]),
            scope_value=json.dumps(scope, ensure_ascii=False),
            manifest_path=str(manifest_path),
            status="completed",
            summary=json.dumps(
                {
                    "request_id": request_id,
                    "translation_count": len(translations),
                    "glossary_entry_count": len(glossary_entries),
                    "artifact_count": 2,
                    "translation_source": translation_source,
                },
                ensure_ascii=False,
            ),
        )

    def inspect(self, *, project_id: int) -> dict[str, list[dict[str, object]]]:
        runs.append(
            {
                "id": export_run.id,
                "project_id": export_run.project_id,
                "scope_type": export_run.scope_type,
                "scope_value": self._decode_summary(export_run.scope_value),
                "status": export_run.status,
                "manifest_path": export_run.manifest_path,
                "summary": summary,
                "translation_source": None if not isinstance(summary, dict) else summary.get("translation_source"),
                "artifact_count": len(artifacts),
            }
        )
```

- [ ] **Step 4: 重新跑定点测试，确认 review/export 来源快照已经落地**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_review_export.py -k "translation_source_snapshot or expose_translation_source_at_top_level" -q`

Expected: PASS，输出 `2 passed`。

- [ ] **Step 5: Commit**

```bash
git add app/services/translation_source_snapshot_service.py app/services/review_service.py app/services/export_service.py tests/test_review_export.py
git commit -m "feat: add translation source snapshots for review and export"
```

---

### Task 6: 更新 README / roadmap / changelog，并跑完整回归收口

**Files:**
- Modify: `README.md`
- Modify: `docs/roadmap.md`
- Modify: `CHANGELOG.md`
- Test: `tests/test_glossary_stage.py`
- Test: `tests/test_translation_assets_service.py`
- Test: `tests/test_translation_inspection_service.py`
- Test: `tests/test_translation_stage.py`
- Test: `tests/test_review_export.py`

- [ ] **Step 1: 先补 README 中四个 inspect 面的说明**

```md
### `inspect.glossary`

返回内容当前包括：

- `entries`
- `candidates`
- `relation_groups`

其中 `relation_groups` 会按 `term_group_key` 聚合正式 glossary entry，并返回角色分布、一致性检查和结构化 warning。

### `glossary.inspect_pipeline`

当前除 `draft_candidates / reviews` 外，还会返回：

- `finalized_terms`
- `finalized_relation_groups`

如果 workflow 尚未执行到 finalize，这两个字段稳定返回空数组 `[]`。

### `inspect.translation`

单段模式现在额外支持：

- `version_id`
- `compare_version_id`

返回里会新增：

- `inspected_version_id`
- `inspected_version_is_active`

其中 `version / provenance / timeline / compare.current_version` 都围绕当前选中的正式版本构建。

### `inspect.review` / `inspect.export`

`runs[*]` 现在会直接返回 `translation_source`，可查看该次 review/export 运行时所使用的译文版本来源快照。
```

- [ ] **Step 2: 更新 roadmap 和 changelog**

```md
### P1.2 术语模型扩展

- 已完成：`gender / age_group / term_group_key / relation_role`
- 已完成尾项：`inspect.glossary relation_groups`、`glossary.inspect_pipeline finalized 视角`、translation glossary 注入校准

### P1.3 历史版本与可追踪性增强

- 已完成：provenance / compare / timeline
- 已完成尾项：`inspect.translation version_id` 历史版本切换、review/export `translation_source` 快照
```

```md
## Unreleased

- `inspect.glossary` 新增 `relation_groups`，可直接查看同组术语的角色分布与一致性告警。
- `glossary.inspect_pipeline` 新增 `finalized_terms / finalized_relation_groups`，可查看 finalize 后的真实裁决视角。
- translation glossary prompt 改为组感知渲染，避免同组术语命中时的歧义。
- `inspect.translation` 新增 `version_id`，支持围绕任意历史正式版本查看 `version / provenance / timeline / compare`。
- `inspect.review` / `inspect.export` 新增 `translation_source`，可直接查看本次运行所依据的译文版本快照。
```

- [ ] **Step 3: 跑分层回归**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_glossary_stage.py tests\test_translation_assets_service.py tests\test_translation_inspection_service.py tests\test_translation_stage.py tests\test_review_export.py -q`

Expected: PASS，新增和受影响的核心测试全部通过。

- [ ] **Step 4: 跑完整回归**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests -q`

Expected: PASS，完整套件全绿；如果通过数大于 README 当前基线，需把最终真实数字回写 README、roadmap 和 changelog。

- [ ] **Step 5: Commit**

```bash
git add README.md docs/roadmap.md CHANGELOG.md tests/test_glossary_stage.py tests/test_translation_assets_service.py tests/test_translation_inspection_service.py tests/test_translation_stage.py tests/test_review_export.py
git commit -m "docs: record P1 glossary and history tail rollout"
```

---

## 自检记录

- 规格覆盖：Task 1 对应 `inspect.glossary relation_groups`；Task 2 对应 `glossary.inspect_pipeline finalized 视角`；Task 3 对应 translation glossary 注入校准；Task 4 对应 `inspect.translation version_id` 与 compare/历史版本语义；Task 5 对应 review/export `translation_source`；Task 6 对应文档和整体验证，覆盖完整 spec。
- 占位符扫描：计划中没有 `TBD`、`TODO`、`后续补`、`类似 Task N` 之类留白；每个代码步骤都给了明确代码方向和命令。
- 命名一致性：统一使用 `relation_groups`、`finalized_relation_groups`、`translation_source`、`version_id`、`inspected_version_id`、`inspected_version_is_active` 这些在 spec 中定稿的名称，没有混入别名。
