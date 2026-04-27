# Local Translation Workbench Slimming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变 action、数据库 schema、CLI 参数和现有输出契约的前提下，把本地翻译工作台的三个巨型服务拆成更小、更可维护的模块。

**执行记录（2026-04-27）：** 已完成本轮维护性瘦身。新增 token usage、pipeline dispatch、translation parallel/payload、glossary prompt/finalize/types 等辅助服务；`workflow_runtime_service.py` 收到 `1064` 行，`translation_workflow_execution_service.py` 收到 `804` 行，`glossary_service.py` 收到 `537` 行。最终完整回归：`302 passed`。

**Architecture:** 本轮只做行为保持型重构，先用现有回归锁住外部行为，再按职责拆分 `WorkflowRuntimeService`、`TranslationWorkflowExecutionService`、`GlossaryService`。每一刀都必须保持现有测试通过；如果需要新增测试，只新增针对服务边界和退化行为的 characterization test，不引入新功能。

**Tech Stack:** Python 3.13、SQLAlchemy ORM、pytest、Alembic、PowerShell

---

## 边界原则

- 不新增数据库表或字段。
- 不新增 action，不改已有 action 参数名。
- 不改 README 已声明的输出语义。
- 不引入 UI、批量项目、模板、报告等 P2 功能。
- 不把 token usage、observability、fallback 继续散落到业务服务里。
- 所有测试串行执行，不能并行使用同一个 `LTW_TEST_DATABASE_URL`。

## 当前主要臃肿点

- `app/services/workflow_runtime_service.py`：同时负责 workflow run 生命周期、step 执行、并发组、失败上下文、summary、token usage。
- `app/services/translation_workflow_execution_service.py`：同时负责分片选择、job 构建、并发会话、provider 调用、payload 汇总、正式版本提交。
- `app/services/glossary_service.py`：同时负责 prompt、模型响应解析、术语裁决、关系复核、finalize、inspect。

---

## 文件结构

- Create: `app/services/workflow_token_usage_service.py`
  责任：集中读取 workflow step/run 的 token usage，替代 runtime/stage inspection 内部重复汇总逻辑。
- Create: `app/services/workflow_pipeline_dispatch_service.py`
  责任：根据 workflow action 调用 glossary/translation pipeline，承接 `_run_glossary_pipeline_step` 与 `_run_translation_pipeline_step`。
- Modify: `app/services/workflow_runtime_service.py`
  责任：保留 workflow run 主循环、状态流转、step/group 编排，不再直接处理 pipeline dispatch 与 token usage 汇总细节。
- Modify: `app/services/stage_run_inspection_service.py`
  责任：改用 `WorkflowTokenUsageService` 读取 usage，避免 inspect 读模型重复实现汇总规则。
- Create: `app/services/translation_workflow_parallel_service.py`
  责任：集中处理并发 session、worker 数量和并发 job 执行。
- Create: `app/services/translation_workflow_payload_service.py`
  责任：集中组装 generate/review/rewrite/finalize 的并发结果 payload。
- Modify: `app/services/translation_workflow_execution_service.py`
  责任：保留 translation workflow 领域动作入口，委托 parallel/payload 辅助服务。
- Create: `app/services/glossary_prompt_service.py`
  责任：集中构建 glossary extraction/decision/review prompt，并解析 provider JSON 响应。
- Create: `app/services/glossary_types.py`
  责任：放置 `GlossaryExtraction` 这类被 glossary prompt/finalize/service 共享的轻量数据结构，避免新服务反向导入 `glossary_service.py` 形成循环依赖。
- Create: `app/services/glossary_finalize_service.py`
  责任：集中构建 finalized terms、provider final judge 请求与 fallback hydrate。
- Modify: `app/services/glossary_service.py`
  责任：保留 glossary 对外入口、inspect、run 委托，不再承载 prompt/parse/finalize 细节。
- Test: `tests/test_workflow_actions.py`
- Test: `tests/test_workflow_runtime_split.py`
- Test: `tests/test_translation_workflow_execution_service.py`
- Test: `tests/test_translation_workflow_actions.py`
- Test: `tests/test_glossary_stage.py`
- Test: `tests/test_project_actions.py`

