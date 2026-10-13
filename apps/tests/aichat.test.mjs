/*
 * apps/shared/aichat.js（端末内 AI へ渡す会話を組み立てる部品）のテスト。
 *
 *   node apps/tests/aichat.test.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const g = {};
const aichatPath = path.join(ROOT, "apps/shared/aichat.js");
if (fs.existsSync(aichatPath)) {
  new Function("window", fs.readFileSync(aichatPath, "utf8"))(g);
}
const A = g.AIChat;

let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};

function codedError(code) {
  const error = new Error("にせ AI の失敗");
  error.code = code;
  return error;
}

if (!A) {
  ok(false, "window.AIChat が公開されている");
} else {
  ok(JSON.stringify(A.MODES) === JSON.stringify({ secretary: "秘書", sparring: "壁打ち", brainstorm: "ブレスト" }), "3つの会話モードを公開する");

  const messages = Array.from({ length: 20 }, (_, index) => ({
    role: index % 2 ? "ai" : "user",
    text: "架空の会話" + index
  }));
  const latest = A.recent(messages, 6);
  ok(latest.length === 12 && latest[0] === messages[8] && latest[11] === messages[19], "直近6往復の12件を切り出す");

  const clipped = A.clip("あ".repeat(3001), 3000);
  ok(clipped.text.length === 3000 && clipped.cut === true, "資料を3,000字で切る");
  ok(A.clip("短い資料", 3000).cut === false, "上限内の資料は切らない");
  ok(A.sourceNotice(true) === "資料が長いため先頭 3,000 字だけ渡しています" && A.sourceNotice(false) === "", "資料を切ったときだけ案内を返す");

  const source = { title: "架空の検討資料", body: "架空の本文" };
  const sparring = A.instructions("sparring", { today: "2026-10-13", context: "", source });
  const brainstorm = A.instructions("brainstorm", { today: "2026-10-13", context: "", source: null });
  const secretary = A.instructions("secretary", { today: "2026-10-13", context: "架空の予定一覧", source: null });
  ok(sparring.includes("問いを 1 つ返す") && sparring.includes("資料: 架空の検討資料\n架空の本文"), "壁打ちの指示と資料を組み立てる");
  ok(brainstorm.includes("8〜10 個"), "ブレストの指示を組み立てる");
  ok(secretary.includes("分かりません") && secretary.includes("2026-10-13（火）") && secretary.includes("架空の予定一覧"), "秘書の指示に日付・曜日・一覧を含める");

  const calls = [];
  const retryingAI = {
    respond(options) {
      calls.push(options);
      if (calls.length === 1) return Promise.reject(codedError("tooLong"));
      return Promise.resolve({ text: "考えを整理できました" });
    }
  };
  const retried = await A.ask(retryingAI, {
    mode: "sparring",
    today: "2026-10-13",
    context: "",
    source: { title: "架空の長い資料", body: "資".repeat(3200) },
    messages,
    question: "架空の企画をどう考えますか"
  });
  const secondHistoryLines = calls[1].prompt.split("\n").filter(line => /^(利用者|相手):/.test(line)).length - 1;
  const secondSourceBody = calls[1].instructions.split("\n").at(-1);
  ok(retried.text === "考えを整理できました" && retried.retried === true && calls.length === 2, "上限超過なら1回だけ減らしてやり直す");
  ok(secondHistoryLines <= 4 && secondSourceBody.length <= 1500, "やり直しは直近2往復・資料1,500字に減らす");
  ok(calls[0].prompt.includes("利用者: 架空の会話8") && calls[0].prompt.endsWith("利用者: 架空の企画をどう考えますか"), "履歴と今回の質問に話者名を付ける");

  let twiceError;
  let twiceCalls = 0;
  try {
    await A.ask({ respond() { twiceCalls++; return Promise.reject(codedError("tooLong")); } }, {
      mode: "brainstorm", today: "2026-10-13", context: "", source: null, messages, question: "架空の案を出して"
    });
  } catch (error) {
    twiceError = error;
  }
  ok(twiceError instanceof Error && twiceError.code === "tooLong" && twiceCalls === 2, "2回とも上限超過なら理由を保って失敗する");

  let refusedError;
  let refusedCalls = 0;
  try {
    await A.ask({ respond() { refusedCalls++; return Promise.reject(codedError("refused")); } }, {
      mode: "secretary", today: "2026-10-13", context: "架空の一覧", source: null, messages: [], question: "教えて"
    });
  } catch (error) {
    refusedError = error;
  }
  ok(refusedError instanceof Error && refusedError.code === "refused" && refusedCalls === 1, "拒否はやり直さず理由を保って失敗する");

  ok(A.errorMessage("unsupported") === "この端末では端末内 AI を使えません（iOS 26 以降の Apple Intelligence 対応機が必要です）", "非対応の案内文を返す");
  ok(A.errorMessage("unavailable") === A.errorMessage("unsupported"), "利用不能は非対応と同じ案内文にする");
  ok(A.errorMessage("oldOS") === "iOS 26 以降にすると使えます", "古いOSの案内文を返す");
  ok(A.errorMessage("disabled") === "設定 → Apple Intelligence と Siri でオンにしてください", "AIがオフの案内文を返す");
  ok(A.errorMessage("notReady") === "AI の準備中です。しばらくしてからもう一度お試しください", "準備中の案内文を返す");
  ok(A.errorMessage("tooLong") === "長くなったため答えられません。新しい会話を始めてください", "上限超過の案内文を返す");
  ok(A.errorMessage("refused") === "答えを作れませんでした。言い方を変えてみてください" && A.errorMessage("failed") === A.errorMessage("refused"), "拒否と失敗の案内文を返す");
}

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
