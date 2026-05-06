# 티켓 전용 운영중계/검수 게이트 패치 계획

> **For Hermes/Codex:** Use subagent-driven-development skill to implement this plan task-by-task. This ticket intentionally excludes the rejected latency/session-adhesion implementation scope.

## Goal

33income 작업을 코드 수정 전에 완성도 높은 티켓으로 고정하고, 사고/완료/진행 이벤트를 안전하게 요약해 1분 단위 운영중계와 코드담당 검수 요청 패킷을 만들 수 있게 한다.

## Architecture

Add a ticket template + validator, add sanitized control-tower operation events using the existing SQLite/runtime surfaces, provide a one-shot relay packet generator that external schedulers/Hermes can run every 60 seconds, and provide a review-handoff generator. The repo produces safe structured packets; actual Discord delivery remains outside this repo unless separately approved.

## Tech Stack

Python 3.11, FastAPI, SQLite, pytest, Windows batch/Task Scheduler documentation.

---

## Explicit In Scope

- Ticket template and local validator for future implementation requests.
- Sanitized `bot_events` insert/list helpers on existing control-tower paths.
- Read-only recent-events API/CLI, including stable event `id` exposure for `since_id` polling.
- One-shot relay packet generation with local dedupe state only.
- Review-handoff packet generation for code 담당 검수요청.
- Windows-first runbook and dry-run/test-only verification.

---

## Explicit Out of Scope

Do **not** implement any of the following in this ticket:

- Runner polling/heartbeat interval changes.
- Control-tower latency/SLO metrics such as queue→pick p95 or dashboard heartbeat-age latency widgets.
- Session preflight/session adhesion/CDP recovery behavior changes.
- Automatic retry of NewTA state-changing operations after timeout/context-destroyed errors, including POST/PUT/send/submit/correction/auth-code flows.
- `stop` priority, active-command clearing, stop queue dedupe, or any reintroduction of reverted commit `5486020 fix: prioritize stop control commands`.
- Linux `systemd` service/timer files as the primary ops path. 33income runtime is Windows-first; systemd may be a future optional appendix only.
- Live NewTA submit/send actions, real Discord API sending, secrets handling, or credential storage.

Current repo baseline before implementation must be verified as:

```bash
cd /home/ubuntu/33income
git status --short --branch
git log -1 --oneline --decorate
git ls-remote origin refs/heads/main
```

Expected at ticket creation time: `6695d0c Revert "fix: prioritize stop control commands"` on `main == origin/main`.

---

## Inputs/Outputs

**Inputs:** markdown ticket paths, existing control-tower command/bot event state, optional local control-tower API URL or explicit SQLite DB path for dry-run tests, and local relay state path.

**Outputs:** validator exit code/messages, sanitized event rows, bounded `/api/ops/events` JSON, copy/paste-safe relay packets, copy/paste-safe review-handoff packets, and Windows-first runbook text.

No output may contain auth codes, passwords, cookies, tokens, Authorization headers, connection strings, raw request/response headers/bodies, or raw Discord IDs unless supplied as display text by the operator.

## Failure Modes

- Missing required ticket section -> validator/review-handoff exits nonzero.
- Malformed `payload_json` or unexpected event payload -> event reader returns sanitized fallback fields rather than raw dumps.
- Event insert/list helper failure -> command queue/complete semantics must remain unchanged; implementation should fail safe or log a short sanitized warning.
- `/api/ops/events` invalid `since_id`/`limit` -> bounded validation error or safe default; never unbounded list.
- Relay state file unavailable -> emit a clear sanitized local error and avoid duplicate network side effects, because the worker must not call Discord.

## Security/Secrets Notes

- Redaction must run before data is written to DB events, logs, API responses, CLI output, relay packets, or review-handoff packets.
- Treat raw request/response headers and bodies as secret-bearing by default.
- Do not read `.env` secrets, browser profiles, cookies, Discord tokens, NewTA credentials, or captured headers for this ticket.
- Tests must use synthetic secret-like strings and temp paths only.

