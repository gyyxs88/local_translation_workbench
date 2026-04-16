# Stage Inspect Runs Failure Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `stage.inspect_runs` 增加结构化 `summary` 和 failed run `diagnostics`，让 glossary / translation 的失败记录可以直接看见主失败 step、实际 profile 与 model，同时对非 workflow 失败稳定退化。

**Architecture:** 保持现有 `StageRun / WorkflowRun / WorkflowStepRun` 写入路径不变，只在读取侧增强。`ProjectQueryService.inspect_stage_runs()` 负责把 `summary` 从字符串解成对象，并仅在 failed run 上组装 `diagnostics`；`WorkflowRepository` 增加最小查询 helper，用 `stage_run_id -> request_id` 两级回退关联 workflow run，再从 failed step runs 中稳定选出第一条主失败 step。

**Tech Stack:** Python 3、SQLAlchemy ORM、pytest、CLI action router

---

## 文件结构

- Modify: `app/repositories/workflows.py`
  责任：增加 workflow run 关联 helper 和 failed step 查询 helper。
- Modify: `app/services/project_query_service.py`
  责任：把 `summary` 转成对象，并为 failed run 组装 `diagnostics`。
- Modify: `tests/test_workflow_actions.py`
  责任：给新的 repository helper 补最小单元测试。
- Modify: `tests/test_project_actions.py`
  责任：锁定 `stage.inspect_runs` 的 completed / workflow failed / non-workflow failed / multi-failed-step 行为。
- Modify: `README.md`
  责任：把 `stage.inspect_runs` 的返回口径更新为结构化 `summary + diagnostics`。
- Modify: `docs/roadmap.md`
  责任：把 `P1.4` 第一刀落地状态同步进去。
- Modify: `CHANGELOG.md`
  责任：记录 `stage.inspect_runs` 失败诊断增强已落地，并刷新回归基线。

---

### Task 1: 为 workflow 失败关联增加最小 repository helper

**Files:**
- Modify: `app/repositories/workflows.py`
- Modify: `tests/test_workflow_actions.py`
- Test: `tests/test_workflow_actions.py`

- [ ] **Step 1: 先在 `tests/test_workflow_actions.py` 写 helper 红测**

