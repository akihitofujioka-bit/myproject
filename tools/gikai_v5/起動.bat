@echo off
rem 号フォルダをこのファイルに落とすと、その号を開いて起動する
cd /d "%~dp0"
where pyw >nul 2>nul
if %errorlevel%==0 (
  start "" pyw -3 app.pyw %1
) else (
  start "" pythonw app.pyw %1
)
