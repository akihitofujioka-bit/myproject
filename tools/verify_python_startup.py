"""指定したフォルダ・ファイルの Python プログラムが、正しく起動するかを確かめる道具。

「文法は正しいのに実行時エラーで落ちる」「import に失敗する」といった、
コマンドは見つかるのに実際には動かせないコードを見分け、**どこが間違っているか**
（ファイル・行番号・その行のコード・エラー内容）を表示する。
（＝ gikai_editor/_pycheck.py と同じ考え方を、任意のフォルダ・ファイルに対して使えるようにしたもの）

確かめ方は 3 段階:
    1. 文法      … py_compile でコンパイルできるか
    2. 読み込み  … __main__ ではない名前で読み込む。import の失敗や、先頭で定義される
                    変数・関数の間違いが分かる。`if __name__ == "__main__":` の中（引数処理や
                    画面表示）は動かさないので、引数が必要なプログラムもここまでは判定できる
    3. 実行      … --run を付けたときだけ。引数なしで実際に実行し、終了コード 0 か時間切れなら OK。
                    引数不足で使い方を表示して終わった場合（終了コード 2 と usage:）は
                    「引数が必要。起動自体は OK」とみなす

使い方:
    python3 tools/verify_python_startup.py <フォルダかファイル> [<フォルダかファイル> ...]
    python3 tools/verify_python_startup.py apps/ --timeout 10
    python3 tools/verify_python_startup.py gikai_editor/ --run
    python3 tools/verify_python_startup.py gikai_editor/ --python /opt/homebrew/bin/python3.12

パッケージ（__init__.py のあるフォルダ）の中のファイルは、パッケージのモジュールとして import するので
相対 import（from .xxx import ...）も正しく確かめられる。

終了コード: 全部 OK なら 0、1つでも NG があれば 1。
"""

import argparse
import json
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path

# 検証の対象に含めないディレクトリ名（仮想環境・キャッシュ・依存パッケージなど）
SKIP_DIR_NAMES = {
    "__pycache__", ".git", "node_modules", ".venv", "venv",
    "wheels", "site-packages", ".pytest_cache",
}

DEFAULT_TIMEOUT = 5.0

# 「読み込み」段階を別プロセスで行うための小さなプログラム。
# 対象ファイルを __main__ ではない名前で読み込み、失敗したら例外の場所を JSON で返す。
IMPORT_RUNNER = r'''
import importlib, json, os, runpy, sys, traceback
path = sys.argv[1]
sys.argv = [path]
sys.stdin = open(os.devnull)

# __init__.py のあるフォルダはパッケージ。その中のファイルは「パッケージのモジュール」として
# import しないと、相対 import（from .xxx import ...）が必ず失敗してしまう
pkg_dir = os.path.dirname(path)
parts = []
while os.path.exists(os.path.join(pkg_dir, "__init__.py")):
    parts.insert(0, os.path.basename(pkg_dir))
    pkg_dir = os.path.dirname(pkg_dir)
sys.path.insert(0, pkg_dir)   # パッケージの親（または同じフォルダ）を import の起点にする
try:
    if parts:
        stem = os.path.splitext(os.path.basename(path))[0]
        importlib.import_module(".".join(parts if stem == "__init__" else parts + [stem]))
    else:
        runpy.run_path(path, run_name="__verify_startup__")
except SystemExit as e:
    # 読み込み中に sys.exit() された。0 なら問題なし（使い方表示など）
    if e.code not in (0, None):
        print(json.dumps({"kind": "SystemExit", "message": "読み込み中に sys.exit(%r) で終了した" % (e.code,), "frames": []}))
        sys.exit(1)
except BaseException as e:
    frames = [{"file": f.filename, "line": f.lineno, "code": f.line or "", "func": f.name}
              for f in traceback.extract_tb(e.__traceback__)]
    if isinstance(e, SyntaxError) and e.filename:
        frames.append({"file": e.filename, "line": e.lineno or 0, "code": (e.text or "").strip(), "func": ""})
    print(json.dumps({"kind": type(e).__name__, "message": str(e), "frames": frames}, ensure_ascii=False))
    sys.exit(1)
'''

