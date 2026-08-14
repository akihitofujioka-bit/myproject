@echo off
setlocal
cd /d "%~dp0"

title 議会だより 原稿編集ツール の終了

set "PY="
where py     >nul 2>&1 && set "PY=py"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )

if not defined PY (
    echo Python が見つかりませんでした。
    pause
    exit /b 1
)

echo.
echo   議会だより 原稿編集ツール を終了しています...
echo.

%PY% "%~dp0app.py" --quit

timeout /t 2 /nobreak >nul 2>&1 || ping -n 3 127.0.0.1 >nul 2>&1
exit /b 0
