@echo off
rem 議会だより かんたん原稿ツール を起動する
cd /d "%~dp0"
where py >nul 2>nul && (start "" pyw app.pyw & exit /b)
where pythonw >nul 2>nul && (start "" pythonw app.pyw & exit /b)
echo Python が見つかりません。python.org から Python を入れて、
echo インストール時に「Add Python to PATH」にチェックしてください。
pause
