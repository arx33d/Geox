@echo off
setlocal
cd /d "%~dp0"
title Geox

rem ============================================================
rem  If Windows blocked this file with a blue "Windows protected
rem  your PC" screen: click "More info" -> "Run anyway".
rem  If right-click -> Properties has an "Unblock" checkbox:
rem  tick it first, then run this file again.
rem ============================================================

rem ---------- 1) existing venv: fastest path ----------
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
  ".venv\Scripts\python.exe" -m geox.server
  goto done
)

rem ---------- 2) private runtime downloaded by a previous run ----------
if exist "runtime\python.exe" (
  "runtime\python.exe" -m pip install --quiet -r requirements.txt
  "runtime\python.exe" -m geox.server
  goto done
)

rem ---------- 3) a real system Python (skips the fake Microsoft Store stub) ------
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys" >nul 2>nul
  if not errorlevel 1 (
    echo Setting up Geox for the first time...
    py -3 -m venv .venv
    if exist ".venv\Scripts\python.exe" goto venv_ready
  )
)
where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys" >nul 2>nul
  if not errorlevel 1 (
    echo Setting up Geox for the first time...
    python -m venv .venv
    if exist ".venv\Scripts\python.exe" goto venv_ready
  )
)

rem ---------- 4) no usable Python: download a private copy ----------
echo No usable Python found. Downloading a private copy, please wait...
if not exist "tools\bootstrap_python.ps1" (
  echo.
  echo tools\bootstrap_python.ps1 is missing. Re-extract the full Geox folder or re-download the release zip.
  pause
  goto done
)
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\bootstrap_python.ps1"
if errorlevel 1 (
  echo.
  echo Setup failed. Check your internet connection and try again.
  pause
  goto done
)
"runtime\python.exe" geox\first_run.py
if errorlevel 1 (
  echo.
  echo Setup failed. Check your internet connection and try again.
  pause
  goto done
)
"runtime\python.exe" -m geox.server
goto done

:venv_ready
".venv\Scripts\python.exe" geox\first_run.py
if errorlevel 1 (
  echo.
  echo Setup failed. Check your internet connection and try again.
  pause
  goto done
)
".venv\Scripts\python.exe" -m geox.server
goto done

:done
echo.
echo Geox has stopped.
pause
