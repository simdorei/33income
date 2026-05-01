# CONTROL_TOWER

`income33.control_tower.app`는 Windows 관제 PC에서 실행하는 관제 서버입니다.

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

## 고정 슬롯 초기화

- agents 18대 (`pc-01` ~ `pc-18`)
- bots 18대
  - sender 9대 (`sender-01` ~ `sender-09`)
  - reporter 9대 (`reporter-01` ~ `reporter-09`)
- 초기 상태는 모두 `offline` / `connection_required` / `접속필요`입니다.
- 실제 agent heartbeat가 들어오면 `last_heartbeat_at`이 갱신되고 해당 PC/봇 상태가 연결 상태로 전환됩니다.

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
  - body: `{ "command": "start|stop|restart|status|open_login|fill_login|submit_auth_code|refresh_page|login_done", "payload": {} }`
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
- bot별 버튼/폼:
  - `시작`, `중지`, `재시작`
  - `로그인 열기` (브라우저 실행)
  - `로그인 입력` (ID/PW 자동 입력 후 로그인 클릭)
  - `인증코드 제출` (관제 입력값 전달)
  - `새로고침` (즉시 refresh URL 이동)
  - `로그인 완료`

`로그인 열기`는 관제 웹에서 화면 스트리밍을 제공하는 기능이 아닙니다. 명령 큐를 통해 해당 봇 PC의 agent가 전용 프로필 브라우저를 열고, 이후 CDP를 통해 로그인 입력/인증코드 제출/새로고침 명령을 수행합니다.

보안 메모:

- 인증코드는 명령 payload로 전달되지만 대시보드/로그에 평문으로 재출력하지 않습니다.
- 서버/CI 검증에서는 `INCOME33_BROWSER_CONTROL_DRY_RUN=1`로 실제 브라우저 없이 흐름 검증이 가능합니다.

현재는 관제 UI/JSON 및 명령 큐 확인 목적이며, 실제 업무 자동화 범위는 단계적으로 확장합니다.
