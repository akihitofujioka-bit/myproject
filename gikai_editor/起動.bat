@echo off
rem 議会だより 原稿編集ツール（Windows 用）
chcp 65001 > nul
cd /d "%~dp0"

where python > nul 2>&1
if errorlevel 1 (
  echo Python が見つかりません。
  echo https://www.python.org/downloads/windows/ からインストールしてください。
  echo インストール時に「Add Python to PATH」に必ずチェックを入れてください。
  pause
  exit /b 1
)

python app.py %*
pause
