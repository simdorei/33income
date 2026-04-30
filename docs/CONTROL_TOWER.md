# CONTROL_TOWER

`income33.control_tower.app`는 Windows 관제 PC에서 실행하는 mock 관제 서버입니다.

## 실행

```bat
cd /d C:\33income
run_control_tower.bat
```

또는 직접:

```bat
python -m uvicorn income33.control_tower.app:app --host 127.0.0.1 --port 8330
```

내부망 공개:

```bat
python -m uvicorn income33.control_tower.app:app --host 0.0.0.0 --port 8330
```

> 내부망 공개 시 Windows 방화벽에서 8330 허용 필요.

## 로그

기본 로그 파일:

- `logs/control_tower.log`

환경변수:

```text
INCOME33_LOG_LEVEL=DEBUG
INCOME33_LOG_DIR=logs
```

운영에서는 `INCOME33_LOG_LEVEL=INFO`로 낮출 수 있습니다.

## 기본 URL

- `http://127.0.0.1:8330`

## mock 초기 데이터

- agents 18대 (`pc-01` ~ `pc-18`)
- bots 18대
  - sender 9대 (`sender-01` ~ `sender-09`)
  - reporter 9대 (`reporter-01` ~ `reporter-09`)
- 초기 상태는 절반 online/절반 offline mock으로 시드됨

## API

### 1) 상태 조회

- `GET /api/health`
- `GET /api/summary`
- `GET /api/agents`
- `GET /api/bots`
- `GET /api/bots?bot_type=sender`
- `GET /api/bots?bot_type=reporter`

### 2) 명령 큐

- `POST /api/bots/{bot_id}/commands`
  - body: `{ "command": "start|stop|restart|status|open_login|login_done", "payload": {} }`
- `GET /api/agents/{pc_id}/commands/poll`
  - pending 명령을 running으로 전환해 반환
- `POST /api/commands/{command_id}/complete`
  - body: `{ "status": "done|failed", "error_message": null }`

### 3) heartbeat

- `POST /api/agents/heartbeat`
  - agent/bot 상태 upsert

## 대시보드

`GET /`에서 아래를 확인/제어 가능:

- 전체 요약 (agents/bots 카운트)
- agent 테이블
- bot 테이블
- bot별 버튼: `시작`, `중지`, `재시작`, `로그인 열기`, `로그인 완료`

`로그인 열기`는 관제 웹에서 직접 원격 화면을 스트리밍하는 기능이 아니라, 명령 큐를 통해 해당 봇 PC의 agent에게 브라우저를 열라고 지시합니다. agent는 `INCOME33_LOGIN_URL`을 전용 프로필(`INCOME33_PROFILE_ROOT/<bot_id>`)로 열고, 사람은 그 봇 PC 화면/원격접속에서 카카오 인증 등 수동 로그인을 완료합니다. 완료 후 관제에서 `로그인 완료`를 누르면 해당 봇을 `idle` 상태로 돌립니다. 서버/CI 검증에서는 `INCOME33_LOGIN_DRY_RUN=1`로 실제 브라우저 실행 없이 큐와 상태 전이만 확인할 수 있습니다.

현재는 mock UI/JSON 확인 목적이며, 실제 업무 자동화 제어는 후속 단계입니다.
