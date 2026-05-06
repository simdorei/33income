# 관제/봇 반응속도 + 세션 접속 안정화 패치 계획 티켓

> **For Hermes/Codex:** 구현은 `subagent-driven-development` 방식으로 단계별 진행, 각 Task 종료마다 테스트 통과 증거(명령/출력) 첨부.

**Goal:** 33income 운영에서 "명령 반응 느림"/"세션 이탈"/"관제 먹통"을 줄여, 명령 체감 응답을 빠르게 하고 세션 유지율을 높인다.

**Architecture:** (1) runner 루프를 `명령 polling`과 `heartbeat` 주기 분리 구조로 바꾸고, (2) control_tower에 지연 측정 지표(command enqueue→pick→complete)를 추가하며, (3) 세션 접속/복구 가드를 표준화한다. 최종적으로 관제 화면에서 지연/세션 상태를 즉시 확인 가능하게 만든다.

**Tech Stack:** Python 3.11, FastAPI, SQLite, requests, pytest.

---

## 운영 목표(SLO)
- 명령 반응: `queue -> agent pick` p95 2초 이하
- 상태 반영: `agent step 변경 -> dashboard 반영` p95 3초 이하
- 세션 안정성: session 관련 실패율 50% 이상 감소(배포 전/후 24h 비교)
- 관제 가용성: control_tower down 탐지~복구 가이드 5분 이내

---

### Task 1: 지연 계측 필드/요약 노출 추가

**Objective:** 반응속도 이슈를 감으로 보지 않고 수치로 추적 가능하게 만든다.

**Files:**
- Modify: `src/income33/db.py`
- Modify: `src/income33/control_tower/service.py`
- Modify: `src/income33/control_tower/agent_command_routes.py`
- Test: `tests/test_control_tower_api.py`

**Step 1 (Test-first):**
- API 응답에 아래 필드가 포함되는 테스트 추가
  - `command_queue_latency_ms` (enqueue->pick)
  - `command_exec_latency_ms` (pick->complete)
  - `heartbeat_age_sec` (now->last_heartbeat)

**Step 2 (Implement):**
- DB command/heartbeat 조회 경로에서 latency 계산 함수 추가.
- `/api/summary` 또는 bot list 응답 payload에 지표 포함.

**Step 3 (Verify):**
- `PYTHONPATH=src pytest -q tests/test_control_tower_api.py -k "summary or heartbeat or command"`

---

### Task 2: runner 루프 주기 분리(빠른 poll, 안정 heartbeat)

**Objective:** 긴 작업/느린 브라우저 유지보수 경로가 명령 수신을 막지 않게 한다.

**Files:**
- Modify: `src/income33/config.py`
- Modify: `src/income33/agent/runner.py`
- Test: `tests/test_config.py`
- Test: `tests/test_agent_runner.py`

**Step 1 (Test-first):**
- 새 설정 키 테스트 추가
  - `INCOME33_AGENT_COMMAND_POLL_INTERVAL_SECONDS` (default 1)
  - `INCOME33_AGENT_HEARTBEAT_INTERVAL_SECONDS` (기존 유지, default 5)
- runner가 poll과 heartbeat를 독립 스케줄로 수행하는 테스트 추가.

**Step 2 (Implement):**
- `run_forever()`를 단일 sleep 루프에서 monotonic 기반 스케줄 루프로 전환.
- command poll은 최소 1초 단위, heartbeat는 기존 주기 유지.
- command 존재 시 즉시 처리 후 다음 poll 대기 최소화.

**Step 3 (Verify):**
- `PYTHONPATH=src pytest -q tests/test_config.py tests/test_agent_runner.py -k "poll or heartbeat or interval"`

---

### Task 3: command poll 실패/지연 내성 강화

**Objective:** control_tower 순간 장애(연결거부/timeout) 시 agent가 멈춘 것처럼 보이지 않게 한다.

**Files:**
- Modify: `src/income33/agent/client.py`
- Modify: `src/income33/agent/runner.py`
- Test: `tests/test_agent_runner.py`

**Step 1 (Test-first):**
- poll 실패(예외/timeout) 시 runner가 프로세스를 종료하지 않고 다음 주기 재시도하는 테스트.
- poll 실패 동안에도 마지막 상태 heartbeat를 유지 전송하는 테스트.

**Step 2 (Implement):**
- `poll_commands` 예외 처리 + bounded backoff(예: 1s→2s→max 10s).
- backoff 중에도 상태 heartbeat는 기존 주기대로 송신.

**Step 3 (Verify):**
- `PYTHONPATH=src pytest -q tests/test_agent_runner.py -k "poll fail or backoff or heartbeat"`

---

### Task 4: 세션 접착(adhesion) 가드 표준화

