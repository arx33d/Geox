@echo off
title Geox
cd /d "%~dp0"

if exist "%~dp0Geox.exe" (
    "%~dp0Geox.exe" %*
) else (
    call "%~dp0run_geox.bat" %*
)
