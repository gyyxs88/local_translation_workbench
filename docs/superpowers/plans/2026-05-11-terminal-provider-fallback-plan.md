# Terminal Provider Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增独立终端兜底层，让普通 provider fallback 链全部失败后固定进入单独维护的终端兜底链。

**Architecture:** 新增 `ltw_terminal_fallback_profiles` 配置表和仓储/service/action。`ProviderResolutionService` 先展开普通 profile fallback 链，再追加 active terminal fallback 链，并在候选、attempts、结果元数据中标记 `chain_role` 与 `terminal_fallback_used`。

**Tech Stack:** Python, SQLAlchemy ORM, Alembic, pytest, 现有 PowerShell CLI/action router。

---

### Task 1: Schema And Repository

**Files:**
- Modify: `app/db/models.py`
- Modify: `app/repositories/provider_profiles.py`
- Create: `migrations/versions/0025_terminal_fallback_profiles.py`
- Test: `tests/test_provider_profile_actions.py`

- [ ] **Step 1: Write failing repository/action tests**

Add tests that create three profiles, call `ProviderProfileService.set_terminal_fallbacks(...)`, inspect the chain, and clear it. Assert ordered dedupe and persisted rows.

- [ ] **Step 2: Run the failing tests**

Run: `.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_provider_profile_actions.py -q`

Expected: FAIL because terminal fallback service methods and model do not exist.

- [ ] **Step 3: Add model and migration**

Add `TerminalFallbackProfile` to `models.py` with `profile_key`, `position`, `status`, `note`, timestamps, and uniqueness on `profile_key`. Add Alembic revision `0025_terminal_fallback_profiles` with `down_revision = "0024_agent_primitives"`.

- [ ] **Step 4: Add repository helpers**

Add helpers to list active terminal fallback rows, replace the chain, clear the chain, and fetch provider/profile metadata for inspect output.

- [ ] **Step 5: Run the tests**

Run the same pytest command. Expected: repository-level failures move to missing service methods.

### Task 2: Service And Actions

**Files:**
- Modify: `app/services/provider_profile_service.py`
- Modify: `app/action_handlers/provider_handlers.py`
- Modify: `app/cli.py`
- Modify: `TOOL.json`
- Test: `tests/test_provider_profile_actions.py`

- [ ] **Step 1: Write failing service and CLI tests**

Add tests for:

- `profile.terminal_fallback_set`
- `profile.terminal_fallback_inspect`
- `profile.terminal_fallback_clear`
- rejection of missing profile keys

- [ ] **Step 2: Run the failing tests**

Run: `.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_provider_profile_actions.py -q`

Expected: FAIL because action handlers are not registered.

- [ ] **Step 3: Implement service methods**

Add:

- `set_terminal_fallbacks(fallback_profile_keys, note=None)`
- `inspect_terminal_fallbacks()`
- `clear_terminal_fallbacks()`

Normalize by trimming, rejecting empty keys, deduping, and requiring every profile to exist.

- [ ] **Step 4: Register actions and CLI argument aliases**

Add handler registration and help text. Reuse existing `fallback_profile_keys_json` parsing and `note`.

- [ ] **Step 5: Run the tests**

Run the same pytest command. Expected: new action tests pass.

### Task 3: Runtime Resolution And Observability

**Files:**
- Modify: `app/providers/base.py`
- Modify: `app/services/provider_resolution_service.py`
- Modify: `app/providers/router.py`
- Modify: `app/services/workflow_step_executor_service.py`
- Test: `tests/test_provider_resolution_service.py`
- Test: `tests/test_provider_profile_actions.py`

- [ ] **Step 1: Write failing resolution tests**

Add tests proving:

- ordinary recursive fallback still expands first;
- terminal fallback profiles append after ordinary chain;
- duplicate terminal profile already present in ordinary chain is skipped;
- terminal fallback success returns `chain_role="terminal_fallback"` and `terminal_fallback_used=True`;
- failed attempts include `chain_role`.

- [ ] **Step 2: Run failing tests**

Run: `.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_provider_resolution_service.py -q`

Expected: FAIL because candidates have no `chain_role` and terminal rows are ignored.

- [ ] **Step 3: Extend provider result metadata**

Add optional fields to `TextGenerationResult`:

- `chain_role: str = "primary"`
- `terminal_fallback_used: bool = False`

- [ ] **Step 4: Extend candidate resolution**

Add `chain_role` to `ResolvedProviderCandidate`. Build normal candidates as `primary` for depth 0 and `normal_fallback` for later ordinary profiles. Append terminal candidates as `terminal_fallback`.

- [ ] **Step 5: Extend failover execution**

Set `chain_role` and `terminal_fallback_used` on successful `TextGenerationResult`. Add `chain_role` to every failed attempt.

- [ ] **Step 6: Extend health check**

Return `chain_role` per attempt and `terminal_fallback_used` at top level.

- [ ] **Step 7: Run resolution tests**

Run the same pytest command. Expected: pass.

### Task 4: Workflow Payload Propagation

**Files:**
- Modify: `app/services/glossary_service.py`
- Modify: `app/services/translation_workflow_execution_service.py`
- Modify: `app/services/translation_workflow_payload_service.py`
- Modify: `app/services/review_quality_loop_service.py`
- Test: focused existing workflow tests if needed

- [ ] **Step 1: Write failing payload tests**

Add focused assertions where provider stubs return `TextGenerationResult(chain_role="terminal_fallback", terminal_fallback_used=True)`, and verify output payload keeps those fields.

- [ ] **Step 2: Run failing tests**

Run the focused tests. Expected: FAIL because payloads currently preserve only profile/model/fallback depth.

- [ ] **Step 3: Propagate metadata**

Whenever a provider result is converted to a step payload or evidence payload, include:

- `chain_role`
- `terminal_fallback_used`

For aggregated payloads, set `terminal_fallback_used=True` if any segment used it, and include `chain_roles`.

- [ ] **Step 4: Run focused tests**

Expected: pass.

### Task 5: Documentation And Regression

**Files:**
- Modify: `README.md`
- Modify: `docs/operations/setup.md`
- Modify: `docs/operations/provider-smoke.md`
- Modify: `docs/operations/troubleshooting.md`
- Modify: `TOOL.json`

- [ ] **Step 1: Update Chinese docs**

Document difference between ordinary fallback and terminal fallback, action usage, health check behavior, and troubleshooting.

- [ ] **Step 2: Run targeted tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests/test_provider_profile_actions.py tools/local_translation_workbench/tests/test_provider_resolution_service.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full regression when database is available**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/local_translation_workbench/tests -q
```

Expected: PASS. If `LTW_TEST_DATABASE_URL` is missing, report that full regression is blocked by environment.
