# Segment 分片落地 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `segment = 章节内翻译分片` 的设计落到 `chaptering / translation / review / export / inspect` 主链，保证长章节稳定切分、短章节保持单片。

**Architecture:** 新增一个独立的 `SegmentShardingService` 负责固定阈值分片、自然段优先切分和超长段落句级回退，`ChapteringService` 只负责消费分片结果并落文件、落库。下游 `translation / review / inspect` 继续沿用现有按 segment 的主循环，只更新 prompt 文案与 export 的章节级回拼展示，避免重写运行时。

**Tech Stack:** Python 3.11、SQLAlchemy ORM、pytest、PowerShell、仓库根目录虚拟环境 `..\..\.venv\Scripts\python.exe`

---

## File Structure

- Create: `app/services/segment_sharding_service.py`
  - 负责固定阈值分片规则、自然段优先合并、超长自然段句级切分。
- Modify: `app/services/chaptering_service.py`
  - 维护 `body_source_text`，调用分片服务，为单章写出 `1..N` 个 segment 文件。
- Modify: `app/services/translation_assets_service.py`
  - 把 prompt 文案从“段落”收口为“分片”。
- Modify: `app/services/export_service.py`
  - 先按章节聚合 segment，再输出章节级 `source_text / translated_text`。
- Create: `tests/test_segment_sharding_service.py`
  - 纯分片规则单测。
- Modify: `tests/test_chaptering_stage.py`
  - 多分片 chaptering 集成测试。
- Modify: `tests/test_chapter_queries.py`
  - `inspect.chapter` 的多分片 summary 测试。
- Modify: `tests/test_segment_queries.py`
  - `inspect.segment` 通过 `chapter_index + segment_index` 命中同章第二个分片。
- Modify: `tests/test_translation_stage.py`
  - `missing_only / failed_only` 在同章多分片场景下的补跑测试。
- Modify: `tests/test_review_export.py`
  - export 按章节回拼的测试。
- Modify: `tests/test_translation_workflow_actions.py`
  - prompt 中 `分片:` 的解析与断言。
- Modify: `README.md`
  - 更新 `segment` 语义、chaptering 分片规则、export 回拼说明。

### Task 1: 新增纯分片规则服务

**Files:**
- Create: `app/services/segment_sharding_service.py`
- Create: `tests/test_segment_sharding_service.py`

- [ ] **Step 1: 先写分片规则的失败测试**

```python
from __future__ import annotations

from tools.local_translation_workbench.app.services.segment_sharding_service import SegmentShardingService


def test_segment_sharding_service_keeps_short_text_as_single_segment() -> None:
    service = SegmentShardingService()

    result = service.build_segments(body_source_text="第一段。\n\n第二段。")

    assert [item.segment_index for item in result] == [1]
    assert result[0].source_text == "第一段。\n\n第二段。"


def test_segment_sharding_service_splits_long_text_at_paragraph_boundaries() -> None:
    service = SegmentShardingService()
    body = f"{'甲' * 1200}\n\n{'乙' * 1200}\n\n{'丙' * 500}"

    result = service.build_segments(body_source_text=body)

    assert [item.segment_index for item in result] == [1, 2]
    assert result[0].source_text == f"{'甲' * 1200}\n\n{'乙' * 1200}"
    assert result[1].source_text == f"{'丙' * 500}"


def test_segment_sharding_service_merges_short_paragraphs_before_cutting() -> None:
    service = SegmentShardingService()
    body = f"{'甲' * 900}\n\n{'乙' * 900}\n\n{'丙' * 900}"

    result = service.build_segments(body_source_text=body)

    assert [item.segment_index for item in result] == [1, 2]
    assert result[0].source_text == f"{'甲' * 900}\n\n{'乙' * 900}"
    assert result[1].source_text == f"{'丙' * 900}"


def test_segment_sharding_service_falls_back_to_sentence_split_for_oversized_paragraph() -> None:
    service = SegmentShardingService()
    body = f"{'甲' * 2100}。{'乙' * 2100}。"

    result = service.build_segments(body_source_text=body)

    assert [item.segment_index for item in result] == [1, 2]
    assert result[0].source_text.endswith("。")
    assert result[1].source_text.endswith("。")
    assert all(len(item.source_text) <= service.HARD_MAX_CHARS for item in result)
```

