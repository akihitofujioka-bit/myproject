@echo off
setlocal
cd /d "%~dp0"

title 議会だより 原稿編集ツール

rem ============================================================
rem  Python を探す
rem   PY  : 画面ありの Python（エラーを見せるときに使う）
rem   PYW : 画面なしの Python（本体はこちらで動かす）
rem ============================================================
set "PY="
where py     >nul 2>&1 && set "PY=py"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )

if not defined PY (
    echo.
    echo  [エラー] Python が見つかりませんでした。
    echo.
    echo  下のページから Python をインストールしてください。
    echo     https://www.python.org/downloads/windows/
    echo.
    echo  インストール画面の一番下にある
    echo  「Add Python to PATH」に必ずチェックを入れてください。
    echo  これを忘れると、このツールは起動できません。
    echo.
    pause
    exit /b 1
)

set "PYW="
where pyw      >nul 2>&1 && set "PYW=pyw"
if not defined PYW ( where pythonw >nul 2>&1 && set "PYW=pythonw" )
if not defined PYW set "PYW=%PY%"

rem ============================================================
rem  起動の目印を消してから、画面を出さずに起動する
rem ============================================================
set "READY=%TEMP%\gikai_editor_run.json"
del "%READY%" >nul 2>&1

echo.
echo   議会だより 原稿編集ツール を起動しています...
echo   ブラウザが開いたら、この画面は自動で閉じます。
echo.

start "" %PYW% "%~dp0app.py"

rem ============================================================
rem  立ち上がるまで待つ（最大 20 秒）
rem ============================================================
for /l %%i in (1,1,20) do (
    if exist "%READY%" goto ready
    timeout /t 1 /nobreak >nul 2>&1 || ping -n 2 127.0.0.1 >nul 2>&1
)

echo.
echo  [エラー] 起動できませんでした。
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
rem 本体は画面なしで動き続けるので、終わるときは
rem ブラウザ画面の右上「終了」ボタンを押すこと。
exit /b 0
