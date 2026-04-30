# 33income 실행 계획

## 0. 전제

- 총 18봇 운영:
  - 발송봇 9대
  - 신고봇 9대
- 실제 업무 자동화는 Windows PC들에서 실행한다.
- 초기 운영 배치는 **컴퓨터 18대 × PC당 1봇**이다.
- 향후 안정화 후 PC 대수는 줄일 수 있다.
  - 1차 축소 후보: 9대 × PC당 2봇
  - 2차 축소 후보: 6대 × PC당 3봇
- 중앙 관제는 별도 PC 또는 대표 PC 1대에서 실행한다.
- 각 봇 PC에는 local agent가 떠 있고, 중앙 관제와 통신한다.
- 로그인/카카오 인증은 사람이 처리한다.
- 자동화는 로그인 이후 업무를 대상으로 한다.
- 각 봇은 독립 브라우저 프로필을 사용한다.
- Python 프로젝트는 각 PC에서 `.venv` 기반으로 실행한다.

## 1. 목표 아키텍처

```text
중앙 관제 PC 또는 관제 서버
  ├─ FastAPI/Flask 기반 로컬/내부 웹서버
  ├─ SQLite DB
  ├─ 컨트롤타워 웹페이지
  ├─ 전체 봇 상태 수집
  ├─ stuck/crashed/login_required 감지
  ├─ 시작/중지/재시작 명령 전송
  └─ Telegram/Discord 알림, 추후 추가

각 봇 PC 1~18대
  ├─ 33income 프로젝트 checkout
  ├─ .venv
  ├─ local agent
  ├─ sender 또는 reporter bot
  ├─ 전용 browser profile
  ├─ heartbeat 전송
  ├─ 로그/스크린샷 저장
  └─ 중앙 관제 명령 수신
```

초기 배치:

```text
PC-01 ~ PC-09   → sender-01 ~ sender-09
PC-10 ~ PC-18   → reporter-01 ~ reporter-09
```

향후 축소 배치 예:

```text
9대 운영:
  PC-01: sender-01 + reporter-01
  PC-02: sender-02 + reporter-02
  ...
  PC-09: sender-09 + reporter-09

6대 운영:
  PC당 3봇 내외 배치
```

## 2. 왜 초기에는 18대 × 1봇인가

초기에는 1 PC당 1봇이 안정성 면에서 유리하다.

장점:

- 한 PC가 죽어도 1봇만 영향받는다.
- 브라우저/세션/쿠키 꼬임이 다른 봇에 전파되지 않는다.
- 로그인/카카오 인증 관리가 단순하다.
- 디버깅 시 원인 분리가 쉽다.
- 각 PC의 CPU/RAM 부담이 낮다.

단점:

- PC 18대의 전원/윈도우 업데이트/원격 접속/네트워크 관리가 필요하다.
- 초기 세팅 시간이 길다.

결론:

```text
초기 안정화 단계: 18대 × 1봇 유지
자동화 안정화 후: 9대 × 2봇 또는 6대 × 3봇으로 축소 검토
```

## 3. venv / Windows 실행 방식

각 PC는 프로젝트별 `.venv`를 사용한다.

초기 사용자는 아래 정도만 수행하도록 만든다.

```bat
git clone <repo-url>
cd 33income
setup_windows.bat
```

중앙 관제 PC:

```bat
run_control_tower.bat
```

각 봇 PC:

```bat
run_agent.bat
```

또는 단일 봇 디버깅용:

```bat
run_sender.bat
run_reporter.bat
```

프로젝트 내부 구성:

```text
.venv/                  # git 제외
requirements.txt
setup_windows.bat       # venv 생성 + 패키지 설치
run_control_tower.bat   # 중앙 관제 웹페이지 실행
run_agent.bat           # 각 봇 PC local agent 실행
run_sender.bat          # 단일 발송봇 디버깅용
run_reporter.bat        # 단일 신고봇 디버깅용
.env                    # git 제외
.env.example            # git 포함
```

`setup_windows.bat` 역할:

1. `.venv` 없으면 생성
2. pip 업그레이드
3. `requirements.txt` 설치
4. Playwright 사용 시 브라우저 엔진 설치

## 4. 구성 요소

### 4.1 중앙 관제 control tower

역할:

- 전체 봇 18대 상태 조회
- 각 PC agent의 heartbeat 수집
- 봇 시작/중지/재시작 명령 전송
- stuck/crashed/login_required 감지
- 상태 DB 저장
- 웹 대시보드 제공
- 추후 Telegram/Discord 알림 발송

초기 URL 예:

```text
http://127.0.0.1:8330
```

나중에 다른 PC에서 접속해야 하면 내부망 IP로 열 수 있다.

```text
http://<관제PC_IP>:8330
```

### 4.2 각 PC local agent

역할:

