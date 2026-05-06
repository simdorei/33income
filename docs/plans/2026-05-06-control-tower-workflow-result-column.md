# Control Tower Workflow Result Column Plan

> **For Hermes:** hand this to Codex/Hephaistos as a small Control Tower-only correction. Do not touch agent runner, browser/CDP/NewTA workflow code, heartbeat scheduling, stop/retry semantics, commit, push, or deploy without a separate Hermes review gate.

## Goal
Show the latest sender/reporting workflow result in a separate dashboard/API column, while leaving repeating heartbeat/current_step updates exactly as they are.

## Architecture
Control Tower already stores command completion state in the `commands` table (`command`, `status`, `finished_at`, `error_message`). Use that as the source of truth and render a separate `last_workflow_result` / `last_workflow_*` column in `/api/bots` and the dashboard. Do not make heartbeat responsible for result display, and do not modify agent code just to change the Control Tower screen.

## Tech Stack
Python, FastAPI/TestClient, SQLite, existing `Database`, `ControlTowerService`, and dashboard HTML renderer.

## Explicit In Scope
- Control Tower-only files:
  - `src/income33/db.py`
  - `src/income33/control_tower/service.py`
  - `src/income33/control_tower/dashboard.py`
  - `tests/test_control_tower_api.py`
- Add/adjust `/api/bots` fields for latest workflow command result.
- Add one dashboard table column separate from `last_heartbeat_at` and `current_step`.
- Use completed command records with `status IN ('done', 'failed')` and `finished_at` ordering.
- Filter to actual sender/reporting workflow commands, not heartbeat/status/login/control commands.

## Explicit Out of Scope
- No changes to `src/income33/agent/*`.
- No browser/CDP/NewTA request changes.
- No heartbeat interval/scheduler/current_step behavior changes.
- No stop priority, command FIFO, retry, repeat schedule, or cancellation changes.
- No live 발송/신고 execution.
- No commit/push/deploy in this task.

## Important Design Decision
Do **not** use `commands.id DESC` as the latest-result definition. That picks the most recently queued completed command, not the most recently finished command.

Use:

```sql
ORDER BY c2.finished_at DESC, c2.id DESC
```

Only include rows where:

```sql
c2.status IN ('done', 'failed')
AND c2.finished_at IS NOT NULL
AND c2.command IN (...workflow result command allowlist...)
```

Recommended workflow-result allowlist:

```python
WORKFLOW_RESULT_COMMANDS = {
    "send_expected_tax_amounts",
    "send_simple_expense_rate_expected_tax_amounts",
    "send_bookkeeping_expected_tax_amount",
    "send_rate_based_bookkeeping_expected_tax_amount",
    "send_rate_based_bookkeeping_expected_tax_amounts",
    "submit_tax_reports",
}
```

Rationale: `status`, `open_login`, `login_done`, `fill_login`, `refresh_page`, `stop`, `restart`, and preview/auth/control commands should not overwrite the operator-facing 발송/신고 result column.

## Task 1: Fix the latest workflow result query

**Objective:** `/api/bots` should return the most recently finished sender/reporting workflow result per bot.

**Files:**
- Modify: `src/income33/db.py`
- Test: `tests/test_control_tower_api.py`

**Implementation notes:**
- Keep `list_bots(bot_type=None)` as the only query surface if possible.
- Add a module-level or class-level allowlist for workflow result commands.
- Join the latest matching command by `finished_at DESC, id DESC`.
- Keep parameterized SQL for `bot_type`; the allowlist may be embedded as static placeholders/tuple, not user input.
- Expose fields:
  - `last_workflow_command_name`
  - `last_workflow_command_status`
  - `last_workflow_finished_at`
  - `last_workflow_error_message`

**Acceptance criteria:**
- A later-finished command wins even when it has a lower `id`.
- A non-workflow command completed later does not replace the last sender/reporting result.
- Bots with no completed workflow result show `None`/empty fields, not heartbeat text.

## Task 2: Format a separate dashboard/API result string

**Objective:** Operators see a compact result value in a separate column, not mixed into heartbeat/current_step.

**Files:**
- Modify: `src/income33/control_tower/service.py`
- Modify: `src/income33/control_tower/dashboard.py`
- Test: `tests/test_control_tower_api.py`

**Implementation notes:**
- Add formatter such as `_format_last_workflow_result(bot)`.
- Suggested output:
  - done: `done: send_expected_tax_amounts @ 2026-...`
  - failed: `failed: submit_tax_reports @ 2026-... (redacted/truncated error)`
- Do not read from `last_heartbeat_at` or `current_step`.
- Dashboard column name should be clear, for example `last_workflow_result` or Korean label if table supports labels later.
- Existing `last_heartbeat_at` column remains unchanged and visible.

**Acceptance criteria:**
- Dashboard contains both `last_workflow_result` and `last_heartbeat_at`.
- Heartbeat/status text can keep updating without overwriting the workflow result.
- Failure messages are HTML-escaped by the existing table renderer and should be reasonably truncated if a long traceback is supplied.

## Task 3: Add regression tests for the blocker found in review

**Objective:** Prevent the `id DESC` bug from returning.

**Files:**
- Modify: `tests/test_control_tower_api.py`

**Required tests:**
1. `test_api_bots_last_workflow_result_uses_finished_at_not_command_id`
   - Queue command A first, command B second.
   - Complete B first.
   - Complete A later.
   - Assert `/api/bots` shows A as latest result.
2. `test_api_bots_last_workflow_result_ignores_non_workflow_command`
   - Complete `send_expected_tax_amounts`.
   - Complete `status` or `open_login` later.
   - Assert workflow result still shows `send_expected_tax_amounts`.
3. `test_dashboard_shows_failed_workflow_error_in_separate_column`
   - Complete `submit_tax_reports` or sender workflow as `failed` with an error message.
   - Assert dashboard shows failed result in result column.
   - Assert `last_heartbeat_at` is still present separately.
4. Existing happy-path test can stay, but should assert `last_workflow_finished_at` too.

## Task 4: Verification

Run from `/home/ubuntu/33income`:

```bash
python -m compileall -q src
PYTHONPATH=src pytest -q tests/test_control_tower_api.py
PYTHONPATH=src pytest -q
ruff check src/income33/db.py src/income33/control_tower/service.py src/income33/control_tower/dashboard.py tests/test_control_tower_api.py
git diff --check
```

Expected:
- targeted Control Tower tests pass
- full pytest pass
- ruff pass
- diff check pass

## Done Criteria
- `/api/bots` exposes workflow-result fields separate from heartbeat fields.
- Dashboard shows a separate workflow result column.
- Repeating heartbeat/current_step behavior is untouched.
- Latest result is selected by `finished_at DESC, id DESC`, not `id DESC` alone.
- Non-workflow control commands do not overwrite the sender/reporting result column.
- No agent/browser/CDP/NewTA/stop/retry changes are present in the diff.
- Tests cover done, failed, out-of-order completion, and non-workflow command ignore cases.
