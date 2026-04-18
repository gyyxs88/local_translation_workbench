# P1.4 可观测性尾项收口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改 `stage.run` 即时返回、不新增 schema 的前提下，补齐 `stage.inspect_runs` 的稳定运行画像，完成 `P1.4` 尾项并为后续合并回主线做好验证准备。

**Architecture:** 这轮实现只增强 `stage.inspect_runs` 的读模型，不动运行写入契约。新增一个专用的 `StageRunInspectionService`，集中组装 `scope_value / context / result / workflow / observability / diagnostics`，让 `ProjectQueryService` 退回薄入口；所有新增能力都通过 `tests/test_project_actions.py` 锁定，避免把 `stage.run` 行为一起卷进去。

**Tech Stack:** Python 3、SQLAlchemy ORM、pytest、PowerShell CLI

---

## 文件结构

- Create: `app/services/stage_run_inspection_service.py`
  责任：集中组装 `stage.inspect_runs` 的单条 run 视图，统一读取 `StageRun.summary`、`WorkflowRun`、`WorkflowStepRun`，输出 `scope_value / context / result / workflow / observability / diagnostics`。
- Modify: `app/services/project_query_service.py`
  责任：`inspect_stage_runs()` 改为委托 `StageRunInspectionService`，只保留项目存在性校验和 run 列表查询。
- Modify: `tests/test_project_actions.py`
  责任：锁非 workflow stage 的基础运行画像，以及 translation/glossary workflow 的 step 摘要、step counts、fallback depth 与结果摘要。
- Modify: `README.md`
  责任：补 `stage.inspect_runs` 新增的 `scope_value / context / result / workflow` 说明。
- Modify: `docs/roadmap.md`
  责任：把 `P1.4` 标记为完成，并同步当前完成口径。
- Modify: `CHANGELOG.md`
  责任：记录 `stage.inspect_runs` 运行画像增强和最新测试基线。

---

### Task 1: 先补非 workflow stage 的基础运行画像

**Files:**
- Create: `app/services/stage_run_inspection_service.py`
- Modify: `app/services/project_query_service.py`
- Modify: `tests/test_project_actions.py`
- Test: `tests/test_project_actions.py`

- [ ] **Step 1: 先写非 workflow stage 的红测**

```python
def test_stage_inspect_runs_exposes_scope_context_and_result_for_non_workflow_stage(
    database_url: str,
    db_session: Session,
    request_id_factory: callable,
) -> None:
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("inspect-runs-base-view-project"),
        source_path="D:/inputs/source.txt",
        source_language="zh",
        target_language="en",
    )
    db_session.add(
        StageRun(
            project_id=project.id,
            stage="chaptering",
            scope_type="chapter_range",
            scope_value='{"type":"chapter_range","start":1,"end":2}',
            status="completed",
            summary=json.dumps(
                {
                    "request_id": "chaptering-base-view-request",
                    "model_profile_id": "profile-chaptering",
                    "chapter_count": 2,
                    "segment_count": 7,
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
    assert run["scope_value"] == {"type": "chapter_range", "start": 1, "end": 2}
    assert run["context"] == {
        "request_id": "chaptering-base-view-request",
        "model_profile_id": "profile-chaptering",
        "workflow_key": None,
        "workflow_run_id": None,
    }
    assert run["result"] == {
        "chapter_count": 2,
        "segment_count": 7,
    }
    assert run["workflow"] is None
```

- [ ] **Step 2: 跑红测，确认当前 `stage.inspect_runs` 还没有这些字段**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_project_actions.py::test_stage_inspect_runs_exposes_scope_context_and_result_for_non_workflow_stage -q`

Expected: FAIL，至少因为 `scope_value`、`context`、`result` 或 `workflow` 字段不存在而失败。

- [ ] **Step 3: 新建 `StageRunInspectionService`，先补基础字段与已有 observability/diagnostics 迁移**

```python
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import StageRun, WorkflowRun, WorkflowStepRun
from ..repositories.workflows import WorkflowRepository