# 例外の種類ごとの、平たい言葉での説明
KIND_HINTS = {
    "ModuleNotFoundError": "import しようとしたモジュール（ライブラリや自作ファイル）が見つからない。名前の綴りか、pip での導入漏れ",
    "ImportError": "モジュールはあるが、その中の名前を取り出せない。関数名・クラス名の綴りか、ライブラリの版違い",
    "NameError": "定義されていない名前を使っている。変数名・関数名の綴り、定義より前に使っていないか",
    "AttributeError": "そのオブジェクトに無い属性・メソッドを呼んでいる。名前の綴りか、型の取り違え",
    "TypeError": "引数の数や型が合っていない",
    "SyntaxError": "文法の誤り。括弧・引用符・コロン・インデントなど",
    "IndentationError": "インデント（字下げ）の誤り",
    "FileNotFoundError": "先頭で開いているファイルが無い。実行する場所（カレントフォルダ）の違いが多い",
    "PermissionError": "読み書きの権限が無い（サンドボックスの中で実行していないか）",
}


def find_py_files(paths):
    """指定されたパスから .py ファイルの一覧を集める。フォルダは再帰的にたどる。"""
    files = []
    for raw in paths:
        p = Path(raw)
        if not p.exists():
            print(f"[警告] 見つかりません: {p}")
            continue
        if p.is_file():
            if p.suffix == ".py":
                files.append(p)
            else:
                print(f"[警告] .py ファイルではないので対象外にします: {p}")
            continue
        for py_file in sorted(p.rglob("*.py")):
            if any(part in SKIP_DIR_NAMES for part in py_file.parts):
                continue
            files.append(py_file)
    return files


def check_syntax(py_file):
    """文法エラーが無いかだけを先に確かめる。実行して確かめる前段階のふるい分け。"""
    with tempfile.TemporaryDirectory() as tmp:
        cache_path = Path(tmp) / "cache.pyc"
        try:
            py_compile.compile(str(py_file), cfile=str(cache_path), doraise=True)
            return True, ""
        except py_compile.PyCompileError as e:
            exc = e.exc_value
            where = ""
            if isinstance(exc, SyntaxError):
                where = f"{py_file} {exc.lineno} 行目\n        {(exc.text or '').strip()}\n  "
            return False, f"文法エラー: {where}{exc.msg if isinstance(exc, SyntaxError) else exc}"


def _describe_frames(py_file, frames):
    """例外の発生場所を「対象ファイル内の最後の行」と「実際に落ちた行」で示す。"""
    own = [f for f in frames if Path(f["file"]).resolve() == py_file.resolve()]
    project = [f for f in frames if "site-packages" not in f["file"] and "/lib/python" not in f["file"]]
    lines = []
    if own:
        f = own[-1]
        lines.append(f"場所: {py_file} {f['line']} 行目\n        {f['code']}")
    last = project[-1] if project else (frames[-1] if frames else None)
    if last and (not own or last is not own[-1]):
        try:
            shown = Path(last["file"]).relative_to(Path.cwd())
        except ValueError:
            shown = last["file"]
        lines.append(f"実際に落ちた行: {shown} {last['line']} 行目\n        {last['code']}")
    return lines


