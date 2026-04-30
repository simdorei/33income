@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>nul
cd /d "%~dp0"

echo [33income] Windows setup started...

call :find_python
if defined PY_CMD goto have_python

echo [INFO] Python was not found. Trying automatic install with winget...
call :install_python
if errorlevel 1 goto fail
call :refresh_path
call :find_python
if defined PY_CMD goto have_python

echo [ERROR] Python install was attempted but Python is still not available.
echo [KO] Python 3.10 or newer must be installed before setup can continue.
echo [EN] Install Python 3.10 or newer, then run setup_windows.bat again.
echo [KO] Download: https://www.python.org/downloads/windows/
echo [EN] Download: https://www.python.org/downloads/windows/
goto fail

:have_python
echo [INFO] Python command: %PY_CMD% %PY_ARGS%
call :run_python --version
if errorlevel 1 goto fail

if exist ".venv\Scripts\python.exe" goto venv_exists
echo [1/7] Creating virtual environment .venv...
call :run_python -m venv .venv
if errorlevel 1 goto fail
goto venv_ready

:venv_exists
echo [1/7] .venv already exists. Skipping creation.

:venv_ready
echo [2/7] Upgrading pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto fail

echo [3/7] Installing requirements...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail

if exist ".env" goto env_exists
echo [4/7] Creating .env from .env.example...
copy /Y ".env.example" ".env" >nul
if errorlevel 1 goto fail
goto env_ready

:env_exists
echo [4/7] .env already exists. Skipping copy.

:env_ready
if exist "config\control_tower.yaml" goto control_config_exists
echo [5/7] Creating config\control_tower.yaml from example...
copy /Y "config\control_tower.example.yaml" "config\control_tower.yaml" >nul
if errorlevel 1 goto fail
goto control_config_ready

:control_config_exists
echo [5/7] config\control_tower.yaml already exists. Skipping copy.

:control_config_ready
if exist "config\agent.yaml" goto agent_config_exists
echo [6/7] Creating config\agent.yaml from example...
copy /Y "config\agent.example.yaml" "config\agent.yaml" >nul
if errorlevel 1 goto fail
goto agent_config_ready

:agent_config_exists
echo [6/7] config\agent.yaml already exists. Skipping copy.

:agent_config_ready
if exist "logs" goto logs_exists
echo [7/7] Creating logs directory...
mkdir "logs"
if errorlevel 1 goto fail
goto logs_ready

:logs_exists
echo [7/7] logs directory already exists. Skipping creation.

:logs_ready
echo.
echo [OK] Setup complete.
echo Next:
echo   1. run_control_tower.bat   - control tower PC
echo   2. run_agent.bat           - each bot PC
exit /b 0

:find_python
set "PY_CMD="
set "PY_ARGS="
py -3 --version >nul 2>nul
if errorlevel 1 goto check_python_cmd
set "PY_CMD=py"
set "PY_ARGS=-3"
goto :eof

:check_python_cmd
python --version >nul 2>nul
if errorlevel 1 goto check_python312
set "PY_CMD=python"
set "PY_ARGS="
goto :eof

:check_python312
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" goto use_python312
goto check_python311

:use_python312
set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
set "PY_ARGS="
goto :eof

:check_python311
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" goto use_python311
goto check_python310

:use_python311
set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
set "PY_ARGS="
goto :eof

:check_python310
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" goto use_python310
goto :eof

:use_python310
set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
set "PY_ARGS="
goto :eof

:run_python
if "%PY_ARGS%"=="" goto run_python_no_args
"%PY_CMD%" %PY_ARGS% %*
exit /b %ERRORLEVEL%

:run_python_no_args
"%PY_CMD%" %*
exit /b %ERRORLEVEL%

:refresh_path
set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts;%LOCALAPPDATA%\Programs\Python\Python310;%LOCALAPPDATA%\Programs\Python\Python310\Scripts;%USERPROFILE%\AppData\Local\Microsoft\WindowsApps"
goto :eof

:install_python
where winget >nul 2>nul
if errorlevel 1 goto winget_missing
echo [INFO] Running winget install for Python.Python.3.12...
winget install --id Python.Python.3.12 --exact --scope user --accept-source-agreements --accept-package-agreements
if errorlevel 1 goto winget_failed
echo [INFO] winget install completed. Re-checking Python...
exit /b 0

:winget_missing
echo [ERROR] winget command was not found.
echo [KO] Python automatic install cannot continue. Install Python manually.
echo [EN] Automatic install cannot continue. Install Python manually.
echo [KO] Download: https://www.python.org/downloads/windows/
echo [EN] Download: https://www.python.org/downloads/windows/
exit /b 1

:winget_failed
echo [ERROR] winget failed to install Python.Python.3.12.
echo [KO] Run this manually or install Python from python.org:
echo [EN] Run this manually or install Python from python.org:
echo winget install --id Python.Python.3.12 --exact --scope user --accept-source-agreements --accept-package-agreements
echo https://www.python.org/downloads/windows/
exit /b 1

:fail
echo.
echo [FAILED] setup_windows.bat failed. Fix the message above and retry.
echo If this window closes too fast, run setup_windows_debug.bat and send setup_windows_debug.log.
pause
exit /b 1
