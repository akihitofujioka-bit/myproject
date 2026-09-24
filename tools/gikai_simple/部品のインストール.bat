@echo off
rem このファイルは Shift_JIS(CP932) で保存しています。
rem chcp で文字コードを変えると、ここの日本語が化けるので変えないこと。
rem 議会だより かんたん原稿ツール に必要な部品を入れる（Windows・インターネット不要）
cd /d "%~dp0"

echo 必要な部品を入れます（wheels フォルダの中だけを見ます。インターネットは使いません）。
echo.

where py >nul 2>nul && (
  py -m pip install --no-index --find-links=wheels python-docx Pillow
  goto done
)
where python >nul 2>nul && (
  python -m pip install --no-index --find-links=wheels python-docx Pillow
  goto done
)
echo Python が見つかりません。
echo python.org から Python を入れて、インストール時に
echo 「Add Python to PATH」にチェックを入れてください。
pause
exit /b

:done
echo.
echo 終わりました。起動.bat をダブルクリックして使ってください。
pause