- [ ] **Step 2: 跑单测，确认现在确实失败**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_segment_sharding_service.py -v`

Expected: `ModuleNotFoundError: No module named 'tools.local_translation_workbench.app.services.segment_sharding_service'`

- [ ] **Step 3: 实现最小可用的分片服务**

```python
from __future__ import annotations

import re
from dataclasses import dataclass

from ..utils import normalize_newlines


@dataclass(frozen=True)
class SegmentShard:
    segment_index: int
    source_text: str


class SegmentShardingService:
    TARGET_CHARS = 2500
    HARD_MAX_CHARS = 4000
    SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[。！？；!?;])")

    def build_segments(self, *, body_source_text: str) -> list[SegmentShard]:
        normalized_text = normalize_newlines(body_source_text).strip()
        if not normalized_text:
            return []

        paragraphs = [
            item.strip()
            for item in re.split(r"\n\s*\n+", normalized_text)
            if item.strip()
        ]

        segments: list[str] = []
        buffer: list[str] = []
        buffer_length = 0

        for paragraph in paragraphs:
            paragraph_chunks = (
                [paragraph]
                if len(paragraph) <= self.HARD_MAX_CHARS
                else self._split_oversized_paragraph(paragraph)
            )
            for chunk in paragraph_chunks:
                separator_length = 2 if buffer else 0
                proposed_length = buffer_length + separator_length + len(chunk)
                if buffer and proposed_length > self.TARGET_CHARS:
                    segments.append("\n\n".join(buffer))
                    buffer = [chunk]
                    buffer_length = len(chunk)
                    continue
                buffer.append(chunk)
                buffer_length = proposed_length

        if buffer:
            segments.append("\n\n".join(buffer))

        return [
            SegmentShard(segment_index=index, source_text=segment_text)
            for index, segment_text in enumerate(segments, start=1)
        ]

    def _split_oversized_paragraph(self, paragraph: str) -> list[str]:
        sentences = [
            item.strip()
            for item in self.SENTENCE_BOUNDARY_PATTERN.split(paragraph)
            if item.strip()
        ]
        if len(sentences) <= 1:
            return self._hard_split(paragraph)

        result: list[str] = []
        buffer = ""
        for sentence in sentences:
            proposed = sentence if not buffer else f"{buffer}{sentence}"
            if buffer and len(proposed) > self.TARGET_CHARS:
                result.append(buffer.strip())
                buffer = sentence
                continue
            buffer = proposed

        if buffer:
            result.append(buffer.strip())

        flattened: list[str] = []
        for item in result:
            if len(item) <= self.HARD_MAX_CHARS:
                flattened.append(item)
                continue
            flattened.extend(self._hard_split(item))
        return flattened

    def _hard_split(self, text: str) -> list[str]:
        return [
            chunk.strip()
            for chunk in (
                text[index:index + self.HARD_MAX_CHARS]
                for index in range(0, len(text), self.HARD_MAX_CHARS)
            )
            if chunk.strip()
        ]
```

- [ ] **Step 4: 重新跑分片单测**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_segment_sharding_service.py -v`

Expected: 4 个测试全部 `PASSED`

- [ ] **Step 5: 提交这一批改动**

```bash
git add app/services/segment_sharding_service.py tests/test_segment_sharding_service.py
git commit -m "feat: add fixed segment sharding service"
```

### Task 2: 让 chaptering 产出真实多分片

**Files:**
- Modify: `app/services/chaptering_service.py`
- Modify: `tests/test_chaptering_stage.py`

- [ ] **Step 1: 先补 chaptering 的失败集成测试**

