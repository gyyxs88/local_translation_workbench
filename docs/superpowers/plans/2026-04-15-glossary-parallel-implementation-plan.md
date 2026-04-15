# Glossary Multi-LLM 真并发 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `glossary_multi_llm_v1` 的双 extractor 在保持现有 quorum / degraded 语义不变的前提下实现真正并发执行。

**Architecture:** 在 `WorkflowRuntimeService` 内只为 glossary 的 tolerant `glossary.extract` step group 增加并发分支，translation 路径和其它 glossary 串行步骤保持不动。主线程先按逻辑顺序创建并发布 `workflow_run` / `workflow_step_run`，再用独立 session + 独立 pipeline worker 并发执行 extractor，最后在主线程按原有 quorum 规则汇总结果并继续后续串行步骤。

**Tech Stack:** Python 3、SQLAlchemy Session / sessionmaker、`concurrent.futures.ThreadPoolExecutor`、pytest

---

## 文件结构

- 修改 `app/services/workflow_runtime_service.py`
  责任：为 glossary extractor tolerant group 增加并发执行分支；拆出“预创建 step run”“worker 执行既有 step run”“汇总 quorum 结果”三个职责；保证事务可见性和主线程后续读取一致。
- 修改 `app/services/glossary_pipeline_service.py`
  责任：增加 `fork_for_session()`，让生产 pipeline 能基于新 session 克隆出独立实例，同时复用已有 provider。
- 修改 `tests/test_workflow_actions.py`
  责任：增加并发验证 tracker / fake pipeline；新增“真并发”与“部分失败但 degraded 继续”的回归；把受并发影响的断言改成稳定写法。

### Task 1: 建立 glossary extractor 并发红测与 pipeline 克隆入口

**Files:**
- Modify: `app/services/glossary_pipeline_service.py:11-18`
- Modify: `tests/test_workflow_actions.py:599-714`
- Test: `tests/test_workflow_actions.py`

- [ ] **Step 1: 写出证明“第二个 extractor 在第一个结束前已经启动”的失败测试**

```python
import threading


class ParallelExtractTracker:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.started_step_keys: list[str] = []
        self.active_workers = 0
        self.max_active_workers = 0
        self.second_started = threading.Event()

    def enter(self, *, step_key: str) -> None:
        with self.lock:
            self.started_step_keys.append(step_key)
            self.active_workers += 1
            self.max_active_workers = max(self.max_active_workers, self.active_workers)
            if len(self.started_step_keys) >= 2:
                self.second_started.set()
        if not self.second_started.wait(timeout=0.5):
            raise AssertionError("第二个 extractor 没有在第一个 extractor 完成前启动。")

    def leave(self) -> None:
        with self.lock:
            self.active_workers -= 1


class FakeParallelRuntimeGlossaryPipeline(FakeRuntimeGlossaryPipeline):
    def __init__(self, session, tracker: ParallelExtractTracker) -> None:
        super().__init__()
        self.session = session
        self.tracker = tracker

    def fork_for_session(self, session):
        return FakeParallelRuntimeGlossaryPipeline(session, self.tracker)

    def extract(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        scope: dict[str, object],
        model_profile_id: str,
        provider_model_name: str | None,
    ) -> dict[str, object]:
        step_run = self.session.get(WorkflowStepRun, workflow_step_run_id)
        assert step_run is not None
        self.tracker.enter(step_key=step_run.step_key)
        try:
            return super().extract(
                workflow_run_id=workflow_run_id,
                workflow_step_run_id=workflow_step_run_id,
                project_id=project_id,
                scope=scope,
                model_profile_id=model_profile_id,
                provider_model_name=provider_model_name,
            )
        finally:
            self.tracker.leave()


def test_glossary_multi_llm_workflow_runs_extractors_in_parallel(db_session) -> None:
    project = TranslationProject(
        request_id="workflow-runtime-parallel-project",
        project_key="workflow-runtime-parallel-project",
        source_path="source.txt",
        source_language="ja",
        target_language="zh-CN",
        status="created",
    )
    db_session.add(project)
    db_session.flush()

    WorkflowProfileService(db_session).ensure_builtin_profiles()
    db_session.commit()

    tracker = ParallelExtractTracker()
    runtime_service = WorkflowRuntimeService(db_session)
    result = runtime_service.run_glossary_workflow(
        workflow_definition=runtime_service.resolve_workflow_definition(
            stage="glossary",
            workflow_key="glossary_multi_llm_v1",
        ),
        workflow_key="glossary_multi_llm_v1",
        request_id="workflow-runtime-parallel-run",
        project_id=project.id,
        scope={"type": "all"},
        request_model_profile_id="default",
        provider_model_name="resolved-default-model",
        pipeline=FakeParallelRuntimeGlossaryPipeline(db_session, tracker),
    )

    assert result.candidate_count == 2
    assert tracker.max_active_workers >= 2
    assert set(tracker.started_step_keys[:2]) == {"extract_primary", "extract_secondary"}
```

