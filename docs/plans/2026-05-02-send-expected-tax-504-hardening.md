# send_expected_tax_amounts 504 하드닝 구현 계획

> **For Hermes/Codex:** `subagent-driven-development` 방식으로 구현(코딩은 delegate_task로 실행), 완료 후 상위 에이전트가 직접 검수/테스트 확인.

**Goal:** `expected tax amount send failed status=504` 발생 시 원인 가시성을 높이고, 일시적 게이트웨이 오류(504/502/503/429)에 대해 안전한 재시도로 성공률을 높인다.

**Architecture:** `browser_control.py`에 전송 전용 재시도 helper를 추가하고, 리스트 발송/단건 발송 경로를 동일한 실패 포맷으로 정규화한다. 테스트는 `tests/test_browser_control.py`에서 TDD로 회귀를 고정한다.

**Tech Stack:** Python 3.11, pytest, monkeypatch 기반 단위 테스트.

---

### Task 1: 전송 응답 실패 진단 메시지 표준화

**Objective:** 실패 메시지에 status/fetch_error/응답 snippet을 포함해 504 원인 분석 가능성 확보.

**Files:**
- Modify: `src/income33/agent/browser_control.py`
- Test: `tests/test_browser_control.py`

**Step 1 (Test-first):**
- `send_expected_tax_amounts`에서 504 응답 시 예외 메시지에 아래가 포함되는 테스트 추가
  - `status=504`
  - `fetch_error=` (없으면 `-`)
  - `hint=` (json.error.message 또는 text 일부)

**Step 2 (Implement):**
- 전송 실패 포맷터 helper 추가
- 리스트 발송/단건 발송 둘 다 동일 포맷 RuntimeError 사용

**Step 3 (Verify):**
- `pytest tests/test_browser_control.py -k "expected_tax_amounts and 504" -v`

---

### Task 2: 전송 API 재시도(일시 장애 한정) 추가

**Objective:** 504/502/503/429 및 fetch_error(status=0)에서 bounded retry 수행.

**Files:**
- Modify: `src/income33/agent/browser_control.py`
- Test: `tests/test_browser_control.py`

**Step 1 (Test-first):**
- 첫 호출 504, 두 번째 200 success일 때 성공 처리 + 호출 횟수 2회 검증 테스트 추가.
- 첫 호출 400 같은 비재시도 상태일 때 즉시 실패(1회 호출) 테스트 추가.

**Step 2 (Implement):**
- helper: `_send_with_retry(...)` 추가
- 기본값(예): attempts=2, backoff_sec=1.0 (env/payload override 허용)
- 재시도 상태 집합: `{0, 429, 502, 503, 504}`

**Step 3 (Verify):**
- `pytest tests/test_browser_control.py -k "retry or non_retry" -v`

---

### Task 3: 기존 동작 회귀 검증 + 실행 검증

**Objective:** 기존 성공 플로우를 깨지 않고 전체 관련 테스트 통과.

**Files:**
- Test only: `tests/test_browser_control.py`, 필요 시 기존 assertion 최소 조정

**Step 1:**
- 관련 테스트 전체 실행:
  - `pytest tests/test_browser_control.py -v`

**Step 2:**
- 에이전트 러너 핵심 회귀 확인:
  - `pytest tests/test_agent_runner.py -k send_expected_tax_amounts -v`

**Step 3:**
- 변경 요약(diff/stat) 확인 및 결과 보고.

---

## Done Criteria

- 504 실패 메시지에 status/fetch_error/hint 포함.
- 504→200 시 동일 command에서 성공 복구.
- 400 등 비재시도 오류는 즉시 실패.
- `tests/test_browser_control.py` 전부 통과.
- `tests/test_agent_runner.py -k send_expected_tax_amounts` 통과.