```python
def test_workflow_repository_prefers_stage_run_id_when_finding_stage_context_run(db_session) -> None:
    WorkflowProfileService(db_session).ensure_builtin_profiles()
    project = TranslationProject(
        request_id="workflow-stage-context-project",
        project_key="workflow-stage-context-project",
        source_path="source.txt",
        source_language="zh",
        target_language="en",
        status="created",
    )
    db_session.add(project)
    db_session.flush()

    repository = WorkflowRepository(db_session)
    older = repository.create_run(
        workflow_key="glossary_single_llm_v1",
        project_id=project.id,
        stage="glossary",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":1}',
        request_id="same-request-id",
        status="failed",
        summary=json.dumps(
            {"request_id": "same-request-id", "workflow_key": "glossary_single_llm_v1", "stage_run_id": 12},
            ensure_ascii=False,
        ),
    )
    repository.create_run(
        workflow_key="glossary_single_llm_v1",
        project_id=project.id,
        stage="glossary",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":1}',
        request_id="same-request-id",
        status="failed",
        summary=json.dumps(
            {"request_id": "same-request-id", "workflow_key": "glossary_single_llm_v1", "stage_run_id": 13},
            ensure_ascii=False,
        ),
    )

    matched = repository.find_latest_run_for_stage_context(
        project_id=project.id,
        stage="glossary",
        request_id="same-request-id",
        stage_run_id=12,
    )

    assert matched is not None
    assert matched.id == older.id


def test_workflow_repository_falls_back_to_request_id_when_stage_run_id_missing(db_session) -> None:
    WorkflowProfileService(db_session).ensure_builtin_profiles()
    project = TranslationProject(
        request_id="workflow-request-fallback-project",
        project_key="workflow-request-fallback-project",
        source_path="source.txt",
        source_language="zh",
        target_language="en",
        status="created",
    )
    db_session.add(project)
    db_session.flush()

    repository = WorkflowRepository(db_session)
    repository.create_run(
        workflow_key="translation_single_llm_v1",
        project_id=project.id,
        stage="translation",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":1}',
        request_id="translation-request-fallback",
        status="failed",
        summary=json.dumps({"request_id": "translation-request-fallback"}, ensure_ascii=False),
    )

    matched = repository.find_latest_run_for_stage_context(
        project_id=project.id,
        stage="translation",
        request_id="translation-request-fallback",
        stage_run_id=999,
    )

    assert matched is not None
    assert matched.request_id == "translation-request-fallback"


def test_workflow_repository_lists_failed_steps_in_id_order(db_session) -> None:
    WorkflowProfileService(db_session).ensure_builtin_profiles()
    project = TranslationProject(
        request_id="workflow-failed-steps-project",
        project_key="workflow-failed-steps-project",
        source_path="source.txt",
        source_language="zh",
        target_language="en",
        status="created",
    )
    db_session.add(project)
    db_session.flush()

    repository = WorkflowRepository(db_session)
    run = repository.create_run(
        workflow_key="translation_multi_llm_v1",
        project_id=project.id,
        stage="translation",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":1}',
        request_id="translation-failed-step-order",
        status="failed",
        summary=json.dumps({"request_id": "translation-failed-step-order"}, ensure_ascii=False),
    )
    repository.create_step_run(
        workflow_run_id=run.id,
        step_key="generate_primary",
        action="translation.generate_draft",
        llm_role="translator",
        model_profile_id="profile-a",
        status="failed",
        input_ref="segment:1",
        output_payload={"error": "primary failed"},
        summary=None,
    )
    repository.create_step_run(
        workflow_run_id=run.id,
        step_key="generate_secondary",
        action="translation.generate_draft",
        llm_role="translator",
        model_profile_id="profile-b",
        status="failed",
        input_ref="segment:1",
        output_payload={"error": "secondary failed"},
        summary=None,
    )

    failed_steps = repository.list_failed_steps_for_run(run.id)

    assert [item.step_key for item in failed_steps] == ["generate_primary", "generate_secondary"]
```

- [ ] **Step 2: 跑 helper 红测，确认方法还不存在**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_workflow_actions.py::test_workflow_repository_prefers_stage_run_id_when_finding_stage_context_run tests\test_workflow_actions.py::test_workflow_repository_falls_back_to_request_id_when_stage_run_id_missing tests\test_workflow_actions.py::test_workflow_repository_lists_failed_steps_in_id_order -q`

Expected: FAIL，报 `AttributeError: 'WorkflowRepository' object has no attribute 'find_latest_run_for_stage_context'`。

- [ ] **Step 3: 在 `app/repositories/workflows.py` 增加最小 helper**

```python
import json

from sqlalchemy import select, update
from sqlalchemy.orm import Session
```

```python
def _decode_summary_payload(self, raw_summary: str | None) -> dict[str, object] | None:
    if raw_summary is None:
        return None
    try:
        payload = json.loads(raw_summary)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def find_latest_run_for_stage_context(
    self,
    *,
    project_id: int,
    stage: str,
    request_id: str | None,
    stage_run_id: int | None,
) -> WorkflowRun | None:
    normalized_stage = stage.strip().lower()
    statement = (
        select(WorkflowRun)
        .where(WorkflowRun.project_id == project_id, WorkflowRun.stage == normalized_stage)
        .order_by(WorkflowRun.id.desc())
    )
    if request_id is not None:
        statement = statement.where(WorkflowRun.request_id == request_id.strip())

    candidates = list(self.session.execute(statement).scalars().all())
    if stage_run_id is not None:
        for item in candidates:
            summary_payload = self._decode_summary_payload(item.summary)
            if summary_payload is None:
                continue
            if int(summary_payload.get("stage_run_id") or -1) == int(stage_run_id):
                return item
    return candidates[0] if candidates else None


def list_failed_steps_for_run(self, workflow_run_id: int) -> list[WorkflowStepRun]:
    statement = (
        select(WorkflowStepRun)
        .where(
            WorkflowStepRun.workflow_run_id == workflow_run_id,
            WorkflowStepRun.status == "failed",
        )
        .order_by(WorkflowStepRun.id.asc())
    )
    return list(self.session.execute(statement).scalars().all())