- [ ] **Step 2: 跑这个测试，确认它在当前串行实现上失败**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_workflow_actions.py -k "runs_extractors_in_parallel" -q`

Expected: FAIL，错误里包含 `第二个 extractor 没有在第一个 extractor 完成前启动。`

- [ ] **Step 3: 给生产 pipeline 加上最小克隆接口**

```python
class GlossaryPipelineService:
    def __init__(self, session, *, provider=None) -> None:
        self.session = session
        self.provider = provider
        self.glossary = GlossaryRepository(session)
        self.glossary_service = GlossaryService(session, provider=provider)

    def fork_for_session(self, session):
        return GlossaryPipelineService(session, provider=self.provider)
```

- [ ] **Step 4: 只跑并发测试，确认它仍然失败但不再卡在“无法克隆 pipeline”**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_workflow_actions.py -k "runs_extractors_in_parallel" -q`

Expected: 仍然 FAIL，失败原因还是“没有并发启动”，不是 `AttributeError: 'GlossaryPipelineService' object has no attribute 'fork_for_session'`

- [ ] **Step 5: Commit**

```bash
git add app/services/glossary_pipeline_service.py tests/test_workflow_actions.py
git commit -m "test: add glossary parallel extractor regression"
```

### Task 2: 在 runtime 中实现 glossary extractor 并发 worker 路径

**Files:**
- Modify: `app/services/workflow_runtime_service.py:1-40`
- Modify: `app/services/workflow_runtime_service.py:500-593`
- Modify: `app/services/workflow_runtime_service.py:658-809`
- Test: `tests/test_workflow_actions.py::test_glossary_multi_llm_workflow_runs_extractors_in_parallel`

- [ ] **Step 1: 先把 runtime 所需的“预创建 step run”与“执行既有 step run”上下文拆出来**

```python
from concurrent.futures import ThreadPoolExecutor


def _prepare_glossary_step_execution(
    self,
    *,
    step_definition: Mapping[str, Any],
    step_index: int,
    workflow_run_id: int,
    request_id: str,
    request_model_profile_id: str,
    request_provider_model_name: str | None,
    project_id: int,
    scope: Mapping[str, Any],
) -> dict[str, Any]:
    resolved_model_profile_id = self.resolve_step_model_profile_id(
        step_definition,
        {
            "request_id": request_id,
            "model_profile_id": request_model_profile_id,
        },
    )
    resolved_step_model_name = self.resolve_step_model_name(
        model_profile_id=resolved_model_profile_id,
        request_model_profile_id=request_model_profile_id,
        request_provider_model_name=request_provider_model_name,
    )
    step_key = str(step_definition.get("step_key") or f"step_{step_index}")
    action = str(step_definition.get("action") or "").strip()
    input_ref = json.dumps({"project_id": project_id, "scope": dict(scope)}, ensure_ascii=False)
    step_summary = self._build_step_summary(
        step_definition=step_definition,
        resolved_model_profile_id=resolved_model_profile_id,
        resolved_model_name=resolved_step_model_name,
    )
    return {
        "step_definition": step_definition,
        "step_index": step_index,
        "step_key": step_key,
        "action": action,
        "resolved_model_profile_id": resolved_model_profile_id,
        "resolved_step_model_name": resolved_step_model_name,
        "input_ref": input_ref,
        "step_summary": step_summary,
        "project_id": project_id,
        "scope": dict(scope),
        "workflow_run_id": workflow_run_id,
    }
```

