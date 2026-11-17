@echo off
title Geox
cd /d "%~dp0"

if exist "%~dp0Geox.exe" (
    if "%~1"=="" (
        "%~dp0Geox.exe" server
    ) else (
        "%~dp0Geox.exe" %*
    )
) else (
    if "%~1"=="" (
        call "%~dp0run_geox.bat" server
    ) else (
        call "%~dp0run_geox.bat" %*
    )
    if errorlevel 1 (
        echo.
        echo [Geox] Application stopped.
        pause
    )
)
