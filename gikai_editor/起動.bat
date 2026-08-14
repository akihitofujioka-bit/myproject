@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo   議会だより 原稿編集ツール
echo ============================================================
echo.
echo 起動しています。しばらくお待ちください...
echo ブラウザが自動で開きます。
echo.
echo 終了するときは、この黒い画面で Ctrl キーを押しながら C を押してください。
echo ============================================================
echo.

rem Python を探す（py ランチャーを優先）
where py >nul 2>&1
if %errorlevel%==0 (
    py -3 app.py %*
    goto :end
)

where python >nul 2>&1
if %errorlevel%==0 (
    python app.py %*
    goto :end
)

echo.
echo [エラー] Python が見つかりませんでした。
echo.
echo 下のページから Python をインストールしてください。
echo    https://www.python.org/downloads/windows/
echo.
echo インストール画面の一番下にある
echo 「Add Python to PATH」に必ずチェックを入れてください。
echo これを忘れると、このツールは起動できません。
echo.

:end
echo.
pause
