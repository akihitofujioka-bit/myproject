# 配布用アプリ「ふたりのメッセージ」（Android）

知り合いに渡すための、**メッセージアプリ単体**の Capacitor プロジェクト。

**手順は [`docs/android-distribution.md`](../docs/android-distribution.md) にまとめてある。**

```bash
npm install     # 初回だけ
npm run apk     # 署名済みの配布用 APK を作る
npm run android # Android Studio で開く
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

- 求める権限は**インターネット接続だけ**（カメラ・連絡先・位置情報・保存領域は求めない）
- 自動バックアップと端末間の移行を**無効**にしている（秘密鍵と履歴を端末の外へ出さないため）
- 暗号化なしの `http://` 通信を**禁止**している
- スクリーンショットと画面録画を**不可**にしている（`MainActivity.java` の `FLAG_SECURE`）

これらは `node apps/tests/android-package.test.mjs` で機械的に検査している。

## 署名鍵について

`keystore.properties` と `*.keystore` は **git 管理から外してある**。
失うと更新できなくなり、漏れると更新版を偽造される。作り方と保管方法は手順書を参照。