- 중앙 관제에 자기 PC/봇 상태 등록
- heartbeat 전송
- 명령 수신:
  - start
  - stop
  - restart
  - status
  - open_login
  - fill_login
  - submit_auth_code
  - refresh_page
- 실제 봇 프로세스 실행/종료
- 로그/스크린샷 경로 보고

중앙 관제와 통신 방식은 초기에는 HTTP polling 방식이 가장 단순하다.

```text
agent → control tower: heartbeat/status POST
agent → control tower: command poll GET
control tower → DB: 상태 저장
```

장점:

- 각 봇 PC가 중앙 관제에 접속만 하면 된다.
- 중앙 관제가 각 PC로 직접 접속할 필요가 줄어든다.
- 방화벽/공유기/내부망 설정이 단순하다.

### 4.3 발송봇 sender

역할:

- 발송 대상 목록 확인
- 대상별 발송 처리
- 성공/실패 기록
- 오류 발생 시 상태/스크린샷/로그 저장

초기 상태:

- 실제 사이트 연동 전에는 mock worker로 heartbeat와 상태 변화만 구현한다.

### 4.4 신고봇 reporter

역할:

- 신고 목록 확인
- 상세/사업장 개수 확인
- 사업장별 보정
- 국세신고 시작 및 완료 확인
- 지방세신고 시작 및 완료 확인
- 실패 유형 기록

처리 원칙:

- 항목 내부 단계는 직렬
- 항목 간 병렬은 낮게 시작
- request 우선, UI fallback 보조

## 5. 봇/PC 상태 모델

PC/agent 상태:

```text
online
offline
agent_stale
agent_error
```

봇 상태:

```text
idle
starting
running
waiting
paused
login_required
login_opened
login_filling
login_auth_required
manual_required
session_active
refreshing
stuck
crashed
restarting
stopped
```

작업 아이템 상태 예시:

```text
pending
opened
business_checked
adjusting
adjusted
national_started
national_done
local_started
local_done
failed_marked
completed
failed
manual_required
```

## 6. 컨트롤타워 웹페이지

### 6.1 메인 대시보드

```text
전체 요약
- 총 PC 수
- 온라인/오프라인 PC 수
- 총 봇: 18
- running / idle / login_required / stuck / crashed 카운트

PC/Agent 테이블
- pc_id
- hostname
- ip
- agent 상태
- 마지막 heartbeat
- 담당 bot_id
- agent version

발송봇 9대 테이블
- bot_id
- PC
- 상태
- 현재 단계
- 마지막 heartbeat
- 처리 대상
- 성공/실패 수
- 버튼: 시작 / 중지 / 재시작 / 로그

신고봇 9대 테이블
- bot_id
- PC
- 상태
- 현재 단계
- 마지막 heartbeat
- 처리 대상
- 성공/실패 수
- 버튼: 시작 / 중지 / 재시작 / 로그
```

### 6.2 상세 화면

```text
/bots/{bot_id}
- 담당 PC
- 최근 로그
- 최근 에러
- 현재 설정
- 브라우저 프로필 경로
- 마지막 스크린샷

/agents/{pc_id}
- PC 상태
- agent 상태
- 실행 중인 봇
- 최근 heartbeat
- 최근 명령 이력
```

### 6.3 제어 기능

초기 지원:

- 봇 시작
- 봇 중지
- 봇 재시작
- 전체 발송봇 시작
- 전체 신고봇 시작
- 전체 정지
- agent 상태 확인

주의:

- `login_required/login_auth_required/manual_required` 상태는 자동재시작하지 않는다.
- 인증이 필요한 경우 관제에서 `로그인 열기` -> `로그인 입력` -> `인증코드 제출` 순으로 명령을 내려 해당 봇 PC의 CDP 브라우저에서 진행한다.
- 세션 유지가 필요하면 `새로고침` 또는 주기 keepalive를 사용한다.

## 7. 데이터 저장

초기 DB는 중앙 관제의 SQLite 사용.

```text
data/33income.db
```

18봇 heartbeat 기준으로 SQLite는 충분히 가볍다.

예: heartbeat 30초 기준

```text
18봇 × 분당 2회 = 분당 36건
하루 약 51,840건
```

단, heartbeat는 전부 이벤트 로그로 무한 INSERT하지 않고 현재 상태는 UPDATE 중심으로 저장한다.

### 7.1 agents

```text
pc_id
hostname
ip_address
status
agent_version
assigned_bot_ids
last_heartbeat_at
error_code
error_message
updated_at
```

### 7.2 bots

```text
bot_id
bot_type: sender/reporter
pc_id
status
profile_dir
pid
last_heartbeat_at
current_step
current_target_id
success_count
failure_count
error_code
error_message
updated_at
```

### 7.3 bot_events

중요 이벤트만 저장한다.

