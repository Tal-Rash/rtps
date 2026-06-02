@echo off
setlocal
cd /d "%~dp0" || exit /b 1
git pull --ff-only
if errorlevel 1 exit /b 1
codex .
