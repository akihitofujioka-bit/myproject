@echo off
setlocal
cd /d "%~dp0"

title デスクトップにアイコンを作る

echo.
echo   デスクトップに「議会だより原稿編集ツール」のアイコンを作ります。
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$ws = New-Object -ComObject WScript.Shell;" ^
 "$desktop = [Environment]::GetFolderPath('Desktop');" ^
 "$lnk = Join-Path $desktop '議会だより原稿編集ツール.lnk';" ^
 "$s = $ws.CreateShortcut($lnk);" ^
 "$s.TargetPath = '%~dp0起動.bat';" ^
 "$s.WorkingDirectory = '%~dp0';" ^
 "$s.IconLocation = '%~dp0icon.ico';" ^
 "$s.Description = '議会だより 原稿編集ツール';" ^
 "$s.WindowStyle = 7;" ^
 "$s.Save();" ^
 "Write-Host ('  作成しました: ' + $lnk)"

if errorlevel 1 (
    echo.
    echo  [エラー] アイコンを作れませんでした。
    echo.
    echo  お手数ですが、次の方法でも作れます。
    echo    1. このフォルダの「起動.bat」を右クリック
    echo    2. 「送る」→「デスクトップ (ショートカットを作成)」を選ぶ
    echo    3. できたショートカットを右クリック→「プロパティ」
    echo    4. 「アイコンの変更」で、このフォルダの icon.ico を選ぶ
    echo.
)

echo.
pause
exit /b 0
