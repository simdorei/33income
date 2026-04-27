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
  - body: `{ "command": "start|stop|restart|status", "payload": {} }`
- `GET /api/agents/{pc_id}/commands/poll`
  - pending 명령을 running으로 전환해 반환
- `POST /api/commands/{command_id}/complete`
  - body: `{ "status": "done|failed", "error_message": null }`

### 3) heartbeat

- `POST /api/agents/heartbeat`
  - agent/bot 상태 upsert

## 대시보드

`GET /`에서 아래를 확인 가능:

- 전체 요약 (agents/bots 카운트)
- agent 테이블
- bot 테이블

현재는 mock UI/JSON 확인 목적이며, 실제 업무 자동화 제어는 후속 단계입니다.
