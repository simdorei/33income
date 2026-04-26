# 33income (Windows-first)

`33income`는 **Windows 관제 PC + Windows 봇 PC 18대** 기준으로 시작하는 운영 골격 레포입니다.

- 관제: FastAPI control tower (`http://127.0.0.1:8330`)
- 봇 PC: local agent + sender/reporter mock runner
- DB: SQLite (`data/33income.db`)
- 목적: 실제 사이트 자동화 전, 멀티-PC 운영 구조를 먼저 검증

> 실제 사이트 자동화 로직은 아직 포함하지 않았고, 현재는 mock 기반 관제/agent/bot 골격입니다.

---

## 1) Windows 빠른 시작

예시 경로:

- `C:\33income\`
- `C:\33income\data\33income.db`
- `C:\33income\profiles\sender-01`
- `C:\33income\logs\sender-01`

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

## 2) 실행 명령 기준 (Windows)

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

## 3) Agent 관제 주소 설정

`.env` 또는 `config/agent.yaml`에서 설정합니다.

```text
CONTROL_TOWER_URL=http://관제PC_IP:8330
```

예:

```text
CONTROL_TOWER_URL=http://192.168.10.10:8330
```

---

## 4) 문서

- `docs/PLAN.md` - 전체 운영/아키텍처 계획 원문
- `docs/LOCAL_SETUP.md` - Windows 로컬 셋업 상세
- `docs/CONTROL_TOWER.md` - 컨트롤타워 API/대시보드
- `docs/AGENT_PC_SETUP.md` - 봇 PC별 배치/설정

---

## 5) 개발 서버(Linux) 검증용만

실운영은 Windows가 기준이며, 아래는 개발/검증 환경에서만 사용합니다.

```bash
python -m compileall src
PYTHONPATH=src python - <<'PY'
from income33.control_tower.app import app
print(app.title)
PY
```
