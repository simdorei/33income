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
INCOME33_AGENT_PC_ID=pc-01
INCOME33_AGENT_HOSTNAME=WIN-PC-01
INCOME33_AGENT_IP_ADDRESS=192.168.10.101
INCOME33_AGENT_BOT_ID=sender-01
INCOME33_AGENT_BOT_TYPE=sender
INCOME33_AGENT_HEARTBEAT_INTERVAL_SECONDS=30

INCOME33_LOGIN_URL=https://newta.3o3.co.kr/login?r=%2F
INCOME33_LOGIN_ID=
INCOME33_LOGIN_PASSWORD=
INCOME33_PROFILE_ROOT=profiles
INCOME33_BROWSER_DEBUG_PORT_BASE=29200
INCOME33_BROWSER_CONTROL_DRY_RUN=0

INCOME33_REFRESH_URL=https://newta.3o3.co.kr/tasks/git
INCOME33_REFRESH_INTERVAL_SECONDS=600
INCOME33_REFRESH_ENABLED=0
```

### Playwright/CDP 메모

- 본 구현은 **설치된 Chrome/Edge**를 `--remote-debugging-port`로 띄우고 Playwright Python이 CDP로 붙습니다.
- Playwright Python 패키지는 필요합니다 (`pip install -r requirements.txt`).
- `py -m playwright install chromium`은 Playwright 관리형 브라우저를 직접 쓸 때만 필요합니다.

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

1. bot mock 상태 tick + heartbeat
2. 명령 큐 poll (`start/stop/restart/status/open_login/fill_login/submit_auth_code/refresh_page/login_done`)
3. keepalive 활성화 시(`INCOME33_REFRESH_ENABLED=1`) 600초 기본 주기로 `INCOME33_REFRESH_URL` 새로고침
4. 처리 완료 ack

## 4. NewTA 로그인 관제 흐름 (B안: 인증코드 대시보드 입력)

1. 관제 웹에서 `로그인 열기` 클릭
2. agent가 해당 봇 PC에서 Chrome/Edge를 전용 프로필로 실행
   - `--user-data-dir=profiles/<bot_id>`
   - `--remote-debugging-port=<base+bot 매핑>`
3. 관제 웹에서 `로그인 입력` 클릭 → agent가 `.env`의 `INCOME33_LOGIN_ID/PASSWORD`를 입력 후 로그인 클릭
4. 인증코드 입력 화면이 뜨면 관제 웹에서 `인증코드 제출` 폼에 코드를 입력
5. agent가 CDP로 해당 코드 입력/제출 후 대시보드 세션 유지
6. 필요 시 `새로고침` 버튼으로 즉시 `INCOME33_REFRESH_URL` 이동

보안:

- 비밀번호/인증코드는 로그/응답에 평문으로 남기지 않습니다.
- `.env.example`은 빈 값만 제공합니다.

## 5. 로그

기본 로그 파일:

- `logs/agent.log`
- (단일 디버깅 실행 시) `logs/sender.log`, `logs/reporter.log`

## 6. 초기 권장 매핑

- `pc-01` ~ `pc-09` → `sender-01` ~ `sender-09` (credit/estimate)
- `pc-10` ~ `pc-18` → `reporter-01` ~ `reporter-09` (report)

## 7. 자동 시작(후보)

- 시작프로그램 폴더
- 작업 스케줄러
- NSSM/서비스화(추후)