- [ ] **Step 2: 跑并发测试，确认它仍然失败，说明只是重构准备，没有提前“写绿”**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_workflow_actions.py -k "runs_extractors_in_parallel" -q`

Expected: FAIL，仍然是串行启动相关断言失败。

- [ ] **Step 3: 实现主线程预创建 step run、发布事务、worker 独立 session 执行并汇总结果**

```python
def _execute_glossary_step_group(self, *, step_definitions, first_step_index, workflow_run_id, request_id,
                                 request_model_profile_id, request_provider_model_name, project_id, scope,
                                 pipeline, heartbeat, policy) -> dict[str, Any]:
    if (
        len(step_definitions) > 1
        and str(step_definitions[0].get("action") or "").strip() == "glossary.extract"
    ):
        prepared_steps = []
        for offset, step_definition in enumerate(step_definitions):
            prepared = self._prepare_glossary_step_execution(
                step_definition=step_definition,
                step_index=first_step_index + offset,
                workflow_run_id=workflow_run_id,
                request_id=request_id,
                request_model_profile_id=request_model_profile_id,
                request_provider_model_name=request_provider_model_name,
                project_id=project_id,
                scope=scope,
            )
            step_run = self.create_step_run(
                workflow_run_id=workflow_run_id,
                step_key=prepared["step_key"],
                action=prepared["action"],
                llm_role=str(step_definition.get("llm_role") or "worker"),
                model_profile_id=prepared["resolved_model_profile_id"],
                input_ref=prepared["input_ref"],
                status="running",
                output_payload=None,
                summary=prepared["step_summary"],
            )
            prepared["step_run_id"] = step_run.id
            prepared_steps.append(prepared)

        self.session.commit()

        with ThreadPoolExecutor(max_workers=len(prepared_steps)) as executor:
            futures = [
                executor.submit(
                    self._execute_glossary_parallel_worker,
                    prepared_step=prepared_step,
                    pipeline=pipeline,
                    heartbeat=heartbeat,
                )
                for prepared_step in prepared_steps
            ]
            executions = [future.result() for future in futures]

        return self._summarize_tolerant_group_result(
            executions=executions,
            step_definitions=step_definitions,
            minimum_success=int(policy["minimum_success"]),
        )

    # 其它 glossary 路径继续走原来的串行逻辑
