@echo off
setlocal

cd /d "%~dp0"

echo RTPS: %CD%
echo.

where git >nul 2>nul
if errorlevel 1 (
    if exist "C:\Program Files\Git\cmd\git.exe" (
        set "PATH=C:\Program Files\Git\cmd;%PATH%"
    )
)

where git >nul 2>nul
if errorlevel 1 (
    echo Git not found. Install Git for Windows or open a new terminal.
    pause
    exit /b 1
)

echo Pulling latest changes...
git pull --ff-only
if errorlevel 1 (
    echo.
    echo git pull failed. Fix the message above, then run this file again.
    pause
    exit /b 1
)

echo.
echo Starting Codex...
where codex >nul 2>nul
if errorlevel 1 (
    echo Codex command not found. Open Codex manually and select this folder:
    echo %CD%
    pause
    exit /b 1
)

codex
