@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "LOG=setup_windows_debug.log"
echo [33income] writing setup log to %CD%\%LOG%
echo ===== 33income setup debug %DATE% %TIME% ===== > "%LOG%"
echo cwd=%CD% >> "%LOG%"
echo user=%USERNAME% computer=%COMPUTERNAME% >> "%LOG%"
echo. >> "%LOG%"

echo [1/5] Checking commands...
(
  echo --- where py ---
  where py
  echo errorlevel=%ERRORLEVEL%
  echo --- where python ---
  where python
  echo errorlevel=%ERRORLEVEL%
  echo --- where git ---
  where git
  echo errorlevel=%ERRORLEVEL%
) >> "%LOG%" 2>&1

echo [2/5] Python versions...
(
  echo --- py -0p ---
  py -0p
  echo errorlevel=%ERRORLEVEL%
  echo --- py -3 --version ---
  py -3 --version
  echo errorlevel=%ERRORLEVEL%
  echo --- python --version ---
  python --version
  echo errorlevel=%ERRORLEVEL%
) >> "%LOG%" 2>&1

echo [3/5] Folder check...
(
  echo --- dir root ---
  dir /b
  echo --- requirements exists ---
  if exist requirements.txt (echo yes) else (echo no)
  echo --- env example exists ---
  if exist .env.example (echo yes) else (echo no)
) >> "%LOG%" 2>&1

echo [4/5] Running setup_windows.bat...
call setup_windows.bat >> "%LOG%" 2>&1
set "SETUP_RC=%ERRORLEVEL%"

echo [5/5] Result: %SETUP_RC%
echo setup_exit_code=%SETUP_RC% >> "%LOG%"

if "%SETUP_RC%"=="0" (
  echo [OK] setup_windows.bat succeeded.
) else (
  echo [FAILED] setup_windows.bat failed. Open or send this file:
  echo %CD%\%LOG%
)

echo.
echo Press any key to close...
pause >nul
exit /b %SETUP_RC%
