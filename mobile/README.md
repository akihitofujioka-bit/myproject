# iPhone / Android アプリとして書き出す（Capacitor）

`apps/` の3つのアプリ（冷蔵庫・書類トラッカー・ふたりのメッセージ）を、そのまま
**iPhone / Android のネイティブアプリ**に包むための設定一式。
Web の作りはそのままで、アプリとして動いているときだけ端末の通知機能を使う。

> **重要：ビルド以降の手順は未検証です。**
> iOS のビルドには Mac と Xcode、Android のビルドには Android Studio が必要で、
> この作業環境（Linux）では実行も確認もできません。
> 設定ファイルと `www` の組み立てまでは動作を確認しています（`npm install` と `npm run build` は通ります）。
> Xcode / Android Studio 以降の手順は一般的なやり方に沿って書いたもので、実機で確かめていません。
>
> なお、**アプリの中身（画面・暗号処理・中継サーバーとのやりとり）は
> ブラウザで実際に動かして確認済み**です（`node apps/tests/messenger.smoke.mjs`）。

## アプリにすると何が変わるか

| | ホーム画面に追加（今の形） | ネイティブアプリ |
| --- | --- | --- |
| 起動・オフライン | できる | できる |
| バーコード読み取り | できる（自前デコーダ） | できる（さらに高精度な部品も追加可） |
| **期限の通知** | カレンダー経由 | **アプリから直接通知**（カレンダーに予定を入れなくてよい） |
| メッセージの着信通知 | 画面を開いているときだけ | **アプリからの通知**（閉じていても気づける） |
| 配布 | URL を開くだけ | iPhone は Mac、Android は Android Studio でのビルドが必要 |
| 費用 | 無料 | 無料（7日ごと再インストール）／年約15,000円で1年間有効 |

通知の切り替えは自動で、アプリ側のコードを変える必要はない。
`apps/shared/native.js` が「アプリとして動いているか」を判定し、
アプリなら端末の通知に登録、ブラウザならこれまでどおりカレンダーに登録する。

## 必要なもの

**iPhone 向け**

- Mac（macOS）
- Xcode（Mac App Store から無料。初回は10GB以上のダウンロードがある）
- Node.js 18 以降
- Apple ID（無料のもので可）

**Android 向け**

- Windows / Mac / Linux のいずれでもよい（**Mac でも作れるし、Mac でなくても作れる**）
- Android Studio（無料。macOS 版があり、Apple Silicon にも対応している。Xcode は要らない）
- Node.js 18 以降

> **Mac 1台あれば iPhone と Android の両方が作れる。**
> iOS 用（`mobile/ios/`）と Android 用（`mobile/android/`）は別のフォルダに作られるため共存でき、
> アプリを直したあとは `npm run sync` を1回実行すれば両方に反映される。

## iPhone の手順

### 1. 準備（Mac のターミナルで）

```bash
git clone https://github.com/akihitofujioka-bit/myproject.git
cd myproject/mobile
npm install
npm run build     # apps/ の中身を www/ に写す
npx cap add ios   # iOS のプロジェクトを作る（初回だけ）
```

### 2. カメラと写真の利用目的を書く（必須）

`mobile/ios/App/App/Info.plist` を開き、`<dict>` の中に次を足す。
**これを忘れるとバーコード読み取りや写真の添付の瞬間にアプリが落ちる。**

```xml
<key>NSCameraUsageDescription</key>
<string>商品のバーコードを読み取るためにカメラを使用します</string>
<key>NSPhotoLibraryUsageDescription</key>
<string>メッセージに添える写真を選ぶために写真を使用します</string>
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

## Android の手順

```bash
cd myproject/mobile
npm install
npm run build       # apps/ の中身を www/ に写す
npx cap add android # Android のプロジェクトを作る（初回だけ）
npm run android     # www を作り直して Android Studio を開く
```

Android Studio が開いたら、端末を USB で繋いで ▶︎（Run）を押す。
端末側で「USBデバッグ」を有効にしておくこと（設定 → デバイス情報 →
ビルド番号を7回タップ → 開発者向けオプション → USBデバッグ）。

- **Mac でも Windows でも Linux でも、同じ手順で作れる。**iPhone と違い Mac は必須ではない
- カメラの許可は `android/app/src/main/AndroidManifest.xml` に
  `<uses-permission android:name="android.permission.CAMERA" />` を足す
- 写真の添付は端末標準の選択画面を使うため、追加の許可は要らない
- 配布は APK をそのまま渡すか、Google Play（初回のみ登録料 約4,000円）
- **自分の端末に入れるだけなら完全に無料で、期限もない**（iPhone の「7日ごとに入れ直し」のような制限がない）

## 「ふたりのメッセージ」を使うときの注意

- **中継サーバーは必ず `https://` で用意すること。** `http://` は端末側の決まりで遮断される
  （`capacitor.config.json` の `android.allowMixedContent` を `false` にしてあるのはこのため）
- 鍵と履歴は端末の中（IndexedDB）にある。**アプリを削除すると会話も消える**。
  機種変更の前に、設定 →「JSONで保存」で書き出すこと
- 用意のしかたと使い方は [`docs/messenger-setup.md`](../docs/messenger-setup.md) にまとめてある

## 費用と有効期限

- **無料の Apple ID**：アプリは**7日間**で起動できなくなる。Mac に繋いで再度 ▶︎ を押せば復活する
- **Apple Developer Program（年 約15,000円）**：1年間有効になる。App Store への公開もこの契約が必要

家族や同僚に配るのでなければ、まず無料で試して、7日ごとの再インストールが面倒なら
契約を検討する、という順序で問題ない。

## アプリを更新するとき

`apps/` の中身を直したあと、次を実行して再ビルドする。

```bash
cd mobile
npm run sync      # www を作り直し、iOS / Android のプロジェクトに反映する
npm run ios       # または npm run android
```

## 補足

- **Service Worker は www から除いている。** アプリ内ではファイルが端末にあるため不要
- **バーコードをさらに高精度にしたい場合**は、Apple / Google の読み取り部品を使うプラグインを足せる。
  `npm i @capacitor-mlkit/barcode-scanning` を入れたうえで、`apps/shared/native.js` に
  読み取り用の関数を足し、`apps/fridge/index.html` の読み取り処理から呼ぶ形になる（未実装）
- 更新の反映は iOS も Android も同じ（`npm run sync` のあと、それぞれの開発環境で再ビルド）
