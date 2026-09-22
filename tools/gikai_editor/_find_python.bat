@echo off
rem ============================================================
rem  使える Python を探して、環境変数 PY と PYW に入れる。
rem  （呼び出し側で  call "%~dp0_find_python.bat"  とする）
rem
rem  ここで大事なのは「コマンドがあるか」ではなく
rem  「本当に動くか」を確かめること。
rem  ほかのソフトが置いていった壊れた Python が PATH に
rem  残っていると「Unable to create process」となって
rem  先に進めなくなるため、実際に _pycheck.py を動かして
rem  ファイルが書けたかどうかで判断する。
rem
rem  setlocal は使わない（呼び出し元に値を返すため）
rem ============================================================

set "PY="
set "PYW="
set "PYFOUND="
set "PYCHK=%TEMP%\gikai_pycheck.txt"
set "PYPROBE=%~dp0_pycheck.py"

rem --- 1) py ランチャー（新しいものから順に）
for %%V in (-3.14 -3.13 -3.12 -3.11 -3.10 -3) do call :try "py %%V" "pyw %%V"

rem --- 2) PATH の python / python3
if not defined PY call :try "python"  "pythonw"
if not defined PY call :try "python3" "pythonw"

rem --- 3) よくあるインストール先を直接見る
if not defined PY call :scan "%LOCALAPPDATA%\Programs\Python"
if not defined PY call :scan "%ProgramFiles%"
if not defined PY call :scan "C:\"

del "%PYCHK%" >nul 2>&1
if not defined PY goto :eof

rem --- 画面なしの Python が使えるか確かめる。だめなら画面ありで動かす。
del "%PYCHK%" >nul 2>&1
%PYW% "%PYPROBE%" "%PYCHK%" >nul 2>&1
if not exist "%PYCHK%" set "PYW=%PY%"
del "%PYCHK%" >nul 2>&1

set "PYFOUND=1"
goto :eof

rem ------------------------------------------------------------
rem  :try  実際に動かしてみて、動いたら採用する
rem        %1 = 画面ありの呼び出し方  %2 = 画面なしの呼び出し方
rem ------------------------------------------------------------
:try
if defined PY goto :eof
del "%PYCHK%" >nul 2>&1
%~1 "%PYPROBE%" "%PYCHK%" >nul 2>&1
if not exist "%PYCHK%" goto :eof
set "PY=%~1"
set "PYW=%~2"
goto :eof

rem ------------------------------------------------------------
rem  :scan  指定フォルダの下から Python3xx を探す
rem ------------------------------------------------------------
:scan
if defined PY goto :eof
if not exist "%~1" goto :eof
for /d %%D in ("%~1\Python3*") do call :trypath "%%~D\python.exe" "%%~D\pythonw.exe"
goto :eof

:trypath
if defined PY goto :eof
if not exist "%~1" goto :eof
del "%PYCHK%" >nul 2>&1
"%~1" "%PYPROBE%" "%PYCHK%" >nul 2>&1
if not exist "%PYCHK%" goto :eof
set "PY=%~1"
set "PYW=%~2"
goto :eof