```python
def _build_sharded_chapter_source() -> str:
    first_paragraph = "甲" * 1300
    second_paragraph = "乙" * 1300
    return f"第1章 很长的一章\n{first_paragraph}\n\n{second_paragraph}\n\n尾声。"


def test_chaptering_service_splits_long_chapter_into_multiple_segment_files(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    source_file = project_workspace / "chapter-sharding.txt"
    source_file.write_text(_build_sharded_chapter_source(), encoding="utf-8")

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("chaptering-sharded-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    result = ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("chaptering-sharded-run"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    project_row = db_session.execute(
        select(TranslationProject).where(TranslationProject.id == project.id)
    ).scalar_one()
    project_root = project_workspace / project_row.project_key
    segments = db_session.execute(
        select(ChapterSegment)
        .where(ChapterSegment.project_id == project.id)
        .order_by(ChapterSegment.segment_index.asc())
    ).scalars().all()

    assert result.chapter_count == 1
    assert result.segment_count == 2
    assert [segment.segment_index for segment in segments] == [1, 2]
    assert (project_root / "segments" / "0001_0001_source.txt").is_file()
    assert (project_root / "segments" / "0001_0002_source.txt").is_file()
    assert "第1章 很长的一章" not in (
        project_root / "segments" / "0001_0001_source.txt"
    ).read_text(encoding="utf-8")


def test_cli_stage_run_chaptering_reports_multi_segment_count(
    project_workspace: Path,
    request_id_factory,
    capsys,
) -> None:
    source_file = project_workspace / "cli-sharded-chapter.txt"
    source_file.write_text(_build_sharded_chapter_source(), encoding="utf-8")

    create_exit_code = main(
        [
            "-Action",
            "project.create",
            "-RequestId",
            request_id_factory("chaptering-sharded-cli-create"),
            "-SourcePath",
            str(source_file),
            "-SourceLanguage",
            "zh",
            "-TargetLanguage",
            "en",
        ]
    )
    create_payload = json.loads(capsys.readouterr().out)
    assert create_exit_code == 0
    assert create_payload["ok"] is True

    stage_exit_code = main(
        [
            "-Action",
            "stage.run",
            "-ProjectId",
            str(create_payload["data"]["id"]),
            "-Stage",
            "chaptering",
            "-ScopeType",
            "all",
            "-RequestId",
            request_id_factory("chaptering-sharded-cli-stage"),
        ]
    )
    stage_payload = json.loads(capsys.readouterr().out)

    assert stage_exit_code == 0
    assert stage_payload["data"]["chapter_count"] == 1
    assert stage_payload["data"]["segment_count"] == 2
```

- [ ] **Step 2: 跑 chaptering 定向测试，确认当前实现还是一章一片**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_chaptering_stage.py -k sharded -v`

Expected: 至少 1 个测试失败，失败信息包含 `assert 1 == 2` 或找不到 `0001_0002_source.txt`

- [ ] **Step 3: 改 chaptering，让它按 body source 产出多分片**

```python
from .segment_sharding_service import SegmentShardingService


class ChapteringService:
    def __init__(self, session: Session, *, base_data_dir: Path) -> None:
        self.session = session
        self.base_data_dir = Path(base_data_dir)
        self.chapters = ChapterRepository(session)
        self.synopsis = SynopsisService(session)
        self.segment_sharding = SegmentShardingService()

    def run(
        self,
        *,
        request_id: str,
        project_id: int,
        source_file_path: Path | None,
        scope: dict[str, object],
        stage_run_id: int | None = None,
        heartbeat: Callable[[], None] | None = None,
    ) -> ChapteringResult:
        project = self.session.get(TranslationProject, project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)
        ensure_scope_supported(scope, stage="chaptering", allowed_types=get_stage_scope_types("chaptering"))

        resolved_source_path = Path(source_file_path or project.source_path)
        if not resolved_source_path.is_file():
            raise ToolError(
                code="file_not_found",
                message=f"找不到章节源文件: {resolved_source_path}",
                status=404,
            )

        content = resolved_source_path.read_text(encoding="utf-8")
        synopsis_result = self.synopsis.extract_explicit_synopsis(content)
        synopsis_row = self.synopsis.apply_extracted_synopsis(
            project_id=project_id,
            synopsis_text=synopsis_result.synopsis_text,
        )
        synopsis_summary = self._build_synopsis_summary(synopsis_row)

        chapter_documents = self._split_into_chapters(synopsis_result.content_without_synopsis)
        project_root = ensure_directory(self.base_data_dir / project.project_key)
        chapter_dir = ensure_directory(project_root / "chapters")
        segment_dir = ensure_directory(project_root / "segments")

        self._mark_related_outputs_stale(project_id=project_id)
        self.chapters.delete_segments_for_project(project_id)
        self.chapters.delete_chapters_for_project(project_id)

        segment_total = 0
        for chapter_index, chapter_document in enumerate(chapter_documents, start=1):
            if heartbeat is not None:
                heartbeat()

            chapter_source_path = chapter_dir / f"{chapter_index:04d}_source.txt"
            chapter_normalized_path = chapter_dir / f"{chapter_index:04d}_normalized.txt"
            chapter_source_path.write_text(chapter_document["source_text"], encoding="utf-8")
            chapter_normalized_path.write_text(chapter_document["normalized_text"], encoding="utf-8")

            chapter_row = self.chapters.create_chapter(
                project_id=project_id,
                chapter_index=chapter_index,
                chapter_title=chapter_document["chapter_title"],
                source_path=str(chapter_source_path),
                normalized_path=str(chapter_normalized_path),
                stage_status="ready",
            )

            shards = self.segment_sharding.build_segments(
                body_source_text=chapter_document["body_source_text"],
            )
            for shard in shards:
                segment_path = segment_dir / f"{chapter_index:04d}_{shard.segment_index:04d}_source.txt"
                segment_path.write_text(shard.source_text, encoding="utf-8")
                self.chapters.create_segment(
                    project_id=project_id,
                    chapter_id=chapter_row.id,
                    segment_index=shard.segment_index,
                    source_text_path=str(segment_path),
                    translation_status="pending",
                    review_status="pending",
                )
                segment_total += 1

        summary = json.dumps(
            {
                "request_id": request_id,
                "chapter_count": len(chapter_documents),
                "segment_count": segment_total,
            },
            ensure_ascii=False,
        )
        if stage_run_id is None:
            self.chapters.create_stage_run(
                project_id=project_id,
                stage="chaptering",
                scope_type=str(scope["type"]),
                scope_value=json.dumps(scope, ensure_ascii=False),
                status="completed",
                summary=summary,
            )
        else:
            stage_run = self.session.get(StageRun, stage_run_id)
            if stage_run is None:
                raise ToolError(code="not_found", message=f"找不到 stage_run {stage_run_id}。", status=404)
            stage_run.status = "completed"
            stage_run.summary = summary
        self.session.commit()
        return ChapteringResult(
            chapter_count=len(chapter_documents),
            segment_count=segment_total,
            synopsis_summary=synopsis_summary,
        )
