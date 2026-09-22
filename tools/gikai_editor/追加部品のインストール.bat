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

call "%~dp0_find_python.bat"

if not defined PYFOUND (
    echo.
    echo  [エラー] 使える Python が見つかりませんでした。
    echo.
    echo  次のものを順に試しましたが、どれも動きませんでした。
    echo     py ランチャー / python / python3 / よくあるインストール先
    echo.
    echo  ほかのソフトが入れた Python が PATH に残っていて、
    echo  それが壊れている場合もこの表示になります。
    echo.
    echo  下のページから Python をインストールし直してください。
    echo     https://www.python.org/downloads/windows/
    echo.
    echo  インストール画面の一番下にある
    echo  「Add Python to PATH」に必ずチェックを入れてください。
    echo.
    pause
    exit /b 1
)

if not exist "%~dp0wheels" (
    echo.
    echo  [エラー] wheels フォルダが見つかりません。
    echo  「追加部品1of2」「追加部品2of2」の ZIP を、
    echo  このフォルダと同じ場所に展開してください。
    echo.
    pause
    exit /b 1
)

echo.
echo  お使いの Python:
%PY% -c "import sys,platform;print('    ',sys.version.split()[0],platform.architecture()[0]);print('     場所:',sys.executable)"
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
echo  wheels フォルダに7個のファイルが揃っているかも確認してください
echo  （追加部品の ZIP を2つとも展開したか）。
echo.
echo  なお部品が無くても、Word とテキストの原稿の取り込み・校正・要約・
echo  Word への差し込みは使えます。
echo.
pause
exit /b 1
