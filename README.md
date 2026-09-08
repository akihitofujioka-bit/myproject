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

ブラウザだけで動く小さなアプリ。データは端末の中だけに保存され、外部への送信は行わない。

| アプリ | 用途 | 場所 |
| --- | --- | --- |
| 冷蔵庫の在庫・賞味期限管理 | 食材の期限管理、バーコードでの登録、食品ロスの記録 | `apps/fridge/` |
| 書類・回覧の期限トラッカー | 提出期限のある書類・回覧・申請の管理 | `apps/docs-tracker/` |
| 蔵書の管理 | 本の ISBN バーコードでの登録、未読/読書中/読了の記録 | `apps/books/` |
| 備蓄・消耗品の管理 | 防災備蓄・常備薬・消耗品の残数と期限の管理、補充時期の通知 | `apps/stock/` |

- パソコンでは `index.html` を開くだけで使える
- **iPhone で使うには GitHub Pages への公開が必要**（カメラとオフライン起動はブラウザの決まりで https でしか動かないため）。`main` への変更を `.github/workflows/pages.yml` が自動で公開し、Safari で開いて「ホーム画面に追加」すると通常のアプリのように使える。初回だけ Settings → Pages の Source を「GitHub Actions」にする操作が要る
- 公開されるのはアプリの画面だけで、入力したデータは端末内に残るため公開されない
- バーコード読み取りは、端末標準の `BarcodeDetector` と自前デコーダ（`apps/fridge/ean.js`）の2段構え。商品名は端末の中で覚え、外部の商品データベースには問い合わせない
- **ISBN-13 は規格上 JAN-13（EAN-13）そのもの**のため、蔵書アプリは同じデコーダで本のバーコードを読む。日本の本は上下2段のバーコードで、上段が ISBN（`978`/`979` 始まり）、下段が日本図書コード（`192` 始まりの分類・価格）。蔵書アプリは上段だけを受け付ける
- 各アプリの先頭には「← アプリ一覧にもどる」を置く。**アプリとして開いたときはブラウザの「戻る」もスワイプも効かない**ため、この導線が無いと一覧に戻れなくなる
- ランチャーからのリンクは `fridge/index.html` のように**ファイル名まで書く**。`fridge/` のようなディレクトリ指定だと、アプリの WebView がルートの `index.html` を返してしまい、子アプリが開けない
- **書類トラッカーは書類ごとに QR コードを発行できる**（`apps/shared/qr.js`。リード・ソロモン誤り訂正まで自前実装で、外部ライブラリも通信も使わない）。紙に貼った QR を iPhone の標準カメラで読むと、`myproject://docs?id=...` で**アプリが起動してその書類が開く**（`apps/shared/deeplink.js` と `@capacitor/app`、Info.plist の `CFBundleURLTypes` で実現）
- QR に入れるのは**書類の識別子だけ**で、書類名などの中身は入れない。紙を落としても内容が漏れないようにするため
- **期限の通知は端末の標準カレンダー経由**。「カレンダーに登録」で予定として渡し、前日と当日に iOS 標準の通知が届く
- 端末を移すときは「JSONで保存」→ 移行先で「JSONから読み込み」
- 書類トラッカーの書き出しを `data/deadlines.json` に置くと `/brief` が締切として拾う
- 詳しい注意事項と動作確認の方法は `apps/README.md` を参照

## iPhone アプリとして書き出す（`mobile/`）

`apps/` の2つのアプリを Capacitor でネイティブアプリに包むための設定一式。
アプリとして動いているときは、カレンダーを経由せず**アプリから直接通知**が出せる。

- 手順: `mobile/README.md`
- **Xcode プロジェクト（`mobile/ios/`）は生成済み**。アプリ名・アイコン・起動画面・カメラの利用目的まで設定してある
- Mac での作業は `npm install && npm run sync` のあと Xcode を開き、署名して実行するだけ
- iOS のビルドと実機動作は未検証（Mac が必要なため）
- アプリ本体は `apps/` 側だけを直せばよく、`npm run sync` で反映する
