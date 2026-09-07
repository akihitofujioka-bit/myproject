# myproject

## 日報・週報ドラフト生成（`/report`）

GitHub（コミット・PR・Issue）、Google カレンダー、PLAUD の文字起こしから対象期間の活動を集め、
日報・週報のドラフトを `reports/` に生成する Claude Code スキル。

```
/report 日報
/report 週報
/report 日報 2026-08-25
```

- スキル定義: `.claude/skills/report/SKILL.md`
- 設定: `.claude/skills/report/config.example.json` を `report.config.json` にコピーして編集
- 生成物はドラフトのみ。メール送信・チャット投稿は行わない
- `reports/daily/`・`reports/weekly/` は業務情報を含むため git 管理対象外

## 朝のブリーフ（`/brief`）

Google カレンダーの予定、期限の近い書類、要対応のメール、前日の日報の持ち越しを集めて、
今日1日の段取りを1枚にまとめた**朝のブリーフ**を `reports/brief/` に生成する Claude Code スキル。

```
/brief
/brief 2026-09-04
```

- スキル定義: `.claude/skills/brief/SKILL.md`
- 設定: `.claude/skills/brief/config.example.json` を `brief.config.json` にコピーして編集
- 読み取り専用。メールの既読化・返信、予定の変更は行わない
- `reports/brief/` は業務情報を含むため git 管理対象外

## 日常アプリ（`apps/`）

ブラウザだけで動く小さなアプリ。データは端末の中だけに保存される。

| アプリ | 用途 | 場所 | 外部との通信 |
| --- | --- | --- | --- |
| 冷蔵庫の在庫・賞味期限管理 | 食材の期限管理、バーコードでの登録、食品ロスの記録 | `apps/fridge/` | なし |
| 書類・回覧の期限トラッカー | 提出期限のある書類・回覧・申請の管理 | `apps/docs-tracker/` | なし |
| ふたりのメッセージ | 相手と自分しか読めない形にした文章・写真のやりとり | `apps/messenger/` | **中継サーバーへ暗号文のみ** |

- パソコンでは `index.html` を開くだけで使える
- **iPhone で使うには GitHub Pages への公開が必要**（カメラとオフライン起動はブラウザの決まりで https でしか動かないため）。`main` への変更を `.github/workflows/pages.yml` が自動で公開し、Safari で開いて「ホーム画面に追加」すると通常のアプリのように使える。初回だけ Settings → Pages の Source を「GitHub Actions」にする操作が要る
- 公開されるのはアプリの画面だけで、入力したデータは端末内に残るため公開されない
- バーコード読み取りは、端末標準の `BarcodeDetector` と自前デコーダ（`apps/fridge/ean.js`）の2段構え。商品名は端末の中で覚え、外部の商品データベースには問い合わせない
- **期限の通知は端末の標準カレンダー経由**。「カレンダーに登録」で予定として渡し、前日と当日に iOS 標準の通知が届く
- 端末を移すときは「JSONで保存」→ 移行先で「JSONから読み込み」
- 書類トラッカーの書き出しを `data/deadlines.json` に置くと `/brief` が締切として拾う
- 詳しい注意事項と動作確認の方法は `apps/README.md` を参照

## ふたりのメッセージ（`apps/messenger/` ＋ `server/`）

Signal や Telegram のような、**相手と自分しか読めない**1対1のメッセージアプリ。文章と写真を送れる。

- 使い方と用意のしかた: **`docs/messenger-setup.md`**
- 中継サーバー: `server/`（`node server/server.mjs`。外部ライブラリなし）
- 暗号の方式は Signal と同じ考え方（X3DH 相当の鍵交換 ＋ Double Ratchet 相当の鍵更新）。
  1通ごとに鍵を作り直すため、いまの鍵が漏れても**過去のメッセージは解読できない**
- 使うのはブラウザと OS に最初から入っている Web Crypto API のみ（ECDH P-256 / HKDF / AES-256-GCM / ECDSA P-256）
- **消えるメッセージ**（会話ごとに時間を設定。既定はオフ）と**1回だけのメッセージ**（1通ごとに指定）に対応
- 中継サーバーは暗号文を預かって渡すだけで、本文と写真は開けない。
  ただし「誰から誰へ、いつ、どれくらいの大きさの暗号文が流れたか」は中継側に残る
- **この暗号処理は第三者の監査を受けていない。**日常の連絡向けであり、身の安全に関わる重大な秘密には Signal を使うこと

### 知り合いに配る（Android）

配布用のアプリ一式は `mobile-messenger/`。手順は **`docs/android-distribution.md`**（相手にそのまま送れる説明文つき）。

- **メッセージアプリだけ**を含む別アプリにしてある（業務書類を扱う書類トラッカーを配布先に渡さないため）
- 求める権限は**インターネット接続だけ**。自動バックアップと端末間移行を無効にし、鍵と履歴を端末の外へ出さない
- 暗号化なしの通信を禁止し、スクリーンショットと画面録画も不可にしている
- `npm run apk` で署名済み APK と、すり替え確認用の SHA-256 が出る
- **APK の組み立て自体はこの環境では未検証**（Android SDK を取得できないため）。
  設定の正しさと、APK に入るのと同じ中身が動くことまでは `node apps/tests/android-package.test.mjs` で確認済み

## iPhone / Android アプリとして書き出す（`mobile/`）

`apps/` の3つのアプリを Capacitor でネイティブアプリに包むための設定一式。
アプリとして動いているときは、カレンダーを経由せず**アプリから直接通知**が出せる。

- 手順: `mobile/README.md`
- iPhone は **Mac と Xcode**、Android は **Android Studio**（Mac 不要）が要る。
  設定ファイルと `www` の組み立てまでは動作確認済みだが、ビルド以降は未検証
- アプリ本体は `apps/` 側だけを直せばよく、`npm run sync` で反映する