```

```python
def _build_chapter_document(
    self,
    *,
    chapter_title: str,
    source_lines: list[str],
    normalized_lines: list[str],
    body_source_lines: list[str],
) -> dict[str, str]:
    return {
        "chapter_title": chapter_title,
        "source_text": "\n".join(source_lines).strip("\n"),
        "normalized_text": "\n".join(normalized_lines).strip(),
        "body_source_text": "\n".join(body_source_lines).strip("\n"),
    }
```

```python
def _split_into_chapters(self, content: str) -> list[dict[str, str]]:
    normalized_content = normalize_newlines(content)
    heading_pattern = re.compile(r"^第(?P<number>\d+)(?:章|回|节)\s*(?P<title>.*)$")
    markdown_heading_pattern = re.compile(
        r"^#{3,6}\s+(?P<number>\d+)(?:\s+(?P<title>.*))?$",
        re.MULTILINE,
    )

    if markdown_heading_pattern.search(normalized_content):
        return self._split_markdown_numeric_headings(
            normalized_content=normalized_content,
            heading_pattern=markdown_heading_pattern,
        )

    chapters: list[dict[str, str]] = []
    current_title: str | None = None
    current_source_lines: list[str] = []
    current_normalized_lines: list[str] = []
    current_body_source_lines: list[str] = []

    for raw_line in normalized_content.split("\n"):
        stripped_line = raw_line.strip()
        heading_match = heading_pattern.match(stripped_line)
        if heading_match:
            if current_title is not None:
                chapters.append(
                    self._build_chapter_document(
                        chapter_title=current_title,
                        source_lines=current_source_lines,
                        normalized_lines=current_normalized_lines,
                        body_source_lines=current_body_source_lines,
                    )
                )
            current_title = stripped_line
            current_source_lines = [raw_line]
            current_normalized_lines = []
            current_body_source_lines = []
            continue

        if current_title is None:
            if stripped_line == "":
                continue
            current_title = "第1章"
            current_source_lines = [raw_line]
            current_normalized_lines = [stripped_line]
            current_body_source_lines = [raw_line]
            continue

        current_source_lines.append(raw_line)
        current_body_source_lines.append(raw_line)
        if stripped_line:
            current_normalized_lines.append(stripped_line)

    if current_title is not None:
        chapters.append(
            self._build_chapter_document(
                chapter_title=current_title,
                source_lines=current_source_lines,
                normalized_lines=current_normalized_lines,
                body_source_lines=current_body_source_lines,
            )
        )

    if not chapters and normalized_content.strip():
        stripped = normalized_content.strip()
        chapters.append(
            self._build_chapter_document(
                chapter_title="第1章",
                source_lines=[stripped],
                normalized_lines=[stripped],
                body_source_lines=[stripped],
            )
        )

    return chapters
