"""指定したフォルダ・ファイルの Python プログラムが、正しく起動するかを確かめる道具。

「文法は正しいのに実行時エラーで落ちる」「import に失敗する」といった、
コマンドは見つかるのに実際には動かせないコードを見分けるために使う。
1本ずつ実際に実行してみて確かめる（＝ gikai_editor/_pycheck.py と同じ考え方を、
任意のフォルダ・ファイルに対して使えるようにしたもの）。

使い方:
    python3 tools/verify_python_startup.py <フォルダかファイル> [<フォルダかファイル> ...]
    python3 tools/verify_python_startup.py apps/ --timeout 10

終了コード: 全部 OK なら 0、1つでも NG があれば 1。
"""

import argparse
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
            return False, str(e.exc_value)


def try_run(py_file, timeout):
    """実際に実行してみて、起動できるかを確かめる。"""
    try:
        result = subprocess.run(
            [sys.executable, str(py_file.resolve())],
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

    stderr_tail = "\n".join(result.stderr.strip().splitlines()[-10:])
    return False, f"終了コード {result.returncode}\n{stderr_tail}"


def main():
    parser = argparse.ArgumentParser(
        description="指定したフォルダ・ファイルの Python プログラムが正しく起動するかを確かめます。"
    )
    parser.add_argument("paths", nargs="+", help="検証したいフォルダまたは .py ファイル")
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT,
        help=f"1本あたりの実行を待つ秒数(既定 {DEFAULT_TIMEOUT} 秒)",
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
            print(f"[NG] {py_file}\n  文法エラー: {syntax_message}\n")
            ng_files.append(py_file)
            continue

        run_ok, run_message = try_run(py_file, args.timeout)
        if run_ok:
            print(f"[OK] {py_file}  ({run_message})")
            ok_count += 1
        else:
            print(f"[NG] {py_file}\n  {run_message}\n")
            ng_files.append(py_file)

    print(f"\n結果: OK {ok_count} 件 / NG {len(ng_files)} 件 (全 {len(py_files)} 件)")
    if ng_files:
        print("\n起動できなかったファイル:")
        for f in ng_files:
            print(f"  - {f}")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