## Rollback Plan

- Disable or stop the external Windows Task Scheduler/manual loop that invokes the one-shot relay worker.
- Delete or ignore the local relay dedupe state file.
- Leave historical sanitized `bot_events` rows in place; do not perform destructive DB schema rollback unless separately approved.
- Revert the implementation commit only after Hermes xhigh review if code was already committed later under a separate approval gate.

## Risks

- Existing `bot_events` has `bot_id` and `pc_id` as NOT NULL, so tower-wide events should use explicit sentinel IDs or be omitted.
- `GET /api/health` and other read-only API routes must not emit events just to produce `control_tower_health_ok`.
- `tools/ops/*.py` must be runnable from repo root without package installation by bootstrapping `<repo>/src` on `sys.path` or by updating verify/runbook commands to set `PYTHONPATH=src`.
- The rejected latency/session plan is untracked in the same working tree; implementation handoff must explicitly ignore it and use only this ticket.

---

## Task 1: Ticket template and validator

**Objective:** Make future implementation tickets complete before a code worker touches the repo.

**Files:**
- Create: `docs/templates/TICKET_TEMPLATE.md`
- Create: `tools/ops/validate_ticket_template.py`
- Create: `tests/test_ops_ticket_template.py`
- Modify: `docs/PLAN.md`

**Required template sections:**
- Goal
- Explicit In Scope
- Explicit Out of Scope
- Current Repo Baseline
- Files To Modify/Create
- Inputs/Outputs
- Failure Modes
- Security/Secrets Notes
- Test Commands
- Rollback Plan
- Review Checklist
- Done Criteria

**Implementation notes:**
- Validator should read a markdown path argument and fail nonzero if required headings are missing.
- Validator must not parse or execute code blocks.
- `docs/PLAN.md` should link the template and explain that coding starts only after template validation passes.

**Test-first acceptance:**
1. Add a test with a minimal invalid markdown ticket and assert the validator fails.
2. Add a test with all required headings and assert the validator passes.
3. Use `tmp_path`; do not write runtime artifacts into repo `logs/` or `data/`.

**Verify:**

```bash
PYTHONPATH=src pytest -q tests/test_ops_ticket_template.py
python tools/ops/validate_ticket_template.py docs/templates/TICKET_TEMPLATE.md
```

---

## Task 2: Sanitized operation event model on existing control-tower paths

**Objective:** Create machine-readable incident/completion/progress events without changing command queue semantics.

**Files:**
- Modify: `src/income33/db.py`
- Modify: `src/income33/control_tower/service.py`
- Modify: `src/income33/logging_utils.py`
- Test: `tests/test_control_tower_api.py`

**Event shape:**

```json
{
  "id": 456,
  "event_type": "incident|completed|progress",
  "reason_code": "command_failed|command_completed|command_enqueued|active_command_stale|control_tower_health_ok",
  "bot_id": "sender-01",
  "pc_id": "pc-01",
  "command_id": 123,
  "message": "short operator-safe message",
  "payload": {"safe_key": "safe_value"},
  "ts": "UTC ISO timestamp"
}
```

**Implementation notes:**
- Reuse the existing `bot_events` table if practical, adding idempotent helpers such as `insert_bot_event()` and `list_recent_bot_events()`.
- Keep `command_id` and `reason_code` in `payload_json` unless a separate schema migration is explicitly justified.
- Emitting events must not alter FIFO polling, repeat scheduling, stop behavior, bot status mapping, or command completion semantics.
- Add redaction helper for operator-safe event text/payload. Redact auth codes, passwords, cookies, tokens, Authorization headers, access-token, refresh-token, connection strings, and raw request/response headers/bodies by default.
- Event logging should be grep-friendly but should not dump raw request/response headers or bodies; only short sanitized summaries are allowed.