**Objective:** 세션 이탈/로그인 요구/CDP 불안정 상황에서 복구 경로를 일관화한다.

**Files:**
- Modify: `src/income33/agent/runner.py`
- Modify: `src/income33/agent/browser_control.py`
- Test: `tests/test_agent_runner.py`
- Test: `tests/test_browser_control.py`

**Step 1 (Test-first):**
- 세션 상태가 `login_required/login_auth_required`일 때 command 처리 전 복구 시퀀스(페이지 refresh/login probe) 수행 테스트.
- `Execution context was destroyed`/fetch timeout 발생 시 1회 세션 재동기화 후 재시도(중복 제출 금지) 테스트.

**Step 2 (Implement):**
- command 실행 전 `session preflight` 헬퍼 도입.
- 브라우저 fetch timeout/env 값을 커맨드별 override 가능하게 하고, 실패 reason code를 구조화 로그로 남김.

**Step 3 (Verify):**
- `PYTHONPATH=src pytest -q tests/test_agent_runner.py tests/test_browser_control.py -k "session or login_required or context destroyed"`

---

### Task 5: 관제 먹통 대비 자동기동/복구 절차 고정

**Objective:** control_tower 미기동으로 전체가 멈추는 사고를 재발 방지한다.

**Files:**
- Modify: `docs/CONTROL_TOWER.md`
- Create: `ops/systemd/income33-control-tower.service` (없다면)
- Create: `ops/systemd/income33-agent-runner@.service` (없다면)
- Test/Verify: 운영 검증 명령 문서화

**Step 1:**
- systemd 유닛 템플릿 작성(`Restart=always`, healthcheck 의존/순서 포함).

**Step 2:**
- 문서에 5분 트리아지 절차(8330 listen, /api/health, /api/summary, agent.log 패턴) 추가.

**Step 3 (Verify):**
- 문서 명령 실행 검증(예: `systemctl status`, `curl /api/health`).

---

### Task 6: 운영 중계용 이벤트 표준(사고/완료) 추가

**Objective:** 중계 봇/CLI가 1분 주기로 읽기 쉬운 표준 이벤트를 제공한다.

**Files:**
- Modify: `src/income33/control_tower/service.py`
- Modify: `src/income33/logging_utils.py`
- (Optional) Create: `tools/ops/poll_incident_events.py`
- Test: `tests/test_control_tower_api.py`

**Step 1 (Test-first):**
- command 실패/완료 시 구조화 이벤트(`event_type`, `bot_id`, `command_id`, `reason_code`, `ts`) 생성 테스트.

**Step 2 (Implement):**
- 기존 로그에 grep-friendly 이벤트 라인 추가.
- 필요 시 최근 이벤트 조회 API 또는 파일(JSONL) 추가.

**Step 3 (Verify):**
- `PYTHONPATH=src pytest -q tests/test_control_tower_api.py -k "event or failure or completed"`

---

### Task 7: 통합 회귀 + 성능 측정 리허설

**Objective:** 패치가 기존 기능을 깨지 않고, 반응속도 개선 수치를 확인한다.

**Files:**
- Test only: `tests/test_control_tower_api.py`, `tests/test_agent_runner.py`, `tests/test_browser_control.py`, `tests/test_config.py`

**Step 1:**
- `PYTHONPATH=src pytest -q tests/test_control_tower_api.py tests/test_agent_runner.py tests/test_browser_control.py tests/test_config.py`

**Step 2:**
- 로컬 리허설 10회 이상에서 아래 측정값 기록:
  - queue->pick latency
  - pick->complete latency
  - heartbeat age

**Step 3:**
- 배포 체크리스트/롤백 조건 작성(새 env key off 시 기존 동작으로 복귀 가능).

---

## Done Criteria
- command 반응 지표가 관제 API에서 조회 가능.
- runner가 poll/heartbeat 분리 주기로 동작.
- control_tower 순간 장애 시 agent가 중단되지 않고 자동 재시도.
- 세션 preflight + 재동기화 가드로 session 관련 실패율 감소.
- 운영 문서에 자동기동/복구 절차 반영.
- 관련 테스트 통과 + 리허설 수치 제출.

---

## 확인 필요(질문)
1. 반응속도 SLO 확정값: p95 기준을 `2초/3초`로 갈지 다른 값으로 갈지?
2. "세션 잘 붙음" 성공 정의: 로그인 재요구율, command 실패율, 또는 수동개입 건수 중 무엇을 1순위 KPI로 볼지?
3. 1분 중계 원본은 `control_tower structured event`를 단일 소스로 고정해도 되는지?
4. systemd 유닛 파일을 repo에 포함할지(ops/), 서버 로컬 문서만 둘지?
5. 배포 순서: reporter 먼저/ sender 먼저/ 동시 배포 중 선호안?
