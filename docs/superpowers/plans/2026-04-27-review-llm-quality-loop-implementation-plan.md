# Review LLM Quality Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade `stage.run review` into a hybrid quality gate that runs hard checks, asks an LLM for quality review, feeds blocking issues back into a translation rewrite prompt, and stops after 2 rewrite rounds.

**Architecture:** Keep `ReviewService` as the stage entrypoint and move prompt construction plus LLM loop behavior into focused services. Persist segment-level review evidence in `ReviewIssue`, create new `SegmentTranslationVersion` rows for rewrites, and expose loop statistics through `ReviewRun.summary`, `stage.run`, and `inspect.review`.

**Tech Stack:** Python 3, SQLAlchemy ORM, Alembic migrations, existing provider abstraction (`Provider.generate_text`), existing token usage helpers, pytest.

---

## File Map

- Modify `app/db/models.py`: add new nullable columns to `ReviewIssue`.
- Create `migrations/versions/0020_review_llm_quality_loop.py`: Alembic migration for the new `ReviewIssue` columns.
- Modify `app/repositories/review.py`: accept and expose segment/version/source/round/rewrite payload fields.
- Modify `app/action_router.py`: let `review` resolve configured model providers.
- Modify `app/action_handlers/stage_handlers.py`: parse `review_mode` and `max_rewrite_rounds`.
- Modify `app/action_handlers/stage_execution.py`: pass review loop options into `StageCommand`.
- Modify `app/services/stage_service.py`: extend `StageCommand` and pass provider/model/options into `ReviewService`.
- Modify `app/services/stage_run_response_service.py`: include review token usage and rewrite counts.
- Modify `app/services/stage_run_orchestrator_service.py`: persist and replay expanded `ReviewResult`.
- Modify `app/services/review_service.py`: keep scope/run orchestration, call hard checks, and delegate LLM loop.
- Create `app/services/review_prompt_service.py`: build/parse LLM quality review and rewrite prompts.
- Create `app/services/review_quality_loop_service.py`: execute segment-level LLM review/rewrite rounds.
- Modify `app/services/export_service.py`: keep export summary stable when `review_status="needs_revision"`.
- Modify `README.md`: document hybrid review options and status semantics.
- Modify `tests/test_review_export.py`: update existing hard-check tests to call `review_mode="hard_only"` and assert new inspect fields.
- Create `tests/test_review_llm_quality_loop.py`: focused tests for provider requirement, LLM review pass, rewrite pass, two-round cap, and token summary.
- Modify `tests/test_stage_action_execution.py`: assert CLI stage command carries review mode/options.
- Modify `tests/test_stage_resume_and_conflict.py`: assert review idempotency replay preserves expanded result summary.
- Modify `tests/test_project_staleness_service.py`: assert `needs_revision` returns to `pending` when upstream translation/glossary changes.

---

### Task 1: Add ReviewIssue Persistence Fields

**Files:**
- Modify: `app/db/models.py`
- Modify: `app/repositories/review.py`
- Create: `migrations/versions/0020_review_llm_quality_loop.py`
- Test: `tests/test_review_llm_quality_loop.py`

- [ ] **Step 1: Write the failing schema/repository test**

Create `tests/test_review_llm_quality_loop.py` with this first test and imports:

```python
from __future__ import annotations

import json

from sqlalchemy import inspect, select

from tools.local_translation_workbench.app.db.models import ReviewIssue
from tools.local_translation_workbench.app.repositories.review import ReviewRepository


def test_review_issue_schema_and_repository_store_segment_loop_payload(db_session) -> None:
    columns = {column["name"] for column in inspect(db_session.bind).get_columns("ltw_review_issues")}

    assert {
        "segment_id",
        "version_id",
        "issue_source",
        "round_index",
        "requires_rewrite",
        "structured_payload",
    } <= columns

    review_run = ReviewRepository(db_session).create_run(
        project_id=1,
        scope_type="all",
        scope_value=json.dumps({"type": "all"}),
        status="completed",
        summary=json.dumps({"request_id": "schema-test"}),
    )
    issue = ReviewRepository(db_session).create_issue(
        project_id=1,
        review_run_id=review_run.id,
        chapter_id=2,
        segment_id=3,
        version_id=4,
        issue_type="mistranslation",
        severity="high",
        message="译文误解了动作。",
        status="open",
        issue_source="llm",
        round_index=1,
        requires_rewrite=True,
        structured_payload={"rewrite_instruction": "修正动作含义。"},
    )
    db_session.commit()

    stored = db_session.execute(select(ReviewIssue).where(ReviewIssue.id == issue.id)).scalar_one()
    assert stored.segment_id == 3
    assert stored.version_id == 4
    assert stored.issue_source == "llm"
    assert stored.round_index == 1
    assert stored.requires_rewrite is True
    assert stored.structured_payload == {"rewrite_instruction": "修正动作含义。"}
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_review_llm_quality_loop.py::test_review_issue_schema_and_repository_store_segment_loop_payload -q
```

Expected: FAIL because the new columns and repository parameters do not exist.

- [ ] **Step 3: Add ORM fields**

In `app/db/models.py`, extend `ReviewIssue`:

```python
    segment_id: Mapped[int | None] = mapped_column(
        ForeignKey("ltw_chapter_segments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    version_id: Mapped[int | None] = mapped_column(
        ForeignKey("ltw_segment_translation_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    issue_source: Mapped[str] = mapped_column(String(16), nullable=False, default="hard", server_default="hard")
    round_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    requires_rewrite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    structured_payload: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
```

Ensure the SQLAlchemy import line in this file contains `Boolean`, `Integer`, and `JSON`.

- [ ] **Step 4: Add the migration**

Create `migrations/versions/0020_review_llm_quality_loop.py`:

```python
"""add review llm quality loop fields"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0020_review_llm_quality_loop"
down_revision = "0019_glossary_age_group_modeling"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ltw_review_issues", sa.Column("segment_id", sa.Integer(), nullable=True))
    op.add_column("ltw_review_issues", sa.Column("version_id", sa.Integer(), nullable=True))
    op.add_column(
        "ltw_review_issues",
        sa.Column("issue_source", sa.String(length=16), nullable=False, server_default="hard"),
    )
    op.add_column(
        "ltw_review_issues",
        sa.Column("round_index", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "ltw_review_issues",
        sa.Column("requires_rewrite", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("ltw_review_issues", sa.Column("structured_payload", sa.JSON(), nullable=True))
    op.create_index("ix_ltw_review_issues_segment_id", "ltw_review_issues", ["segment_id"])
    op.create_index("ix_ltw_review_issues_version_id", "ltw_review_issues", ["version_id"])
    op.create_foreign_key(
        "fk_review_issue_segment",
        "ltw_review_issues",
        "ltw_chapter_segments",
        ["segment_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_review_issue_version",
        "ltw_review_issues",
        "ltw_segment_translation_versions",
        ["version_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_review_issue_version", "ltw_review_issues", type_="foreignkey")
    op.drop_constraint("fk_review_issue_segment", "ltw_review_issues", type_="foreignkey")
    op.drop_index("ix_ltw_review_issues_version_id", table_name="ltw_review_issues")
    op.drop_index("ix_ltw_review_issues_segment_id", table_name="ltw_review_issues")
    op.drop_column("ltw_review_issues", "structured_payload")
    op.drop_column("ltw_review_issues", "requires_rewrite")
    op.drop_column("ltw_review_issues", "round_index")
    op.drop_column("ltw_review_issues", "issue_source")
    op.drop_column("ltw_review_issues", "version_id")
    op.drop_column("ltw_review_issues", "segment_id")
```

