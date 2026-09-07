/*
 * 配布用の APK（署名済み）を作る。
 *
 *   npm run apk
 *
 * 事前に、署名鍵と keystore.properties を1回だけ作っておく必要がある。
 * 作り方は docs/android-distribution.md を参照（このスクリプトも手順を表示する）。
 *
 * Android SDK が要る（Android Studio を入れると一緒に入る）。
 */
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PROJECT = path.resolve(HERE, "..");
const ANDROID = path.join(PROJECT, "android");
const PROPS = path.join(PROJECT, "keystore.properties");

function fail(message) {
  console.error("\n" + message + "\n");
  process.exit(1);
}

if (!fs.existsSync(ANDROID)) {
  fail("android フォルダがありません。先に `npx cap add android` を実行してください。");
}

if (!fs.existsSync(PROPS)) {
  fail([
    "署名鍵の設定（keystore.properties）がありません。",
    "配布する APK には署名が要ります。次の2つを1回だけ行ってください。",
    "",
    "【1】署名鍵を作る（暗証番号を2回聞かれます。忘れないように控えてください）",
    "",
    "  cd " + PROJECT,
    "  keytool -genkeypair -v -keystore messenger-release.keystore \\",
    "    -alias messenger -keyalg RSA -keysize 4096 -validity 10000",
    "",
    "【2】" + PROPS + " を作り、次の4行を書く",
    "",
    "  storeFile=messenger-release.keystore",
    "  storePassword=（上で決めた暗証番号）",
    "  keyAlias=messenger",
    "  keyPassword=（上で決めた暗証番号）",
    "",
    "※ この鍵と暗証番号を失うと、以後このアプリを更新できなくなります（作り直しになります）。",
    "※ 鍵と keystore.properties は git 管理から外してあります。人に渡さないでください。"
  ].join("\n"));
}

// 中身を最新にしてから組み立てる
const gradlew = process.platform === "win32" ? "gradlew.bat" : "./gradlew";
console.log("APK を組み立てています（初回は数分かかります）…\n");
const built = spawnSync(gradlew, ["assembleRelease"], { cwd: ANDROID, stdio: "inherit", shell: process.platform === "win32" });

if (built.status !== 0) {
  fail([
    "組み立てに失敗しました。よくある原因：",
    "  - Android SDK が見つからない → Android Studio を一度起動して SDK を入れる",
    "    （または android/local.properties に sdk.dir=/Users/自分/Library/Android/sdk と書く）",
    "  - keystore.properties の暗証番号が違う"
  ].join("\n"));
}

const apk = path.join(ANDROID, "app/build/outputs/apk/release/app-release.apk");
if (!fs.existsSync(apk)) fail("APK が見つかりません: " + apk);

const bytes = fs.readFileSync(apk);
const digest = createHash("sha256").update(bytes).digest("hex").replace(/(.{4})/g, "$1 ").trim();

console.log("\n============================================================");
console.log("できあがりました。このファイルを相手に渡してください。");
console.log("");
console.log("  場所　: " + apk);
console.log("  大きさ: " + (bytes.length / 1024 / 1024).toFixed(1) + " MB");
console.log("");
console.log("  確認用の符号（SHA-256）:");
console.log("  " + digest);
console.log("");
console.log("  渡したあと、相手の手元のファイルの符号が上と同じか読み合わせると、");
console.log("  途中ですり替えられていないことを確認できます。");
console.log("  相手側の確認方法（パソコン）: shasum -a 256 ファイル名");
console.log("============================================================\n");
