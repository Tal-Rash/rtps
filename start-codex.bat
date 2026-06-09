@echo off
setlocal
cd /d "%~dp0" || exit /b 1
echo Working folder: %CD%
echo.
git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 (
  echo ERROR: This folder is not a Git repository.
  pause
  exit /b 1
)

git pull --ff-only
if errorlevel 1 (
  echo.
  echo Git pull failed.
  echo If you see an "Unlink of file ..." message, close any editor,
  echo file manager, or sync client that may be holding the repository,
  echo then run this file again.
  echo.
  pause
  exit /b 1
)
echo.
echo Latest changes are pulled.
echo.
echo Open Codex Desktop manually and select this folder:
echo %CD%
echo.
start "" explorer.exe "%CD%"
pause
