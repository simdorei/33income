# AGENT_PC_SETUP (Windows)

각 봇 PC는 Windows 기준으로 아래처럼 배치합니다.

## 1. 배포/설치

권장: GitHub 레포 페이지에서 `Code > Download ZIP`으로 받아 `C:\33income`에 압축 해제 후 실행.

예)

1. ZIP 다운로드 후 `C:\33income-main`에 압축 해제
2. 필요 시 폴더명을 `C:\33income`으로 변경
3. `setup_windows.bat` 실행

개발 clone 방식(선택):

```bat
git clone <repo-url> C:\33income
cd /d C:\33income
setup_windows.bat
```

ZIP 업데이트 시 기존 운영값 유지:

- 새 ZIP은 다른 폴더에 먼저 풉니다.
- 기존 폴더에서 아래를 복사합니다.
  - `.env`
  - `config/agent.yaml`
  - `data/`
  - `logs/`

## 2. agent 설정

### .env 방식(권장)

`C:\33income\.env` 수정:

```text
CONTROL_TOWER_URL=http://관제PC_IP:8330
INCOME33_LOGIN_URL=about:blank
INCOME33_PROFILE_ROOT=profiles
INCOME33_LOGIN_DRY_RUN=0
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
3. 명령 큐 poll (`start/stop/restart/status/open_login/login_done`)
4. 처리 완료 ack

로그인 관제 흐름:

1. 관제 웹에서 봇 행의 `로그인 열기` 클릭
2. agent가 해당 봇 PC에서 `INCOME33_LOGIN_URL`을 브라우저로 염
3. 브라우저는 `profiles/<bot_id>` 전용 프로필을 사용하므로 쿠키/세션이 봇별로 분리됨
   - 서버 검증/테스트에서는 `INCOME33_LOGIN_DRY_RUN=1`로 실제 브라우저 실행 없이 launch plan만 확인 가능
4. 사람이 봇 PC 화면 또는 원격접속으로 로그인/카카오 인증 완료
5. 관제 웹에서 `로그인 완료` 클릭
6. 봇 상태가 `idle`로 돌아가고 이후 시작/자동화 단계에서 같은 프로필을 재사용

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
