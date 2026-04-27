# RELEASE_ZIP

`33income` 임시 프로젝트 배포는 **release ZIP** 기준으로 진행합니다.

## 1) ZIP 생성 (개발 PC)

```bash
cd /path/to/33income
PYTHONPATH=src python scripts/make_release_zip.py
```

커스텀 출력 경로:

```bash
PYTHONPATH=src python scripts/make_release_zip.py --output dist/33income-release.zip
```

## 2) ZIP 포함/제외 기준

### 포함

- `src/`
- `config/*.example.yaml`
- `.env.example`
- `.gitignore`
- `.bat` 실행 파일
- `requirements.txt`, `pyproject.toml`
- `README.md`, `docs/`, `scripts/`

### 제외

- `.git/`, `.venv/`, `__pycache__/`, `.pytest_cache/`
- `data/`, `logs/`, `profiles/`, `tmp/`, `dist/`
- `.env`
- `config/control_tower.yaml`, `config/agent.yaml`

## 3) Windows 배포 절차

1. 생성된 ZIP을 대상 PC로 복사
2. `C:\33income`에 압축 해제
3. 초기화/실행

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

## 4) 참고

- 기본 로그 레벨은 개발 편의를 위해 `DEBUG`를 권장
- 운영 시 `.env`에서 `INCOME33_LOG_LEVEL=INFO`로 낮출 수 있음
