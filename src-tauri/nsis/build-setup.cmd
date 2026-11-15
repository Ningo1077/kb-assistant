@echo off
REM Rebuild the KB-Assistant NSIS installer without an MSVC toolchain.
REM   1) create a clean EMPTY seed database (never copy the dev machine's app.db)
REM   2) compile setup.nsi with the NSIS tools cached in target\.tauri\NSIS
REM Output: ..\target\release\bundle\nsis\KB-Assistant_<VERSION>_x64-setup.exe
setlocal
cd /d "%~dp0"

if not exist seed mkdir seed

if not exist "..\..\backend\.venv\Scripts\python.exe" (
  echo [ERROR] backend\.venv missing. Run backend\scripts\prepare-backend.bat first.
  exit /b 1
)

set "PY=..\..\backend\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "..\..\backend\scripts\make_seed_db.py" "seed\app.db"
if errorlevel 1 (
  echo [ERROR] Cannot create empty seed database
  exit /b 1
)

"..\target\.tauri\NSIS\Bin\makensis.exe" setup.nsi
if errorlevel 1 (
  echo [ERROR] NSIS build failed
  exit /b 1
)

echo.
echo Done: ..\target\release\bundle\nsis\KB-Assistant_^<VERSION^>_x64-setup.exe
endlocal
