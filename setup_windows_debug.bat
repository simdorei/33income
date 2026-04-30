@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>nul
cd /d "%~dp0"

set "LOG=setup_windows_debug.log"
echo [33income] writing setup log to %CD%\%LOG%

echo ===== 33income setup debug %DATE% %TIME% ===== > "%LOG%"
echo cwd=%CD% >> "%LOG%"
echo user=%USERNAME% computer=%COMPUTERNAME% >> "%LOG%"
echo. >> "%LOG%"

echo --- git log -1 --oneline --- >> "%LOG%"
git log -1 --oneline >> "%LOG%" 2>&1
echo errorlevel=%ERRORLEVEL% >> "%LOG%"

echo --- where py --- >> "%LOG%"
where py >> "%LOG%" 2>&1
echo errorlevel=%ERRORLEVEL% >> "%LOG%"

echo --- where python --- >> "%LOG%"
where python >> "%LOG%" 2>&1
echo errorlevel=%ERRORLEVEL% >> "%LOG%"

echo --- where winget --- >> "%LOG%"
where winget >> "%LOG%" 2>&1
echo errorlevel=%ERRORLEVEL% >> "%LOG%"

echo --- where git --- >> "%LOG%"
where git >> "%LOG%" 2>&1
echo errorlevel=%ERRORLEVEL% >> "%LOG%"

echo --- py -0p --- >> "%LOG%"
py -0p >> "%LOG%" 2>&1
echo errorlevel=%ERRORLEVEL% >> "%LOG%"

echo --- py -3 --version --- >> "%LOG%"
py -3 --version >> "%LOG%" 2>&1
echo errorlevel=%ERRORLEVEL% >> "%LOG%"

echo --- python --version --- >> "%LOG%"
python --version >> "%LOG%" 2>&1
echo errorlevel=%ERRORLEVEL% >> "%LOG%"

echo --- winget --version --- >> "%LOG%"
winget --version >> "%LOG%" 2>&1
echo errorlevel=%ERRORLEVEL% >> "%LOG%"

echo --- common python paths --- >> "%LOG%"
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" echo Python312=yes >> "%LOG%"
if not exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" echo Python312=no >> "%LOG%"
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" echo Python311=yes >> "%LOG%"
if not exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" echo Python311=no >> "%LOG%"
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" echo Python310=yes >> "%LOG%"
if not exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" echo Python310=no >> "%LOG%"

echo --- root files --- >> "%LOG%"
dir /b >> "%LOG%" 2>&1

echo --- setup output --- >> "%LOG%"
call setup_windows.bat >> "%LOG%" 2>&1
set "SETUP_RC=%ERRORLEVEL%"

echo setup_exit_code=%SETUP_RC% >> "%LOG%"
if "%SETUP_RC%"=="0" goto ok

echo [FAILED] setup_windows.bat failed. Open or send this file:
echo "%CD%\%LOG%"
goto done

:ok
echo [OK] setup_windows.bat succeeded.

:done
echo.
echo Press any key to close...
pause >nul
exit /b %SETUP_RC%
