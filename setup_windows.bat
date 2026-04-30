@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>nul

cd /d "%~dp0"

echo [33income] Windows setup started...
call :resolve_python
if not defined PY_CMD (
    echo [INFO] Python was not found. Trying automatic install with winget...
    call :try_install_python
    if errorlevel 1 goto :fail
    call :refresh_python_search_paths
    call :resolve_python
)
if not defined PY_CMD (
    echo [ERROR] Python install was attempted but Python is still not available.
    echo [KO] Install Python 3.10+ manually, then re-run setup_windows.bat.
    echo [EN] Install Python 3.10+ manually, then re-run setup_windows.bat.
    echo [KO] 권장: winget install --id Python.Python.3.12 --exact --scope user
    echo [EN] Suggested: winget install --id Python.Python.3.12 --exact --scope user
    goto :fail
)
if defined PY_ARGS (
    echo [INFO] Python command: "%PY_CMD%" %PY_ARGS%
) else (
    echo [INFO] Python command: "%PY_CMD%"
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/7] Creating virtual environment .venv...
    call :run_python -m venv .venv
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

:resolve_python
set "PY_CMD="
set "PY_ARGS="
where py >nul 2>nul
if not errorlevel 1 (
    set "PY_CMD=py"
    set "PY_ARGS=-3"
    goto :eof
)

where python >nul 2>nul
if not errorlevel 1 (
    set "PY_CMD=python"
    goto :eof
)

for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
) do (
    if exist "%%~P" (
        set "PY_CMD=%%~fP"
        goto :eof
    )
)
goto :eof

:run_python
if defined PY_ARGS (
    "%PY_CMD%" %PY_ARGS% %*
) else (
    "%PY_CMD%" %*
)
exit /b %ERRORLEVEL%

:refresh_python_search_paths
set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts;%LOCALAPPDATA%\Programs\Python\Python310;%LOCALAPPDATA%\Programs\Python\Python310\Scripts;%USERPROFILE%\AppData\Local\Microsoft\WindowsApps"
goto :eof

:try_install_python
where winget >nul 2>nul
if errorlevel 1 (
    echo [ERROR] winget command was not found.
    echo [KO] 자동 설치를 진행할 수 없습니다. Python 3.10+를 수동 설치하세요.
    echo [EN] Automatic install cannot continue. Install Python 3.10+ manually.
    echo [KO] 설치 예: https://www.python.org/downloads/windows/
    echo [EN] Example: https://www.python.org/downloads/windows/
    echo [KO] 또는 winget 가능 환경에서 아래 실행:
    echo [EN] Or run this where winget is available:
    echo         winget install --id Python.Python.3.12 --exact --scope user --accept-source-agreements --accept-package-agreements --silent
    exit /b 1
)

echo [INFO] Running winget install for Python.Python.3.12...
winget install --id Python.Python.3.12 --exact --scope user --accept-source-agreements --accept-package-agreements --silent --disable-interactivity
if errorlevel 1 (
    echo [ERROR] winget failed to install Python.Python.3.12.
    echo [KO] 수동 설치 후 setup_windows.bat를 다시 실행하세요.
    echo [EN] Install Python manually, then run setup_windows.bat again.
    echo [KO] 설치 예: https://www.python.org/downloads/windows/
    echo [EN] Example: https://www.python.org/downloads/windows/
    echo [KO] 또는 winget 명령을 관리자 CMD에서 직접 실행해 원인을 확인하세요.
    echo [EN] Or run winget command directly in admin CMD to inspect details.
    echo         winget install --id Python.Python.3.12 --exact --scope user --accept-source-agreements --accept-package-agreements --silent
    exit /b 1
)

echo [INFO] winget install completed. Re-checking Python...
exit /b 0

:fail
echo.
echo [FAILED] setup_windows.bat failed. Fix the message above and retry.
echo.
echo If this window closes too fast, run setup_windows_debug.bat and send setup_windows_debug.log.
pause
exit /b 1
