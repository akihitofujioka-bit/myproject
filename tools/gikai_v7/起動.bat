@echo off
setlocal
cd /d "%~dp0"
title Gikai V7
call "%~dp0_find_python.bat"
if not defined PYFOUND (
    echo Python with tkinter was not found.
    pause
    exit /b 1
)
if "%~1"=="" (
    start "" %PYW% app.pyw
) else (
    start "" %PYW% app.pyw "%~1"
)
