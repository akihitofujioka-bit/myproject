# Apple Watch アプリを作る（第1段階：見るだけ）

最終更新: 2026-09-19

iPhone の「日常アプリ」が持っている**今日の会議・期限が近い書類・買い物リスト**を、
Apple Watch の画面に出すためのアプリ。手首を上げるだけで確認できるようにする。

> **どこまで確認済みか**
> - JavaScript 側（送る一覧の組み立て）は `apps/tests/watch.test.mjs` で検証済み（Node のみ、ブラウザ不要）
> - **Swift 側（iPhone のプラグインと Watch アプリ）はビルドも実機動作も未検証。**
>   この作業環境に Mac・Xcode・Apple Watch が無いため確認できない。エラーが出たら文面を共有してほしい

## 0. 前提

| 必要なもの | 備考 |
|---|---|
| **Apple Developer Program（年 約15,000円）** | Apple Watch アプリの実機導入には事実上必須。無料の Apple ID では不安定 |
| Xcode | Mac App Store から |
| iPhone と Apple Watch | 同じ Apple ID でペアリング済みであること |

仕組みは次のとおり。外部のサーバーは一切経由しない。

```
アプリの画面（HTML/JS）
  └ apps/shared/watch.js         … 一覧を組み立てる
      └ WatchBridge プラグイン（iPhone・Swift）
          └ WatchConnectivity    … iPhone と Apple Watch の直接通信
              └ Watch アプリ（SwiftUI）
```

## 1. Xcode に Watch アプリのターゲットを足す

**この手順だけは Xcode の画面から行う必要がある**（プロジェクト定義ファイルを手で書くと壊れやすいため）。

```bash
cd myproject/mobile
git pull
npm install
npm run sync
open ios/App/App.xcodeproj
```

Xcode で:

1. メニューの **File → New → Target…**
2. 上のタブで **watchOS** を選び、**App** を選んで **Next**
3. 次のように入れる
   - **Product Name**: `WatchApp`
   - **Interface**: `SwiftUI`
   - **Language**: `Swift`
   - **Include Notification Scene**: **チェックを外す**
   - **Watch App for Existing iOS App** になっていること（App の中に入る形）
4. **Finish**。「Activate scheme?」と聞かれたら **Activate**

これで `WatchApp Watch App` のような名前のフォルダとターゲットができる。

## 2. 中身をこのリポジトリのものに入れ替える

Xcode が自動で作った `ContentView.swift` と `〜App.swift` は使わない。

1. 新しくできたフォルダの中の **`ContentView.swift`** と **`WatchAppApp.swift`**（名前は環境により異なる）を選び、右クリック → **Delete → Move to Trash**
2. メニューの **File → Add Files to "App"…**
3. `mobile/ios/App/WatchAppSources/` の中の **4つの .swift ファイルすべて**を選ぶ
   - `DailyAppsWatchApp.swift`（入口）
   - `ContentView.swift`（画面）
   - `WatchStore.swift`（iPhone からの受け取り）
   - `Snapshot.swift`（データの形）
4. 下の **Add to targets** で、**Watch アプリのターゲットだけにチェック**を入れる（`App` のチェックは外す）
5. **Add**

## 3. 署名する

1. 左の一覧で **App** を選び、**Signing & Capabilities**
2. 上のターゲット一覧で **Watch アプリのターゲット**を選び、**Team** に自分（Developer Program の Apple ID）を選ぶ
3. Bundle Identifier は `jp.myproject.dailyapps.watchkitapp` のように、iPhone 側のあとに続く形になっていればよい

WatchConnectivity に追加の権限（Capability）は要らない。

## 4. 実機に入れる

1. iPhone を Mac に繋ぎ、画面上部の実行先を **自分の iPhone** にする
2. **▶︎** を押して iPhone アプリを入れる
3. iPhone の **Watch App → 一般 → App のインストール** で「日常アプリ」を Apple Watch に入れる
   （自動で入ることもある。数分かかる場合がある）

Xcode の実行先を Apple Watch にして直接入れることもできる。

## 5. 使いかた

1. **iPhone で「日常アプリ」を開く**（冷蔵庫・備蓄・書類トラッカーのどれでもよい）
2. 開いた時点と、内容を変えた時点で、自動的に Apple Watch へ送られる
3. Apple Watch で「日常」アプリを開くと、会議・期限・買い物が並ぶ

送られるのは**最新の一覧だけ**で、履歴は溜まらない。通信できないときは、前回届いた内容を表示する。
Watch の画面の下にある **最新にする** を押すと、iPhone が手元にあれば取り直せる。

## 6. 送っている内容

| 欄 | 中身 | 範囲 |
|---|---|---|
| 会議 | 件名・日付・開始時刻・場所・懇親会の有無 | 今日から1週間先まで |
| 期限 | 件名・期限・種別・提出先・状態 | 2週間先まで（過ぎたものも残す） |
| 買い物 | 品名のみ（備蓄は「品名 あと○個」） | 冷蔵庫は直近2週間で使い切ったもの、備蓄は最低在庫数を下回ったもの |

それぞれ最大 20 件まで。金額・メモ・購入店は送らない。

**外部のサーバーには一切送信しない。** iPhone と Apple Watch の直接通信（WatchConnectivity）だけを使う。
受け取った内容は Apple Watch の中（UserDefaults）に控えとして残る。

## 7. 買い物の消し込みについて

この第1段階の Watch アプリは**見るだけ**で、手首から消し込む機能は入れていない。
消し込みたい場合は、[買い物リストを Apple Watch で使う](apple-watch-shopping-list.md) の
リマインダー経由の方法を使う（Watch のリマインダー App でタップして消せる）。

手首から直接この台帳を書き換えるのは第2段階になる。往復の通信と、
iPhone 側で書き戻す仕組みが必要になるため、第1段階が実機で安定してから着手するのが安全。

## 8. うまくいかないとき

| 症状 | 確認すること |
|---|---|
| ビルドが通らない | 手順 2 の「Add to targets」で、Watch 側のターゲットだけにチェックが入っているか。`App` 側にも入っていると二重定義になる |
| 「まだ何も届いていません」のまま | iPhone で「日常アプリ」を一度開く。Apple Watch が iPhone とペアリングされているか |
| Watch アプリが Watch に出てこない | iPhone の Watch App → 一般 → App のインストール から入れる。反映に数分かかることがある |
| 内容が古い | Watch の画面下の「最新にする」を押す。それでも変わらなければ iPhone 側のアプリを開き直す |
| 期限が出てこない | 書類トラッカーの状態が「完了」になっていないか。完了したものは送らない |
| 会議が出てこない | 1週間より先の会議は送らない。カレンダーには入っているので、文字盤のコンプリケーションで確認できる |

## 9. 次にできること（未実装）

- **文字盤のコンプリケーション**（WidgetKit の別ターゲットが必要）
- **手首からの消し込み・状態変更**（Watch → iPhone の書き戻し）
- **Watch 単体での通知**

---

関連：
- [予定が近づいたら Apple Watch を振動させる設定](apple-watch-event-haptics.md)
- [買い物リストを Apple Watch で使う](apple-watch-shopping-list.md)
