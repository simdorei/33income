@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM 33income Windows installer/updater
REM - Public repo clone/update helper for control-tower and bot PCs.
REM - Force-updates tracked code with fetch/reset.
REM - Keeps local .env, config\*.yaml, data\, logs\, profiles\ because they are git-ignored.
REM - Warning: local tracked code edits are discarded on update.

set "REPO_URL=https://github.com/simdorei/33income.git"
set "TARGET_DIR=C:\33income"

if not "%INCOME33_REPO_URL%"=="" set "REPO_URL=%INCOME33_REPO_URL%"
if not "%INCOME33_INSTALL_DIR%"=="" set "TARGET_DIR=%INCOME33_INSTALL_DIR%"
if not "%~1"=="" set "TARGET_DIR=%~1"

echo.
echo [33income] Install/update started
echo   repo   : %REPO_URL%
echo   target : %TARGET_DIR%
echo.

where git >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Git for Windows was not found.
    echo         Install Git first: https://git-scm.com/download/win
    echo         Then re-run this script.
    exit /b 1
)

if exist "%TARGET_DIR%\.git" (
    echo [1/3] Existing git checkout found. Force-updating tracked code...
    git -C "%TARGET_DIR%" remote get-url origin >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] %TARGET_DIR% has a .git folder but origin remote is not configured.
        exit /b 1
    )
    git -C "%TARGET_DIR%" fetch origin main
    if errorlevel 1 (
        echo.
        echo [ERROR] git fetch failed.
        exit /b 1
    )
    git -C "%TARGET_DIR%" reset --hard origin/main
    if errorlevel 1 (
        echo.
        echo [ERROR] git reset failed.
        exit /b 1
    )
    echo [INFO] Update complete. Local ignored runtime files such as .env, data, logs, and profiles are preserved.
) else (
    if exist "%TARGET_DIR%" (
        if exist "%TARGET_DIR%\setup_windows.bat" (
            echo [1/3] Existing non-git 33income folder found. Skipping clone.
            echo       For future git updates, rename/delete this folder and run this script again.
        ) else (
            echo [ERROR] Target folder exists but does not look like 33income:
            echo         %TARGET_DIR%
            echo         Remove/rename it, or pass another target path:
            echo         install_or_update_33income.bat D:\33income
            exit /b 1
        )
    ) else (
        echo [1/3] Cloning repository...
        git clone "%REPO_URL%" "%TARGET_DIR%"
        if errorlevel 1 (
            echo [ERROR] git clone failed.
            exit /b 1
        )
    )
)

echo [2/3] Running setup_windows.bat...
cd /d "%TARGET_DIR%"
if errorlevel 1 (
    echo [ERROR] Could not enter target folder: %TARGET_DIR%
    exit /b 1
)

if not exist "setup_windows.bat" (
    echo [ERROR] setup_windows.bat was not found in %TARGET_DIR%.
    exit /b 1
)

call "setup_windows.bat"
if errorlevel 1 (
    echo [ERROR] setup_windows.bat failed.
    exit /b 1
)

echo.
echo [3/3] Done.
echo.
echo Next steps:
echo   - First time on each PC: edit %TARGET_DIR%\.env
echo   - Control tower PC     : run_control_tower.bat
echo   - Bot PC               : run_agent.bat
echo.
echo Update later:
echo   cd /d %TARGET_DIR%
echo   install_or_update_33income.bat
echo.
exit /b 0