```

- [ ] **Step 4: 重新跑 helper 测试，确认查询规则稳定**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_workflow_actions.py::test_workflow_repository_prefers_stage_run_id_when_finding_stage_context_run tests\test_workflow_actions.py::test_workflow_repository_falls_back_to_request_id_when_stage_run_id_missing tests\test_workflow_actions.py::test_workflow_repository_lists_failed_steps_in_id_order -q`

Expected: PASS，输出 `3 passed`。

- [ ] **Step 5: 提交 Task 1**

```bash
git add app/repositories/workflows.py tests/test_workflow_actions.py
git commit -m "test: add workflow diagnostics repository helpers"
```

### Task 2: 先把 `stage.inspect_runs` 的 `summary` 收成对象，并锁定 completed run 语义

**Files:**
- Modify: `app/services/project_query_service.py`
- Modify: `tests/test_project_actions.py`
- Test: `tests/test_project_actions.py`

- [ ] **Step 1: 把现有 `stage.inspect_runs` 用例增强为结构化 `summary` 红测**

把 `test_cli_stage_inspect_runs_returns_filtered_runs` 补成下面这些断言：

```python
run = inspect_payload["data"]["runs"][0]

assert run["stage"] == "chaptering"
assert isinstance(run["summary"], dict)
assert run["summary"]["request_id"].startswith("pytest-")
assert run["summary"]["chapter_count"] == 1
assert run["diagnostics"] is None
```

- [ ] **Step 2: 跑 completed run 红测，确认当前 `summary` 还是字符串**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_project_actions.py -k "stage_inspect_runs_returns_filtered_runs" -q`

Expected: FAIL，断言提示 `run["summary"]` 是 `str`，或者缺少 `diagnostics` 字段。

- [ ] **Step 3: 在 `ProjectQueryService.inspect_stage_runs()` 里先落结构化 `summary`**

```python
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import Chapter, ExportRun, GlossaryEntry, ReviewRun, SegmentTranslation, StageRun
from ..repositories.workflows import WorkflowRepository
```

```python
class ProjectQueryService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.projects = ProjectRepository(session)
        self.workflows = WorkflowRepository(session)
        self.idempotency = IdempotencyService(session)

    def _decode_summary_payload(self, raw_summary: str | None) -> dict[str, object] | None:
        if raw_summary is None:
            return None
        try:
            payload = json.loads(raw_summary)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None
```

```python
return {
    "project_id": project_id,
    "runs": [
        {
            "id": item.id,
            "stage": item.stage,
            "scope_type": item.scope_type,
            "status": item.status,
            "summary": self._decode_summary_payload(item.summary),
            "diagnostics": None,
        }
        for item in runs
    ],
}
```

- [ ] **Step 4: 重新跑 completed run 测试**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_project_actions.py -k "stage_inspect_runs_returns_filtered_runs" -q`

Expected: PASS，输出 `1 passed`。

- [ ] **Step 5: 提交 Task 2**

```bash
git add app/services/project_query_service.py tests/test_project_actions.py
git commit -m "feat: expose structured stage inspect summaries"
```

### Task 3: 为 failed run 增加 diagnostics，并锁定 workflow / non-workflow / 多失败 step 场景

**Files:**
- Modify: `app/services/project_query_service.py`
- Modify: `tests/test_project_actions.py`
- Test: `tests/test_project_actions.py`

- [ ] **Step 1: 在 `tests/test_project_actions.py` 追加 workflow failed、non-workflow failed、多 failed step 红测**

