# この Vault について

Obsidian の Vault（ノート置き場）です。
**Obsidian では「リポジトリのルート」を Vault として開き、ノートはこの `vault/` 配下に置きます。**
（iPhone の Obsidian Git がリポジトリを Vault ルートに clone する仕様に合わせた構成です。）

## フォルダの役割（PARA 法）

| フォルダ | 入れるもの |
|---|---|
| `Projects/` | 終わりがある取り組み。アプリ1つ＝ノート1枚 |
| `Areas/` | 終わりがない継続的な領域（健康、家計、学習など） |
| `Resources/` | 資料・調べもの・参考リンク |
| `Archive/` | 終わったプロジェクトの置き場 |
| `Daily/` | デイリーノート（その日のメモ） |
| `Logs/` | Claude Code とのセッション作業記録 |
| `Templates/` | ノートのひな形 |

## 最初にやること

1. Obsidian でリポジトリのルートを Vault として開く
2. 設定 → コアプラグイン → **デイリーノート** をオン → 新規ファイルの場所を `vault/Daily`、テンプレートを `vault/Templates/daily` に設定
3. 設定 → コアプラグイン → **テンプレート** をオン → フォルダを `vault/Templates` に設定

詳しい手順（GitHub トークンの作成、iPhone の設定）は `docs/obsidian-setup.md` にあります。

## 覚えることは3つだけ

- `[[` と打つと他のノートへのリンクが挿入できる
- `- [ ] やること` でチェックボックスになる
- 何か作ったら [[00-Index]] に1行足す
