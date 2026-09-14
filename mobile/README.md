# iPhone アプリとして書き出す（Capacitor）

`apps/` の2つのアプリを、そのまま **iPhone のネイティブアプリ**に包むための設定一式。
Web の作りはそのままで、アプリとして動いているときだけ端末の通知機能を使う。

> **どこまで確認済みか**
> - iOS プロジェクトの生成（`npx cap add ios`）、`npm install`、`www` の組み立て、`cap sync` までは
>   **この環境で実行して成功を確認済み**。生成された `ios/` はこのリポジトリに入っている
> - **Xcode でのビルドと実機での動作は未検証**（Mac が必要なため）。手順は一般的なやり方に沿って書いている

Capacitor 8 は CocoaPods を使わず Swift Package Manager で依存を解決するため、
**Mac 側で必要なのは Xcode の操作だけ**になっている。

## アプリにすると何が変わるか

| | ホーム画面に追加（PWA） | ネイティブアプリ |
| --- | --- | --- |
| 起動・オフライン | できる | できる |
| バーコード読み取り | できる（自前デコーダ） | できる（さらに高精度な部品も追加可） |
| **期限の通知** | カレンダー経由 | **アプリから直接通知**（カレンダーに予定を入れなくてよい） |
| 配布 | URL を開くだけ | Mac でのビルドが必要 |
| 費用 | 無料 | 無料（7日ごと再インストール）／年約15,000円で1年間有効 |

通知の切り替えは自動で、アプリ側のコードを変える必要はない。
`apps/shared/native.js` が「アプリとして動いているか」を判定し、
アプリなら端末の通知に登録、ブラウザならこれまでどおりカレンダーに登録する。

## 準備済みのもの

このリポジトリの `mobile/ios/` に Xcode プロジェクトが入っている。次は設定済み。

- アプリ名：**日常アプリ**（`CFBundleDisplayName`）
- Bundle Identifier：`jp.myproject.dailyapps`
- **カメラの利用目的**（`NSCameraUsageDescription`）— 未設定だと読み取り時にアプリが落ちるため設定済み
- アプリアイコンと起動画面
- 画面の向き：縦のみ／対応 iOS：15.0 以降
- ローカル通知プラグイン（`@capacitor/local-notifications`）

## 必要なもの

- Mac（macOS）
- Xcode（Mac App Store から無料。初回は10GB以上のダウンロードがある）
- Node.js 18 以降
- Apple ID（無料のもので可）

## 手順（Mac で）

### 1. 取得して組み立てる

```bash
git clone https://github.com/akihitofujioka-bit/myproject.git
cd myproject/mobile
npm install       # Xcode を開く前に必須（Package.swift が node_modules を参照するため）
npm run sync      # apps/ の中身を www/ に写し、iOS プロジェクトへ反映する
```

### 2. Xcode で開く

```bash
open ios/App/App.xcodeproj
```

初回は Swift Package の取得が走るので、ネットワークに繋いだまま少し待つ。

### 3. 署名して実機に入れる

1. 左の一覧から **App** を選び、**Signing & Capabilities** タブを開く
2. **Team** に自分の Apple ID を選ぶ（初回は「Add an Account…」から登録）
3. Bundle Identifier が他人と重複するとエラーになる。その場合は `jp.myproject.dailyapps` の後ろに何か足す
4. iPhone を Mac に繋ぎ、画面上部の実行先を自分の iPhone にする
5. ▶︎（Run）を押す

### 4. iPhone 側で許可する

初回は「信頼されていない開発元」と出るので、
**設定 → 一般 → VPNとデバイス管理** から自分の Apple ID を選び「信頼」する。

そのあとアプリを開き、

- **通知の許可**：「カレンダーに登録」を初めて押したときに聞かれる。許可すると、以降は
  カレンダーを経由せずアプリから直接通知が出る
- **カメラの許可**：バーコードを初めて読むときに聞かれる

## 費用と有効期限

- **無料の Apple ID**：アプリは**7日間**で起動できなくなる。Mac に繋いで再度 ▶︎ を押せば復活する
- **Apple Developer Program（年 約15,000円）**：1年間有効になる。App Store への公開もこの契約が必要

家族や同僚に配るのでなければ、まず無料で試して、7日ごとの再インストールが面倒なら
契約を検討する、という順序で問題ない。

## アプリを更新するとき

`apps/` の中身が変わったら、Mac で次を実行して Xcode から再ビルドする。

```bash
cd mobile
git pull
npm run sync
open ios/App/App.xcodeproj
```

## 補足

- **Service Worker は www から除いている。** アプリ内ではファイルが端末にあるため不要
- `ios/App/App/public`（web の実体）と `capacitor.config.json` は `npm run sync` で作られる生成物のため、
  git の管理対象外にしている。**clone 直後は必ず `npm run sync` を実行する**
- **バーコードをさらに高精度にしたい場合**は、Apple / Google の読み取り部品を使うプラグインを足せる。
  `npm i @capacitor-mlkit/barcode-scanning` を入れたうえで、`apps/shared/native.js` に
  読み取り用の関数を足し、`apps/fridge/index.html` の読み取り処理から呼ぶ形になる（未実装）
- **Android も同じ手順で作れる**（`npx cap add android`、必要なのは Android Studio）。Mac は不要
