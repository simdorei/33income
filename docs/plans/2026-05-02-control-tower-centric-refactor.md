# Control Tower 중심 리팩토링 실행 계획

> **For Hermes:** subagent-driven-development 방식으로 태스크 단위 구현 + 매 라운드 코드리뷰 수행.

**Goal:** sender/reporter는 실행기 역할로 단순화하고, 운영 변화(버튼/명령조합/대상선정/검증)는 control_tower에서 중앙 관리한다.

**Architecture:**
- Control Tower: command orchestration, payload validation, UX forms, retry policy metadata
- Agent(sender/reporter): command executor + browser/API side effects + status/heartbeat return
- Shared command schema: command name 최소화, payload 표준화

**Tech Stack:** FastAPI(control_tower), Python agent runner/browser_control, pytest

---

## Task 1: 현행 기능 인벤토리
**Objective:** 현재 sender/reporter/control_tower에 분산된 기능/중복을 표로 정리한다.

**Files:**
- Modify: `docs/plans/2026-05-02-control-tower-centric-refactor.md`
- Inspect: `src/income33/control_tower/app.py`, `src/income33/control_tower/service.py`, `src/income33/agent/runner.py`, `src/income33/agent/browser_control.py`, `src/income33/models.py`

**Output:**
- command별 “결정로직 위치 vs 실행로직 위치” 매트릭스
- 중앙화 가능한 것/불가능한 것(브라우저 side-effect) 분류

## Task 2: Command Schema 표준화
**Objective:** 커맨드 폭증을 막는 표준 payload 구조를 정의한다.

**Files:**
- Modify: `src/income33/models.py`, `src/income33/control_tower/service.py`
- Test: `tests/test_control_tower_api.py`

**Plan:**
- 유지: 핵심 업무 커맨드(`send_expected_tax_amounts` 등)
- 추가: `tax_doc_ids` 목록 payload 표준화 (list[int])
- 제한: reporter에서 sender-only 커맨드 차단 유지

## Task 3: taxDocId 목록 발송 UX 정식화
**Objective:** dashboard에서 목록 붙여넣기(쉼표/공백/줄바꿈)를 안전하게 큐잉한다.

**Files:**
- Modify: `src/income33/control_tower/app.py`
- Test: `tests/test_control_tower_api.py`

**Acceptance:**
- `/ui/bots/{bot_id}/send-expected-tax-amounts-list` 라우트
- invalid token 시 400
- dedupe 후 `send_expected_tax_amounts` payload 전달

## Task 4: Sender/Reporter 슬림화 리팩토링
**Objective:** 에이전트는 실행기 역할만 남기고 정책/분기 로직은 타워로 이동 가능한 부분부터 이전한다.

**Files:**
- Modify: `src/income33/agent/runner.py`, `src/income33/bots/sender.py`, `src/income33/bots/reporter.py`
- Test: `tests/test_agent_runner.py`

**Scope(1차):**
- command dispatch 경량화
- 상태문구/카운트 정책 중 타워 이관 가능한 부분 분리

## Task 5: 검증/릴리즈
**Objective:** 회귀 없이 운영 반영 가능 상태를 만든다.

**Files:**
- Test: `tests/test_browser_control.py`, `tests/test_agent_runner.py`, `tests/test_control_tower_api.py`

**Run:**
- `python -m compileall src`
- `PYTHONPATH=src pytest -q`
- `git diff --check`

---

## Codex xhigh 실행 방식
1. 태스크별 Codex xhigh 작업 지시
2. 결과 수신 즉시 Hermes 1차 리뷰(스펙 적합성)
3. 통과 시 Hermes 2차 리뷰(코드 품질/운영 리스크)
4. 수정 요청 반복
5. 각 태스크 완료 후 커밋

## 운영 원칙
- UI/흐름 변경은 control_tower 우선
- 외부 API 헤더/쿼리/body 변경은 agent patch 필요
- sender-only 위험 동작 차단 규칙 유지

---

## Task 2 Detailed Spec

### 1) 공통 Command Envelope (sender/reporter 공용)
```json
{
  "command": "<string>",
  "target": {
    "bot_id": "sender-01",
    "bot_role": "sender"
  },
  "payload": {},
  "meta": {
    "request_id": "ct-20260502-0001",
    "issued_at": "2026-05-02T02:00:00Z",
    "issued_by": "control_tower",
    "priority": "normal",
    "dry_run": false,
    "trace": {
      "workflow": "manual-ui",
      "operator": "admin"
    }
  },
  "retry": {
    "interval_sec": 300,
    "max_attempts": 3,
    "fallback": {
      "action": "mark_failed",
      "notify": ["slack:#ops-alert"],
      "next_command": null
    }
  }
}
```

