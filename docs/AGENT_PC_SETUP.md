# AGENT_PC_SETUP (Windows)

각 봇 PC는 Windows 기준으로 아래처럼 배치합니다.

## 1. 배포/설치

권장: release ZIP을 받아 `C:\33income`에 압축 해제 후 실행.

개발 clone 방식:

```bat
git clone <repo-url> C:\33income
cd /d C:\33income
setup_windows.bat
```

## 2. agent 설정

### .env 방식(권장)

`C:\33income\.env` 수정:

```text
CONTROL_TOWER_URL=http://관제PC_IP:8330
INCOME33_AGENT_PC_ID=pc-01
INCOME33_AGENT_HOSTNAME=WIN-PC-01
INCOME33_AGENT_IP_ADDRESS=192.168.10.101
INCOME33_AGENT_BOT_ID=sender-01
INCOME33_AGENT_BOT_TYPE=sender
INCOME33_AGENT_HEARTBEAT_INTERVAL_SECONDS=30
INCOME33_LOG_LEVEL=DEBUG
INCOME33_LOG_DIR=logs
INCOME33_HTTP_TIMEOUT_SECONDS=10
```

### config/agent.yaml 방식

`C:\33income\config\agent.yaml` 수정:

```yaml
agent:
  pc_id: pc-01
  hostname: WIN-PC-01
  ip_address: 192.168.10.101
  control_tower_url: http://192.168.10.10:8330
  heartbeat_interval_seconds: 30

bot:
  bot_id: sender-01
  bot_type: sender
```

## 3. 실행

```bat
cd /d C:\33income
run_agent.bat
```

agent 동작:

1. bot mock 상태 tick
2. 관제 heartbeat 전송
3. 명령 큐 poll (`start/stop/restart/status`)
4. 처리 완료 ack

## 4. 로그

기본 로그 파일:

- `logs/agent.log`
- (단일 디버깅 실행 시) `logs/sender.log`, `logs/reporter.log`

단일 디버깅:

```bat
run_sender.bat
run_reporter.bat
```

## 5. 초기 권장 매핑

- `pc-01` ~ `pc-09` → `sender-01` ~ `sender-09`
- `pc-10` ~ `pc-18` → `reporter-01` ~ `reporter-09`

## 6. 자동 시작(후보)

- 시작프로그램 폴더
- 작업 스케줄러
- NSSM/서비스화(추후)