```python
def test_stage_inspect_runs_exposes_workflow_failed_diagnostics(
    database_url: str,
    db_session: Session,
    request_id_factory: callable,
) -> None:
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("inspect-runs-workflow-failed-project"),
        source_path="D:/inputs/source.txt",
        source_language="zh",
        target_language="en",
    )
    stage_run = StageRun(
        project_id=project.id,
        stage="translation",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":1}',
        status="failed",
        summary=json.dumps(
            {
                "request_id": "translation-failed-request",
                "model_profile_id": "profile-request",
                "workflow_key": "translation_multi_llm_v1",
                "error": {"code": "provider_error", "message": "review failed", "status": 502},
            },
            ensure_ascii=False,
        ),
    )
    db_session.add(stage_run)
    db_session.flush()

    workflow_run = WorkflowRun(
        workflow_key="translation_multi_llm_v1",
        project_id=project.id,
        stage="translation",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":1}',
        request_id="translation-failed-request",
        status="failed",
        summary=json.dumps(
            {
                "request_id": "translation-failed-request",
                "workflow_key": "translation_multi_llm_v1",
                "stage_run_id": stage_run.id,
            },
            ensure_ascii=False,
        ),
    )
    db_session.add(workflow_run)
    db_session.flush()

    db_session.add(
        WorkflowStepRun(
            workflow_run_id=workflow_run.id,
            step_key="review_drafts",
            action="translation.review_draft",
            llm_role="reviewer",
            model_profile_id="profile-review",
            status="failed",
            input_ref="segment:1",
            output_payload={"error": "review failed", "actual_model_name": "model-review"},
            summary=json.dumps({"provider_model_name": "model-review"}, ensure_ascii=False),
        )
    )
    db_session.commit()

    payload = route_action(
        {
            "action": "stage.inspect_runs",
            "project_id": str(project.id),
            "stage": "translation",
            "limit": "1",
        }
    )

    run = payload["data"]["runs"][0]
    assert run["diagnostics"]["error"]["code"] == "provider_error"
    assert run["diagnostics"]["failure_step"] == {
        "step_key": "review_drafts",
        "action": "translation.review_draft",
    }
    assert run["diagnostics"]["model_profile_id"] == "profile-review"
    assert run["diagnostics"]["model_name"] == "model-review"
```

```python
def test_stage_inspect_runs_exposes_non_workflow_failed_diagnostics(
    database_url: str,
    db_session: Session,
    request_id_factory: callable,
) -> None:
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("inspect-runs-chaptering-failed-project"),
        source_path="D:/inputs/source.txt",
        source_language="zh",
        target_language="en",
    )
    db_session.add(
        StageRun(
            project_id=project.id,
            stage="chaptering",
            scope_type="all",
            scope_value='{"type":"all"}',
            status="failed",
            summary=json.dumps(
                {
                    "request_id": "chaptering-failed-request",
                    "model_profile_id": "profile-chaptering",
                    "error": {"code": "file_not_found", "message": "找不到章节源文件", "status": 404},
                },
                ensure_ascii=False,
            ),
        )
    )
    db_session.commit()

    payload = route_action(
        {
            "action": "stage.inspect_runs",
            "project_id": str(project.id),
            "stage": "chaptering",
            "limit": "1",
        }
    )

    run = payload["data"]["runs"][0]
    assert run["diagnostics"]["error"]["code"] == "file_not_found"
    assert run["diagnostics"]["failure_step"] is None
    assert run["diagnostics"]["model_profile_id"] == "profile-chaptering"
    assert run["diagnostics"]["model_name"] is None
```

```python
def test_stage_inspect_runs_uses_first_failed_step_when_multiple_steps_failed(
    database_url: str,
    db_session: Session,
    request_id_factory: callable,
) -> None:
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("inspect-runs-multi-failed-project"),
        source_path="D:/inputs/source.txt",
        source_language="zh",
        target_language="en",
    )
    stage_run = StageRun(
        project_id=project.id,
        stage="translation",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":1}',
        status="failed",
        summary=json.dumps(
            {
                "request_id": "translation-failed-fallback-request",
                "model_profile_id": "profile-request-fallback",
                "workflow_key": "translation_multi_llm_v1",
                "error": {"code": "workflow_quorum_failed", "message": "too many failed steps", "status": 502},
            },
            ensure_ascii=False,
        ),
    )
    db_session.add(stage_run)
    db_session.flush()

    workflow_run = WorkflowRun(
        workflow_key="translation_multi_llm_v1",
        project_id=project.id,
        stage="translation",
        scope_type="chapter_range",
        scope_value='{"type":"chapter_range","start":1,"end":1}',
        request_id="translation-failed-fallback-request",
        status="failed",
        summary=json.dumps({"request_id": "translation-failed-fallback-request"}, ensure_ascii=False),
    )
    db_session.add(workflow_run)
    db_session.flush()

    db_session.add_all(
        [
            WorkflowStepRun(
                workflow_run_id=workflow_run.id,
                step_key="generate_primary",
                action="translation.generate_draft",
                llm_role="translator",
                model_profile_id="profile-primary",
                status="failed",
                input_ref="segment:1",
                output_payload={"error": "primary failed", "actual_model_name": "model-primary"},
                summary=None,
            ),
            WorkflowStepRun(
                workflow_run_id=workflow_run.id,
                step_key="generate_secondary",
                action="translation.generate_draft",
                llm_role="translator",
                model_profile_id="profile-secondary",
                status="failed",
                input_ref="segment:1",
                output_payload={"error": "secondary failed", "actual_model_name": "model-secondary"},
                summary=None,
            ),
        ]
    )
    db_session.commit()

    payload = route_action(
        {
            "action": "stage.inspect_runs",
            "project_id": str(project.id),
            "stage": "translation",
            "limit": "1",
        }
    )

    run = payload["data"]["runs"][0]
    assert run["diagnostics"]["failure_step"]["step_key"] == "generate_primary"
    assert run["diagnostics"]["model_profile_id"] == "profile-primary"
    assert run["diagnostics"]["model_name"] == "model-primary"
```

