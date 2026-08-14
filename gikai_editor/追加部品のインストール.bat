@echo off
setlocal
cd /d "%~dp0"

title 追加部品のインストール

echo ============================================================
echo   議会だより 原稿編集ツール  追加部品のインストール
echo ============================================================
echo.
echo  次の部品を入れると、できることが増えます。
echo.
echo    Pillow   写真の切り出し・向きの補正・解像度の判定
echo    PyMuPDF  PDF で届いた原稿の読み込み
echo    pypdf    PyMuPDF が使えないときの予備
echo.
echo  部品は「wheels」フォルダに同梱してあります。
echo  インターネットには接続しません。
echo.
pause

set "PY="
where py     >nul 2>&1 && set "PY=py"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )

if not defined PY (
    echo.
    echo  [エラー] Python が見つかりませんでした。
    echo  先に Python をインストールしてください。
    echo     https://www.python.org/downloads/windows/
    echo  インストール画面の「Add Python to PATH」に必ずチェックを。
    echo.
    pause
    exit /b 1
)

if not exist "%~dp0wheels" (
    echo.
    echo  [エラー] wheels フォルダが見つかりません。
    echo  ZIP を展開するとき、フォルダごと展開されているか確認してください。
    echo.
    pause
    exit /b 1
)

echo.
echo  お使いの Python:
%PY% -c "import sys,platform;print('   ',sys.version.split()[0],platform.architecture()[0])"
echo.
echo  インストールしています...
echo.

rem --no-index を付けているので、同梱したファイルだけを見に行く（外部に接続しない）
%PY% -m pip install --no-index --find-links "%~dp0wheels" Pillow pymupdf pypdf

if errorlevel 1 goto failed

echo.
echo  --- 確認 ---
%PY% -c "import PIL,pymupdf,pypdf;print('    Pillow',PIL.__version__,'/ PyMuPDF 使えます / pypdf',pypdf.__version__)"
if errorlevel 1 goto failed

echo.
echo  インストールが終わりました。
echo  「起動.bat」またはデスクトップのアイコンから起動してください。
echo.
pause
exit /b 0

:failed
echo.
echo  [エラー] インストールできませんでした。
echo.
echo  同梱している部品は次の環境向けです。
echo     Windows 64ビット版 / Python 3.10・3.11・3.12・3.13・3.14
echo.
echo  上に表示された「お使いの Python」が、これに当てはまるか確認してください。
echo  32ビット版の Python をお使いの場合は、64ビット版を入れ直してください。
echo.
echo  なお部品が無くても、Word とテキストの原稿の取り込み・校正・要約・
echo  Word への差し込みは使えます。
echo.
pause
exit /b 1
