@echo off
rem 字が欠けないかを確かめる見本（架空の第998号）を作り、できたフォルダを開く。
setlocal
cd /d "%~dp0"
title 確かめ用の見本を作る
call "%~dp0_find_python.bat"
if not defined PYFOUND (
    echo.
    echo  [エラー] 使える Python が見つかりませんでした。
    echo  python.org の Windows 用 Python を入れ直してください。
    echo  入れる画面のいちばん下の「Add Python to PATH」に必ずチェックを入れてください。
    echo.
    pause
    exit /b 1
)
%PY% check_sample.py
echo.
echo  できました。開いたフォルダの「出力」の中にある 第998号.docx を Word で開き、
echo  行の端や段の下の字が切れていないか、写真のまわりの字が重なっていないかを見てください。
echo.
start "" explorer "%~dp0試し出力\確かめ用_第998号"
pause