- [ ] **Step 2: 跑 failed diagnostics 红测**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_project_actions.py -k "workflow_failed_diagnostics or non_workflow_failed_diagnostics or first_failed_step" -q`

Expected: FAIL，至少会因为 `diagnostics` 仍是 `None` 或 `failure_step` 缺失而失败。

- [ ] **Step 3: 在 `ProjectQueryService` 里组装 failed run diagnostics**

```python
from ..db.models import Chapter, ExportRun, GlossaryEntry, ReviewRun, SegmentTranslation, StageRun, WorkflowStepRun
```

```python
def _build_failed_run_diagnostics(
    self,
    *,
    stage_run: StageRun,
    summary_payload: dict[str, object] | None,
) -> dict[str, object] | None:
    if stage_run.status != "failed":
        return None

    error_payload = None
    if isinstance(summary_payload, dict) and isinstance(summary_payload.get("error"), dict):
        error_payload = dict(summary_payload["error"])

    diagnostics: dict[str, object] = {
        "error": error_payload,
        "failure_step": None,
        "model_profile_id": (
            str(summary_payload.get("model_profile_id"))
            if isinstance(summary_payload, dict) and summary_payload.get("model_profile_id") is not None
            else None
        ),
        "model_name": None,
    }

    if stage_run.stage not in {"glossary", "translation"}:
        return diagnostics

    step_context = self._resolve_workflow_failure_step(stage_run=stage_run, summary_payload=summary_payload)
    if step_context is None:
        return diagnostics

    diagnostics["failure_step"] = step_context["failure_step"]
    diagnostics["model_profile_id"] = step_context.get("model_profile_id") or diagnostics["model_profile_id"]
    diagnostics["model_name"] = step_context.get("model_name")
    return diagnostics
```

```python
def _resolve_workflow_failure_step(
    self,
    *,
    stage_run: StageRun,
    summary_payload: dict[str, object] | None,
) -> dict[str, object] | None:
    request_id = None if summary_payload is None else summary_payload.get("request_id")
    workflow_run = self.workflows.find_latest_run_for_stage_context(
        project_id=stage_run.project_id,
        stage=stage_run.stage,
        request_id=None if request_id is None else str(request_id),
        stage_run_id=stage_run.id,
    )
    if workflow_run is None:
        return None

    failed_steps = self.workflows.list_failed_steps_for_run(workflow_run.id)
    if not failed_steps:
        return None

    step_run = failed_steps[0]
    output_payload = step_run.output_payload if isinstance(step_run.output_payload, dict) else {}
    step_summary = self._decode_summary_payload(step_run.summary)
    model_name = (
        output_payload.get("actual_model_name")
        or output_payload.get("provider_model_name")
        or (step_summary.get("provider_model_name") if isinstance(step_summary, dict) else None)
    )
    return {
        "failure_step": {
            "step_key": str(step_run.step_key),
            "action": str(step_run.action),
        },
        "model_profile_id": str(step_run.model_profile_id),
        "model_name": None if model_name is None else str(model_name),
    }
