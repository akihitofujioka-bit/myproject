---
name: tool-zip
description: 渡すための zip を、ツールのフォルダから作る。tools/ の下にツール（gikai_simple・nippo など）を新しく作ったとき、または中身を直したときに、渡しやすいよう zip も同時に作る。ユーザーが「zip も作って」「渡せる形にして」「配布用にまとめて」と言ったときにも使う。日本語のファイル名が Windows で化けない形式で作り、__MACOSX を混ぜず、保存先の絶対パスを必ず報告する。zip をどこかへ送ったりコピーしたりはしない。
---

# 配布用 zip を作る

このリポジトリのツールは、**別のパソコンへ USB で持ち込んで使う**。
そのため、ツールを作ったり直したりしたら、渡せる形の zip も一緒に作っておく。

## 大原則

1. **送らない・コピーしない。** zip を作るところまで。メール添付、クラウドへのアップロード、
   iCloud への複製は一切しない。**利用者が自分で運ぶ**。
2. **保存先の絶対パスを必ず報告する。** どこにできたか分からないと渡せない。
3. **作業データを混ぜない。** 号フォルダ、原稿、写真、議事録などの**個人情報を含むものは絶対に入れない**。
   入れるのはツール本体（プログラム・説明書・辞書）だけ。
4. **`zip` コマンドや Finder の「圧縮」を使わない。** macOS のそれらは、
   日本語のファイル名を cp437 で記録するため **Windows で「Φ╡╖σïò.bat」のように化ける**うえ、
   **`__MACOSX` という余計なフォルダ**が入って「フォルダが 2 つある」状態になる。
   必ず後述の Python で作る。
5. **中のフォルダ名は半角英数にする。** 展開したときに文字化けや長いパスで困らないようにする。
6. **zip にしか無いファイルを作らない。** `部品のインストール.bat` や README の
   「いちばん簡単な入れ方」を zip の中だけで直すと、次に zip を作り直したときに
   **消える**（実際に一度消しかけた）。中身を直すときは**必ずリポジトリの側を直し**、
   zip はそこから作る。例外は `wheels/` の `.whl` だけ（数MB のバイナリなので
   `.gitignore` に入れてある。**zip を作り直すときは前の zip から引き継ぐ**）。
7. **ダブルクリックで起動するファイルの実行権限を保つ。** `日報ツール.command` のような
   起動用ファイルは、権限が落ちるとダブルクリックしても動かない。
   Python の `zipfile` は権限をそのまま記録するので、手順どおりに作れば保たれる（手順 3 で確認）。

## ツールによって入れないものが違う

| ツール | 入れないもの | 理由 |
|---|---|---|
| 共通 | `__pycache__` `.claude` `.DS_Store` `*.pyc` | 作業の跡 |
| `gikai_simple` | `第○号/` `出力/` `写真/` `別添/` | **原稿・写真などの個人情報** |
| `nippo` | `.build/`（`nippo_ocr`） | swiftc が作り直すバイナリ。渡す先で作られる |
| 共通 | `tests/` フォルダ、`test_*.py` | 開発用。使う人には要らない |

**渡す先の OS を間違えないこと。** `gikai_simple` は Windows（役場）向け、
`nippo` は **macOS 専用**（OCR に macOS の Vision を使い、起動が `.command`）。

## 手順

### 1. ツールが動く状態か確かめる

zip にする前に、必ずテストを通す。壊れたものを渡さないため。
テストの置き方はツールによって違うので、まず探す。

```bash
ls tools/<ツール名>/tests tools/<ツール名>/test_*.py 2>/dev/null
```

- `tests/` フォルダがある（`gikai_simple`） → `cd tools/<ツール名> && python3 -m unittest discover -s tests`
- `test_*.py` が直下にある（`nippo`） → `python3 tools/<ツール名>/test_*.py`

読み込みだけ確かめたいときは、起動チェックの道具を使う。

```bash
python3 tools/verify_python_startup.py tools/<ツール名>
```

### 1-2. `wheels/`（Windows 用の部品）を用意する

`gikai_simple` と `nippo` の zip には、役場のパソコン（ネットにつながらない）で
部品を入れるための `.whl` を同梱する。これは `.gitignore` に入れてあるので
リポジトリには無い。**前に作った zip から引き継ぐ**のがいちばん確実。

```bash
cd "$TMPDIR" && rm -rf ziptmp && mkdir ziptmp && cd ziptmp \
  && unzip -q /Users/ichishi/myproject/tools/<ツール名>.zip \
  && ls <ツール名>/wheels/
```

