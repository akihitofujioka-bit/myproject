# iPhone アプリとして書き出す（Capacitor）

`apps/` の2つのアプリを、そのまま **iPhone のネイティブアプリ**に包むための設定一式。
Web の作りはそのままで、アプリとして動いているときだけ端末の通知機能を使う。

> **重要：この手順は未検証です。**
> iOS のビルドには Mac と Xcode が必要で、この作業環境（Linux）では実行も確認もできません。
> 設定ファイルと `www` の組み立てまでは動作を確認しています（`npm install` と `npm run build` は通ります）。
> Xcode 以降の手順は一般的なやり方に沿って書いたもので、実機で確かめていません。

## アプリにすると何が変わるか

| | ホーム画面に追加（今の形） | ネイティブアプリ |
| --- | --- | --- |
| 起動・オフライン | できる | できる |
| バーコード読み取り | できる（自前デコーダ） | できる（さらに高精度な部品も追加可） |
| **期限の通知** | カレンダー経由 | **アプリから直接通知**（カレンダーに予定を入れなくてよい） |
| 配布 | URL を開くだけ | Mac でのビルドが必要 |
| 費用 | 無料 | 無料（7日ごと再インストール）／年約15,000円で1年間有効 |

通知の切り替えは自動で、アプリ側のコードを変える必要はない。
`apps/shared/native.js` が「アプリとして動いているか」を判定し、
アプリなら端末の通知に登録、ブラウザならこれまでどおりカレンダーに登録する。

## 必要なもの

- Mac（macOS）
- Xcode（Mac App Store から無料。初回は10GB以上のダウンロードがある）
- Node.js 18 以降
- Apple ID（無料のもので可）

## 手順

### 1. 準備（Mac のターミナルで）

```bash
git clone https://github.com/akihitofujioka-bit/myproject.git
cd myproject/mobile
npm install
npm run build     # apps/ の中身を www/ に写す
npx cap add ios   # iOS のプロジェクトを作る（初回だけ）
```

### 2. カメラの利用目的を書く（必須）

`mobile/ios/App/App/Info.plist` を開き、`<dict>` の中に次の2行を足す。
**これを忘れるとバーコード読み取りの瞬間にアプリが落ちる。**

```xml
<key>NSCameraUsageDescription</key>
<string>商品のバーコードを読み取るためにカメラを使用します</string>
```

### 3. Xcode で開いてiPhoneに入れる

```bash
npm run ios       # www を作り直して Xcode を開く
```

Xcode が開いたら：

1. 左の一覧から **App** を選び、**Signing & Capabilities** タブを開く
2. **Team** に自分の Apple ID を選ぶ（初回は「Add an Account…」から登録）
3. **Bundle Identifier** が他人と重複するとエラーになる。その場合は `jp.myproject.dailyapps` の後ろに何か足す
4. iPhone を Mac に繋ぎ、画面上部の実行先を自分の iPhone にする
5. ▶︎（Run）を押す

### 4. iPhone 側で許可する

初回は「信頼されていない開発元」と出るので、
**設定 → 一般 → VPNとデバイス管理** から自分の Apple ID を選び「信頼」する。

## 費用と有効期限

- **無料の Apple ID**：アプリは**7日間**で起動できなくなる。Mac に繋いで再度 ▶︎ を押せば復活する
- **Apple Developer Program（年 約15,000円）**：1年間有効になる。App Store への公開もこの契約が必要

家族や同僚に配るのでなければ、まず無料で試して、7日ごとの再インストールが面倒なら
契約を検討する、という順序で問題ない。

## アプリを更新するとき

`apps/` の中身を直したあと、Mac で次を実行して Xcode から再ビルドする。

```bash
cd mobile
npm run sync      # www を作り直し、iOS プロジェクトに反映する
npm run ios
```

## 補足

- **Service Worker は www から除いている。** アプリ内ではファイルが端末にあるため不要
- **バーコードをさらに高精度にしたい場合**は、Apple / Google の読み取り部品を使うプラグインを足せる。
  `npm i @capacitor-mlkit/barcode-scanning` を入れたうえで、`apps/shared/native.js` に
  読み取り用の関数を足し、`apps/fridge/index.html` の読み取り処理から呼ぶ形になる（未実装）
- **Android も同じ手順で作れる**（`npx cap add android`、必要なのは Android Studio）。Mac は不要
