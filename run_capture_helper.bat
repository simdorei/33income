@echo off
setlocal
cd /d %~dp0
if not exist .venv\Scripts\activate.bat (
  echo .venv not found. Run setup_windows.bat first.
  exit /b 1
)
call .venv\Scripts\activate.bat
if not defined INCOME33_CAPTURE_DIR set INCOME33_CAPTURE_DIR=captures
python -m uvicorn income33.capture.app:app --host 127.0.0.1 --port 33133