```

```python
def _execute_glossary_precreated_step(
    self,
    *,
    prepared_step: Mapping[str, Any],
    pipeline,
    heartbeat,
    allow_failure: bool,
) -> dict[str, Any]:
    if heartbeat is not None:
        heartbeat()
    step_run = self.session.get(WorkflowStepRun, int(prepared_step["step_run_id"]))
    if step_run is None:
        raise ToolError(code="not_found", message=f"找不到 step_run {prepared_step['step_run_id']}。", status=404)
    step_definition = prepared_step["step_definition"]
    step_log = {
        "step_key": prepared_step["step_key"],
        "action": prepared_step["action"],
        "llm_role": str(step_definition.get("llm_role") or "worker"),
        "model_profile_id": prepared_step["resolved_model_profile_id"],
        "input_ref": prepared_step["input_ref"],
        "status": "running",
        "output_payload": None,
        "summary": prepared_step["step_summary"],
    }
    try:
        output_payload = self._run_glossary_pipeline_step(
            action=prepared_step["action"],
            pipeline=pipeline,
            workflow_run_id=int(prepared_step["workflow_run_id"]),
            workflow_step_run_id=int(prepared_step["step_run_id"]),
            project_id=int(prepared_step["project_id"]),
            scope=prepared_step["scope"],
            model_profile_id=str(prepared_step["resolved_model_profile_id"]),
            provider_model_name=prepared_step["resolved_step_model_name"],
        )
    except Exception as step_exc:
        step_log["status"] = "failed"
        step_log["output_payload"] = {"error": str(step_exc)}
        self.mark_step_status(step_run.id, status="failed", output_payload={"error": str(step_exc)})
        if allow_failure:
            return {
                "succeeded": False,
                "step_log": step_log,
                "exception": step_exc,
                "finalize_payload": None,
            }
        setattr(step_exc, "_workflow_step_logs", [dict(step_log)])
        raise
    output_payload = self._decorate_step_output_payload(
        output_payload=output_payload,
        resolved_model_profile_id=str(prepared_step["resolved_model_profile_id"]),
        resolved_model_name=prepared_step["resolved_step_model_name"],
    )
    step_log["status"] = "completed"
    step_log["output_payload"] = output_payload
    self.mark_step_status(step_run.id, status="completed", output_payload=output_payload)
    return {
        "succeeded": True,
        "step_log": step_log,
        "exception": None,
        "finalize_payload": dict(output_payload) if prepared_step["action"] == "glossary.finalize" else None,
    }
```

```python
def _execute_glossary_parallel_worker(self, *, prepared_step: Mapping[str, Any], pipeline, heartbeat) -> dict[str, Any]:
    worker_session = self.log_session_factory()
    try:
        worker_runtime = WorkflowRuntimeService(worker_session)
        worker_pipeline = pipeline.fork_for_session(worker_session)
        execution = worker_runtime._execute_glossary_precreated_step(
            prepared_step=prepared_step,
            pipeline=worker_pipeline,
            heartbeat=heartbeat,
            allow_failure=True,
        )
        worker_session.commit()
        return execution
    except Exception:
        worker_session.rollback()
        raise
    finally:
        worker_session.close()
```

```python
def _summarize_tolerant_group_result(
    self,
    *,
    executions: list[Mapping[str, Any]],
    step_definitions: list[Mapping[str, Any]],
    minimum_success: int,
) -> dict[str, Any]:
    success_count = sum(1 for item in executions if item["succeeded"])
    failed_step_keys = [str(item["step_log"]["step_key"]) for item in executions if not item["succeeded"]]
    finalize_payload = None
    for item in executions:
        if item["succeeded"] and isinstance(item.get("finalize_payload"), dict):
            finalize_payload = dict(item["finalize_payload"])
    if success_count < minimum_success:
        action = str(step_definitions[0].get("action") or "<unknown>")
        error = ToolError(
            code="workflow_quorum_failed",
            message=f"workflow tolerant step group {action} 至少需要 {minimum_success} 个成功步骤，实际仅 {success_count} 个成功。",
            status=502,
        )
        setattr(error, "_workflow_step_logs", [dict(item["step_log"]) for item in executions])
        raise error
    return {
        "success_count": success_count,
        "failed_step_keys": failed_step_keys,
        "degraded": bool(failed_step_keys),
        "finalize_payload": finalize_payload,
        "step_logs": [dict(item["step_log"]) for item in executions],
    }
```

- [ ] **Step 4: 跑并发测试，确认它转绿**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_workflow_actions.py -k "runs_extractors_in_parallel" -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/workflow_runtime_service.py
git commit -m "feat: parallelize glossary extractor step group"
```

### Task 3: 补齐并发下的 quorum / degraded 回归并稳住现有断言

**Files:**
- Modify: `tests/test_workflow_actions.py:687-991`
- Modify: `app/services/workflow_runtime_service.py:532-593`
- Test: `tests/test_workflow_actions.py`

