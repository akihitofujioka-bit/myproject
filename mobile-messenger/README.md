# アプリ「ふたりのメッセージ」（Android / iPhone）

**メッセージアプリ単体**の Capacitor プロジェクト。
相手に渡す Android 版と、自分の iPhone に入れる iOS 版の両方をここから作る。

| 目的 | 手順書 |
| --- | --- |
| 知り合いに渡す（Android） | [`docs/android-distribution.md`](../docs/android-distribution.md) |
| 自分の iPhone に入れる | [`docs/iphone-install.md`](../docs/iphone-install.md) |

```bash
npm install     # 初回だけ
npm run apk     # 署名済みの配布用 APK を作る（Android）
npm run android # Android Studio で開く
npm run ios     # Xcode で開く（Mac が必要）
```

## `mobile/` との違い

| | `mobile/` | `mobile-messenger/`（ここ） |
| --- | --- | --- |
| 中身 | 冷蔵庫・書類トラッカー・メッセージの3つ | **メッセージだけ** |
| 用途 | 自分用 | **人に渡す用** |
| アプリ識別子 | `jp.myproject.dailyapps` | `jp.myproject.messenger` |

**業務書類を扱う「書類・回覧の期限トラッカー」を配布先に渡さないため**に分けてある。
この分離は意図的なものなので、`scripts/build-www.mjs` に他のアプリを足さないこと。

## 安全上の設定

| 項目 | Android | iPhone |
| --- | --- | --- |
| 求める権限 | インターネット接続だけ | 写真・カメラ（利用目的を明記） |
| バックアップ | 自動バックアップ・端末間移行を無効 | iCloud・パソコンへのバックアップから除外 |
| `http://` 通信 | 禁止 | 禁止 |
| スクリーンショット | **不可**（`FLAG_SECURE`） | iOS に止める仕組みが無いため**可能** |
| アプリ切り替えの一覧 | 会話が写らない | 会話が写らない（単色で覆う） |

バックアップを外しているため、**どちらの端末でも機種変更でメッセージは引き継がれない**。
引き継ぐときはアプリの「JSONで保存」を使う。

これらは `node apps/tests/mobile-package.test.mjs` で機械的に検査している。

## 署名鍵について

`keystore.properties` と `*.keystore` は **git 管理から外してある**。
失うと更新できなくなり、漏れると更新版を偽造される。作り方と保管方法は手順書を参照。