def try_import(py_file, timeout, python=sys.executable):
    """__main__ ではない名前で読み込み、import の失敗や先頭の定義の誤りを確かめる。"""
    try:
        result = subprocess.run(
            [python, "-c", IMPORT_RUNNER, str(py_file.resolve())],
            cwd=str(py_file.parent), capture_output=True, text=True,
            stdin=subprocess.DEVNULL, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return True, f"読み込みに {timeout:.0f} 秒以上かかりました（先頭で常駐処理を始めている可能性。__main__ の中に移すのが望ましい）"
    if result.returncode == 0:
        return True, "読み込み OK"
    try:
        info = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        tail = "\n".join(result.stderr.strip().splitlines()[-10:])
        return False, f"読み込み失敗（終了コード {result.returncode}）\n  {tail}"
    kind = info.get("kind", "Error")
    frames = info.get("frames", [])
    if kind == "IndexError" and frames and "sys.argv" in frames[-1].get("code", ""):
        # 先頭で sys.argv を使う＝引数必須のスクリプト。__main__ ガードが無いだけで間違いではない
        return True, f"引数が必要なスクリプトです（{frames[-1]['line']} 行目で sys.argv を使用。ここまでは読み込めています）"
    out = [f"種類: {kind}" + (f"（{KIND_HINTS[kind]}）" if kind in KIND_HINTS else "")]
    out += _describe_frames(py_file, info.get("frames", []))
    out.append(f"内容: {info.get('message', '')}")
    return False, "\n  ".join(out)


def try_run(py_file, timeout, python=sys.executable):
    """実際に実行してみて、起動できるかを確かめる（--run のとき）。"""
    try:
        result = subprocess.run(
            [python, str(py_file.resolve())],
            cwd=str(py_file.parent),
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        # 指定時間内に終わらなかった＝サーバ等でずっと動き続けている可能性がある。
        # クラッシュはしていないので「起動はできている」とみなす。
        return True, f"{timeout:.0f}秒たっても終了しませんでした(サーバ等の常駐プログラムの可能性。起動自体はできています)"

    if result.returncode == 0:
        return True, "正常終了しました"
    if result.returncode == 2 and ("usage:" in result.stderr or "使い方" in result.stderr + result.stdout):
        return True, "引数が必要なプログラムです(使い方を表示して終了。起動自体はできています)"

    stderr_tail = "\n".join(result.stderr.strip().splitlines()[-10:])
    return False, f"実行失敗: 終了コード {result.returncode}\n  {stderr_tail}"


def main():
    parser = argparse.ArgumentParser(
        description="指定したフォルダ・ファイルの Python プログラムが正しく起動するかを確かめます。"
    )
    parser.add_argument("paths", nargs="+", help="検証したいフォルダまたは .py ファイル")
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT,
        help=f"1本あたりの実行を待つ秒数(既定 {DEFAULT_TIMEOUT} 秒)",
    )
    parser.add_argument(
        "--run", action="store_true",
        help="読み込みに加えて、引数なしで実際に実行もしてみる（画面を開く・サーバを起動するプログラムに注意）",
    )
    parser.add_argument(
        "--python", default=sys.executable,
        help="検査に使う Python（既定はこの道具を動かしている Python）。専用環境のプロジェクトはその Python を指定する",
    )
    args = parser.parse_args()

    py_files = find_py_files(args.paths)
    if not py_files:
        print("検証対象の .py ファイルが見つかりませんでした。")
        sys.exit(1)

    print(f"{len(py_files)} 件の Python ファイルを検証します。\n")

    ok_count = 0
    ng_files = []

    for py_file in py_files:
        syntax_ok, syntax_message = check_syntax(py_file)
        if not syntax_ok:
            print(f"[NG] {py_file}\n  {syntax_message}\n")
            ng_files.append(py_file)
            continue

        import_ok, import_message = try_import(py_file, args.timeout, args.python)
        if not import_ok:
            print(f"[NG] {py_file}\n  {import_message}\n")
            ng_files.append(py_file)
            continue

        if args.run:
            run_ok, run_message = try_run(py_file, args.timeout, args.python)
            if not run_ok:
                print(f"[NG] {py_file}\n  {run_message}\n")
                ng_files.append(py_file)
                continue
            print(f"[OK] {py_file}  ({import_message}、{run_message})")
        else:
            print(f"[OK] {py_file}  ({import_message})")
        ok_count += 1

    print(f"\n結果: OK {ok_count} 件 / NG {len(ng_files)} 件 (全 {len(py_files)} 件)")
    if ng_files:
        print("\n起動できなかったファイル:")
        for f in ng_files:
            print(f"  - {f}")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