---

### Task 1: 建立瘦身基线和不可变契约

**Files:**
- Modify: `docs/superpowers/plans/2026-04-27-local-translation-workbench-slimming.md`
- Test: `tests/test_translation_inspection_service.py`
- Test: `tests/test_translation_stage.py`
- Test: `tests/test_project_actions.py`
- Test: `tests/test_glossary_stage.py`
- Test: `tests/test_translation_workflow_actions.py`

- [ ] **Step 1: 确认工作区当前状态**

Run:

```powershell
git status --short
```

Expected: 输出当前未提交改动。若已有未提交改动，不回滚；先判断是否属于当前 token usage/observability 现场。

- [ ] **Step 2: 跑 translation inspect 定向回归**

Run:

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_inspection_service.py tests\test_translation_stage.py -k "version_id or compare or timeline or provenance" -q
```

Expected: PASS，当前基线为 `21 passed`。

- [ ] **Step 3: 串行跑 stage.inspect_runs 定向回归**

Run:

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_project_actions.py -k "inspect_runs" -q
```

Expected: PASS，当前基线为 `8 passed`。不要和其他 pytest 并行跑同一个测试库。

- [ ] **Step 4: 跑 workflow 与 glossary 受影响回归**

Run:

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_workflow_actions.py tests\test_workflow_runtime_split.py tests\test_translation_workflow_execution_service.py tests\test_translation_workflow_actions.py tests\test_glossary_stage.py -q
```

Expected: PASS。若失败，先记录失败测试名和错误，不进入拆分。

---

### Task 2: 抽出 workflow token usage 汇总

**Files:**
- Create: `app/services/workflow_token_usage_service.py`
- Modify: `app/services/workflow_runtime_service.py`
- Modify: `app/services/stage_run_inspection_service.py`
- Test: `tests/test_project_actions.py`
- Test: `tests/test_translation_workflow_actions.py`

- [ ] **Step 1: 新建 token usage 读取服务**

Create `app/services/workflow_token_usage_service.py`:

```python
from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import WorkflowRun, WorkflowStepRun
from ..token_usage import merge_token_usage_payloads, normalize_token_usage_payload


class WorkflowTokenUsageService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def summarize_step_runs(self, *, workflow_run_id: int) -> dict[str, int] | None:
        step_runs = self.session.execute(
            select(WorkflowStepRun).where(WorkflowStepRun.workflow_run_id == workflow_run_id)
        ).scalars().all()
        return merge_token_usage_payloads(
            None if not isinstance(step.output_payload, dict) else step.output_payload.get("token_usage")
            for step in step_runs
        )

    def summarize_step_logs(self, step_logs: list[Mapping[str, object]]) -> dict[str, int] | None:
        return merge_token_usage_payloads(
            None
            if not isinstance(step_log.get("output_payload"), Mapping)
            else step_log["output_payload"].get("token_usage")
            for step_log in step_logs
        )

    def read_workflow_run_usage(self, *, workflow_run: WorkflowRun) -> dict[str, int] | None:
        summary_payload = workflow_run.summary
        if isinstance(summary_payload, str) and summary_payload.strip():
            import json

            try:
                decoded = json.loads(summary_payload)
            except json.JSONDecodeError:
                decoded = None
            if isinstance(decoded, dict):
                usage = normalize_token_usage_payload(decoded.get("token_usage"))
                if usage is not None:
                    return usage
        return self.summarize_step_runs(workflow_run_id=int(workflow_run.id))
