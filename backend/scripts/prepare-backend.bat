@echo off
REM Create the backend virtualenv that desktop installers bundle.
REM Run this once on a fresh clone, before `tauri build` or nsis\build-setup.cmd.
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
  echo Creating backend\.venv ...
  python -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Failed to create venv. Is Python on PATH?
    exit /b 1
  )
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Failed to install backend dependencies.
  exit /b 1
)

echo Backend venv ready: %CD%\.venv
endlocal
