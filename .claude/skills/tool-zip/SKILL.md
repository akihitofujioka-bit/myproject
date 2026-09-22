---
name: tool-zip
description: 役場のパソコンへ渡すための zip を、ツールのフォルダから作る。tools/ の下にツール（gikai_simple など）を新しく作ったとき、または中身を直したときに、渡しやすいよう zip も同時に作る。ユーザーが「zip も作って」「渡せる形にして」「配布用にまとめて」と言ったときにも使う。Windows で日本語のファイル名が化けない形式で作り、保存先の絶対パスを必ず報告する。zip をどこかへ送ったりコピーしたりはしない。
---

# 配布用 zip を作る

このリポジトリのツールは、**役場のパソコン（Windows）へ USB で持ち込んで使う**。
そのため、ツールを作ったり直したりしたら、渡せる形の zip も一緒に作っておく。

## 大原則

1. **送らない・コピーしない。** zip を作るところまで。メール添付、クラウドへのアップロード、
   iCloud への複製は一切しない。**利用者が自分で運ぶ**。
2. **保存先の絶対パスを必ず報告する。** どこにできたか分からないと渡せない。
3. **作業データを混ぜない。** 号フォルダ、原稿、写真、議事録などの**個人情報を含むものは絶対に入れない**。
   入れるのはツール本体（プログラム・説明書・辞書）だけ。
4. **`zip` コマンドを使わない。** macOS の `zip` は日本語のファイル名を cp437 で記録するため、
   **Windows で「Φ╡╖σïò.bat」のように化ける**。必ず後述の Python で作る。
5. **中のフォルダ名は半角英数にする。** 展開したときに文字化けや長いパスで困らないようにする。

## 手順

### 1. ツールが動く状態か確かめる

zip にする前に、必ずテストを通す。壊れたものを渡さないため。

```bash
cd tools/<ツール名> && python3 -m unittest discover -s tests
```

読み込みだけ確かめたいときは、起動チェックの道具を使う。

```bash
python3 tools/verify_python_startup.py tools/<ツール名>
```

### 2. zip を作る

`tools/<ツール名>.zip` に作る。**`tools/*.zip` は `.gitignore` に入れてあるので、
git には入らない**（中身は同じリポジトリのソースから作り直せるため）。

```bash
cd /Users/ichishi/myproject && python3 - <<'EOF'
import zipfile, os

TOOL = "gikai_simple"          # ← ツール名に変える
SRC  = f"tools/{TOOL}"
OUT  = f"tools/{TOOL}.zip"

# 入れないもの（作業の跡・個人情報が入りうるもの）
SKIP_DIR  = {"__pycache__", ".claude", ".git", "tests", "第", "出力", "写真", "別添"}
SKIP_FILE = {".DS_Store"}
SKIP_EXT  = {".pyc", ".zip", ".docx", ".doc", ".xlsx", ".jpg", ".jpeg", ".png"}

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in SKIP_DIR and not d.startswith("第")]
        for f in sorted(files):
            if f in SKIP_FILE or os.path.splitext(f)[1].lower() in SKIP_EXT:
                continue
            p = os.path.join(root, f)
            # 展開すると TOOL という名前のフォルダになる
            z.write(p, os.path.join(TOOL, os.path.relpath(p, SRC)))

z = zipfile.ZipFile(OUT)
print("壊れていないか:", z.testzip() or "OK")
for i in z.infolist():
    flag = "UTF-8" if i.flag_bits & 0x800 else "ascii"
    print(f"  [{flag}] {i.filename}  {i.file_size:,}バイト")
print("合計", len(z.infolist()), "ファイル /", os.path.getsize(OUT), "バイト")
EOF
```

**テストも渡したいとき**は `SKIP_DIR` から `"tests"` を外す。
（ふだんは外して渡す。役場の人が使うのはツール本体だけで、テストは開発用のため。）

### 3. 確かめる

出力を見て、次の 2 つを確認する。

- **日本語のファイル名に `[UTF-8]` が付いているか**（`起動.bat` など）。`ascii` になっていたら Windows で化ける
- **入れてはいけないものが混ざっていないか**（号フォルダ、`.docx`、写真）

### 4. 報告する

**絶対パスと中身を書く。** 例:

```
/Users/ichishi/myproject/tools/gikai_simple.zip（28KB・9 ファイル）
展開すると gikai_simple フォルダになります。
USB にコピーして役場のパソコンへ持ち込み、起動.bat から起動してください。
```

iCloud などへ置きたい場合は、**利用者が自分でコピーする**。こちらからはしない。

## やらないこと

- zip をどこかへ**送らない・コピーしない**（メール、クラウド、iCloud、共有フォルダ）
- **作業データを入れない**（号フォルダ、原稿、写真、議事録、名簿）
- macOS の `zip` コマンドを使わない（日本語が化ける）
- git に入れない（`tools/*.zip` は `.gitignore` 済み。変更しない）
