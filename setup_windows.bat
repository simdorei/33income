@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>nul

cd /d "%~dp0"

echo [33income] Windows setup started...

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    set "PY_CMD=py -3"
) else (
    where python >nul 2>nul
    if not %ERRORLEVEL%==0 (
        echo [ERROR] Python launcher(py^) or python.exe was not found.
        echo         Install Python 3.10+ from https://www.python.org/downloads/windows/
        goto :fail
    )
    set "PY_CMD=python"
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/7] Creating virtual environment (.venv)...
    %PY_CMD% -m venv .venv
    if errorlevel 1 goto :fail
) else (
    echo [1/7] .venv already exists. Skipping creation.
)

echo [2/7] Upgrading pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail

echo [3/7] Installing requirements...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

if not exist ".env" (
    echo [4/7] Creating .env from .env.example...
    copy /Y ".env.example" ".env" >nul
) else (
    echo [4/7] .env already exists. Skipping copy.
)

if not exist "config\control_tower.yaml" (
    echo [5/7] Creating config\control_tower.yaml from example...
    copy /Y "config\control_tower.example.yaml" "config\control_tower.yaml" >nul
) else (
    echo [5/7] config\control_tower.yaml already exists. Skipping copy.
)

if not exist "config\agent.yaml" (
    echo [6/7] Creating config\agent.yaml from example...
    copy /Y "config\agent.example.yaml" "config\agent.yaml" >nul
) else (
    echo [6/7] config\agent.yaml already exists. Skipping copy.
)

if not exist "logs" (
    echo [7/7] Creating logs directory...
    mkdir "logs"
) else (
    echo [7/7] logs directory already exists. Skipping creation.
)

echo.
echo [OK] Setup complete.
echo Next:
echo   1^) run_control_tower.bat   (on control tower PC)
echo   2^) run_agent.bat           (on each bot PC)
exit /b 0

:fail
echo.
echo [FAILED] setup_windows.bat failed. Fix the message above and retry.
echo.
echo If this window closes too fast, run setup_windows_debug.bat and send setup_windows_debug.log.
pause
exit /b 1
