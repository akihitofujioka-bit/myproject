#!/bin/bash
# Apple Watch に、アプリをビルドして入れ直す（Mac 専用）。
#
#   USB 接続: cd mobile && npm run apple-watch
#   WiFi 接続: cd mobile && WIFI=1 npm run apple-watch
#
# やること: www の組み立て → cap sync → Watch アプリをビルド → Apple Watch へ転送 → 起動。
# Xcode の画面操作は不要。Apple Watch はペアリング済みで、iPhone と同じ WiFi に接続していることを確認。
set -eo pipefail
cd "$(dirname "$0")/.."

WIFI_MODE="${WIFI:-0}"
DEVICE="${IPHONE_UDID:-}"

# Apple Watch を探す（iPhone でペアリング済みのもの）
if [ -z "${DEVICE}" ]; then
  echo "▶ ペアリング済みの Apple Watch を探索中…"
  if [ "${WIFI_MODE}" = "1" ]; then
    DEVICE=$(xcrun devicectl list devices 2>/dev/null \
      | grep -E "physical.*network" | grep -Ei "Watch" \
      | grep -oE '[0-9A-Fa-f]{8}-[0-9A-Fa-f]{16}' | head -1)
  else
    DEVICE=$(xcrun devicectl list devices 2>/dev/null \
      | grep -E "physical" | grep -Ei "Watch" \
      | grep -oE '[0-9A-Fa-f]{8}-[0-9A-Fa-f]{16}' | head -1)
  fi
fi

if [ -z "${DEVICE}" ]; then
  if [ "${WIFI_MODE}" = "1" ]; then
    echo "✗ WiFi 接続の Apple Watch が見つかりません。以下を確認してください：" >&2
    echo "  1. Apple Watch が WiFi に接続している" >&2
    echo "  2. Mac と同じ WiFi ネットワークに繋がっている" >&2
    echo "  3. Apple Watch が iPhone とペアリングされている" >&2
    echo "  複数台あるときは IPHONE_UDID=xxxx WIFI=1 npm run apple-watch で指定できます。" >&2
  else
    echo "✗ USB 接続の Apple Watch が見つかりません。以下を確認してください：" >&2
    echo "  1. Apple Watch が USB で Mac に接続している（またはペアリング済み iPhone で接続）" >&2
    echo "  2. Apple Watch が iPhone とペアリングされている" >&2
    echo "  3. 「このコンピュータを信頼」をタップしている" >&2
    echo "  複数台あるときは IPHONE_UDID=xxxx npm run apple-watch で指定できます。" >&2
  fi
  exit 1
fi

CONNECTION_TYPE="USB"
if [ "${WIFI_MODE}" = "1" ]; then
  CONNECTION_TYPE="WiFi"
fi
echo "▶ 転送先: ${DEVICE}（${CONNECTION_TYPE} 接続）"

echo "▶ www を組み立てて iOS プロジェクトへ反映…"
npm run sync

BUILD_DIR="${BUILD_DIR:-$PWD/.build}"
WATCH_SCHEME="${WATCH_SCHEME:-WatchApp}"

echo "▶ Watch アプリをビルド中（署名は自動更新）…"
xcodebuild -project ios/App/App.xcodeproj -scheme "$WATCH_SCHEME" -configuration Debug \
  -destination "id=${DEVICE}" -derivedDataPath "$BUILD_DIR" \
  -allowProvisioningUpdates -allowProvisioningDeviceRegistration build \
  | grep -E "^\*\* BUILD|error:"

WATCH_APP="$BUILD_DIR/Build/Products/Debug-watchos/WatchApp.app"
if [ ! -d "$WATCH_APP" ]; then
  echo "✗ Watch ビルド成果物が見つかりません: $WATCH_APP" >&2
  echo "  Scheme 名が違う可能性があります。以下で確認してください：" >&2
  echo "  cd ios/App && xcodebuild -project App.xcodeproj -list | grep -A 20 'Schemes:'" >&2
  echo "  見つかった Scheme を WATCH_SCHEME=<名前> npm run apple-watch で指定してください。" >&2
  exit 1
fi

VERSION=$(cat www/version.txt)   # build-www.mjs が書いた「日時（コミット番号）」
echo "▶ Apple Watch へインストール中（版 ${VERSION}）…"
xcrun devicectl device install app --device "${DEVICE}" "$WATCH_APP" | grep -E "App installed|bundleID"

# 起動はおまけ。Apple Watch がロック中だと拒否されるので、その場合は手で開いてもらう。
BUNDLE_ID="jp.myproject.dailyapps.watchkit"
if xcrun devicectl device process launch --device "${DEVICE}" "$BUNDLE_ID" >/dev/null 2>&1; then
  echo "✓ 完了。Watch アプリを起動しました。"
else
  echo "✓ インストールは完了（Apple Watch がロック中のため自動起動はできませんでした。Watch から開いてください）。"
fi
echo "  Apple Watch で壱師アプリを開き、「版 ${VERSION}」と出ていれば新しい版です。"
