@echo off
setlocal EnableExtensions

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv is missing.
    echo         Run setup_windows.bat first.
    exit /b 1
)

if not exist "config\agent.yaml" (
    echo [ERROR] config\agent.yaml not found.
    echo         Copy from config\agent.example.yaml or rerun setup_windows.bat.
    exit /b 1
)

set "PYTHONPATH=%CD%\src"
".venv\Scripts\python.exe" -m income33.agent.runner
