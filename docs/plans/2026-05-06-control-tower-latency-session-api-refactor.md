# 33income Control Tower Latency / Session Adhesion API Boundary Note (Phase 1)

## Scope
- This document is **read-only architecture guidance** for Phase 1.
- Runtime/session behavior changes are **out of scope** in Phase 1~2.
- Ticket 3~6, granular route implementation, runner cadence changes, session preflight/runtime behavior changes require separate approval.

## Current command flow (as-is)
1. UI or API enqueue: `POST /api/bots/{bot_id}/commands` or dashboard UI wrapper.
2. Command row inserted into `commands` with `status='pending'` and `created_at`.
3. Agent polls: `GET /api/agents/{pc_id}/commands/poll`.
4. Pending commands for that PC transition to `running` with `picked_at`.
5. Agent completes via `POST /api/commands/{id}/complete`, setting `status`, `finished_at`, `error_message`.
6. Dashboard/API read model is generated from `bots` + `commands` joins (`/`, `/api/bots`, `/api/summary`).

## Current session path (as-is)
- Session-relevant commands currently include `open_login`, `fill_login`, `login_done`, `refresh_page`.
- Heartbeat pipeline: `POST /api/agents/heartbeat` writes
  - agent liveness (`agents.last_heartbeat_at`, repo/version metadata),
  - bot liveness/status (`bots.status`, `bots.current_step`, `bots.last_heartbeat_at`).
- Existing bot status/current_step values are propagated to dashboard and `/api/bots` as session-observable state.
- Runtime login/session probe methods (e.g., `inspect_login_state`) and browser refresh logic are intentionally unchanged in Phase 1~2.

## Cohesive boundaries (target design)

### 1) `CommandQueue` boundary
Responsibility:
- enqueue/poll/complete lifecycle
- assignment and ordering guarantees (`pending -> running -> done|failed`)
- command payload persistence and compatibility

Must not absorb:
- latency analytics policy,
- session adhesion scoring logic,
- workflow-specific request parsing.

### 2) `CommandMetrics` boundary
Responsibility:
- read-only latency fields from existing timestamps
  - `queue_latency_ms = picked_at - created_at`
  - `execution_latency_ms = finished_at - picked_at`
- dashboard/API read fields:
  - `last_command_queue_latency_ms`
  - `last_command_execution_latency_ms`
  - `heartbeat_age_seconds`
- aggregate read model (p95/max) from recent completed commands

Must not change:
- command state machine,
- queue ordering,
- runtime polling cadence.

### 3) `SessionAdhesion` boundary
Responsibility:
- typed read model for session health/freshness/affinity (future tickets)
- model-only exposure first, behavior changes later via approval gate

Phase 1~2 status:
- only document contract and acceptance metrics,
- no runtime preflight/retry mutation.

### 4) `WorkflowCommands` boundary
Responsibility:
- sender/reporter use-case input shaping,
- backward-compatible wrappers over existing enqueue API,
- domain-scoped payload builders (not god utility).

Phase 1~2 status:
- no granular route rollout yet,
- keep existing endpoints as source of truth.

## Backward-compatible wrapper policy
1. Keep existing endpoints stable:
   - `POST /api/bots/{bot_id}/commands`
   - `POST /api/commands/{id}/complete`
   - existing dashboard UI actions and columns
2. New read fields are additive only; existing response keys remain intact.
3. Any future granular route is introduced as alias/wrapper first, with parity tests proving equivalent queue rows/payloads.
4. No deletion of old routes until caller migration + approval.

## Acceptance criteria (Phase 1~2)

### Latency metrics
- Per-command read fields populate when timestamps exist:
  - `queue_latency_ms` when `picked_at` exists
  - `execution_latency_ms` when `picked_at` and `finished_at` exist
- Per-bot read fields are available on `/api/bots` and visible on dashboard:
  - `last_command_queue_latency_ms`
  - `last_command_execution_latency_ms`
  - `heartbeat_age_seconds`
- Aggregate summary read model includes recent completed-command p95/max for queue/execution latency.

### Session adhesion observability (read-only in Phase 1~2)
- Existing heartbeat-driven `status/current_step/last_heartbeat_at` remains visible and unchanged.
- No session runtime behavior modification (no preflight/retry/cadence changes).

### Compatibility and safety
- Command status transitions and assignment order are unchanged.
- Existing API/UI fields and behavior stay compatible.
- All new metrics are additive/read-only and HTML-escaped in dashboard rendering.

## Verification checklist for Phase 1~2
- `python -m compileall -q src tests`
- `PYTHONPATH=src pytest -q tests/test_control_tower_api.py -k "latency or heartbeat or command"`
- `PYTHONPATH=src pytest -q tests/test_control_tower_api.py tests/test_agent_runner.py tests/test_browser_control.py tests/test_config.py`

## Explicit non-goals
- No Ticket 3~6 execution.
- No granular route runtime rollout.
- No runner poll cadence split.
- No session preflight or NewTA retry behavior changes.
- No deploy/restart/commit/push without review authorization.