```

- [ ] **Step 2: 修改 runtime 使用新服务**

In `app/services/workflow_runtime_service.py`, replace local usage helpers with:

```python
from .workflow_token_usage_service import WorkflowTokenUsageService
```

Inside `__init__`:

```python
self.token_usage = WorkflowTokenUsageService(session)
```

Replace:

```python
self._summarize_workflow_step_token_usage(workflow_run_id=workflow_run_id)
self._summarize_step_logs_token_usage(executed_steps)
```

with:

```python
self.token_usage.summarize_step_runs(workflow_run_id=workflow_run_id)
self.token_usage.summarize_step_logs(executed_steps)
```

Delete `_summarize_workflow_step_token_usage` and `_summarize_step_logs_token_usage` from `WorkflowRuntimeService`.

- [ ] **Step 3: 修改 stage inspect 使用新服务**

In `app/services/stage_run_inspection_service.py`, add:

```python
from .workflow_token_usage_service import WorkflowTokenUsageService
```

Inside `__init__`:

```python
self.token_usage = WorkflowTokenUsageService(session)
```

Replace duplicated workflow/step usage aggregation with:

```python
workflow_token_usage = self.token_usage.read_workflow_run_usage(workflow_run=workflow_run)
```

and:

```python
return self.token_usage.read_workflow_run_usage(workflow_run=workflow_run)
```

- [ ] **Step 4: 跑定向回归**

Run:

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_project_actions.py -k "inspect_runs" -q
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_workflow_actions.py -q
```

Expected: PASS。

---

### Task 3: 抽出 workflow pipeline dispatch

**Files:**
- Create: `app/services/workflow_pipeline_dispatch_service.py`
- Modify: `app/services/workflow_runtime_service.py`
- Test: `tests/test_workflow_actions.py`
- Test: `tests/test_workflow_runtime_split.py`

- [ ] **Step 1: 新建 dispatch 服务壳**

Create `app/services/workflow_pipeline_dispatch_service.py`:

```python
from __future__ import annotations

from typing import Any, Mapping

from ..errors import ToolError


class WorkflowPipelineDispatchService:
    def run_glossary_action(
        self,
        *,
        action: str,
        pipeline,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        scope: Mapping[str, Any],
        model_profile_id: str,
        provider_model_name: str | None,
    ) -> dict[str, object]:
        if action == "glossary.extract":
            return pipeline.extract(
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=workflow_step_run_id,
                project_id=project_id,
                scope=dict(scope),
                model_profile_id=model_profile_id,
                provider_model_name=provider_model_name,
            )
        if action == "glossary.normalize":
            return pipeline.normalize(workflow_run_id=workflow_run_id, workflow_step_run_id=workflow_step_run_id)
        if action == "glossary.review_relations":
            return pipeline.review_relations(
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=workflow_step_run_id,
                model_profile_id=model_profile_id,
                provider_model_name=provider_model_name,
            )
        if action == "glossary.review_scope":
            return pipeline.review_scope(
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=workflow_step_run_id,
                model_profile_id=model_profile_id,
                provider_model_name=provider_model_name,
            )
        if action == "glossary.finalize":
            return pipeline.finalize(
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=workflow_step_run_id,
                project_id=project_id,
                model_profile_id=model_profile_id,
                provider_model_name=provider_model_name,
            )
        if action == "glossary.inspect_pipeline":
            return pipeline.inspect_pipeline(workflow_run_id=workflow_run_id)
        raise ToolError(code="invalid_arguments", message=f"不支持的 glossary workflow action: {action}。", status=400)

    def run_translation_action(
        self,
        *,
        action: str,
        pipeline,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        scope: Mapping[str, Any],
        model_profile_id: str,
        provider_model_name: str | None,
        step_definition: Mapping[str, Any],
        heartbeat=None,
    ) -> dict[str, object]:
        if action == "translation.generate_draft":
            return pipeline.generate_draft(
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=workflow_step_run_id,
                project_id=project_id,
                scope=dict(scope),
                model_profile_id=model_profile_id,
                provider_model_name=provider_model_name,
                draft_role=str(step_definition.get("draft_role") or "primary"),
                heartbeat=heartbeat,
            )
        if action == "translation.review_draft":
            return pipeline.review_draft(
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=workflow_step_run_id,
                model_profile_id=model_profile_id,
                provider_model_name=provider_model_name,
                heartbeat=heartbeat,
            )
        if action == "translation.rewrite_draft":
            return pipeline.rewrite_draft(
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=workflow_step_run_id,
                model_profile_id=model_profile_id,
                provider_model_name=provider_model_name,
                heartbeat=heartbeat,
            )
        if action == "translation.finalize":
            return pipeline.finalize(
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=workflow_step_run_id,
                project_id=project_id,
                model_profile_id=model_profile_id,
                provider_model_name=provider_model_name,
                heartbeat=heartbeat,
            )
        if action == "translation.inspect_pipeline":
            return pipeline.inspect_pipeline(workflow_run_id=workflow_run_id)
        raise ToolError(code="invalid_arguments", message=f"不支持的 translation workflow action: {action}。", status=400)
```

