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

if "%INCOME33_LOG_LEVEL%"=="" set "INCOME33_LOG_LEVEL=DEBUG"
if "%INCOME33_LOG_DIR%"=="" set "INCOME33_LOG_DIR=logs"
if not exist "%INCOME33_LOG_DIR%" mkdir "%INCOME33_LOG_DIR%"

set "PYTHONPATH=%CD%\src"

".venv\Scripts\python.exe" -m income33.control_tower.app