```

```python
def _split_markdown_numeric_headings(
    self,
    *,
    normalized_content: str,
    heading_pattern: re.Pattern[str],
) -> list[dict[str, str]]:
    lines = normalized_content.split("\n")
    chapters: list[dict[str, str]] = []
    preface_source_lines: list[str] = []
    preface_normalized_lines: list[str] = []
    current_title: str | None = None
    current_source_lines: list[str] = []
    current_normalized_lines: list[str] = []
    current_body_source_lines: list[str] = []

    for raw_line in lines:
        stripped_line = raw_line.strip()
        heading_match = heading_pattern.match(stripped_line)
        if heading_match:
            if current_title is None:
                current_title = self._build_markdown_chapter_title(heading_match)
                current_source_lines = [*preface_source_lines, raw_line]
                current_normalized_lines = [*preface_normalized_lines, stripped_line]
                current_body_source_lines = []
                continue

            chapters.append(
                self._build_chapter_document(
                    chapter_title=current_title,
                    source_lines=current_source_lines,
                    normalized_lines=current_normalized_lines,
                    body_source_lines=current_body_source_lines,
                )
            )
            current_title = self._build_markdown_chapter_title(heading_match)
            current_source_lines = [raw_line]
            current_normalized_lines = [stripped_line]
            current_body_source_lines = []
            continue

        if current_title is None:
            preface_source_lines.append(raw_line)
            if stripped_line:
                preface_normalized_lines.append(stripped_line)
            continue

        current_source_lines.append(raw_line)
        current_body_source_lines.append(raw_line)
        if stripped_line:
            current_normalized_lines.append(stripped_line)

    if current_title is not None:
        chapters.append(
            self._build_chapter_document(
                chapter_title=current_title,
                source_lines=current_source_lines,
                normalized_lines=current_normalized_lines,
                body_source_lines=current_body_source_lines,
            )
        )

    if chapters:
        return chapters

    stripped = normalized_content.strip()
    if stripped:
        return [
            self._build_chapter_document(
                chapter_title="第1章",
                source_lines=[stripped],
                normalized_lines=[stripped],
                body_source_lines=[stripped],
            )
        ]
    return []
```

- [ ] **Step 4: 重跑 chaptering 定向测试**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_chaptering_stage.py -k sharded -v`

Expected: `test_chaptering_service_splits_long_chapter_into_multiple_segment_files` 与 `test_cli_stage_run_chaptering_reports_multi_segment_count` 全部 `PASSED`

- [ ] **Step 5: 提交 chaptering 改动**

```bash
git add app/services/chaptering_service.py tests/test_chaptering_stage.py
git commit -m "feat: shard long chapters into stable segments"
```

### Task 3: 补齐 inspect 与 translation 的多分片语义

**Files:**
- Modify: `app/services/translation_assets_service.py`
- Modify: `tests/test_chapter_queries.py`
- Modify: `tests/test_segment_queries.py`
- Modify: `tests/test_translation_stage.py`
- Modify: `tests/test_translation_workflow_actions.py`
- Modify: `tests/test_review_export.py`

- [ ] **Step 1: 先加多分片 inspect / rerun 的失败测试**