前の zip が無いときは、ネットにつながるパソコンで作る（Python 3.11・64 ビット Windows 用）。

```bash
pip download --platform win_amd64 --only-binary=:all: --python-version 311 -d wheels python-docx Pillow
```

この展開したフォルダを土台にし、**リポジトリの最新ソースで上書きしてから** zip にする。
`git ls-files` で一覧を取るときは **`-z` を付ける**（付けないと日本語のファイル名が
`\350\250\255...` という形で返り、コピーに失敗する）。

### 2. zip を作る

`tools/<ツール名>.zip` に作る。**`tools/*.zip` は `.gitignore` に入れてあるので、
git には入らない**（中身は同じリポジトリのソースから作り直せるため）。

```bash
cd /Users/ichishi/myproject && python3 - <<'EOF'
import zipfile, os

TOOL = "gikai_simple"          # ← ツール名に変える
SRC  = f"tools/{TOOL}"
OUT  = f"tools/{TOOL}.zip"

# 入れないもの。上の表を見てツールに合わせる
SKIP_DIR  = {"__pycache__", ".claude", ".git", ".build", "tests", "第", "出力", "写真", "別添"}
SKIP_FILE = {".DS_Store"}
SKIP_EXT  = {".pyc", ".zip", ".docx", ".doc", ".xlsx", ".jpg", ".jpeg", ".png"}

def skip(name):
    return (name in SKIP_FILE
            or os.path.splitext(name)[1].lower() in SKIP_EXT
            or name.startswith("test_"))      # tests フォルダでないテストも外す

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in SKIP_DIR and not d.startswith("第")]
        for f in sorted(files):
            if skip(f):
                continue
            p = os.path.join(root, f)
            # 展開すると TOOL という名前のフォルダ 1 つになる
            z.write(p, os.path.join(TOOL, os.path.relpath(p, SRC)))

z = zipfile.ZipFile(OUT)
print("壊れていないか:", z.testzip() or "OK")
print("いちばん上のフォルダ:", sorted({n.split('/')[0] for n in z.namelist()}))
for i in z.infolist():
    flag = "UTF-8" if i.flag_bits & 0x800 else "ascii"
    mode = (i.external_attr >> 16) & 0o777
    x = " 実行可" if mode & 0o111 else ""
    print(f"  [{flag}] {i.filename}  {i.file_size:,}バイト  {oct(mode)[2:]}{x}")
print("合計", len(z.infolist()), "ファイル /", f"{os.path.getsize(OUT):,}", "バイト")
EOF
```

**テストも渡したいとき**は `SKIP_DIR` から `"tests"` を、`skip()` から `test_` の行を外す。
（ふだんは外して渡す。使う人にはツール本体だけで足りるため。）

### 3. 確かめる

出力を見て、次の 4 つを確認する。

- **いちばん上のフォルダが 1 つだけか。** 2 つあるなら `__MACOSX` が混ざっている
- **日本語のファイル名に `[UTF-8]` が付いているか**（`起動.bat` `日報ツール.command` など）。
  `ascii` だと Windows で `Φ╡╖σïò.bat` のように化ける
- **起動用のファイルが「実行可」か**（`.command` `.sh` など。`755` と出る）
- **入れてはいけないものが混ざっていないか**（号フォルダ、`.docx`、写真、`.build`）

不安なときは展開して確かめる。

```bash
cd "$TMPDIR" && rm -rf ziptest && mkdir ziptest && cd ziptest \
  && unzip -q /Users/ichishi/myproject/tools/<ツール名>.zip && ls -lR | head -20
```

### 4. 報告する

**絶対パスと中身を書く。** 例:

```
/Users/ichishi/myproject/tools/gikai_simple.zip（67KB・13 ファイル）
展開すると gikai_simple フォルダ 1 つになります。
USB にコピーして役場のパソコンへ持ち込み、起動.bat から起動してください。
```

iCloud などへ置きたい場合は、**利用者が自分でコピーする**。こちらからはしない。

## やらないこと

- zip をどこかへ**送らない・コピーしない**（メール、クラウド、iCloud、共有フォルダ）
- **作業データを入れない**（号フォルダ、原稿、写真、議事録、名簿）
- macOS の `zip` コマンドや、Finder の右クリック →「圧縮」を使わない
  （**日本語が化ける**うえ、`__MACOSX` が入る）
- git に入れない（`tools/*.zip` は `.gitignore` 済み。変更しない）