- [ ] **Step 1: 写出“一个 extractor 失败、另一个成功、workflow 仍 degraded 继续”的失败测试**

```python
class FakeParallelQuorumGlossaryPipeline(FakeParallelRuntimeGlossaryPipeline):
    def __init__(self, session, tracker: ParallelExtractTracker, failing_step_key: str) -> None:
        super().__init__(session, tracker)
        self.failing_step_key = failing_step_key

    def fork_for_session(self, session):
        return FakeParallelQuorumGlossaryPipeline(session, self.tracker, self.failing_step_key)

    def extract(
        self,
        *,
        workflow_run_id: int,
        workflow_step_run_id: int,
        project_id: int,
        scope: dict[str, object],
        model_profile_id: str,
        provider_model_name: str | None,
    ) -> dict[str, object]:
        step_run = self.session.get(WorkflowStepRun, workflow_step_run_id)
        assert step_run is not None
        self.tracker.enter(step_key=step_run.step_key)
        try:
            if step_run.step_key == self.failing_step_key:
                raise ToolError(code="provider_error", message=f"模拟 {step_run.step_key} 失败。", status=502)
            return {"draft_candidate_count": 2}
        finally:
            self.tracker.leave()


def test_glossary_multi_llm_parallel_workflow_allows_one_extractor_failure_with_quorum(db_session) -> None:
    project = TranslationProject(
        request_id="workflow-runtime-parallel-quorum-project",
        project_key="workflow-runtime-parallel-quorum-project",
        source_path="source.txt",
        source_language="ja",
        target_language="zh-CN",
        status="created",
    )
    db_session.add(project)
    db_session.flush()

    WorkflowProfileService(db_session).ensure_builtin_profiles()
    db_session.commit()

    tracker = ParallelExtractTracker()
    runtime_service = WorkflowRuntimeService(db_session)
    result = runtime_service.run_glossary_workflow(
        workflow_definition=runtime_service.resolve_workflow_definition(
            stage="glossary",
            workflow_key="glossary_multi_llm_v1",
        ),
        workflow_key="glossary_multi_llm_v1",
        request_id="workflow-runtime-parallel-quorum-run",
        project_id=project.id,
        scope={"type": "all"},
        request_model_profile_id="default",
        provider_model_name="resolved-default-model",
        pipeline=FakeParallelQuorumGlossaryPipeline(db_session, tracker, "extract_primary"),
    )

    workflow_run = db_session.execute(
        select(WorkflowRun).where(
            WorkflowRun.workflow_key == "glossary_multi_llm_v1",
            WorkflowRun.request_id == "workflow-runtime-parallel-quorum-run",
        )
    ).scalar_one()
    step_runs = db_session.execute(
        select(WorkflowStepRun)
        .where(WorkflowStepRun.workflow_run_id == workflow_run.id)
        .order_by(WorkflowStepRun.id.asc())
    ).scalars().all()
    step_status_map = {item.step_key: item.status for item in step_runs}
    summary = json.loads(workflow_run.summary or "{}")

    assert result.candidate_count == 2
    assert tracker.max_active_workers >= 2
    assert workflow_run.status == "insufficient_evidence"
    assert step_status_map["extract_primary"] == "failed"
    assert step_status_map["extract_secondary"] == "completed"
    assert summary["degraded"] is True
    assert summary["degradation_reason"] == "low_confidence"
```