**Test-first acceptance:**
1. Completing a command with status `done` emits `event_type=completed`, `reason_code=command_completed`.
2. Completing a command with status `failed` emits `event_type=incident`, `reason_code=command_failed`, with sanitized error text.
3. Queueing a command may emit `progress`/`command_enqueued`, but it must not change command status/order.
4. Redaction tests prove secrets are replaced with `[REDACTED]`.

**Verify:**

```bash
PYTHONPATH=src pytest -q tests/test_control_tower_api.py -k "event or command_completed or command_failed or redaction"
```

---

## Task 3: Read-only recent-events API/CLI for relay source

**Objective:** Provide a single safe source that a 1-minute relay job can poll without touching NewTA or command execution.

**Files:**
- Modify: `src/income33/control_tower/public_routes.py`
- Create: `tools/ops/poll_ops_events.py`
- Test: `tests/test_control_tower_api.py`
- Test: `tests/test_ops_relay.py`

**API/CLI behavior:**
- Add a read-only API such as `GET /api/ops/events?since_id=<id>&limit=<n>` or a clearly named equivalent.
- Return only sanitized events.
- Default limit should be bounded, for example `50`; hard max should be bounded, for example `200`.
- CLI should read from the local control-tower API URL or an explicit SQLite DB path in dry-run tests.
- CLI must not require or print Discord tokens.

**Test-first acceptance:**
1. API returns events after `since_id` and excludes older events.
2. API limit is bounded.
3. CLI prints JSON with no secret-looking values.
4. All tests use temp DB/log directories.

**Verify:**

```bash
PYTHONPATH=src pytest -q tests/test_control_tower_api.py tests/test_ops_relay.py -k "ops_events or since_id or limit"
```

---

## Task 4: 60-second relay packet generator, no direct Discord dependency

**Objective:** Generate deduped `[INCIDENT]`, `[COMPLETED]`, and `[PROGRESS]` packets that Hermes/worker tooling can relay to the active Discord thread every minute.

**Files:**
- Create: `tools/ops/relay_worker.py`
- Create: `tests/test_ops_relay.py`
- Modify: `docs/CONTROL_TOWER.md`
- Modify: `docs/AGENT_PC_SETUP.md` if it exists and references agent/tower runtime operations.

**Implementation notes:**
- Make the worker one-shot: each invocation reads recent events, emits at most one concise packet per category, updates a local state file, and exits.
- Scheduling belongs outside the Python module: Windows Task Scheduler, a batch loop, Hermes cron, or manual runbook. Do not add systemd service/timer files in this ticket.
- State file path should default under runtime data/log dir, not under tracked source files. It must be overrideable for tests.
- Dedup by event ID first; if unavailable, dedupe by stable hash of `(event_type, reason_code, bot_id, command_id, message)`.
- Output should be plain text and/or JSON. It should not call Discord APIs or require Discord credentials.
- Allowed public prefixes:
  - `[INCIDENT]`
  - `[COMPLETED]`
  - `[PROGRESS]`
- Suppress raw tracebacks, raw NewTA request/response headers/bodies, cookies/tokens/auth codes, and chain-of-thought-like text.

**Test-first acceptance:**
1. First run emits new events and writes dedupe state.
2. Second run with same events emits nothing or an explicit “no new events” marker.
3. New event after state file emits exactly one packet.
4. Secret-looking payload values are redacted.
5. No network call to Discord is made.

**Verify:**

```bash
PYTHONPATH=src pytest -q tests/test_ops_relay.py
python tools/ops/relay_worker.py --help
```

---

## Task 5: Review-handoff packet generator

**Objective:** When a ticket is ready, generate a code-review request packet with exactly the information the code 담당 needs.

**Files:**
- Create: `tools/ops/review_handoff.py`
- Test: `tests/test_ops_ticket_template.py`
- Modify: `docs/templates/TICKET_TEMPLATE.md`

**Packet fields:**
- Ticket path
- Goal
- In-scope files
- Out-of-scope exclusions
- Test commands
- Risks
- Rollback plan
- Specific review questions
- Current repo baseline command outputs, redacted if needed