- [ ] **Step 5: Extend ReviewRepository.create_issue**

Update `app/repositories/review.py`:

```python
    def create_issue(
        self,
        *,
        project_id: int,
        review_run_id: int,
        chapter_id: int,
        issue_type: str,
        severity: str = "medium",
        message: str,
        status: str = "open",
        segment_id: int | None = None,
        version_id: int | None = None,
        issue_source: str = "hard",
        round_index: int = 0,
        requires_rewrite: bool = False,
        structured_payload: dict[str, object] | None = None,
    ) -> ReviewIssue:
        issue = ReviewIssue(
            project_id=project_id,
            review_run_id=review_run_id,
            chapter_id=chapter_id,
            segment_id=segment_id,
            version_id=version_id,
            issue_type=issue_type,
            severity=severity,
            message=message,
            status=status,
            issue_source=issue_source,
            round_index=round_index,
            requires_rewrite=requires_rewrite,
            structured_payload=structured_payload,
        )
```

- [ ] **Step 6: Run the schema/repository test**

Run:

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_review_llm_quality_loop.py::test_review_issue_schema_and_repository_store_segment_loop_payload -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add app\db\models.py app\repositories\review.py migrations\versions\0020_review_llm_quality_loop.py tests\test_review_llm_quality_loop.py
git commit -m "feat: persist review loop issue metadata"
```

---

### Task 2: Add Review Prompt Service

**Files:**
- Create: `app/services/review_prompt_service.py`
- Test: `tests/test_review_llm_quality_loop.py`

- [ ] **Step 1: Add prompt parsing tests**

Append these tests to `tests/test_review_llm_quality_loop.py`:

```python
from tools.local_translation_workbench.app.errors import ToolError
from tools.local_translation_workbench.app.services.review_prompt_service import ReviewPromptService


def test_review_prompt_service_parses_llm_review_json() -> None:
    service = ReviewPromptService()
    result = service.parse_quality_review_response(
        json.dumps(
            {
                "passed": False,
                "score": 0.4,
                "issues": [
                    {
                        "issue_type": "mistranslation",
                        "severity": "high",
                        "requires_rewrite": True,
                        "message": "动作误译。",
                        "source_evidence": "她推开门。",
                        "translation_evidence": "She closed the door.",
                        "rewrite_instruction": "把动作改为推开门。",
                    }
                ],
            },
            ensure_ascii=False,
        )
    )

    assert result["passed"] is False
    assert result["score"] == 0.4
    assert result["issues"][0]["issue_type"] == "mistranslation"
    assert result["issues"][0]["requires_rewrite"] is True


def test_review_prompt_service_rejects_non_json_review_response() -> None:
    service = ReviewPromptService()

    try:
        service.parse_quality_review_response("not json")
    except ToolError as exc:
        assert exc.code == "provider_error"
        assert "LLM 质检必须返回 JSON" in exc.message
    else:
        raise AssertionError("expected ToolError")


def test_review_prompt_service_accepts_json_or_plain_rewrite_response() -> None:
    service = ReviewPromptService()

    assert service.parse_rewrite_response('{"translated_text":"Fixed text."}') == "Fixed text."
    assert service.parse_rewrite_response("Plain fixed text.") == "Plain fixed text."
```

- [ ] **Step 2: Run the failing prompt tests**

Run:

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_review_llm_quality_loop.py::test_review_prompt_service_parses_llm_review_json tests\test_review_llm_quality_loop.py::test_review_prompt_service_rejects_non_json_review_response tests\test_review_llm_quality_loop.py::test_review_prompt_service_accepts_json_or_plain_rewrite_response -q
```

Expected: FAIL because `ReviewPromptService` does not exist.

- [ ] **Step 3: Create ReviewPromptService**

Create `app/services/review_prompt_service.py`:

