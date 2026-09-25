@echo off
rem 議会だより 前年同月号 差し込みツールを起動する
rem このファイルは Shift_JIS(CP932)・CRLF で保存している。UTF-8 にすると日本語が化ける
cd /d "%~dp0"
where py >nul 2>nul && (start "" pyw -3 app.pyw & exit /b)
where pythonw >nul 2>nul && (start "" pythonw app.pyw & exit /b)
echo Python が見つかりません。python.org から Python を入れて、
echo インストールの最初の画面で「Add Python to PATH」にチェックを付けてください。
echo 追加の部品は要りません（Python だけで動きます）。
pause