- [ ] **Step 2: 修改 runtime 委托 dispatch**

In `WorkflowRuntimeService.__init__`:

```python
from .workflow_pipeline_dispatch_service import WorkflowPipelineDispatchService

self.pipeline_dispatch = WorkflowPipelineDispatchService()
```

Replace `_run_glossary_pipeline_step(...)` body with a call to:

```python
return self.pipeline_dispatch.run_glossary_action(
    action=action,
    pipeline=pipeline,
    workflow_run_id=workflow_run_id,
    workflow_step_run_id=workflow_step_run_id,
    project_id=project_id,
    scope=scope,
    model_profile_id=model_profile_id,
    provider_model_name=provider_model_name,
)
```

Replace `_run_translation_pipeline_step(...)` body with:

```python
return self.pipeline_dispatch.run_translation_action(
    action=action,
    pipeline=pipeline,
    workflow_run_id=workflow_run_id,
    workflow_step_run_id=workflow_step_run_id,
    project_id=project_id,
    scope=scope,
    model_profile_id=model_profile_id,
    provider_model_name=provider_model_name,
    step_definition=step_definition,
    heartbeat=heartbeat,
)
```

- [ ] **Step 3: 跑 workflow 回归**

Run:

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_workflow_actions.py tests\test_workflow_runtime_split.py -q
```

Expected: PASS。

---

### Task 4: 拆 translation workflow 的并发与 payload 汇总

**Files:**
- Create: `app/services/translation_workflow_parallel_service.py`
- Create: `app/services/translation_workflow_payload_service.py`
- Modify: `app/services/translation_workflow_execution_service.py`
- Test: `tests/test_translation_workflow_execution_service.py`
- Test: `tests/test_translation_workflow_actions.py`

- [ ] **Step 1: 抽并发服务**

Create `app/services/translation_workflow_parallel_service.py`:

```python
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable


class TranslationWorkflowParallelService:
    def __init__(self, *, parallel_session_factory=None, max_parallel_workers: int = 4) -> None:
        self.parallel_session_factory = parallel_session_factory
        self.max_parallel_workers = max_parallel_workers

    def should_run_parallel(self, *, job_count: int) -> bool:
        return self.parallel_session_factory is not None and job_count > 1

    def worker_count(self, *, job_count: int) -> int:
        return max(1, min(self.max_parallel_workers, job_count))

    def run_parallel_jobs(self, *, jobs: list[dict[str, object]], worker: Callable[[dict[str, object]], dict[str, object]]) -> list[dict[str, object]]:
        with ThreadPoolExecutor(max_workers=self.worker_count(job_count=len(jobs))) as executor:
            return list(executor.map(worker, jobs))
```

- [ ] **Step 2: 抽 payload 服务**

Create `app/services/translation_workflow_payload_service.py`:

```python
from __future__ import annotations

from ..token_usage import merge_token_usage_payloads


class TranslationWorkflowPayloadService:
    def generation_payload(self, *, results: list[dict[str, object]], model_profile_id: str) -> dict[str, object]:
        return self._with_common_counts(results=results, model_profile_id=model_profile_id, key="draft_count")

    def review_payload(self, *, results: list[dict[str, object]], model_profile_id: str) -> dict[str, object]:
        return self._with_common_counts(results=results, model_profile_id=model_profile_id, key="review_count")

    def rewrite_payload(self, *, results: list[dict[str, object]], model_profile_id: str) -> dict[str, object]:
        return self._with_common_counts(results=results, model_profile_id=model_profile_id, key="rewrite_count")

    def finalize_payload(self, *, results: list[dict[str, object]], model_profile_id: str) -> dict[str, object]:
        active_version_ids = [int(item["active_version_id"]) for item in results if item.get("active_version_id")]
        payload = self._with_common_counts(results=results, model_profile_id=model_profile_id, key="finalized_count")
        payload["active_version_ids"] = active_version_ids
        return payload

    def _with_common_counts(self, *, results: list[dict[str, object]], model_profile_id: str, key: str) -> dict[str, object]:
        token_usage = merge_token_usage_payloads(item.get("token_usage") for item in results)
        payload: dict[str, object] = {
            key: len(results),
            "segment_count": len(results),
            "model_profile_id": model_profile_id,
        }
        if token_usage is not None:
            payload["token_usage"] = token_usage
        return payload