```text
id
bot_id
pc_id
level
event_type
message
payload_json
created_at
```

예:

```text
started
stopped
restarted
login_required
heartbeat_lost
recovered
crashed
stuck
```

### 7.4 items

```text
id
bot_type
external_id
status
current_step
assigned_bot_id
retry_count
error_code
error_message
created_at
updated_at
```

### 7.5 commands

중앙 관제가 agent에게 내리는 명령 큐.

```text
id
pc_id
bot_id
command: start/stop/restart/status/open_login/fill_login/submit_auth_code/refresh_page/login_done
status: pending/running/done/failed
payload_json
created_at
picked_at
finished_at
error_message
```

## 8. 브라우저 프로필 전략

각 PC 안의 프로필 경로 예시:

```text
profiles/
  sender-01/
```

향후 PC당 여러 봇 운영 시:

```text
profiles/
  sender-01/
  reporter-01/
```

원칙:

- 프로필 공유 금지
- 로그인 세션은 각 프로필에 유지
- 브라우저/프로필 꼬임이 생기면 해당 봇만 재로그인/재시작

## 9. request-first / UI fallback 전략

초기 구현 순서:

1. Playwright 또는 브라우저 세션 준비
2. 로그인 상태 감지
3. 목록 조회 request 확인
4. 상세/사업장 개수 request 확인
5. 상태 변경 request 확인
6. 상태 조회/polling request 확인
7. request가 불안정한 단계만 UI fallback 처리

금지/주의:

- 고정 cookie 문자열 복붙 장기 사용 금지
- 긴 sleep 기반 처리 지양
- 상태조회 polling 우선

## 10. 알림 정책

초기에는 웹 UI만 구현하고, 이후 Telegram/Discord 알림 추가.

알림 기준:

```text
login_required: 즉시
crashed: 즉시
agent_stale: 즉시
heartbeat 2~3분 없음: warning
heartbeat 5분 없음: critical/stuck
hard_restart 실행: 알림
recovered: 복구 알림 1회
```

## 11. 구현 단계

### Phase 1. 프로젝트 뼈대

- Python 패키지 구조 생성
- Windows `.venv`/bat 세팅
- `.env.example`
- 기본 config 로더
- SQLite 초기화
- 중앙 관제 FastAPI 웹서버
- mock agent / mock bot 18대 상태 표시

완료 기준:

- Windows에서 `setup_windows.bat` 후 `run_control_tower.bat` 실행
- 웹페이지에서 18개 봇과 PC/agent 상태 확인

### Phase 2. agent/command 구조

- local agent 실행
- agent heartbeat 구현
- 중앙 관제 command queue 구현
- start/stop/restart mock 처리

완료 기준:

- agent가 중앙 관제에 online으로 표시
- 웹 UI에서 sender-01 시작/중지/재시작 명령 가능

### Phase 3. 실제 봇 프로세스 제어

- 봇 프로세스 시작/종료
- pid 추적
- heartbeat 수집
- 로그 수집
- stuck/crashed 감지

완료 기준:

- 실제 bot runner를 웹 UI에서 제어 가능
- heartbeat 끊기면 stuck/crashed 표시

### Phase 4. 브라우저 프로필/로그인 상태

- 봇별 브라우저 프로필 생성
- 브라우저 실행
- 로그인 필요 감지
- `login_required` 상태 반영

완료 기준:

- 각 봇이 독립 프로필로 브라우저 실행
- 로그인 페이지 감지 시 자동작업 중단

### Phase 5. 발송봇 실제 로직

- 발송 목록 조회
- 단일 대상 발송 성공 케이스 구현
- 실패 기록
- sender-01부터 검증 후 9대로 확장

### Phase 6. 신고봇 실제 로직

- 신고 목록 조회
- 상세/사업장 수 확인
- 보정 처리
- 국세/지방세 시작
- 상태 polling
- 실패 유형 기록
- reporter-01부터 검증 후 9대로 확장

### Phase 7. 운영 안정화 및 PC 대수 축소 검토

- 재시작 정책 정리
- 알림 추가
- 로그/스크린샷 다운로드
- 설정 UI 또는 config 파일 정리
- PC당 2봇 테스트
- 안정적이면 9대 × 2봇 또는 6대 × 3봇 검토

## 12. 첫 코딩 범위 추천

실제 사이트 자동화 전에 아래까지만 먼저 만든다.

1. 프로젝트 구조
2. Windows `.venv` 세팅 bat
3. 중앙 관제 FastAPI 기본 웹페이지
4. SQLite DB
5. mock PC/agent 18대와 sender/reporter 18봇 표시
6. mock start/stop/restart command queue
7. heartbeat/stuck 상태 시뮬레이션

이렇게 해야 실제 request 분석 전에도 **18대 PC 기반 운영 골격**을 먼저 검증할 수 있다.
