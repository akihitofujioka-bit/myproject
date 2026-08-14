@echo off
setlocal
cd /d "%~dp0"

title 議会だより 原稿編集ツール

call "%~dp0_find_python.bat"

if not defined PYFOUND (
    echo.
    echo  [エラー] 使える Python が見つかりませんでした。
    echo.
    echo  次のものを順に試しましたが、どれも動きませんでした。
    echo     py ランチャー / python / python3 / よくあるインストール先
    echo.
    echo  ほかのソフトが入れた Python が PATH に残っていて、
    echo  それが壊れている場合もこの表示になります。
    echo.
    echo  下のページから Python をインストールし直してください。
    echo     https://www.python.org/downloads/windows/
    echo.
    echo  インストール画面の一番下にある
    echo  「Add Python to PATH」に必ずチェックを入れてください。
    echo.
    pause
    exit /b 1
)

set "READY=%TEMP%\gikai_editor_run.json"
del "%READY%" >nul 2>&1

echo.
echo   議会だより 原稿編集ツール を起動しています...
echo   ブラウザが開いたら、この画面は自動で閉じます。
echo.

start "" %PYW% "%~dp0app.py"

for /l %%i in (1,1,20) do (
    if exist "%READY%" goto ready
    timeout /t 1 /nobreak >nul 2>&1 || ping -n 2 127.0.0.1 >nul 2>&1
)

echo.
echo  [エラー] 起動できませんでした。
echo.
echo  使おうとした Python: %PY%
echo.
if exist "%~dp0起動エラー.log" (
    echo  --- 記録された内容 ---
    type "%~dp0起動エラー.log"
    echo.
)
echo  この画面の内容を担当者にお伝えください。
echo.
pause
exit /b 1

:ready
rem 起動できたので、この画面は閉じる。
rem 終わるときはブラウザ画面の右上「終了」ボタンを押すこと。
exit /b 0