```

- [ ] **Step 3: 修改 execution service 委托**

In `TranslationWorkflowExecutionService.__init__`:

```python
from .translation_workflow_parallel_service import TranslationWorkflowParallelService
from .translation_workflow_payload_service import TranslationWorkflowPayloadService

self.parallel = TranslationWorkflowParallelService(
    parallel_session_factory=parallel_session_factory,
    max_parallel_workers=max_parallel_workers,
)
self.payloads = TranslationWorkflowPayloadService()
```

Replace repeated branches:

```python
if self.parallel_session_factory is None or len(jobs) == 1:
    results = [self._generate_draft_for_segment_in_session(job=job) for job in jobs]
else:
    self.session.commit()
    results = self.run_parallel_jobs(jobs=jobs, worker=lambda job: self._generate_draft_for_segment(job=job))
```

with:

```python
if not self.parallel.should_run_parallel(job_count=len(jobs)):
    results = [self._generate_draft_for_segment_in_session(job=job) for job in jobs]
else:
    self.session.commit()
    results = self.parallel.run_parallel_jobs(jobs=jobs, worker=lambda job: self._generate_draft_for_segment(job=job))
```

Use the same pattern for review, rewrite, and finalize.

- [ ] **Step 4: 跑 translation workflow 回归**

Run:

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_translation_workflow_execution_service.py tests\test_translation_workflow_actions.py -q
```

Expected: PASS。

---

### Task 5: 拆 glossary prompt/parse/finalize

**Files:**
- Create: `app/services/glossary_types.py`
- Create: `app/services/glossary_prompt_service.py`
- Create: `app/services/glossary_finalize_service.py`
- Modify: `app/services/glossary_service.py`
- Test: `tests/test_glossary_stage.py`

- [ ] **Step 1: 先抽共享 glossary 类型，避免循环导入**

Create `app/services/glossary_types.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


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

In `app/services/glossary_service.py`, remove the local `GlossaryExtraction` dataclass and add:

```python
from .glossary_types import GlossaryExtraction
```

- [ ] **Step 2: 新建 prompt service**

Create `app/services/glossary_prompt_service.py`:

```python
from __future__ import annotations

import json

from ..errors import ToolError
from .glossary_types import GlossaryExtraction


class GlossaryPromptService:
    def strip_code_fence(self, content: str) -> str:
        stripped = content.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            return "\n".join(lines).strip()
        return stripped

    def parse_extraction_response(self, content: str) -> list[GlossaryExtraction]:
        try:
            payload = json.loads(self.strip_code_fence(content))
        except json.JSONDecodeError as exc:
            raise ToolError(code="provider_error", message="术语提取返回不是有效 JSON。", status=502) from exc
        items = payload.get("terms") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ToolError(code="provider_error", message="术语提取 JSON 必须是数组或包含 terms 数组。", status=502)
        return [
            GlossaryExtraction(
                source_term=str(item.get("source_term") or "").strip(),
                suggested_term=str(item.get("translated_term") or item.get("target_term") or "").strip(),
                category=str(item.get("category") or "other").strip(),
                note=None if item.get("note") is None else str(item.get("note")),
                term_group_key=str(item.get("term_group_key") or item.get("source_term") or "").strip(),
                relation_role=str(item.get("relation_role") or "independent").strip(),
                gender=None if item.get("gender") is None else str(item.get("gender")).strip(),
                age_group=None if item.get("age_group") is None else str(item.get("age_group")).strip(),
            )
            for item in items
            if isinstance(item, dict)
        ]
```

- [ ] **Step 3: 新建 finalize service**

Create `app/services/glossary_finalize_service.py`:

```python
from __future__ import annotations


