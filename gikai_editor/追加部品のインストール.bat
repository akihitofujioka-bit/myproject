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
echo.
echo  この作業のときだけインターネットに接続します。
echo  （ツール本体は、使うときに外部と通信することはありません）
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

echo.
echo  インストールしています。数分かかることがあります...
echo.

%PY% -m pip install --upgrade pip
%PY% -m pip install -r "%~dp0requirements.txt"

if errorlevel 1 (
    echo.
    echo  [エラー] インストールできませんでした。
    echo.
    echo  よくある原因:
    echo    ・インターネットにつながっていない
    echo    ・職場のネットワークが外部への接続を制限している
    echo.
    echo  部品が無くても、Word とテキストの原稿の取り込み、
    echo  校正、Word への差し込みは使えます。
    echo.
    pause
    exit /b 1
)

echo.
echo  インストールが終わりました。
echo  「起動.bat」またはデスクトップのアイコンから起動してください。
echo.
pause
exit /b 0
