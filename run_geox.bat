@echo off
setlocal
cd /d "%~dp0"

rem ---------- 1) existing venv wins ----------
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
  ".venv\Scripts\python.exe" -m geox.server
  goto end
)

rem ---------- 2) private runtime (installed by first run) ----------
if exist "runtime\python.exe" (
  "runtime\python.exe" -m pip install --quiet -r requirements.txt
  "runtime\python.exe" -m geox.server
  goto end
)

rem ---------- 3) system python ----------
where py >nul 2>nul
if %errorlevel%==0 (
  echo Setting up Geox for the first time...
  py -3 -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
  ".venv\Scripts\python.exe" -m geox.server
  goto end
)
where python >nul 2>nul
if %errorlevel%==0 (
  echo Setting up Geox for the first time...
  python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
  ".venv\Scripts\python.exe" -m geox.server
  goto end
)

rem ---------- 4) no python at all: download a private copy ----------
echo No Python found - downloading a private copy (~11 MB + dependencies)...
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\bootstrap_python.ps1"
if errorlevel 1 (
  echo Setup failed - check your internet connection.
  pause
  goto end
)
"runtime\python.exe" -m geox.server

:end
pause