- [ ] **Step 2: 跑 quorum 测试，确认它在未补齐汇总逻辑前失败**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_workflow_actions.py::test_glossary_multi_llm_parallel_workflow_allows_one_extractor_failure_with_quorum -q`

Expected: FAIL，常见失败形态应是 `degraded` 没有保留、`workflow_run.status` 不对，或失败 step 没被正确写回。

- [ ] **Step 3: 把 tolerant group 汇总逻辑收口成统一函数，并把现有顺序敏感断言改成稳定写法**

```python
def _summarize_tolerant_group_result(
    self,
    *,
    executions: list[Mapping[str, Any]],
    step_definitions: list[Mapping[str, Any]],
    minimum_success: int,
) -> dict[str, Any]:
    success_count = sum(1 for item in executions if item["succeeded"])
    failed_step_keys = [str(item["step_log"]["step_key"]) for item in executions if not item["succeeded"]]
    finalize_payload = None
    for item in executions:
        if item["succeeded"] and isinstance(item.get("finalize_payload"), dict):
            finalize_payload = dict(item["finalize_payload"])
    if success_count < minimum_success:
        action = str(step_definitions[0].get("action") or "<unknown>")
        error = ToolError(
            code="workflow_quorum_failed",
            message=f"workflow tolerant step group {action} 至少需要 {minimum_success} 个成功步骤，实际仅 {success_count} 个成功。",
            status=502,
        )
        setattr(error, "_workflow_step_logs", [dict(item["step_log"]) for item in executions])
        raise error
    return {
        "success_count": success_count,
        "failed_step_keys": failed_step_keys,
        "degraded": bool(failed_step_keys),
        "finalize_payload": finalize_payload,
        "step_logs": [dict(item["step_log"]) for item in executions],
    }
```

```python
step_status_map = {item.step_key: item.status for item in step_runs}
assert step_status_map["extract_primary"] == "completed"
assert step_status_map["extract_secondary"] == "completed"
assert [item.step_key for item in step_runs[2:]] == [
    "normalize_candidates",
    "review_relations",
    "review_scope",
    "finalize_terms",
]
```

- [ ] **Step 4: 跑 glossary workflow 相关目标测试，确认全部转绿**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_workflow_actions.py::test_glossary_multi_llm_workflow_executes_all_steps tests\test_workflow_actions.py::test_glossary_multi_llm_workflow_runs_extractors_in_parallel tests\test_workflow_actions.py::test_glossary_multi_llm_parallel_workflow_allows_one_extractor_failure_with_quorum -q`

Expected: PASS，至少覆盖：
- `test_glossary_multi_llm_workflow_executes_all_steps`
- `test_glossary_multi_llm_workflow_runs_extractors_in_parallel`
- `test_glossary_multi_llm_parallel_workflow_allows_one_extractor_failure_with_quorum`

- [ ] **Step 5: Commit**

```bash
git add app/services/workflow_runtime_service.py tests/test_workflow_actions.py
git commit -m "test: cover glossary parallel quorum behavior"
```

### Task 4: 做全量验证，确保 monorepo 与独立仓库模式都没被误伤

**Files:**
- Modify: `app/services/workflow_runtime_service.py`
- Modify: `app/services/glossary_pipeline_service.py`
- Modify: `tests/test_workflow_actions.py`
- Test: `tests/test_cli_smoke.py`

- [ ] **Step 1: 跑 workflow 目标集，确认没有局部脆弱点**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_workflow_actions.py tests\test_cli_smoke.py -q`

Expected: PASS

- [ ] **Step 2: 在 standalone 仓库视角跑完整工具测试**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests -q`

Expected: PASS

- [ ] **Step 3: 在 NovelT 根目录跑 monorepo 回归**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests -q`

Expected: PASS

- [ ] **Step 4: 用 `git diff --stat` 和 `git diff` 自检本轮新增改动只落在计划内文件**

Run: `git diff --stat`

Run: `git diff`

Expected: 当前工作区如果已经有早先的 README / docs 变更，不要回退它们；本轮新增的代码改动只应落在：
- `app/services/workflow_runtime_service.py`
- `app/services/glossary_pipeline_service.py`
- `tests/test_workflow_actions.py`

- [ ] **Step 5: Commit**

```bash
git add app/services/workflow_runtime_service.py app/services/glossary_pipeline_service.py tests/test_workflow_actions.py
git commit -m "feat: enable parallel glossary multi-llm execution"
```
