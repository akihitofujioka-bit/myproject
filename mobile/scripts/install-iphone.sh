#!/bin/bash
# USB で繋いだ iPhone に、アプリをビルドして入れ直す（Mac 専用）。
#
#   cd mobile && npm run iphone
#
# やること: www の組み立て → cap sync → 署名付きビルド → iPhone へ転送 → 起動。
# Xcode の画面操作は不要。iPhone はロックを解除しておく。
# 無料の Apple ID 署名は 7 日で切れるので、切れたらこれをもう一度実行すればよい。
set -e
cd "$(dirname "$0")/.."

DEVICE="${IPHONE_UDID:-}"
if [ -z "${DEVICE}" ]; then
  # 繋がっている本物の iPhone（physical）を 1 台選ぶ。シミュレータや Apple Watch は除く。
  DEVICE=$(xcrun devicectl list devices 2>/dev/null \
    | grep -E "physical" | grep -Ei "iPhone" \
    | grep -oE '[0-9A-Fa-f]{8}-[0-9A-Fa-f]{16}' | head -1)
fi
if [ -z "${DEVICE}" ]; then
  echo "✗ iPhone が見つかりません。USB 接続とロック解除、「このコンピュータを信頼」を済ませてください。" >&2
  echo "  複数台あるときは IPHONE_UDID=xxxx npm run iphone で指定できます。" >&2
  exit 1
fi
echo "▶ 転送先: ${DEVICE}"

echo "▶ www を組み立てて iOS プロジェクトへ反映…"
npm run sync

BUILD_DIR="${BUILD_DIR:-$PWD/.build}"
echo "▶ ビルド中（署名は自動更新）…"
xcodebuild -project ios/App/App.xcodeproj -scheme App -configuration Debug \
  -destination "id=${DEVICE}" -derivedDataPath "$BUILD_DIR" \
  -allowProvisioningUpdates -allowProvisioningDeviceRegistration build \
  | grep -E "^\*\* BUILD|error:" || true

APP="$BUILD_DIR/Build/Products/Debug-iphoneos/App.app"
if [ ! -d "$APP" ]; then
  echo "✗ ビルド成果物が見つかりません: $APP" >&2
  exit 1
fi

VERSION=$(cat www/version.txt)   # build-www.mjs が書いた「日時（コミット番号）」
echo "▶ iPhone へインストール中（版 ${VERSION}）…"
xcrun devicectl device install app --device "${DEVICE}" "$APP" | grep -E "App installed|bundleID"

# 起動はおまけ。iPhone がロック中だと拒否されるので、その場合は手で開いてもらう。
if xcrun devicectl device process launch --device "${DEVICE}" jp.myproject.dailyapps >/dev/null 2>&1; then
  echo "✓ 完了。アプリを起動しました。"
else
  echo "✓ インストールは完了（iPhone がロック中のため自動起動はできませんでした。ホーム画面から開いてください）。"
fi
echo "  トップ画面の一番下に「版 ${VERSION}」と出ていれば新しい版です。"
