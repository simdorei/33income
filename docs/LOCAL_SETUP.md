# LOCAL_SETUP (Windows 기준)

이 문서는 `33income`를 **Windows 로컬 PC에서 바로 실행**하기 위한 단계입니다.

## 0. 전제

- 운영 환경은 전부 Windows
  - 관제 PC: Windows
  - 봇 PC 18대: Windows
- Python 3.10+ 권장
  - `setup_windows.bat`는 `py/python`이 없으면 `winget`으로 Python 자동 설치를 먼저 시도합니다.
  - `winget` 미사용 환경이면 Python 수동 설치가 필요합니다.
- Git for Windows 설치 (public repo clone/update 기준)

## 1. 배포 방식

### 권장: Git clone/update 배포

```bat
cd /d C:\
git clone https://github.com/simdorei/33income.git C:\33income
cd /d C:\33income
setup_windows.bat
```

이미 받은 PC에서 업데이트:

```bat
cd /d C:\33income
install_or_update_33income.bat
```

아직 `C:\33income`이 없는 PC에서 통합 스크립트를 바로 받아 실행:

```bat
powershell -NoProfile -ExecutionPolicy Bypass -Command "iwr -UseBasicParsing https://raw.githubusercontent.com/simdorei/33income/main/install_or_update_33income.bat -OutFile $env:TEMP\install_or_update_33income.bat" && "%TEMP%\install_or_update_33income.bat"
```

## 2. 초기 세팅

```bat
cd /d C:\33income
setup_windows.bat
```

`setup_windows.bat`가 수행하는 작업:

1. `py/python` 확인, 없으면 `winget` Python 자동 설치 시도
2. `.venv` 생성
3. pip 업그레이드
4. `requirements.txt` 설치
5. `.env` 생성(없을 때)
6. `config/control_tower.yaml` 생성(없을 때)
7. `config/agent.yaml` 생성(없을 때)
8. `logs` 폴더 생성

## 2-1. 업데이트 시 데이터 보존

- `.env`, `config/control_tower.yaml`, `config/agent.yaml`, `data/`, `logs/`, `profiles/`는 git에 올라가지 않습니다.
- `install_or_update_33income.bat`는 `git fetch origin main` + `git reset --hard origin/main`으로 tracked 코드를 강제 업데이트한 뒤 `setup_windows.bat`를 실행합니다.
- 로컬 tracked 코드 수정은 버려지지만, `.env`/`config/*.yaml`/`data`/`logs`/`profiles`처럼 git-ignored인 운영 파일은 유지됩니다.
- `setup_windows.bat`는 `.env`/`config/*.yaml`이 없을 때만 example 파일을 복사해 초기화합니다.

## 3. 관제 PC 실행

```bat
cd /d C:\33income
run_control_tower.bat
```

확인 URL:

```text
http://127.0.0.1:8330
```

내부망 공개 실행 예:

```bat
python -m uvicorn income33.control_tower.app:app --host 0.0.0.0 --port 8330
```

> 이 경우 Windows Defender 방화벽에서 TCP 8330 인바운드 허용 필요.

## 4. 봇 PC 실행

각 봇 PC마다:

```bat
cd /d C:\33income
run_agent.bat
```

단일 디버깅:

```bat
run_sender.bat
run_reporter.bat
```

## 5. 로그/타임아웃 설정

기본 예시 (`.env`):

```text
INCOME33_LOG_LEVEL=DEBUG
INCOME33_LOG_DIR=logs
INCOME33_HTTP_TIMEOUT_SECONDS=10
```

로그 파일:

- `logs/control_tower.log`
- `logs/agent.log`
- `logs/sender.log`
- `logs/reporter.log`

운영에서 로그량을 줄일 때:

```text
INCOME33_LOG_LEVEL=INFO
```

## 6. 관제 주소 설정

`.env` 또는 `config/agent.yaml`에 관제 주소를 지정합니다.

```text
CONTROL_TOWER_URL=http://관제PC_IP:8330
```

예:

```text
CONTROL_TOWER_URL=http://192.168.10.10:8330
```

## 7. 폴더 예시 (Windows)

- `C:\33income\data\33income.db`
- `C:\33income\profiles\sender-01`
- `C:\33income\logs\agent.log`

## 8. Windows 자동 시작(후보)

현재 레포에서는 자동시작을 직접 구성하지 않습니다. 후보만 유지:

- 시작프로그램 폴더
- 작업 스케줄러
- NSSM/서비스화(추후 단계)