```python
from __future__ import annotations

import json

from ..errors import ToolError


class ReviewPromptService:
    ALLOWED_ISSUE_TYPES = {
        "omission",
        "mistranslation",
        "glossary_mismatch",
        "character_voice",
        "tone_style",
        "fluency",
        "formatting",
        "other",
    }
    ALLOWED_SEVERITIES = {"low", "medium", "high"}

    def build_quality_review_prompt(
        self,
        *,
        source_language: str,
        target_language: str,
        chapter_index: int,
        chapter_title: str,
        segment_index: int,
        round_index: int,
        source_text: str,
        translated_text: str,
        glossary_entries: list[object],
        prior_issues: list[dict[str, object]],
    ) -> str:
        glossary_lines = [self._format_glossary_entry(entry) for entry in glossary_entries]
        prior_issue_lines = [
            f"- {item.get('issue_type', 'other')} | {item.get('severity', 'medium')} | {item.get('message', '')}"
            for item in prior_issues
        ]
        return (
            "你是小说翻译质检员。请只基于原文、译文和术语表判断是否存在需要重译的问题。\n"
            f"源语言: {source_language}\n"
            f"目标语言: {target_language}\n"
            f"章节: {chapter_index} {chapter_title}\n"
            f"分片: {segment_index}\n"
            f"质检轮次: {round_index}\n"
            "规则:\n"
            "- 只报告有原文或译文证据支持的问题。\n"
            "- 不因个人风格偏好触发重译。\n"
            "- 轻微润色建议使用 severity=low 且 requires_rewrite=false。\n"
            "- 漏译、误译、术语错译和人物语气严重偏离使用 requires_rewrite=true。\n"
            "- 只返回 JSON，不要 Markdown，不要解释。\n"
            'JSON 结构: {"passed": true, "score": 0.0, "issues": []}\n'
            "术语表:\n"
            f"{chr(10).join(glossary_lines) if glossary_lines else '(无命中术语)'}\n"
            "上一轮未解决问题:\n"
            f"{chr(10).join(prior_issue_lines) if prior_issue_lines else '(无)'}\n\n"
            "原文:\n"
            f"{source_text}\n\n"
            "当前译文:\n"
            f"{translated_text}"
        )

    def build_rewrite_prompt(
        self,
        *,
        source_language: str,
        target_language: str,
        chapter_index: int,
        chapter_title: str,
        segment_index: int,
        source_text: str,
        translated_text: str,
        glossary_entries: list[object],
        blocking_issues: list[dict[str, object]],
    ) -> str:
        glossary_lines = [self._format_glossary_entry(entry) for entry in glossary_entries]
        issue_lines = [
            (
                f"- {item.get('issue_type', 'other')} | {item.get('severity', 'medium')} | "
                f"{item.get('message', '')} | instruction: {item.get('rewrite_instruction', '')}"
            )
            for item in blocking_issues
        ]
        return (
            "你是小说翻译引擎。请根据质检问题重译当前分片。\n"
            f"源语言: {source_language}\n"
            f"目标语言: {target_language}\n"
            f"章节: {chapter_index} {chapter_title}\n"
            f"分片: {segment_index}\n"
            "要求:\n"
            "- 修复所有质检问题。\n"
            "- 保留没有问题的译文信息。\n"
            "- 优先遵守术语表 target_term。\n"
            "- 只返回修订后的译文文本；也可以返回 JSON: {\"translated_text\":\"...\"}。\n"
            "术语表:\n"
            f"{chr(10).join(glossary_lines) if glossary_lines else '(无命中术语)'}\n"
            "质检问题:\n"
            f"{chr(10).join(issue_lines)}\n\n"
            "原文:\n"
            f"{source_text}\n\n"
            "当前译文:\n"
            f"{translated_text}"
        )

    def parse_quality_review_response(self, content: str) -> dict[str, object]:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ToolError(code="provider_error", message="LLM 质检必须返回 JSON。", status=502) from exc
        if not isinstance(payload, dict):
            raise ToolError(code="provider_error", message="LLM 质检必须返回 JSON 对象。", status=502)
        issues = payload.get("issues", [])
        if not isinstance(issues, list):
            raise ToolError(code="provider_error", message="LLM 质检 JSON 的 issues 必须是数组。", status=502)
        normalized_issues = [self._normalize_issue(item) for item in issues if isinstance(item, dict)]
        passed = bool(payload.get("passed", not normalized_issues))
        return {
            "passed": passed and not any(bool(item["requires_rewrite"]) for item in normalized_issues),
            "score": self._parse_float(payload.get("score")),
            "issues": normalized_issues,
        }

    def parse_rewrite_response(self, content: str) -> str:
        stripped = content.strip()
        if stripped == "":
            raise ToolError(code="provider_error", message="重译返回为空。", status=502)
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            return stripped
        if isinstance(payload, dict):
            translated_text = str(payload.get("translated_text") or "").strip()
            if translated_text:
                return translated_text
        raise ToolError(code="provider_error", message="重译 JSON 必须包含 translated_text。", status=502)

    def _normalize_issue(self, item: dict[str, object]) -> dict[str, object]:
        issue_type = str(item.get("issue_type") or "other").strip()
        if issue_type not in self.ALLOWED_ISSUE_TYPES:
            issue_type = "other"
        severity = str(item.get("severity") or "medium").strip().lower()
        if severity not in self.ALLOWED_SEVERITIES:
            severity = "medium"
        requires_rewrite = bool(item.get("requires_rewrite") or severity == "high")
        return {
            "issue_type": issue_type,
            "severity": severity,
            "requires_rewrite": requires_rewrite,
            "message": str(item.get("message") or "LLM 质检发现问题。").strip(),
            "source_evidence": str(item.get("source_evidence") or "").strip(),
            "translation_evidence": str(item.get("translation_evidence") or "").strip(),
            "rewrite_instruction": str(item.get("rewrite_instruction") or "").strip(),
        }

    def _format_glossary_entry(self, entry: object) -> str:
        return (
            f"- {entry.source_term} => {entry.target_term}"
            f" | role: {entry.relation_role}"
            f" | group: {entry.term_group_key}"
        )

    def _parse_float(self, value: object) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
```

- [ ] **Step 4: Run prompt tests**

Run:

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_review_llm_quality_loop.py::test_review_prompt_service_parses_llm_review_json tests\test_review_llm_quality_loop.py::test_review_prompt_service_rejects_non_json_review_response tests\test_review_llm_quality_loop.py::test_review_prompt_service_accepts_json_or_plain_rewrite_response -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app\services\review_prompt_service.py tests\test_review_llm_quality_loop.py
git commit -m "feat: add review llm prompt service"
```

---

### Task 3: Build Review Quality Loop Service

**Files:**
- Create: `app/services/review_quality_loop_service.py`
- Modify: `tests/test_review_llm_quality_loop.py`

- [ ] **Step 1: Add focused loop tests**

Append provider and helper imports/tests:

```python
from pathlib import Path

from tools.local_translation_workbench.app.providers.base import TextGenerationResult
from tools.local_translation_workbench.app.repositories.projects import ProjectService
from tools.local_translation_workbench.app.services.chaptering_service import ChapteringService
from tools.local_translation_workbench.app.services.review_quality_loop_service import ReviewQualityLoopService
from tools.local_translation_workbench.app.services.translation_service import TranslationService


class SequencedReviewProvider:
    def __init__(self, outputs: list[str], usage_sequence: list[dict[str, int]] | None = None) -> None:
        self.outputs = list(outputs)
        self.usage_sequence = list(usage_sequence or [])
        self.calls: list[dict[str, object]] = []

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        self.calls.append({"prompt": prompt, "model_name": model_name, "timeout_seconds": timeout_seconds})
        content = self.outputs.pop(0)
        usage = self.usage_sequence.pop(0) if self.usage_sequence else None
        return TextGenerationResult(
            content=content,
            provider_name="sequenced_review_provider",
            model_name=model_name,
            model_profile_id="profile-review-loop",
            usage=usage,
        )


