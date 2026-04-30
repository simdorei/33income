# 33income (Windows-first)

`33income`는 **Windows 관제 PC + Windows 봇 PC 18대** 기준으로 시작하는 운영 골격 레포입니다.

- 관제: FastAPI control tower (`http://127.0.0.1:8330`)
- 봇 PC: local agent + sender/reporter mock runner
- DB: SQLite (`data/33income.db`)
- 목적: 실제 사이트 자동화 전, 멀티-PC 운영 구조를 먼저 검증

> 실제 사이트 자동화 로직은 아직 포함하지 않았고, 현재는 mock 기반 관제/agent/bot 골격입니다.

---

## 1) 배포 기준: Git clone/update (권장)

수정/업데이트가 계속 있을 운영 PC는 **Git clone** 기준을 권장합니다. Public repo이므로 GitHub 로그인 없이 받을 수 있고, 이후에는 `install_or_update_33income.bat`로 최신 `origin/main`을 강제 반영합니다.

### 1-1. 최초 설치 (Windows 대상 PC)

가장 단순한 방식:

```bat
cd /d C:\
git clone https://github.com/simdorei/33income.git C:\33income
cd /d C:\33income
setup_windows.bat
```

또는 repo 안의 통합 스크립트를 사용합니다:

```bat
cd /d C:\33income
install_or_update_33income.bat
```

아직 `C:\33income` 폴더가 없는 PC에서 스크립트만 바로 내려받아 실행하려면 CMD에서:

```bat
powershell -NoProfile -ExecutionPolicy Bypass -Command "iwr -UseBasicParsing https://raw.githubusercontent.com/simdorei/33income/main/install_or_update_33income.bat -OutFile $env:TEMP\install_or_update_33income.bat" && "%TEMP%\install_or_update_33income.bat"
```

> Git for Windows가 먼저 설치되어 있어야 합니다: https://git-scm.com/download/win

### 1-2. 실행

관제 PC:

```bat
cd /d C:\33income
run_control_tower.bat
```

봇 PC:

```bat
cd /d C:\33income
run_agent.bat
```

### 1-3. 업데이트

```bat
cd /d C:\33income
install_or_update_33income.bat
```

또는 수동으로:

```bat
cd /d C:\33income
git fetch origin main
git reset --hard origin/main
setup_windows.bat
```

`install_or_update_33income.bat`도 위와 같은 강제 업데이트 방식을 사용합니다. 로컬 tracked 코드 수정은 버리고 최신 `origin/main`으로 맞추지만, `.env`, `config/*.yaml`, `data/`, `logs/`, `profiles/`는 git-ignored라 업데이트해도 유지됩니다.

---

## 2) Windows 빠른 시작

예시 경로:

- `C:\33income\`
- `C:\33income\data\33income.db`
- `C:\33income\profiles\sender-01`
- `C:\33income\logs\agent.log`

### 관제 PC (Windows)

```bat
git clone https://github.com/simdorei/33income.git C:\33income
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
git clone https://github.com/simdorei/33income.git C:\33income
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
rem py/python 없으면 winget으로 Python 자동 설치 시도
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

---

## 7) 개발 서버(Linux) 검증용만

실운영은 Windows가 기준이며, 아래는 개발/검증 환경에서만 사용합니다.

```bash
python -m compileall src
PYTHONPATH=src python - <<'PY'
from income33.control_tower.app import app
print(app.title)
PY
```
