@echo off
rem 架空の見本の号（第999号）と、格子の確かめ用の Word を作り、できたフォルダを開く。
rem 役場のパソコンの Word で、ツールの計算どおりに文字が並ぶかを確かめるために使う。
setlocal
cd /d "%~dp0"
title 確かめ用の見本を作る
call "%~dp0_find_python.bat"
if not defined PYFOUND (
    echo.
    echo  [エラー] 使える Python が見つかりませんでした。
    echo.
    echo  py ランチャー / python / python3 / よくあるインストール先 を順に試しましたが、
    echo  どれも動きませんでした。ほかのソフトが入れた Python が残っていて、
    echo  それが壊れている場合もこの表示になります。
    echo.
    echo  python.org の Windows 用 Python をインストールし直してください。
    echo  インストール画面の一番下の「Add Python to PATH」に必ずチェックを入れてください。
    echo.
    pause
    exit /b 1
)
%PY% demo_edition.py
%PY% trial.py
echo.
echo  できました。開いたフォルダの中の次の 2 つを Word で開いてください。
echo    段階1_格子の確認.docx  … どの行も「終」の字が段の下の端に来ていれば計算どおり
echo    第999号\出力\第999号.docx … 文字が枠からはみ出していないか
echo.
start "" explorer "%~dp0試し出力"
pause