class StageRunInspectionService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.workflows = WorkflowRepository(session)

    def build_stage_run_payload(self, *, stage_run: StageRun) -> dict[str, object]:
        summary_payload = self._decode_summary_payload(stage_run.summary)
        workflow_run = self._resolve_workflow_run(stage_run=stage_run, summary_payload=summary_payload)
        return {
            "id": stage_run.id,
            "stage": stage_run.stage,
            "scope_type": stage_run.scope_type,
            "scope_value": self._decode_scope_value(stage_run.scope_value),
            "status": stage_run.status,
            "summary": summary_payload,
            "context": self._build_context_payload(summary_payload=summary_payload, workflow_run=workflow_run),
            "result": self._build_result_payload(
                stage=stage_run.stage,
                summary_payload=summary_payload,
            ),
            "workflow": self._build_workflow_payload(stage=stage_run.stage, workflow_run=workflow_run),
            "observability": self._build_run_observability(
                stage_run=stage_run,
                summary_payload=summary_payload,
                workflow_run=workflow_run,
            ),
            "diagnostics": self._build_failed_run_diagnostics(
                stage_run=stage_run,
                summary_payload=summary_payload,
                workflow_run=workflow_run,
            ),
        }

    def _decode_scope_value(self, raw_scope_value: str | None) -> dict[str, object] | None:
        if raw_scope_value is None:
            return None
        try:
            payload = json.loads(raw_scope_value)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _build_context_payload(
        self,
        *,
        summary_payload: dict[str, object] | None,
        workflow_run: WorkflowRun | None,
    ) -> dict[str, object]:
        return {
            "request_id": None if not isinstance(summary_payload, dict) else summary_payload.get("request_id"),
            "model_profile_id": None if not isinstance(summary_payload, dict) else summary_payload.get("model_profile_id"),
            "workflow_key": (
                None
                if workflow_run is None
                else str(workflow_run.workflow_key)
            ),
            "workflow_run_id": None if workflow_run is None else int(workflow_run.id),
        }

    def _build_result_payload(self, *, stage: str, summary_payload: dict[str, object] | None) -> dict[str, object] | None:
        if not isinstance(summary_payload, dict):
            return None
        if stage == "chaptering":
            return {
                "chapter_count": self._read_optional_int(summary_payload.get("chapter_count")) or 0,
                "segment_count": self._read_optional_int(summary_payload.get("segment_count")) or 0,
            }
        return None
```

```python
class ProjectQueryService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.projects = ProjectRepository(session)
        self.workflows = WorkflowRepository(session)
        self.idempotency = IdempotencyService(session)
        self.stage_runs = StageRunInspectionService(session)

    def inspect_stage_runs(
        self,
        *,
        project_id: int,
        stage: str | None = None,
        limit: int = 20,
    ) -> dict[str, object]:
        project = self.projects.get_by_id(project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)

        normalized_limit = max(1, min(limit, 200))
        statement = select(StageRun).where(StageRun.project_id == project_id)
        if stage:
            statement = statement.where(StageRun.stage == stage.strip().lower())
        statement = statement.order_by(StageRun.id.desc()).limit(normalized_limit)

        runs = list(self.session.execute(statement).scalars().all())
        return {
            "project_id": project_id,
            "runs": [self.stage_runs.build_stage_run_payload(stage_run=item) for item in runs],
        }
```

- [ ] **Step 4: 跑定点测试，确认基础运行画像已经返回**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_project_actions.py::test_stage_inspect_runs_exposes_scope_context_and_result_for_non_workflow_stage -q`

Expected: PASS，输出 `1 passed`。

- [ ] **Step 5: Commit**

```bash
git add app/services/stage_run_inspection_service.py app/services/project_query_service.py tests/test_project_actions.py
git commit -m "feat: add stage run base inspection view"
```

---

### Task 2: 补 glossary / translation 的 workflow 级摘要与结果收口

**Files:**
- Modify: `app/services/stage_run_inspection_service.py`
- Modify: `tests/test_project_actions.py`
- Test: `tests/test_project_actions.py`

- [ ] **Step 1: 先写 workflow 摘要红测**

```python
def test_stage_inspect_runs_exposes_workflow_summary_for_translation_runs(
    database_url: str,
    db_session: Session,
    request_id_factory: callable,
) -> None:
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("inspect-runs-workflow-summary-project"),
        source_path="D:/inputs/source.txt",
        source_language="zh",
        target_language="en",
    )
    stage_run = StageRun(
        project_id=project.id,
        stage="translation",
        scope_type="chapter_list",
        scope_value='{"type":"chapter_list","chapters":[1,2]}',
        status="completed",
        summary=json.dumps(
            {
                "request_id": "translation-workflow-summary-request",
                "model_profile_id": "profile-translation",
                "workflow_key": "translation_multi_llm_v1",
                "translated_segments": 5,
                "active_version_ids": [11, 12, 13, 14, 15],
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
        scope_type="chapter_list",
        scope_value='{"type":"chapter_list","chapters":[1,2]}',
        request_id="translation-workflow-summary-request",
        status="completed",
        summary=json.dumps(
            {
                "request_id": "translation-workflow-summary-request",
                "stage_run_id": stage_run.id,
            },
            ensure_ascii=False,
        ),
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
                status="completed",
                input_ref="segment:1",
                output_payload={"fallback_depth": 1, "actual_model_name": "model-primary"},
                summary=None,
            ),
            WorkflowStepRun(
                workflow_run_id=workflow_run.id,
                step_key="review_drafts",
                action="translation.review_draft",
                llm_role="reviewer",
                model_profile_id="profile-review",
                status="running",
                input_ref="segment:1",
                output_payload=None,
                summary=json.dumps({"provider_model_name": "model-review"}, ensure_ascii=False),
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
    assert run["context"] == {
        "request_id": "translation-workflow-summary-request",
        "model_profile_id": "profile-translation",
        "workflow_key": "translation_multi_llm_v1",
        "workflow_run_id": workflow_run.id,
    }
    assert run["result"] == {
        "translated_segments": 5,
        "active_version_count": 5,
    }
    assert run["workflow"]["id"] == workflow_run.id
    assert run["workflow"]["step_counts"] == {
        "total": 2,
        "completed": 1,
        "failed": 0,
        "running": 1,
    }
    assert run["workflow"]["steps"][0]["fallback_depth"] == 1
    assert run["workflow"]["steps"][0]["actual_model_name"] == "model-primary"
    assert run["workflow"]["steps"][1]["actual_model_name"] == "model-review"
```