```python
def _build_single_long_chapter_source() -> str:
    first_shard = "第一片正文" + ("甲" * 1294)
    second_shard = "第二片正文" + ("乙" * 1294)
    return f"第1章 长夜\n{first_shard}\n\n{second_shard}\n\n尾声。"


def test_chapter_query_service_inspect_chapter_reports_multiple_segments_for_single_chapter(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    source_file = project_workspace / "inspect-sharded-chapter.txt"
    source_file.write_text(_build_single_long_chapter_source(), encoding="utf-8")

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("inspect-sharded-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )
    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("inspect-sharded-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    payload = ChapterQueryService(db_session).inspect_chapter(
        project_id=project.id,
        chapter_index=1,
    )

    assert payload["chapter"]["summary"]["segment_count"] == 2
    assert [item["segment_index"] for item in payload["chapter"]["segments"]] == [1, 2]


def test_chapter_query_service_inspect_segment_supports_second_shard_locator(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    source_file = project_workspace / "inspect-second-shard.txt"
    source_file.write_text(_build_single_long_chapter_source(), encoding="utf-8")

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("inspect-second-shard-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )
    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("inspect-second-shard-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )

    payload = ChapterQueryService(db_session).inspect_segment(
        project_id=project.id,
        chapter_index=1,
        segment_index=2,
    )

    assert payload["segment"]["segment_index"] == 2
    assert payload["segment"]["source_text"].startswith("第二片正文")


def test_translation_service_missing_only_translates_only_missing_shards_in_same_chapter(
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
        source_text=_build_single_long_chapter_source(),
    )

    TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=FakeProvider(),
    ).run(
        request_id=request_id_factory("translation-sharded-initial"),
        project_id=project_id,
        scope={"type": "chapter_list", "chapters": [1]},
        model_profile_id="profile-sharded-initial",
    )

    segments = db_session.execute(
        select(ChapterSegment)
        .where(ChapterSegment.project_id == project_id)
        .order_by(ChapterSegment.segment_index.asc())
    ).scalars().all()
    second_segment = segments[1]
    second_translation = db_session.execute(
        select(SegmentTranslation).where(
            SegmentTranslation.project_id == project_id,
            SegmentTranslation.segment_id == second_segment.id,
        )
    ).scalar_one()
    second_translation.active_version_id = None
    second_segment.translation_status = "pending"
    db_session.commit()

    rerun_provider = FakeProvider()
    result = TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=rerun_provider,
    ).run(
        request_id=request_id_factory("translation-sharded-missing-only"),
        project_id=project_id,
        scope={"type": "missing_only"},
        model_profile_id="profile-sharded-missing-only",
    )

    assert result.translated_segments == 1
    assert len(rerun_provider.calls) == 1
    assert "分片: 2" in str(rerun_provider.calls[0]["prompt"])
```

- [ ] **Step 2: 跑定向测试，确认 prompt 文案和多分片补跑还没打通**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_chapter_queries.py tests/test_segment_queries.py tests/test_translation_stage.py -k "shard or sharded" -v`

Expected: 至少 1 个测试失败，失败信息包含 `分片: 2` 未命中或 `segment_count == 2` 不成立

- [ ] **Step 3: 更新 prompt 文案，并把相关测试 fixture 同步到“分片”语义**

```python
class TranslationAssetsService:
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
            f"分片: {segment_index}\n"
            "只返回译文，不要解释。\n"
            "如果正文命中了术语表中的 source_term，译文必须优先使用该条目的 target_term。\n"
            "同组命中的多条表面形式必须分别按各自 source_term 对应 target_term 翻译，不能互换。\n"
            "不要把当前命中的 alias/title 改写成同组 canonical，反之亦然。\n"
            "同一术语在同一分片内不要出现多种译法。"
        )
        if glossary_entries:
            prompt += "\n术语表：\n" + self._render_glossary_groups(glossary_entries)
        return f"{prompt}\n\n{source_text}"
```

```python
class MixedProvider:
    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        self.call_count += 1
        source_text = prompt.rsplit("\n\n", maxsplit=1)[-1]
        if "生成 source synopsis" in prompt:
            content = "源简介内容"
        elif "翻译 target synopsis" in prompt:
            content = "目标简介内容"
        elif "章节: 1" in prompt and "分片: 1" in prompt:
            content = source_text
        else:
            content = f"[{model_name}] {source_text}"
        return TextGenerationResult(
            content=content,
            provider_name="mixed_provider",
            model_name=model_name,
        )
```

```python
segment_match = re.search(r"分片:\s*(\d+)", prompt)
```

- [ ] **Step 4: 重跑 inspect / translation 定向测试**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_chapter_queries.py tests/test_segment_queries.py tests/test_translation_stage.py tests/test_translation_workflow_actions.py tests/test_review_export.py -k "shard or sharded or 分片" -v`

Expected: 新增的多分片 inspect / rerun 测试全部 `PASSED`

- [ ] **Step 5: 提交 inspect / translation 语义修正**

```bash
git add app/services/translation_assets_service.py tests/test_chapter_queries.py tests/test_segment_queries.py tests/test_translation_stage.py tests/test_translation_workflow_actions.py tests/test_review_export.py
git commit -m "refactor: align translation prompts with segment shards"
```