**Implementation notes:**
- Generator should read a markdown ticket and output a copy/paste-safe review packet.
- It should not mention raw Discord IDs unless the operator passes them as display text.
- It should not send messages itself.
- It should fail if required ticket sections are missing.

**Test-first acceptance:**
1. Valid ticket produces a packet containing all required fields.
2. Missing rollback/test section fails.
3. Packet redacts secrets from embedded text.

**Verify:**

```bash
PYTHONPATH=src pytest -q tests/test_ops_ticket_template.py -k "handoff or validate"
python tools/ops/review_handoff.py docs/templates/TICKET_TEMPLATE.md
```

---

## Task 6: Windows-first operations runbook

**Objective:** Make the relay/review workflow operable on the actual 33income Windows-first runtime.

**Files:**
- Create: `docs/plans/relay-review-gate-runbook.md`
- Modify: `docs/CONTROL_TOWER.md`
- Modify: `docs/AGENT_PC_SETUP.md` if present

**Runbook must include:**
- How to run ticket validation.
- How to generate review handoff packet.
- How to run one-shot relay worker manually.
- How to schedule relay worker every 60 seconds with Windows Task Scheduler or a safe batch loop.
- How to point the relay worker at `http://127.0.0.1:8330` or a LAN control tower URL.
- How to verify `/api/health`, `/api/summary`, and `/api/ops/events`.
- Where dedupe state/log files live.
- Rollback: delete/disable the scheduled task and remove/ignore relay state file; no DB schema-destructive rollback.

**Verify:**

```bash
python tools/ops/validate_ticket_template.py docs/plans/relay-review-gate-runbook.md || true
PYTHONPATH=src pytest -q tests/test_ops_relay.py tests/test_ops_ticket_template.py
```

The runbook does not need to follow the ticket template exactly unless it is intended to be a ticket.

---

## Task 7: Integration verification and review gate

**Objective:** Prove the ticket-only relay/review system works without changing latency/session/stop semantics.

**Required checks:**

```bash
python -m compileall src tools
PYTHONPATH=src pytest -q tests/test_control_tower_api.py tests/test_ops_relay.py tests/test_ops_ticket_template.py
PYTHONPATH=src pytest -q
git diff --check
```

**Manual/dry-run rehearsal:**
1. Start a control tower against a temp DB/log dir or use TestClient fixtures.
2. Create one completed command event and one failed command event through test/API paths.
3. Run `tools/ops/relay_worker.py` with a temp state file.
4. Confirm output has `[COMPLETED]` and `[INCIDENT]` lines and no secrets.
5. Run it again and confirm dedupe suppresses duplicates.
6. Run `tools/ops/review_handoff.py` against this ticket and confirm the packet is copy/paste-safe.

**Safety assertions:**
- No NewTA browser/CDP calls occur.
- No POST/PUT/send/submit/correction/auth-code workflow is retried by this ticket.
- Existing command FIFO/polling/heartbeat behavior is unchanged except for passive event writes.
- No systemd files are created.
- No Discord token/API call is required.

---

## Done Criteria

- Ticket template exists and validator enforces required sections.
- Sanitized event helpers/API/CLI exist and are covered by tests.
- Relay worker can generate 60-second-safe deduped packets without direct Discord dependency.
- Review handoff generator produces a complete code 담당 검수요청 packet.
- Windows-first runbook documents manual and scheduled operation.
- Full verification commands pass.
- This ticket handoff does not include commit, push, or runtime deployment; any later commit/push/deploy requires a separate Hermes xhigh review/authorization gate.

---

## Review Request

Code implementation/review 담당 should verify:

1. The excluded latency/session/stop/systemd scopes are actually absent.
2. The event/relay/review tooling is read-only or passive except for safe local state/event inserts.
3. Redaction covers auth codes, passwords, cookies, tokens, Authorization headers, connection strings, raw request/response headers/bodies, and long tracebacks.
4. Tests use temp DB/log/state paths and do not touch real NewTA or Discord.
5. The plan is executable task-by-task without guessing file paths or acceptance criteria.
