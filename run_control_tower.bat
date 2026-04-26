@echo off
setlocal EnableExtensions

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv is missing.
    echo         Run setup_windows.bat first.
    exit /b 1
)

if not exist "config\control_tower.yaml" (
    echo [ERROR] config\control_tower.yaml not found.
    echo         Copy from config\control_tower.example.yaml or rerun setup_windows.bat.
    exit /b 1
)

if not exist ".env" (
    echo [WARN] .env not found. Using defaults.
)

set "HOST=%INCOME33_CONTROL_TOWER_HOST%"
if "%HOST%"=="" set "HOST=127.0.0.1"
set "PORT=%INCOME33_CONTROL_TOWER_PORT%"
if "%PORT%"=="" set "PORT=8330"

set "PYTHONPATH=%CD%\src"

".venv\Scripts\python.exe" -m uvicorn income33.control_tower.app:app --host %HOST% --port %PORT%