### Task 4: 按章节回拼 export 输出

**Files:**
- Modify: `app/services/export_service.py`
- Modify: `tests/test_review_export.py`

- [ ] **Step 1: 先补 export 回拼的失败测试**

```python
def _prepare_project_with_sharded_translations(
    *,
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> int:
    source_file = project_workspace / "review-export-sharded-source.txt"
    source_file.write_text(_build_single_long_chapter_source(), encoding="utf-8")

    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("review-export-sharded-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )

    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("review-export-sharded-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )
    TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=MixedProvider(),
    ).run(
        request_id=request_id_factory("review-export-sharded-translation"),
        project_id=project.id,
        scope={"type": "all"},
        model_profile_id="profile-review-export-sharded",
    )
    return project.id
```

```python
def test_export_reassembles_multi_segment_chapter_into_single_translation_record(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_project_with_sharded_translations(
        database_url=database_url,
        project_workspace=project_workspace,
        db_session=db_session,
        request_id_factory=request_id_factory,
    )

    ReviewService(db_session).run(
        request_id=request_id_factory("review-export-sharded-review"),
        project_id=project_id,
        scope={"type": "all"},
    )
    result = ExportService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("review-export-sharded-export"),
        project_id=project_id,
        scope={"type": "all"},
    )

    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    export_text = Path(result.manifest_path).with_name("export.md").read_text(encoding="utf-8")

    assert len(manifest["translations"]) == 1
    chapter_translation = manifest["translations"][0]
    assert chapter_translation["chapter_index"] == 1
    assert chapter_translation["segment_count"] == 2
    assert "第一片正文" in chapter_translation["source_text"]
    assert "第二片正文" in chapter_translation["source_text"]
    assert chapter_translation["source_text"].index("第一片正文") < chapter_translation["source_text"].index("第二片正文")
    assert export_text.count("### 第1章 第1章 长夜") == 0
    assert export_text.count("### 第1章 长夜") == 1
```

- [ ] **Step 2: 跑 export 定向测试，确认当前 manifest 还是按分片平铺**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_review_export.py -k sharded -v`

Expected: 失败信息包含 `len(manifest["translations"]) == 1` 不成立

- [ ] **Step 3: 改 export，让 manifest 和 Markdown 都按章节回拼**

```python
def _group_rows_by_chapter(
    self,
    rows: list[tuple[Chapter, ChapterSegment, SegmentTranslation | None, SegmentTranslationVersion | None]],
) -> list[tuple[Chapter, list[tuple[ChapterSegment, SegmentTranslation | None, SegmentTranslationVersion | None]]]]:
    grouped: list[tuple[Chapter, list[tuple[ChapterSegment, SegmentTranslation | None, SegmentTranslationVersion | None]]]] = []
    current_chapter: Chapter | None = None
    bucket: list[tuple[ChapterSegment, SegmentTranslation | None, SegmentTranslationVersion | None]] = []

    for chapter, segment, translation, version in rows:
        if current_chapter is None or current_chapter.id != chapter.id:
            if current_chapter is not None:
                grouped.append((current_chapter, bucket))
            current_chapter = chapter
            bucket = []
        bucket.append((segment, translation, version))

    if current_chapter is not None:
        grouped.append((current_chapter, bucket))
    return grouped


def _build_chapter_translation_record(
    self,
    *,
    chapter: Chapter,
    rows: list[tuple[ChapterSegment, SegmentTranslation | None, SegmentTranslationVersion | None]],
) -> dict[str, object]:
    source_parts = [
        Path(segment.source_text_path).read_text(encoding="utf-8").strip()
        for segment, _, _ in rows
    ]
    translated_parts = [
        version.translated_text.strip()
        for _, _, version in rows
        if version is not None and version.translated_text.strip()
    ]
    return {
        "chapter_id": chapter.id,
        "chapter_index": chapter.chapter_index,
        "chapter_title": chapter.chapter_title,
        "segment_count": len(rows),
        "source_text": "\n\n".join(source_parts).strip(),
        "translated_text": "\n\n".join(translated_parts).strip(),
        "translation_status": "translated" if all(segment.translation_status == "translated" for segment, _, _ in rows) else "partial",
        "review_status": "reviewed" if all(segment.review_status == "reviewed" for segment, _, _ in rows) else "pending",
    }
