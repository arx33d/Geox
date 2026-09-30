@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m geox.cli %*
  exit /b %errorlevel%
)

if exist "runtime\python.exe" (
  "runtime\python.exe" -m geox.cli %*
  exit /b %errorlevel%
)

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m geox.cli %*
  exit /b %errorlevel%
)

where python >nul 2>nul
if %errorlevel%==0 (
  python -m geox.cli %*
  exit /b %errorlevel%
)

echo No Python found - setting up environment first...
call "%~dp0run_geox.bat"
