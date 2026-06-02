@echo off
setlocal
cd /d "%~dp0" || exit /b 1
git pull --ff-only
if errorlevel 1 exit /b 1
echo.
echo Latest changes are pulled.
echo.
echo Open Codex Desktop manually and select this folder:
echo %CD%
echo.
start "" explorer.exe "%CD%"
pause