class GlossaryFinalizeService:
    def build_finalized_terms(self, *, candidates: list[object], relation_reviews: dict[int, object], scope_reviews: dict[int, object]) -> list[dict[str, object]]:
        finalized: list[dict[str, object]] = []
        for candidate in candidates:
            finalized.append(
                {
                    "draft_candidate_id": int(candidate.id),
                    "chapter_id": candidate.chapter_id,
                    "source_term": candidate.source_term,
                    "target_term": candidate.suggested_term,
                    "category": candidate.category,
                    "note": None if candidate.evidence_payload is None else candidate.evidence_payload.get("note"),
                    "gender": candidate.gender,
                    "age_group": candidate.age_group,
                    "term_group_key": candidate.term_group_key,
                    "relation_role": candidate.relation_role,
                    "scope_level": candidate.scope_level,
                    "scope_chapter_id": candidate.scope_chapter_id,
                }
            )
        return finalized
```

- [ ] **Step 4: 让 GlossaryService 委托新服务**

In `GlossaryService.__init__`:

```python
from .glossary_prompt_service import GlossaryPromptService
from .glossary_finalize_service import GlossaryFinalizeService

self.prompts = GlossaryPromptService()
self.finalizer = GlossaryFinalizeService()
```

Replace `_strip_code_fence` and `_parse_extraction_response` call sites with:

```python
self.prompts.strip_code_fence(content)
self.prompts.parse_extraction_response(content)
```

Move finalized term construction call sites to:

```python
self.finalizer.build_finalized_terms(
    candidates=draft_items,
    relation_reviews=relation_review_index,
    scope_reviews=scope_review_index,
)
```

- [ ] **Step 5: 跑 glossary 回归**

Run:

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_glossary_stage.py -q
```

Expected: PASS。

---

### Task 6: 文档与最终验证收口

**Files:**
- Modify: `README.md`
- Modify: `docs/roadmap.md`
- Modify: `CHANGELOG.md`
- Test: `tests`

- [ ] **Step 1: 在 roadmap 记录本轮是维护性瘦身，不是新功能**

Add to `docs/roadmap.md` P2 前或新增维护小节:

```md
## 维护性收口

当前 P1 已完成，后续新增功能前先执行维护性瘦身：

- 拆分 `workflow_runtime_service.py`
- 拆分 `translation_workflow_execution_service.py`
- 拆分 `glossary_service.py`
- 保持 action、CLI、数据库 schema 和 inspect 输出契约不变
```

- [ ] **Step 2: 更新 CHANGELOG**

Add under `[Unreleased] -> 变更`:

```md
- 启动本地翻译工作台维护性瘦身，优先拆分 workflow runtime、translation workflow execution 与 glossary service 的内部职责；本轮不新增 action、不改数据库 schema。
```

- [ ] **Step 3: 跑完整回归**

Run:

```powershell
D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests -q
```

Expected: PASS。若完整通过数变化，把 README、roadmap、CHANGELOG 的回归基线同步为真实数字。

- [ ] **Step 4: 检查大文件是否确实缩小**

Run:

```powershell
Get-ChildItem -Recurse app\services -File -Filter *.py |
  Where-Object { $_.FullName -notmatch '__pycache__' } |
  ForEach-Object {
    $lines = (Get-Content -Encoding UTF8 $_.FullName | Measure-Object -Line).Lines
    [PSCustomObject]@{ Lines=$lines; Name=$_.Name }
  } |
  Sort-Object Lines -Descending |
  Select-Object -First 15
```

Expected:

- `workflow_runtime_service.py` 明显低于当前 `1138` 行。
- `translation_workflow_execution_service.py` 明显低于当前 `911` 行。
- `glossary_service.py` 明显低于当前 `964` 行。

---

## 自检记录

- 规格覆盖：本计划只覆盖维护性瘦身，不覆盖 P2 新功能；目标正是停止继续膨胀。
- 占位符扫描：没有 `TBD`、`TODO`、`稍后实现`；每个任务都有具体文件、代码方向和验证命令。
- 类型一致性：新增服务均使用现有 `Session`、`WorkflowRun`、`WorkflowStepRun`、`GlossaryExtraction`、`ToolError` 类型；不引入新 schema。
- 风险控制：所有步骤都以现有行为测试为验收标准，任何失败先停下定位，不继续扩大重构范围。