### 2) 필드 표준안
| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `command` | string | Y | 실행 명령명. 예: `send_expected_tax_amounts` |
| `target.bot_id` | string | Y | 실행 대상 agent ID |
| `target.bot_role` | enum(`sender`,`reporter`) | Y | 대상 역할 |
| `payload` | object | Y | 명령별 입력 파라미터 |
| `meta.request_id` | string | Y | 멱등/추적 키 |
| `meta.issued_at` | datetime(ISO8601) | Y | 발행 시각(UTC) |
| `meta.priority` | enum(`low`,`normal`,`high`) | N | 큐 우선순위 |
| `meta.dry_run` | bool | N | 실행 없이 검증만 수행 |
| `retry.interval_sec` | int | Y | 재시도 간격(초) |
| `retry.max_attempts` | int | Y | 최대 시도 횟수(최초 포함) |
| `retry.fallback` | object | N | 재시도 소진 후 후속 정책 |
| `retry.fallback.action` | enum(`mark_failed`,`enqueue_command`,`escalate`) | N | 실패 처리 방식 |
| `retry.fallback.next_command` | object\|null | N | `enqueue_command` 시 다음 명령 |

### 3) sender-only guard (타워/에이전트 이중 방어)
- 원칙: `sender-only` 명령은 `target.bot_role=sender`에서만 허용.
- control_tower 검증: enqueue 전 role mismatch면 즉시 400.
- agent 최종 검증: reporter가 수신 시 `forbidden_command` 상태 반환, 실행 금지.
- 권장 에러 포맷:
```json
{
  "status": "rejected",
  "code": "SENDER_ONLY_COMMAND",
  "message": "command send_expected_tax_amounts is sender-only",
  "request_id": "ct-20260502-0001"
}
```

### 4) 명령별 payload 예시

#### 4-1) `send_expected_tax_amounts` (`tax_doc_ids` 목록)
```json
{
  "command": "send_expected_tax_amounts",
  "target": {
    "bot_id": "sender-01",
    "bot_role": "sender"
  },
  "payload": {
    "tax_doc_ids": [10101, 10102, 10108],
    "batch_label": "2026-05-2w-expected-tax"
  },
  "meta": {
    "request_id": "ct-20260502-0100",
    "issued_at": "2026-05-02T02:05:00Z",
    "issued_by": "control_tower",
    "priority": "high",
    "dry_run": false
  },
  "retry": {
    "interval_sec": 180,
    "max_attempts": 4,
    "fallback": {
      "action": "escalate",
      "notify": ["slack:#tax-ops"]
    }
  }
}
```

#### 4-2) `preview_send_targets`
```json
{
  "command": "preview_send_targets",
  "target": {
    "bot_id": "reporter-01",
    "bot_role": "reporter"
  },
  "payload": {
    "filters": {
      "corp_name": "33",
      "status": ["READY", "RETRY"]
    },
    "limit": 200
  },
  "meta": {
    "request_id": "ct-20260502-0200",
    "issued_at": "2026-05-02T02:10:00Z",
    "issued_by": "control_tower",
    "dry_run": true
  },
  "retry": {
    "interval_sec": 0,
    "max_attempts": 1,
    "fallback": {
      "action": "mark_failed"
    }
  }
}
```

#### 4-3) browser action generic envelope (safe whitelist)
```json
{
  "command": "browser_action",
  "target": {
    "bot_id": "sender-01",
    "bot_role": "sender"
  },
  "payload": {
    "action": "click",
    "args": {
      "selector": "button#submit"
    }
  },
  "meta": {
    "request_id": "ct-20260502-0300",
    "issued_at": "2026-05-02T02:12:00Z",
    "issued_by": "control_tower"
  },
  "retry": {
    "interval_sec": 5,
    "max_attempts": 2,
    "fallback": {
      "action": "mark_failed"
    }
  }
}
```

- `payload.action` whitelist(예시): `click`, `type`, `select`, `wait_for`, `screenshot`.
- 금지: 임의 JS 실행, 임의 URL 외부 이동, 파일시스템 접근.
- `args`는 action별 schema 고정(추가 키 차단)으로 주입 공격 방지.

### 5) 최소 검증 규칙(요약)
- 공통: `command/target/payload/meta.request_id/retry` 필수.
- `tax_doc_ids`: `list[int]`, 빈 배열 금지, 중복 제거는 control_tower에서 수행.
- `retry.max_attempts >= 1`, `retry.interval_sec >= 0`.
- `dry_run=true`면 side-effect 명령은 실행 대신 검증 결과만 반환.