```python
def test_stage_inspect_runs_keeps_diagnostics_and_workflow_view_together_for_failed_translation_run(
    database_url: str,
    db_session: Session,
    request_id_factory: callable,
) -> None:
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("inspect-runs-failed-workflow-view-project"),
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
                "request_id": "translation-failed-workflow-view-request",
                "model_profile_id": "profile-request-failed",
                "workflow_key": "translation_multi_llm_v1",
                "error": {"code": "provider_error", "message": "rewrite failed", "status": 502},
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
        request_id="translation-failed-workflow-view-request",
        status="failed",
        summary=json.dumps({"request_id": "translation-failed-workflow-view-request", "stage_run_id": stage_run.id}, ensure_ascii=False),
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
                status="completed",
                input_ref="segment:1",
                output_payload={"fallback_depth": 1, "actual_model_name": "model-primary"},
                summary=None,
            ),
            WorkflowStepRun(
                workflow_run_id=workflow_run.id,
                step_key="rewrite_consensus",
                action="translation.rewrite_draft",
                llm_role="translator",
                model_profile_id="profile-rewrite",
                status="failed",
                input_ref="segment:1",
                output_payload={"actual_model_name": "model-rewrite"},
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
    assert run["diagnostics"]["failure_step"] == {
        "step_key": "rewrite_consensus",
        "action": "translation.rewrite_draft",
    }
    assert run["workflow"]["status"] == "failed"
    assert run["workflow"]["step_counts"] == {
        "total": 2,
        "completed": 1,
        "failed": 1,
        "running": 0,
    }
    assert [step["step_key"] for step in run["workflow"]["steps"]] == [
        "generate_primary",
        "rewrite_consensus",
    ]
```