def _prepare_one_segment_project(database_url: str, project_workspace: Path, db_session, request_id_factory) -> int:
    source_file = project_workspace / "review-loop-source.txt"
    source_file.write_text("第1章 开始\n她推开门。", encoding="utf-8")
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("review-loop-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )
    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("review-loop-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )
    TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=SequencedReviewProvider(["Source synopsis", "Target synopsis", "She closed the door."]),
    ).run(
        request_id=request_id_factory("review-loop-translation"),
        project_id=project.id,
        scope={"type": "all"},
        model_profile_id="profile-review-loop",
    )
    return project.id


def test_quality_loop_rewrites_until_llm_review_passes(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_one_segment_project(database_url, project_workspace, db_session, request_id_factory)
    provider = SequencedReviewProvider(
        [
            json.dumps(
                {
                    "passed": False,
                    "issues": [
                        {
                            "issue_type": "mistranslation",
                            "severity": "high",
                            "requires_rewrite": True,
                            "message": "动作误译。",
                            "rewrite_instruction": "把 closed 改为 opened。",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            json.dumps({"translated_text": "She opened the door."}, ensure_ascii=False),
            json.dumps({"passed": True, "issues": []}, ensure_ascii=False),
        ],
        usage_sequence=[
            {"input_tokens": 10, "output_tokens": 5},
            {"input_tokens": 11, "output_tokens": 6},
            {"input_tokens": 12, "output_tokens": 7},
        ],
    )
    service = ReviewQualityLoopService(db_session, base_data_dir=project_workspace, provider=provider)

    result = service.run(
        project_id=project_id,
        rows=service.resolve_review_rows_for_tests(project_id=project_id),
        hard_issues_by_segment={},
        model_profile_id="profile-review-loop",
        provider_model_name="review-model",
        max_rewrite_rounds=2,
    )

    assert result["passed_segment_count"] == 1
    assert result["needs_revision_segment_count"] == 0
    assert result["rewrite_segment_count"] == 1
    assert result["token_usage"]["call_count"] == 3
    assert len(result["rewrite_version_ids"]) == 1
```

- [ ] **Step 2: Run the failing loop test**

Run:

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_review_llm_quality_loop.py::test_quality_loop_rewrites_until_llm_review_passes -q
```

Expected: FAIL because `ReviewQualityLoopService` does not exist.

- [ ] **Step 3: Create ReviewQualityLoopService skeleton and helpers**

Create `app/services/review_quality_loop_service.py` with these imports and class shell:

```python
from __future__ import annotations

import hashlib
from pathlib import Path
from time import perf_counter

from sqlalchemy import and_, select

from ..db.models import Chapter, ChapterSegment, SegmentTranslation, SegmentTranslationVersion, TranslationProject
from ..errors import ToolError
from ..providers.base import Provider
from ..repositories.glossary import GlossaryRepository
from ..repositories.translations import TranslationRepository
from ..token_usage import merge_token_usage_payloads, summarize_generation_results
from ..utils.paths import ensure_directory
from .review_prompt_service import ReviewPromptService
from .translation_assets_service import TranslationAssetsService

ReviewRow = tuple[Chapter, ChapterSegment, SegmentTranslation | None, SegmentTranslationVersion | None]


class ReviewQualityLoopService:
    def __init__(self, session, *, base_data_dir: Path, provider: Provider | None) -> None:
        self.session = session
        self.base_data_dir = Path(base_data_dir)
        self.provider = provider
        self.prompts = ReviewPromptService()
        self.glossary = GlossaryRepository(session)
        self.translations = TranslationRepository(session)
        self.translation_assets = TranslationAssetsService()

    def resolve_review_rows_for_tests(self, *, project_id: int) -> list[ReviewRow]:
        statement = (
            select(Chapter, ChapterSegment, SegmentTranslation, SegmentTranslationVersion)
            .join(ChapterSegment, ChapterSegment.chapter_id == Chapter.id)
            .outerjoin(
                SegmentTranslation,
                and_(SegmentTranslation.segment_id == ChapterSegment.id, SegmentTranslation.project_id == project_id),
            )
            .outerjoin(SegmentTranslationVersion, SegmentTranslationVersion.id == SegmentTranslation.active_version_id)
            .where(Chapter.project_id == project_id, ChapterSegment.project_id == project_id)
            .order_by(Chapter.chapter_index.asc(), ChapterSegment.segment_index.asc())
        )
        return list(self.session.execute(statement).all())
```

- [ ] **Step 4: Implement run and review/rewrite loop**

Add this method body to the class:

```python
    def run(
        self,
        *,
        project_id: int,
        rows: list[ReviewRow],
        hard_issues_by_segment: dict[int, list[dict[str, object]]],
        model_profile_id: str,
        provider_model_name: str | None,
        max_rewrite_rounds: int,
    ) -> dict[str, object]:
        if self.provider is None:
            raise ToolError(code="invalid_arguments", message="review_mode=hybrid 需要可用 provider。", status=400)
        project = self.session.get(TranslationProject, project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        all_issues: list[dict[str, object]] = []
        rewrite_version_ids: list[int] = []
        round_summaries: list[dict[str, object]] = []
        token_payloads: list[dict[str, int]] = []
        passed_count = 0
        needs_revision_count = 0

        for chapter, segment, translation, version in rows:
            result = self._run_segment_loop(
                project=project,
                chapter=chapter,
                segment=segment,
                translation=translation,
                version=version,
                hard_issues=hard_issues_by_segment.get(int(segment.id), []),
                model_profile_id=model_profile_id,
                provider_model_name=provider_model_name or model_profile_id,
                max_rewrite_rounds=max_rewrite_rounds,
            )
            all_issues.extend(result["issues"])
            rewrite_version_ids.extend(int(item) for item in result["rewrite_version_ids"])
            round_summaries.extend(result["rounds"])
            if result["status"] == "reviewed":
                segment.review_status = "reviewed"
                passed_count += 1
            else:
                segment.review_status = "needs_revision"
                needs_revision_count += 1
            if result.get("token_usage") is not None:
                token_payloads.append(result["token_usage"])

        return {
            "issues": all_issues,
            "passed_segment_count": passed_count,
            "needs_revision_segment_count": needs_revision_count,
            "rewrite_segment_count": len(set(rewrite_version_ids)),
            "rewrite_version_ids": rewrite_version_ids,
            "rounds": round_summaries,
            "token_usage": merge_token_usage_payloads(token_payloads),
        }
```

- [ ] **Step 5: Implement segment loop and version creation**

Add these methods to the class:

```python
    def _run_segment_loop(
        self,
        *,
        project: TranslationProject,
        chapter: Chapter,
        segment: ChapterSegment,
        translation: SegmentTranslation | None,
        version: SegmentTranslationVersion | None,
        hard_issues: list[dict[str, object]],
        model_profile_id: str,
        provider_model_name: str,
        max_rewrite_rounds: int,
    ) -> dict[str, object]:
        if version is None or translation is None:
            return {"status": "needs_revision", "issues": hard_issues, "rewrite_version_ids": [], "rounds": []}

        issues = list(hard_issues)
        rewrite_version_ids: list[int] = []
        round_summaries: list[dict[str, object]] = []
        token_payloads: list[dict[str, int]] = []
        current_version = version
        current_translation = translation
        prior_blocking_issues = list(hard_issues)

        for round_index in range(max_rewrite_rounds + 1):
            source_text = Path(segment.source_text_path).read_text(encoding="utf-8").strip()
            glossary_entries = self._matched_glossary_entries(
                project_id=int(project.id),
                chapter_id=int(chapter.id),
                source_text=source_text,
            )
            review_started = perf_counter()
            provider_result = self.provider.generate_text(
                prompt=self.prompts.build_quality_review_prompt(
                    source_language=str(project.source_language),
                    target_language=str(project.target_language),
                    chapter_index=int(chapter.chapter_index),
                    chapter_title=str(chapter.chapter_title),
                    segment_index=int(segment.segment_index),
                    round_index=round_index,
                    source_text=source_text,
                    translated_text=str(current_version.translated_text),
                    glossary_entries=glossary_entries,
                    prior_issues=prior_blocking_issues,
                ),
                model_name=provider_model_name,
                timeout_seconds=120,
            )
            token_payload = summarize_generation_results([provider_result])
            if token_payload is not None:
                token_payloads.append(token_payload)
            review_payload = self.prompts.parse_quality_review_response(provider_result.content)
            llm_issues = [
                self._issue_payload(
                    chapter=chapter,
                    segment=segment,
                    version=current_version,
                    issue=item,
                    provider_result=provider_result,
                    round_index=round_index,
                )
                for item in review_payload["issues"]
            ]
            issues.extend(llm_issues)
            blocking_issues = [
                item for item in prior_blocking_issues + llm_issues
                if bool(item.get("requires_rewrite")) or str(item.get("severity")) == "high"
            ]
            round_summaries.append(
                {
                    "segment_id": int(segment.id),
                    "round_index": round_index,
                    "llm_review_elapsed_seconds": round(perf_counter() - review_started, 3),
                    "llm_issue_count": len(llm_issues),
                    "blocking_issue_count": len(blocking_issues),
                    "review_model": provider_result.model_name,
                }
            )
            if not blocking_issues:
                return {
                    "status": "reviewed",
                    "issues": issues,
                    "rewrite_version_ids": rewrite_version_ids,
                    "rounds": round_summaries,
                    "token_usage": merge_token_usage_payloads(token_payloads),
                }
            if round_index >= max_rewrite_rounds:
                return {
                    "status": "needs_revision",
                    "issues": issues,
                    "rewrite_version_ids": rewrite_version_ids,
                    "rounds": round_summaries,
                    "token_usage": merge_token_usage_payloads(token_payloads),
                }

            rewrite_result = self._rewrite_segment(
                project=project,
                chapter=chapter,
                segment=segment,
                translation=current_translation,
                current_version=current_version,
                source_text=source_text,
                glossary_entries=glossary_entries,
                blocking_issues=blocking_issues,
                model_profile_id=model_profile_id,
                provider_model_name=provider_model_name,
            )
            current_version = rewrite_result["version"]
            current_translation.active_version_id = current_version.id
            rewrite_version_ids.append(int(current_version.id))
            prior_blocking_issues = blocking_issues
            if rewrite_result.get("token_usage") is not None:
                token_payloads.append(rewrite_result["token_usage"])

        return {"status": "needs_revision", "issues": issues, "rewrite_version_ids": rewrite_version_ids, "rounds": round_summaries}

    def _rewrite_segment(
        self,
        *,
        project: TranslationProject,
        chapter: Chapter,
        segment: ChapterSegment,
        translation: SegmentTranslation,
        current_version: SegmentTranslationVersion,
        source_text: str,
        glossary_entries: list[object],
        blocking_issues: list[dict[str, object]],
        model_profile_id: str,
        provider_model_name: str,
    ) -> dict[str, object]:
        provider_result = self.provider.generate_text(
            prompt=self.prompts.build_rewrite_prompt(
                source_language=str(project.source_language),
                target_language=str(project.target_language),
                chapter_index=int(chapter.chapter_index),
                chapter_title=str(chapter.chapter_title),
                segment_index=int(segment.segment_index),
                source_text=source_text,
                translated_text=str(current_version.translated_text),
                glossary_entries=glossary_entries,
                blocking_issues=blocking_issues,
            ),
            model_name=provider_model_name,
            timeout_seconds=180,
        )
        translated_text = self.prompts.parse_rewrite_response(provider_result.content)
        next_version_index = self.translations.get_next_version_index(int(translation.id))
        translation_root = ensure_directory(self.base_data_dir / str(project.project_key) / "translations")
        segment_output_dir = ensure_directory(translation_root / "segments" / f"{int(segment.id):08d}")
        version_path = segment_output_dir / f"v{next_version_index:04d}.txt"
        current_path = segment_output_dir / "current.txt"
        version_path.write_text(translated_text, encoding="utf-8")
        current_path.write_text(translated_text, encoding="utf-8")
        version = self.translations.create_version(
            project_id=int(project.id),
            segment_translation_id=int(translation.id),
            version_index=next_version_index,
            source_hash=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
            glossary_snapshot_id=self.translation_assets.compute_glossary_snapshot_id(glossary_entries),
            provider_name=provider_result.provider_name,
            model_profile_id=provider_result.model_profile_id or model_profile_id,
            model_name=provider_result.model_name,
            source_text=source_text,
            translated_text=translated_text,
            translated_text_path=str(version_path),
            status="completed",
        )
        segment.translation_status = "translated"
        segment.review_status = "pending"
        return {"version": version, "token_usage": summarize_generation_results([provider_result])}
```

- [ ] **Step 6: Implement issue and glossary helpers**

Add these helpers:

```python
    def _matched_glossary_entries(self, *, project_id: int, chapter_id: int, source_text: str) -> list[object]:
        entries = self.glossary.list_active_entries_for_matching(
            project_id,
            scope_level="chapter_term",
            scope_chapter_id=chapter_id,
            include_project_scope=True,
        )
        return self.translation_assets.build_prompt_glossary_entries(
            glossary_entries=entries,
            source_text=source_text,
        )

    def _issue_payload(
        self,
        *,
        chapter: Chapter,
        segment: ChapterSegment,
        version: SegmentTranslationVersion,
        issue: dict[str, object],
        provider_result,
        round_index: int,
    ) -> dict[str, object]:
        return {
            "project_id": int(chapter.project_id),
            "chapter_id": int(chapter.id),
            "segment_id": int(segment.id),
            "version_id": int(version.id),
            "issue_type": str(issue["issue_type"]),
            "severity": str(issue["severity"]),
            "message": str(issue["message"]),
            "status": "open",
            "issue_source": "llm",
            "round_index": round_index,
            "requires_rewrite": bool(issue["requires_rewrite"]),
            "structured_payload": {
                "source_evidence": issue.get("source_evidence"),
                "translation_evidence": issue.get("translation_evidence"),
                "rewrite_instruction": issue.get("rewrite_instruction"),
                "reviewer_model": provider_result.model_name,
                "reviewer_model_profile_id": provider_result.model_profile_id,
                "fallback_depth": int(provider_result.fallback_depth or 0),
            },
        }
```

- [ ] **Step 7: Run the loop test**

Run:

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_review_llm_quality_loop.py::test_quality_loop_rewrites_until_llm_review_passes -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add app\services\review_quality_loop_service.py tests\test_review_llm_quality_loop.py
git commit -m "feat: add review quality rewrite loop"
```

---

### Task 4: Integrate Hybrid Loop Into ReviewService

**Files:**
- Modify: `app/services/review_service.py`
- Modify: `app/services/stage_service.py`
- Modify: `app/services/stage_run_response_service.py`
- Modify: `app/services/stage_run_orchestrator_service.py`
- Test: `tests/test_review_export.py`
- Test: `tests/test_review_llm_quality_loop.py`

- [ ] **Step 1: Add service-level integration tests**

Append:

```python
from tools.local_translation_workbench.app.services.review_service import ReviewService


def test_review_service_hybrid_loop_writes_llm_issues_and_new_active_version(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_one_segment_project(database_url, project_workspace, db_session, request_id_factory)
    provider = SequencedReviewProvider(
        [
            json.dumps(
                {
                    "passed": False,
                    "issues": [
                        {
                            "issue_type": "mistranslation",
                            "severity": "high",
                            "requires_rewrite": True,
                            "message": "动作误译。",
                            "rewrite_instruction": "把 closed 改为 opened。",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            "She opened the door.",
            json.dumps({"passed": True, "issues": []}, ensure_ascii=False),
        ]
    )

    result = ReviewService(db_session, base_data_dir=project_workspace, provider=provider).run(
        request_id=request_id_factory("review-hybrid"),
        project_id=project_id,
        scope={"type": "all"},
        model_profile_id="profile-review-loop",
        provider_model_name="review-model",
        review_mode="hybrid",
        max_rewrite_rounds=2,
    )

    issues = db_session.execute(select(ReviewIssue).where(ReviewIssue.review_run_id == result.run_id)).scalars().all()
    active_version = db_session.execute(select(SegmentTranslationVersion).order_by(SegmentTranslationVersion.id.desc())).scalars().first()

    assert result.issue_count == 1
    assert result.rewrite_segment_count == 1
    assert issues[0].issue_source == "llm"
    assert issues[0].segment_id is not None
    assert active_version.translated_text == "She opened the door."
```

- [ ] **Step 2: Run the failing integration test**

Run:

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_review_llm_quality_loop.py::test_review_service_hybrid_loop_writes_llm_issues_and_new_active_version -q
```

Expected: FAIL because `ReviewService` does not accept provider/options.

- [ ] **Step 3: Expand ReviewResult**

In `app/services/review_service.py`, replace `ReviewResult`:

```python
@dataclass(frozen=True)
class ReviewResult:
    issue_count: int
    run_id: int
    mode: str = "hard_only"
    passed_segment_count: int = 0
    needs_revision_segment_count: int = 0
    rewrite_segment_count: int = 0
    rewrite_version_ids: list[int] | None = None
    token_usage: dict[str, int] | None = None
```

- [ ] **Step 4: Update ReviewService constructor and run signature**

Change `ReviewService.__init__`:

```python
    def __init__(self, session: Session, *, base_data_dir: Path | None = None, provider=None) -> None:
        self.session = session
        self.base_data_dir = Path(base_data_dir or "data/projects")
        self.provider = provider
```

Change `run` parameters:

```python
        model_profile_id: str = "default",
        provider_model_name: str | None = None,
        review_mode: str = "hybrid",
        max_rewrite_rounds: int = 2,
```

- [ ] **Step 5: Convert hard issues to segment-aware payloads**

Change `_build_issue` to include these fields in each returned dict:

```python
                "segment_id": int(segment.id),
                "version_id": None if version is None else int(version.id),
                "issue_source": "hard",
                "round_index": 0,
                "requires_rewrite": True,
                "structured_payload": None,
```

For `glossary_term_missing`, use `version_id=int(version.id)` and `requires_rewrite=True`.

- [ ] **Step 6: Call ReviewQualityLoopService in hybrid mode**

Inside `ReviewService.run`, after collecting hard issues, build:

```python
hard_issues_by_segment: dict[int, list[dict[str, object]]] = {}
for issue in issues:
    segment_id = issue.get("segment_id")
    if segment_id is not None:
        hard_issues_by_segment.setdefault(int(segment_id), []).append(issue)
```

Then:

```python
loop_summary: dict[str, object] = {
    "issues": [],
    "passed_segment_count": len(rows),
    "needs_revision_segment_count": 0,
    "rewrite_segment_count": 0,
    "rewrite_version_ids": [],
    "rounds": [],
    "token_usage": None,
}
if review_mode == "hybrid":
    from .review_quality_loop_service import ReviewQualityLoopService

    loop_summary = ReviewQualityLoopService(
        self.session,
        base_data_dir=self.base_data_dir,
        provider=self.provider,
    ).run(
        project_id=project_id,
        rows=rows,
        hard_issues_by_segment=hard_issues_by_segment,
        model_profile_id=model_profile_id,
        provider_model_name=provider_model_name,
        max_rewrite_rounds=max_rewrite_rounds,
    )
    issues = list(loop_summary["issues"])
else:
    for _, segment, _, _ in rows:
        segment.review_status = "needs_revision" if hard_issues_by_segment.get(int(segment.id)) else "reviewed"
```

- [ ] **Step 7: Expand review run summary and result**

Build summary:

```python
summary = {
    "request_id": request_id,
    "mode": review_mode,
    "max_rewrite_rounds": max_rewrite_rounds,
    "issue_count": len(issues),
    "segment_count": len(rows),
    "passed_segment_count": int(loop_summary["passed_segment_count"]),
    "needs_revision_segment_count": int(loop_summary["needs_revision_segment_count"]),
    "rewrite_segment_count": int(loop_summary["rewrite_segment_count"]),
    "rewrite_version_ids": list(loop_summary["rewrite_version_ids"]),
    "rounds": list(loop_summary["rounds"]),
    "translation_source": self.translation_source.build_snapshot(rows=rows),
}
if loop_summary.get("token_usage") is not None:
    summary["token_usage"] = loop_summary["token_usage"]
```

Return:

```python
return ReviewResult(
    issue_count=len(issues),
    run_id=review_run.id,
    mode=review_mode,
    passed_segment_count=int(loop_summary["passed_segment_count"]),
    needs_revision_segment_count=int(loop_summary["needs_revision_segment_count"]),
    rewrite_segment_count=int(loop_summary["rewrite_segment_count"]),
    rewrite_version_ids=[int(item) for item in loop_summary["rewrite_version_ids"]],
    token_usage=loop_summary.get("token_usage"),
)
```

- [ ] **Step 8: Update StageService call**

In `app/services/stage_service.py`, extend `StageCommand`:

```python
    review_mode: str = "hybrid"
    max_rewrite_rounds: int = 2
```

Change review dispatch:

```python
            return ReviewService(
                self.session,
                base_data_dir=self.base_data_dir,
                provider=self.provider,
            ).run(
                request_id=command.request_id,
                project_id=command.project_id,
                scope=command.scope,
                model_profile_id=command.model_profile_id,
                provider_model_name=command.provider_model_name,
                review_mode=command.review_mode,
                max_rewrite_rounds=command.max_rewrite_rounds,
                heartbeat=heartbeat,
            )
```

- [ ] **Step 9: Update stage response and orchestrator summary**

In `app/services/stage_run_response_service.py`, add under review:

```python
        data["mode"] = result.mode
        data["passed_segment_count"] = result.passed_segment_count
        data["needs_revision_segment_count"] = result.needs_revision_segment_count
        data["rewrite_segment_count"] = result.rewrite_segment_count
        data["rewrite_version_ids"] = result.rewrite_version_ids or []
        if result.token_usage is not None:
            data["token_usage"] = result.token_usage
```

In `app/services/stage_run_orchestrator_service.py`, update `_result_to_summary_payload` review branch and `_replay_existing_result` review branch with the same fields.

- [ ] **Step 10: Run integration tests**

Run:

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_review_llm_quality_loop.py tests\test_review_export.py -q
```

Expected: existing hard-only tests may fail until Task 5 updates their calls.

- [ ] **Step 11: Commit**

```powershell
git add app\services\review_service.py app\services\stage_service.py app\services\stage_run_response_service.py app\services\stage_run_orchestrator_service.py tests\test_review_llm_quality_loop.py
git commit -m "feat: integrate review quality loop"
```

---

### Task 5: Wire CLI Stage Options and Provider Resolution

**Files:**
- Modify: `app/action_router.py`
- Modify: `app/action_handlers/stage_handlers.py`
- Modify: `app/action_handlers/stage_execution.py`
- Test: `tests/test_stage_action_execution.py`
- Test: `tests/test_review_export.py`

- [ ] **Step 1: Add CLI command parsing tests**

In `tests/test_stage_action_execution.py`, add:

```python
def test_stage_run_review_passes_review_loop_options(monkeypatch) -> None:
    captured = {}

    def fake_execute_stage_command(**kwargs):
        captured.update(kwargs)

        class Result:
            issue_count = 0
            run_id = 1
            mode = "hard_only"
            passed_segment_count = 1
            needs_revision_segment_count = 0
            rewrite_segment_count = 0
            rewrite_version_ids = []
            token_usage = None

        return Result()

    monkeypatch.setattr(
        "tools.local_translation_workbench.app.action_handlers.stage_handlers.execute_stage_command",
        fake_execute_stage_command,
    )

    from tools.local_translation_workbench.app.cli import main

    exit_code = main(
        [
            "-Action",
            "stage.run",
            "-Stage",
            "review",
            "-ProjectId",
            "123",
            "-RequestId",
            "review-cli-options",
            "-ReviewMode",
            "hard_only",
            "-MaxRewriteRounds",
            "1",
        ]
    )

    assert exit_code == 0
    assert captured["stage"] == "review"
    assert captured["review_mode"] == "hard_only"
    assert captured["max_rewrite_rounds"] == 1
```

- [ ] **Step 2: Run the failing CLI test**

Run:

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_stage_action_execution.py::test_stage_run_review_passes_review_loop_options -q
```

Expected: FAIL because stage execution does not accept these arguments.

- [ ] **Step 3: Let review resolve provider**

In `app/action_router.py`:

```python
def _resolve_model_stage_provider(*, session, config, stage: str, model_profile_id: str):
    if stage not in {"glossary", "translation", "review"}:
        return None
    return build_provider_from_profile(session, config, model_profile_id)
```

- [ ] **Step 4: Parse review options in stage handler**

In `app/action_handlers/stage_handlers.py`:

```python
    review_mode = arguments.get("review_mode", arguments.get("reviewmode", "hybrid")).strip().lower()
    max_rewrite_rounds = int(arguments.get("max_rewrite_rounds", arguments.get("maxrewriterounds", "2")))
```

Pass both to `execute_stage_command(...)`.

- [ ] **Step 5: Pass options through stage_execution**

In `app/action_handlers/stage_execution.py`, add function parameters:

```python
    review_mode: str = "hybrid",
    max_rewrite_rounds: int = 2,
```

Pass them into `StageCommand(...)`:

```python
            review_mode=review_mode,
            max_rewrite_rounds=max_rewrite_rounds,
```

- [ ] **Step 6: Update existing hard review tests**

In `tests/test_review_export.py`, every direct call to `ReviewService(db_session).run(...)` that is testing hard checks should include:

```python
        review_mode="hard_only",
```

Direct hard-only tests continue using `ReviewService(db_session)` because `base_data_dir` is only required for rewrite output files in hybrid mode.

- [ ] **Step 7: Run CLI and review tests**

Run:

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_stage_action_execution.py::test_stage_run_review_passes_review_loop_options tests\test_review_export.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add app\action_router.py app\action_handlers\stage_handlers.py app\action_handlers\stage_execution.py tests\test_stage_action_execution.py tests\test_review_export.py
git commit -m "feat: wire review loop stage options"
```

---

### Task 6: Enhance Inspect, Export Summary, and Staleness Semantics

**Files:**
- Modify: `app/services/review_service.py`
- Modify: `app/services/export_service.py`
- Modify: `app/services/project_staleness_service.py`
- Test: `tests/test_review_llm_quality_loop.py`
- Test: `tests/test_project_staleness_service.py`
- Test: `tests/test_review_export.py`

- [ ] **Step 1: Add inspect assertions**

Append:

```python
def test_inspect_review_exposes_llm_loop_fields(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_one_segment_project(database_url, project_workspace, db_session, request_id_factory)
    provider = SequencedReviewProvider(
        [
            json.dumps(
                {
                    "passed": False,
                    "issues": [
                        {
                            "issue_type": "mistranslation",
                            "severity": "high",
                            "requires_rewrite": True,
                            "message": "动作误译。",
                            "rewrite_instruction": "修正动作。",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            "She opened the door.",
            json.dumps({"passed": True, "issues": []}, ensure_ascii=False),
        ]
    )
    ReviewService(db_session, base_data_dir=project_workspace, provider=provider).run(
        request_id=request_id_factory("review-inspect-loop"),
        project_id=project_id,
        scope={"type": "all"},
        model_profile_id="profile-review-loop",
        provider_model_name="review-model",
        review_mode="hybrid",
        max_rewrite_rounds=2,
    )

    payload = ReviewService(db_session).inspect(project_id=project_id)

    assert payload["runs"][0]["summary"]["mode"] == "hybrid"
    assert payload["runs"][0]["summary"]["rewrite_segment_count"] == 1
    assert payload["issues"][0]["issue_source"] == "llm"
    assert payload["issues"][0]["segment_id"] is not None
    assert payload["issues"][0]["requires_rewrite"] is True
    assert payload["issues"][0]["structured_payload"]["rewrite_instruction"] == "修正动作。"
```

- [ ] **Step 2: Run the failing inspect test**

Run:

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_review_llm_quality_loop.py::test_inspect_review_exposes_llm_loop_fields -q
```

Expected: FAIL until inspect returns new fields.

- [ ] **Step 3: Expand inspect issue payload**

In `ReviewService.inspect`, add fields:

```python
                    "segment_id": issue.segment_id,
                    "version_id": issue.version_id,
                    "issue_source": issue.issue_source,
                    "round_index": issue.round_index,
                    "requires_rewrite": issue.requires_rewrite,
                    "structured_payload": issue.structured_payload,
```

- [ ] **Step 4: Confirm staleness resets needs_revision**

In `tests/test_project_staleness_service.py`, add an assertion to an existing staleness test after upstream changes:

```python
    assert all(row.review_status == "pending" for row in db_session.execute(select(ChapterSegment)).scalars().all())
```

The existing `ProjectStalenessService` already sets any non-pending review status back to `pending`, so this should pass after `needs_revision` is introduced.

- [ ] **Step 5: Check export summary behavior**

In `tests/test_review_export.py`, add or adjust a test so one segment has `review_status="needs_revision"` before export:

```python
    segment = db_session.execute(select(ChapterSegment).where(ChapterSegment.project_id == project_id)).scalars().first()
    segment.review_status = "needs_revision"
    db_session.commit()
```

Assert manifest review summary does not report all segments as reviewed:

```python
    assert manifest["review_summary"]["review_status"] != "reviewed"
```

- [ ] **Step 6: Keep export review status derived from all segment statuses**

Set the summary expression to:

```python
            "review_status": "reviewed"
            if all(segment.review_status == "reviewed" for segment, _, _ in rows)
            else "pending",
```

- [ ] **Step 7: Run inspect/export/staleness tests**

Run:

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_review_llm_quality_loop.py::test_inspect_review_exposes_llm_loop_fields tests\test_project_staleness_service.py tests\test_review_export.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add app\services\review_service.py app\services\export_service.py app\services\project_staleness_service.py tests\test_review_llm_quality_loop.py tests\test_project_staleness_service.py tests\test_review_export.py
git commit -m "feat: expose review loop inspection"
```

---

### Task 7: Add Two-Round Cap and Failure Tests

**Files:**
- Modify: `tests/test_review_llm_quality_loop.py`
- Modify: `app/services/review_quality_loop_service.py`

- [ ] **Step 1: Add two-round cap test**

Append:

```python
def test_quality_loop_stops_after_two_rewrite_rounds(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_one_segment_project(database_url, project_workspace, db_session, request_id_factory)
    failing_review = json.dumps(
        {
            "passed": False,
            "issues": [
                {
                    "issue_type": "mistranslation",
                    "severity": "high",
                    "requires_rewrite": True,
                    "message": "仍然误译。",
                    "rewrite_instruction": "继续修正。",
                }
            ],
        },
        ensure_ascii=False,
    )
    provider = SequencedReviewProvider(
        [
            failing_review,
            "Rewrite one.",
            failing_review,
            "Rewrite two.",
            failing_review,
        ]
    )

    result = ReviewService(db_session, base_data_dir=project_workspace, provider=provider).run(
        request_id=request_id_factory("review-two-round-cap"),
        project_id=project_id,
        scope={"type": "all"},
        model_profile_id="profile-review-loop",
        provider_model_name="review-model",
        review_mode="hybrid",
        max_rewrite_rounds=2,
    )

    segment = db_session.execute(select(ChapterSegment).where(ChapterSegment.project_id == project_id)).scalar_one()
    versions = db_session.execute(
        select(SegmentTranslationVersion).where(SegmentTranslationVersion.project_id == project_id)
    ).scalars().all()

    assert result.needs_revision_segment_count == 1
    assert result.rewrite_segment_count == 2
    assert segment.review_status == "needs_revision"
    assert len(versions) == 3
    assert len(provider.calls) == 5
```

- [ ] **Step 2: Add hybrid provider requirement test**

Append:

```python
def test_review_hybrid_requires_provider(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_one_segment_project(database_url, project_workspace, db_session, request_id_factory)

    try:
        ReviewService(db_session, base_data_dir=project_workspace).run(
            request_id=request_id_factory("review-provider-required"),
            project_id=project_id,
            scope={"type": "all"},
            model_profile_id="profile-review-loop",
            review_mode="hybrid",
            max_rewrite_rounds=2,
        )
    except ToolError as exc:
        assert exc.code == "invalid_arguments"
        assert "provider" in exc.message
    else:
        raise AssertionError("expected ToolError")
```

- [ ] **Step 3: Run cap and provider tests**

Run:

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_review_llm_quality_loop.py::test_quality_loop_stops_after_two_rewrite_rounds tests\test_review_llm_quality_loop.py::test_review_hybrid_requires_provider -q
```

Expected: PASS. The loop must use `range(max_rewrite_rounds + 1)` and trigger rewrites only when `round_index < max_rewrite_rounds`, so the test makes exactly 5 provider calls.

- [ ] **Step 4: Commit**

```powershell
git add app\services\review_quality_loop_service.py tests\test_review_llm_quality_loop.py
git commit -m "test: cover review rewrite round cap"
```

---

### Task 8: Update Documentation and Run Regression

**Files:**
- Modify: `README.md`
- Test: multiple pytest targets

- [ ] **Step 1: Update README review documentation**

In `README.md`, update these sections:

Under `stage.run` optional parameters, add:

```markdown
- `review_mode`：`review` 阶段可选，默认 `hybrid`。`hybrid` 会执行硬质检 + LLM 质检 + 最多 2 轮重译；`hard_only` 只执行本地规则质检。
- `max_rewrite_rounds`：`review` 阶段可选，默认 `2`，表示 LLM 质检发现阻断问题后最多重译几轮。
```

Under glossary/translation/review linkage, replace the old review sentence with:

```markdown
- `review` 默认是混合审校：先运行本地硬质检，再运行 LLM 质检；如果发现阻断问题，会把问题、原文、当前译文和命中术语输入翻译 LLM 进行重译，最多重译 2 轮。`review_mode=hard_only` 可用于只跑本地规则质检。
```

Under `inspect.review`, add:

```markdown
`issues[*]` 会返回 `segment_id / version_id / issue_source / round_index / requires_rewrite / structured_payload`，用于追踪 LLM 质检和重译链路。
```

- [ ] **Step 2: Run focused review regression**

Run:

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_review_llm_quality_loop.py tests\test_review_export.py tests\test_stage_action_execution.py tests\test_stage_resume_and_conflict.py tests\test_project_staleness_service.py -q
```

Expected: PASS.

- [ ] **Step 3: Run diff check**

Run:

```powershell
git diff --check
```

Expected: exit code 0. LF-to-CRLF warnings are acceptable in this repository.

- [ ] **Step 4: Commit docs and final fixes**

```powershell
git add README.md tests\test_review_llm_quality_loop.py tests\test_review_export.py tests\test_stage_action_execution.py tests\test_stage_resume_and_conflict.py tests\test_project_staleness_service.py app
git commit -m "docs: document review quality loop"
```

---

## Self-Review

Spec coverage:

- Hybrid review mode is covered by Tasks 4 and 5.
- LLM quality prompt and JSON parsing are covered by Task 2.
- Rewrite prompt and new `SegmentTranslationVersion` creation are covered by Task 3.
- Two rewrite rounds are covered by Task 7.
- Review issue metadata, run summary, inspect payload, token usage, and docs are covered by Tasks 1, 4, 6, and 8.

Placeholder scan:

- The plan contains no incomplete markers and no unspecified file targets.
- Each code-changing task includes file paths, concrete code fragments, test commands, and expected outcomes.

Type consistency:

- `ReviewResult` fields match the stage response and orchestrator replay fields.
- `ReviewIssue` model fields match repository arguments and inspect payload names.
- `ReviewQualityLoopService.run(...)` return keys match `ReviewService.run(...)` summary construction.
