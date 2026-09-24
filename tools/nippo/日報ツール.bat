@echo off
rem 日報ツールを起動する（Windows 用）
rem 文字化けを防ぐため、この画面の文字コードを UTF-8 にする
chcp 65001 >nul
cd /d "%~dp0"

rem py ランチャー → python の順に、実際に動くものを探す
where py >nul 2>nul && (
  start "" pyw nippo.py
  exit /b
)
where pythonw >nul 2>nul && (
  start "" pythonw nippo.py
  exit /b
)
echo Python が見つかりません。
echo python.org から Python を入れて、インストール時に
echo 「Add Python to PATH」にチェックを入れてください。
pause
