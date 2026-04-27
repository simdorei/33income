# 33income (Windows-first)

`33income`는 **Windows 관제 PC + Windows 봇 PC 18대** 기준으로 시작하는 운영 골격 레포입니다.

- 관제: FastAPI control tower (`http://127.0.0.1:8330`)
- 봇 PC: local agent + sender/reporter mock runner
- DB: SQLite (`data/33income.db`)
- 목적: 실제 사이트 자동화 전, 멀티-PC 운영 구조를 먼저 검증

> 실제 사이트 자동화 로직은 아직 포함하지 않았고, 현재는 mock 기반 관제/agent/bot 골격입니다.

---

## 1) 배포 기준: GitHub Download ZIP (권장)

임시 운영/현장 PC 배포는 **Git clone 없이 GitHub `Code > Download ZIP`** 흐름을 기본으로 권장합니다.

### 1-1. ZIP 다운로드/압축 해제 (Windows 대상 PC)

1. GitHub 레포 페이지에서 `Code > Download ZIP`
2. ZIP을 예: `C:\33income-main`에 압축 해제
3. 필요하면 폴더명을 `C:\33income`으로 변경

### 1-2. 초기 실행

관제 PC:

```bat
cd /d C:\33income
setup_windows.bat
run_control_tower.bat
```

봇 PC:

```bat
cd /d C:\33income
setup_windows.bat
run_agent.bat
```

### 1-3. ZIP 방식 업데이트 시 주의

- GitHub ZIP에는 `.env`, `data/`, `logs/`가 포함되지 않습니다.
- `setup_windows.bat`는 `.env`와 `config/*.yaml`이 없을 때 example 파일을 복사해 초기화합니다.
- 기존 운영값을 유지하려면 **새 ZIP을 다른 폴더에 푼 뒤** 아래를 기존 폴더에서 복사하세요.
  - `.env`
  - `config/control_tower.yaml`, `config/agent.yaml`
  - `data/`
  - `logs/`

---

## 2) Windows 빠른 시작 (Git clone은 선택사항)

예시 경로:

- `C:\33income\`
- `C:\33income\data\33income.db`
- `C:\33income\profiles\sender-01`
- `C:\33income\logs\agent.log`

### 관제 PC (Windows)

```bat
git clone <repo-url> C:\33income
cd /d C:\33income
setup_windows.bat
run_control_tower.bat
```

브라우저에서 확인:

```text
http://127.0.0.1:8330
```

### 봇 PC (Windows, 각 PC)

```bat
git clone <repo-url> C:\33income
cd /d C:\33income
setup_windows.bat
run_agent.bat
```

단일 디버깅:

```bat
run_sender.bat
run_reporter.bat
```

---

## 3) 로깅 (개발 기본: 상세)

공통 환경변수:

```text
INCOME33_LOG_LEVEL=DEBUG
INCOME33_LOG_DIR=logs
INCOME33_HTTP_TIMEOUT_SECONDS=10
```

기본 로그 파일:

- `logs/control_tower.log`
- `logs/agent.log`
- `logs/sender.log`
- `logs/reporter.log`

로깅은 console + rotating file handler(기본 5MB × 5개)로 구성됩니다.

운영 시 로그를 줄이려면:

```text
INCOME33_LOG_LEVEL=INFO
```

---

## 4) 실행 명령 기준 (Windows)

`setup_windows.bat` 내부 기준:

```bat
py -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

컨트롤타워 실행 기준:

```bat
python -m uvicorn income33.control_tower.app:app --host 127.0.0.1 --port 8330
```

내부망 공개 시:

```bat
python -m uvicorn income33.control_tower.app:app --host 0.0.0.0 --port 8330
```

> 내부망 공개 시 Windows Defender 방화벽에서 TCP 8330 인바운드 허용이 필요합니다.

---

## 5) Agent 관제 주소 설정

`.env` 또는 `config/agent.yaml`에서 설정합니다.

```text
CONTROL_TOWER_URL=http://관제PC_IP:8330
```

예:

```text
CONTROL_TOWER_URL=http://192.168.10.10:8330
```

---

## 6) 문서

- `docs/PLAN.md` - 전체 운영/아키텍처 계획 원문
- `docs/LOCAL_SETUP.md` - Windows 로컬 셋업 상세
- `docs/CONTROL_TOWER.md` - 컨트롤타워 API/대시보드
- `docs/AGENT_PC_SETUP.md` - 봇 PC별 배치/설정
- `docs/CAPTURE_MODE.md` - 로그인된 브라우저 request 자동 캡처 MVP

---

## 7) Capture Mode: 로그인된 브라우저 요청 캡처

수동으로 DevTools 헤더/body를 복사하지 않고, 로그인된 브라우저에서 발생하는 `fetch`/`XHR`을 로컬 파일로 저장한다.

```bat
cd /d C:\33income
setup_windows.bat
run_capture_helper.bat
```

그 다음 로그인된 페이지에서 `browser_capture_snippet.js`를 DevTools Console/Snippets로 실행하고 평소 작업을 수행한다.

결과 파일:

```text
C:\33income\captures\YYYYMMDD\captures.jsonl
```

기본값으로 `Cookie`, `Authorization`, `token/session/csrf` 계열 헤더 값은 redaction된다.

---

## 8) 개발 서버(Linux) 검증용만

실운영은 Windows가 기준이며, 아래는 개발/검증 환경에서만 사용합니다.

```bash
python -m compileall src
PYTHONPATH=src python - <<'PY'
from income33.control_tower.app import app
print(app.title)
PY
```