```

并把主循环改成：

```python
runs_payload = []
for item in runs:
    summary_payload = self._decode_summary_payload(item.summary)
    runs_payload.append(
        {
            "id": item.id,
            "stage": item.stage,
            "scope_type": item.scope_type,
            "status": item.status,
            "summary": summary_payload,
            "diagnostics": self._build_failed_run_diagnostics(
                stage_run=item,
                summary_payload=summary_payload,
            ),
        }
    )
```

- [ ] **Step 4: 重新跑 failed diagnostics 测试**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_project_actions.py -k "workflow_failed_diagnostics or non_workflow_failed_diagnostics or first_failed_step" -q`

Expected: PASS，输出 `3 passed`。

- [ ] **Step 5: 跑 `stage.inspect_runs` 相关小回归**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_project_actions.py -k "stage_inspect_runs" -q`

Expected: PASS，输出 `4 passed`。

- [ ] **Step 6: 提交 Task 3**

```bash
git add app/services/project_query_service.py tests/test_project_actions.py
git commit -m "feat: add stage inspect run failure diagnostics"
```

### Task 4: 同步文档并完成全量验证

**Files:**
- Modify: `README.md`
- Modify: `docs/roadmap.md`
- Modify: `CHANGELOG.md`
- Test: `tests/test_workflow_actions.py`
- Test: `tests/test_project_actions.py`
- Test: `tests`

- [ ] **Step 1: 更新 README、路线图和 changelog**

在 `README.md` 的 `stage.inspect_runs` 小节补成下面这个口径：

```md
### `stage.inspect_runs`

查看阶段执行记录。必填参数：

- `project_id`

可选参数：

- `stage`
- `limit`

返回结果里：

- `summary` 现在直接是对象，不再是 JSON 字符串
- failed run 会额外返回 `diagnostics`
- 当前 `diagnostics` 会包含：
  - `error`
  - `failure_step`
  - `model_profile_id`
  - `model_name`
```

在 `docs/roadmap.md` 的 `4.4 可观测性与失败恢复增强` 小节改成：

```md
### 4.4 可观测性与失败恢复增强

范围：

- 已完成第一刀：`stage.inspect_runs` 已支持结构化 `summary` 和 failed run `diagnostics`，可直接查看 `error / failure_step / model_profile_id / model_name`。
- 继续补阶段耗时、fallback 命中、resume/rerun 诊断等更完整的运行观测信息。
- 提升 inspect 和运行记录的信息密度，方便快速定位异常。
```

在 `CHANGELOG.md` 的 `Unreleased` 里补：

```md
### 新增

- `stage.inspect_runs` 已支持结构化 `summary` 和 failed run `diagnostics`，可直接查看 `error / failure_step / model_profile_id / model_name`。

### 变更

- `stage.inspect_runs` 不再返回字符串形式的 `summary`，而是直接返回对象。
- 已验证的完整回归基线刷新为 `218 passed`。
```

- [ ] **Step 2: 跑目标回归**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_workflow_actions.py tests\test_project_actions.py -q`

Expected: PASS，输出 `37 passed`。

- [ ] **Step 3: 跑完整回归**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests -q`

Expected: PASS，输出 `218 passed`。

- [ ] **Step 4: 提交 Task 4**

```bash
git add README.md docs/roadmap.md CHANGELOG.md
git commit -m "docs: record stage inspect run diagnostics"
```

## Self-Review

- Spec 覆盖检查：
  - `summary` 改成对象：Task 2
  - `diagnostics` 只覆盖 failed run：Task 2、Task 3
  - workflow stage 失败关联：Task 1、Task 3
  - non-workflow failed 退化：Task 3
  - 多 failed steps 取第一条：Task 1、Task 3
  - 文档与回归同步：Task 4
- 占位符检查：全文没有 `TODO`、`TBD`、`后续再补` 这类不可执行占位语句。
- 类型一致性检查：
  - `summary` 始终表示对象
  - `diagnostics` 始终使用 `error / failure_step / model_profile_id / model_name`
  - repository helper 命名统一为 `find_latest_run_for_stage_context` 和 `list_failed_steps_for_run`