- [ ] **Step 2: 跑红测，确认当前 workflow 级摘要还不存在**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_project_actions.py -k "workflow_summary_for_translation_runs or keeps_diagnostics_and_workflow_view_together" -q`

Expected: FAIL，至少因为 `context.workflow_run_id`、`result` 或 `workflow` 字段不存在而失败。

- [ ] **Step 3: 扩 `StageRunInspectionService`，补 result/workflow 组装**

```python
class StageRunInspectionService:
    def _build_result_payload(self, *, stage: str, summary_payload: dict[str, object] | None) -> dict[str, object] | None:
        if not isinstance(summary_payload, dict):
            return None
        if stage == "chaptering":
            return {
                "chapter_count": self._read_optional_int(summary_payload.get("chapter_count")) or 0,
                "segment_count": self._read_optional_int(summary_payload.get("segment_count")) or 0,
            }
        if stage == "glossary":
            return {
                "candidate_count": self._read_optional_int(summary_payload.get("candidate_count")) or 0,
            }
        if stage == "translation":
            active_version_ids = summary_payload.get("active_version_ids")
            active_version_count = len(active_version_ids) if isinstance(active_version_ids, list) else 0
            return {
                "translated_segments": self._read_optional_int(summary_payload.get("translated_segments")) or 0,
                "active_version_count": active_version_count,
            }
        if stage == "review":
            return {
                "issue_count": self._read_optional_int(summary_payload.get("issue_count")) or 0,
                "review_run_id": self._read_optional_int(summary_payload.get("run_id")),
            }
        if stage == "export":
            return {
                "artifact_count": self._read_optional_int(summary_payload.get("artifact_count")) or 0,
                "export_run_id": self._read_optional_int(summary_payload.get("run_id")),
                "manifest_path": summary_payload.get("manifest_path"),
            }
        return None

    def _build_workflow_payload(self, *, stage: str, workflow_run: WorkflowRun | None) -> dict[str, object] | None:
        if workflow_run is None or stage not in {"glossary", "translation"}:
            return None

        step_rows = list(
            self.session.execute(
                select(WorkflowStepRun)
                .where(WorkflowStepRun.workflow_run_id == workflow_run.id)
                .order_by(WorkflowStepRun.id.asc())
            ).scalars().all()
        )
        steps = [
            {
                "step_run_id": int(step.id),
                "step_key": str(step.step_key),
                "action": str(step.action),
                "llm_role": str(step.llm_role),
                "model_profile_id": str(step.model_profile_id),
                "status": str(step.status),
                "fallback_depth": self._read_fallback_depth(step.output_payload)
                or self._read_fallback_depth(self._decode_summary_payload(step.summary)),
                "actual_model_name": self._resolve_step_actual_model_name(step),
            }
            for step in step_rows
        ]
        return {
            "id": int(workflow_run.id),
            "workflow_key": str(workflow_run.workflow_key),
            "status": str(workflow_run.status),
            "step_counts": {
                "total": len(step_rows),
                "completed": sum(1 for step in step_rows if step.status == "completed"),
                "failed": sum(1 for step in step_rows if step.status == "failed"),
                "running": sum(1 for step in step_rows if step.status == "running"),
            },
            "steps": steps,
        }

    def _resolve_step_actual_model_name(self, step_run: WorkflowStepRun) -> str | None:
        output_payload = step_run.output_payload if isinstance(step_run.output_payload, dict) else {}
        summary_payload = self._decode_summary_payload(step_run.summary)
        for candidate in (
            output_payload.get("actual_model_name"),
            output_payload.get("provider_model_name"),
            None if not isinstance(summary_payload, dict) else summary_payload.get("provider_model_name"),
        ):
            if candidate not in {None, ""}:
                return str(candidate)
        return None
```

- [ ] **Step 4: 跑定点测试，确认 workflow 级摘要与诊断共存**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_project_actions.py -k "workflow_summary_for_translation_runs or keeps_diagnostics_and_workflow_view_together" -q`

Expected: PASS，输出 `2 passed`。

- [ ] **Step 5: 跑 `stage.inspect_runs` 全部定向回归**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_project_actions.py -k "inspect_runs" -q`

Expected: PASS，所有 `inspect_runs` 相关测试都通过。

- [ ] **Step 6: Commit**

```bash
git add app/services/stage_run_inspection_service.py app/services/project_query_service.py tests/test_project_actions.py
git commit -m "feat: enrich stage inspect runs observability view"
```

---

### Task 3: 同步文档、跑整体验证并准备回主线

**Files:**
- Modify: `README.md`
- Modify: `docs/roadmap.md`
- Modify: `CHANGELOG.md`
- Test: `tests/test_project_actions.py`
- Test: `tests/test_stage_resume_and_conflict.py`
- Test: `tests`

- [ ] **Step 1: 更新 README、路线图和变更记录**

```md
README:
- `stage.inspect_runs` 新增 `scope_value / context / result / workflow`
- `workflow` 只对 `glossary / translation` 返回

roadmap:
- `P1.4` 标记为完成
- 当前完成口径明确覆盖 failed diagnostics、timing/recovery/fallback、稳定运行画像

CHANGELOG:
- 记录 `stage.inspect_runs` 运行画像增强
- 刷新最新全量回归基线
```

- [ ] **Step 2: 跑 `stage.inspect_runs` 相关层级回归**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests\test_project_actions.py tests\test_stage_resume_and_conflict.py -q`

Expected: PASS。

- [ ] **Step 3: 跑完整回归**

Run: `D:\Project\NovelT\.venv\Scripts\python.exe -m pytest tests -q`

Expected: PASS，记录最新完整基线。

- [ ] **Step 4: Commit**

```bash
git add README.md docs/roadmap.md CHANGELOG.md
git commit -m "docs: record P1.4 observability tail rollout"
```

- [ ] **Step 5: 合并回主线前检查**

Run:

```bash
git status --short
git log --oneline -6
```

Expected:

- 工作区干净
- 最近提交顺序清晰，包含 spec、plan、实现、文档

---

## 自检

- spec 覆盖：
  - `scope_value`、`context`、`result`、`workflow` 都有独立任务覆盖
  - 保留 `summary / observability / diagnostics` 的边界在 Task 1/2 中体现
  - 非 workflow stage 与 workflow stage 都有红绿测试
- 无占位符：
  - 所有任务都给出明确文件、测试名、命令和 commit 信息
- 命名一致：
  - 统一使用 `scope_value / context / result / workflow / workflow_run_id / active_version_count / step_counts`