```

```python
chapter_groups = self._group_rows_by_chapter(rows)
translations = [
    self._build_chapter_translation_record(chapter=chapter, rows=chapter_rows)
    for chapter, chapter_rows in chapter_groups
]
chapter_ids = sorted({chapter.id for chapter, _ in chapter_groups})
chapter_indexes = sorted({chapter.chapter_index for chapter, _ in chapter_groups})
```

```python
def _render_export_markdown(
    self,
    translations: list[dict[str, object]],
    glossary_entries: list[dict[str, object]],
    review_summary: dict[str, object],
    *,
    source_synopsis_text: str | None,
    target_synopsis_text: str,
) -> str:
    lines: list[str] = ["# Local Translation Export", ""]
    lines.append("## 简介（原文）")
    lines.extend(self._render_fenced_text_block(source_synopsis_text or "（无）"))
    lines.append("")
    lines.append("## 简介（译文）")
    lines.extend(self._render_fenced_text_block(target_synopsis_text))
    lines.append("")
    lines.append("## Translations")
    for item in translations:
        lines.append(f"### 第{item['chapter_index']}章 {item['chapter_title']}")
        lines.append("#### 原文")
        lines.extend(self._render_fenced_text_block(str(item["source_text"]) or "（空）"))
        lines.append("")
        lines.append("#### 译文")
        lines.extend(self._render_fenced_text_block(str(item["translated_text"]) or "（空）"))
        lines.append("")

    lines.append("## Glossary")
    if glossary_entries:
        for entry in glossary_entries:
            lock_flag = "locked" if int(entry["locked"]) else "unlocked"
            lines.append(f"- {entry['source_term']} -> {entry['target_term']} ({lock_flag})")
    else:
        lines.append("- 无术语")
    lines.append("")

    lines.append("## Review Summary")
    lines.append(f"- issue_count: {review_summary['issue_count']}")
    for issue in review_summary["issues"]:
        lines.append(f"- {issue['issue_type']}: {issue['message']}")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"
```

- [ ] **Step 4: 重跑 export 定向测试**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_review_export.py -k sharded -v`

Expected: `test_export_reassembles_multi_segment_chapter_into_single_translation_record` 为 `PASSED`

- [ ] **Step 5: 提交 export 回拼改动**

```bash
git add app/services/export_service.py tests/test_review_export.py
git commit -m "feat: reassemble export output by chapter"
```

### Task 5: 更新 README 并跑完整回归

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 先把 README 的关键说明补全**

```markdown
- `segment` 的真实语义现在是“章节内翻译分片”，不是自然段编号。
- `chaptering` 会先按整章读取正文；短章节保留 1 个 segment，长章节按自然段优先、句级兜底的固定规则切成多个 segment。
- `inspect.chapter / inspect.segment / inspect.translation` 继续使用 segment 视角做定位与补跑，但 `export` 会按 `chapter_index + segment_index` 回拼成章节级输出。
```

```markdown
### `inspect.segment`

查看单个翻译分片详情。必填参数：

- `project_id`

分片定位参数必须且只能使用一种方式：

- `segment_id`
- `chapter_index + segment_index`
```

- [ ] **Step 2: 运行这轮改动涉及的重点测试组合**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/test_segment_sharding_service.py tests/test_chaptering_stage.py tests/test_chapter_queries.py tests/test_segment_queries.py tests/test_translation_stage.py tests/test_translation_workflow_actions.py tests/test_review_export.py -v`

Expected: 命中本轮改动的测试全部通过，`pytest` 退出码为 `0`

- [ ] **Step 3: 运行完整回归**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests -q`

Expected: 完整测试套件全部通过，输出形态为 `... passed`，`pytest` 退出码为 `0`

- [ ] **Step 4: 提交 README 与最终验证结果**

```bash
git add README.md
git commit -m "docs: describe segment sharding behavior"
```

## Self-Review

- 设计稿第 6 节的四条规则都已映射到任务：固定阈值在 Task 1，chaptering 产物在 Task 2，inspect / translation 语义在 Task 3，export 回拼在 Task 4。
- 没有留下 `TODO / TBD / implement later / add tests for the above` 这类占位语句。
- 所有新增命名保持一致：统一使用 `SegmentShardingService`、`build_segments()`、`SegmentShard`、`body_source_text`、`分片`。
```
