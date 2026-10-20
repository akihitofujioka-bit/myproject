/*
 * 予定アプリの端末内 AI 画面（Playwright が必要）。
 *
 *   NODE_PATH=<playwright の場所> node apps/tests/scheduleai.test.mjs
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { waitAsync } from "./tools/waitasync.mjs";

const require = createRequire(import.meta.url);
let chromium;
try {
  ({ chromium } = require("playwright"));
} catch (error) {
  console.error("Playwright が見つかりません。");
  process.exit(1);
}

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const types = { ".html": "text/html", ".js": "text/javascript", ".png": "image/png" };
const server = http.createServer((request, response) => {
  const file = path.join(ROOT, decodeURIComponent(request.url.split("?")[0]));
  fs.readFile(file, (error, data) => {
    if (error) { response.writeHead(404); response.end(); return; }
    response.writeHead(200, { "content-type": types[path.extname(file)] || "application/octet-stream" });
    response.end(data);
  });
});
await new Promise((resolve, reject) => {
  server.once("error", reject);
  server.listen(0, "127.0.0.1", resolve);
});

const base = `http://127.0.0.1:${server.address().port}/apps/schedule/index.html`;
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
let failures = 0;
const ok = (condition, label) => {
  console.log((condition ? "PASS " : "FAIL ") + label);
  if (!condition) failures++;
};

const fakeNative = reason => {
  const RealDate = Date;
  // 2026-10-13 10:00 から実際の経過時間だけ進む時計（止めると履歴の更新日時がそろい、新しい順が決まらない）
  const fixedStart = new RealDate("2026-10-13T10:00:00+09:00").getTime();
  const realStart = RealDate.now();
  const fixedNow = () => fixedStart + (RealDate.now() - realStart);
  function FixedDate(...args) {
    if (!new.target) return RealDate(...args);
    return new RealDate(...(args.length ? args : [fixedNow()]));
  }
  Object.setPrototypeOf(FixedDate, RealDate);
  FixedDate.prototype = RealDate.prototype;
  FixedDate.now = fixedNow;
  window.Date = FixedDate;
  window.__ai = { calls: [], alertCount: 0, reason, refusedCount: 0, statusCalls: 0 };
  window.alert = () => { window.__ai.alertCount++; };
  const codedError = code => {
    const error = new Error("にせ AI の失敗");
    error.code = code;
    return error;
  };
  const respond = options => {
    window.__ai.calls.push(options);
    if (options.instructions.includes("登録用の下書き")) {
      if (options.prompt.includes("順番を確かめる")) {
        return new Promise(resolve => {
          window.__ai.resolveDraft = () => resolve({ text: JSON.stringify({ kind: "event", title: "順番確認の架空予定", date: "2026-10-20", start: "10:00", end: "11:00", place: "", memo: "" }) });
        });
      }
      if (options.prompt.includes("JSON失敗")) return Promise.resolve({ text: "JSONではありません" });
      if (options.prompt.includes("TODO")) {
        return Promise.resolve({ text: JSON.stringify({ kind: "TODO", title: "架空の資料を出す", date: "2026-10-16", start: "", end: "", place: "", memo: "" }) });
      }
      return Promise.resolve({ text: JSON.stringify({ kind: "event", title: "架空の打合せ", date: "2026-10-20", start: "10:00", end: "11:00", place: "架空会議室", memo: "架空メモ" }) });
    }
    if (options.prompt.includes("遅い答え")) {
      return new Promise(resolve => { window.__ai.resolveDelayed = () => resolve({ text: "遅れて届いた架空の答え" }); });
    }
    if (options.prompt.includes("答え失敗で下書きなし")) return Promise.reject(codedError("refused"));
    if (options.prompt.includes("拒否して") && window.__ai.refusedCount++ === 0) return Promise.reject(codedError("refused"));
    if (options.prompt.includes("危険な文字")) return Promise.resolve({ text: "<script>alert(1)</script>" });
    return Promise.resolve({ text: "架空の答えです" });
  };
  window.Capacitor = {
    isNativePlatform: () => true,
    Plugins: {
      OnDeviceAI: {
        status: () => {
          window.__ai.statusCalls++;
          return Promise.resolve(window.__ai.reason ? { available: false, reason: window.__ai.reason } : { available: true, reason: "" });
        },
        respond
      }
    },
    nativePromise: (plugin, method) => {
      if (plugin === "SpeechMemo" && method === "isSupported") return Promise.resolve({ supported: false });
      return Promise.resolve({ supported: false, authorized: false, cancelled: true });
    }
  };
};

async function unavailable(reason, expected) {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.addInitScript(fakeNative, reason);
  await page.goto(base);
  await page.click("#aiViewBtn");
  await page.waitForFunction(() => !document.getElementById("aiUnavailable").hidden);
  ok((await page.locator("#aiView").innerText()).trim() === expected, reason + " の理由だけを表示する");
  await page.close();
}

try {
  await unavailable("disabled", "設定 → Apple Intelligence と Siri でオンにしてください");
  await unavailable("unsupported", "この端末では端末内 AI を使えません（iOS 26 以降の Apple Intelligence 対応機が必要です）");
  await unavailable("oldOS", "iOS 26 以降にすると使えます");

  const statusPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await statusPage.addInitScript(fakeNative, "disabled");
  await statusPage.goto(base);
  await statusPage.click("#aiViewBtn");
  await statusPage.waitForFunction(() => !document.getElementById("aiUnavailable").hidden);
  await statusPage.evaluate(() => { window.__ai.reason = ""; });
  await statusPage.click("#listViewBtn");
  await statusPage.click("#aiViewBtn");
  await statusPage.waitForFunction(() => !document.getElementById("aiWorkspace").hidden);
  ok(await statusPage.locator("#aiQuestion").isVisible(), "AI タブを開き直したとき利用可否を確かめ直す");
  const statusCallsBeforeVisible = await statusPage.evaluate(() => window.__ai.statusCalls);
  await statusPage.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await statusPage.waitForFunction(count => window.__ai.statusCalls > count, statusCallsBeforeVisible);
  ok(true, "アプリに戻ったとき利用可否を確かめ直す");
  await statusPage.close();

  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.addInitScript(fakeNative, "");
  await page.goto(base);
  await page.evaluate(async () => {
    localStorage.clear();
    localStorage.setItem("schedule.v1", JSON.stringify({ version: 1, items: [{
      id: "event-1", title: "架空の委員会", dueOn: "2026-10-20", startTime: "10:00", endTime: "12:00", dest: "", note: ""
    }], calIds: {}, dismissedHints: [] }));
    localStorage.setItem("docs-tracker.v1", JSON.stringify({
      v: 1,
      items: [{ id: "old", title: "既存の架空項目", dueOn: "2026-10-30", note: "残すメモ" }],
      calIds: { old: "calendar-1" },
      memos: [{ id: "memo-1", text: "残すメモ" }]
    }));
    await new Promise(resolve => {
      const request = indexedDB.deleteDatabase("ichishi-history");
      request.onsuccess = request.onerror = request.onblocked = resolve;
    });
  });
  await page.reload();
  const fixedDate = await page.evaluate(() => ({
    now: new Date().toISOString(),
    timestamp: Date.now(),
    withArgument: new Date("2027-01-02T03:04:05Z").toISOString()
  }));
  ok(fixedDate.now.startsWith("2026-10-13T01:") && fixedDate.timestamp >= 1791853200000 && fixedDate.timestamp < 1791853200000 + 3600000, "画面テストの現在日時を2026年10月13日10時台にそろえる");
  ok(fixedDate.withArgument === "2027-01-02T03:04:05.000Z", "引数ありの new Date はそのまま動く");
  await page.click("#aiViewBtn");
  await page.waitForFunction(() => !document.getElementById("aiWorkspace").hidden);

  await page.fill("#aiQuestion", "来週の予定は？");
  await page.click("#aiSend");
  await page.waitForFunction(() => document.getElementById("aiConversation").textContent.includes("架空の答えです"));
  await waitAsync(page, async () => {
    const chats = await window.AIHistory.list({ kind: "chat" });
    return chats[0] && chats[0].messages.length === 2;
  });
  const secretaryCall = await page.evaluate(() => window.__ai.calls.find(call => call.instructions.includes("あなたは議員の秘書")));
  ok(secretaryCall.instructions.includes("10/20(火) 10:00-12:00 架空の委員会"), "秘書へ期間内の架空予定を渡す");
  ok((await page.locator("#aiConversation").innerText()).includes("端末内 AI の答えです。日時は予定一覧で確かめてください"), "答えの注意書きを表示する");
  const firstChat = await page.evaluate(async () => (await window.AIHistory.list({ kind: "chat" }))[0]);
  ok(firstChat.title === "来週の予定は？" && firstChat.mode === "secretary" && firstChat.sourceId === "", "最初の送信で題名・モード・資料IDを履歴へ保存する");
  ok(firstChat.messages.length === 2 && firstChat.messages[0].role === "user" && firstChat.messages[1].role === "ai", "質問を先に保存してから回答を追記する");

  await page.click("#aiNewChat");
  const callsBeforeOrderedDraft = await page.evaluate(() => window.__ai.calls.length);
  await page.fill("#aiQuestion", "順番を確かめる架空予定を入れて");
  await page.click("#aiSend");
  await page.waitForFunction(() => document.getElementById("aiConversation").textContent.includes("下書きを作っています…"));
  const orderedCalls = await page.evaluate(start => window.__ai.calls.slice(start).map(call => call.instructions.includes("登録用の下書き") ? "draft" : "answer"), callsBeforeOrderedDraft);
  ok(orderedCalls.join(",") === "answer,draft", "秘書の答えのあとに下書きを呼ぶ");
  ok((await page.locator("#aiConversation").innerText()).includes("架空の答えです\n下書きを作っています…"), "下書き中は答えの吹き出しに案内を出す");
  await page.evaluate(() => window.__ai.resolveDraft());
  await page.waitForFunction(() => document.querySelector("[data-ai-event-draft]") && !document.getElementById("aiConversation").textContent.includes("下書きを作っています…"));

  await page.click("#aiNewChat");
  const draftsBeforeFailedAnswer = await page.evaluate(() => window.__ai.calls.filter(call => call.instructions.includes("登録用の下書き")).length);
  await page.fill("#aiQuestion", "答え失敗で下書きなしの架空予定を入れて");
  await page.click("#aiSend");
  await page.waitForFunction(() => document.getElementById("toast").textContent.includes("言い方を変えて"));
  const draftsAfterFailedAnswer = await page.evaluate(() => window.__ai.calls.filter(call => call.instructions.includes("登録用の下書き")).length);
  ok(draftsAfterFailedAnswer === draftsBeforeFailedAnswer, "秘書の答えが失敗したら下書きを呼ばない");

  await page.click("#aiNewChat");
  await page.fill("#aiQuestion", "来週火曜10時に架空の打合せを入れて");
  await page.click("#aiSend");
  await page.waitForFunction(() => document.querySelector("[data-ai-event-draft]"));
  await page.click("[data-ai-event-draft]");
  ok(await page.locator("#f-title").inputValue() === "架空の打合せ", "予定下書きの件名を登録画面へ入れる");
  ok(await page.locator("#f-date").inputValue() === "2026-10-20" && await page.locator("#f-start").inputValue() === "10:00", "予定下書きの日付と時刻を登録画面へ入れる");

  await page.click("#aiViewBtn");
  await page.click("#aiNewChat");
  await page.fill("#aiQuestion", "金曜までに架空の資料を出す、TODOに追加して");
  await page.click("#aiSend");
  await page.waitForFunction(() => document.querySelector("[data-ai-todo-draft]"));
  await page.click("[data-ai-todo-draft]");
  ok(await page.locator("#aiTodoTitle").inputValue() === "架空の資料を出す" && await page.locator("#aiTodoDate").inputValue() === "2026-10-16", "TODOの件名と期限を直せる欄へ入れる");
  await page.fill("#aiTodoTitle", "直した架空の資料");
  await page.click("#aiTodoAdd");
  const todoData = await page.evaluate(() => JSON.parse(localStorage.getItem("docs-tracker.v1")));
  ok(todoData.items.length === 2 && todoData.items[0].title === "既存の架空項目" && todoData.items[1].title === "直した架空の資料" && todoData.items[1].kind === "TODO", "既存項目を残してTODOを1件足す");
  ok(todoData.memos[0].text === "残すメモ" && todoData.calIds.old === "calendar-1", "既存のメモと設定を残す");

  await page.click("#aiNewChat");
  await page.fill("#aiQuestion", "JSON失敗の予定を追加して");
  await page.click("#aiSend");
  await page.waitForFunction(() => document.querySelector("[data-ai-empty-draft]"));
  ok((await page.locator("#aiConversation").innerText()).includes("下書きを作れませんでした。登録画面を空で開きますか？"), "JSONでない下書きは空の登録画面を案内する");

  const source = await page.evaluate(async () => window.AIHistory.add({
    kind: "document", title: "架空の長い書類", body: "資".repeat(4000), mode: "", messages: [], sourceId: "", eventTitles: []
  }));
  await page.click('[data-ai-mode="sparring"]');
  await page.click("#aiChooseSource");
  await page.waitForFunction(id => document.querySelector(`[data-history-id="${id}"] [data-history-select]`), source.id);
  await page.click(`[data-history-id="${source.id}"] [data-history-select]`);
  await page.waitForFunction(() => document.getElementById("aiSourceNotice").textContent.includes("3,000"));
  await page.fill("#aiQuestion", "この資料を考えたい");
  await page.click("#aiSend");
  await page.waitForFunction(() => document.getElementById("aiConversation").textContent.includes("架空の答えです"));
  await waitAsync(page, async id => {
    const chats = await window.AIHistory.list({ kind: "chat" });
    return chats.some(chat => chat.sourceId === id && chat.messages.length === 2);
  }, source.id);
  const sourceCall = await page.evaluate(() => window.__ai.calls.filter(call => call.instructions.includes("資料: 架空の長い書類")).at(-1));
  ok((await page.locator("#aiSourceNotice").innerText()) === "資料が長いため先頭 3,000 字だけ渡しています", "長い資料の切り詰めを案内する");
  ok(sourceCall.instructions.split("\n").at(-1).length === 3000, "資料本文は先頭3,000字だけ渡す");
  const sourceChat = await page.evaluate(async id => (await window.AIHistory.list({ kind: "chat" })).find(chat => chat.sourceId === id), source.id);
  ok(sourceChat.mode === "sparring" && sourceChat.sourceId === source.id, "資料付き会話のモードと資料IDを保存する");

  const callsBeforeSourceLoad = await page.evaluate(() => window.__ai.calls.length);
  await page.evaluate(id => {
    const realGet = window.AIHistory.get;
    window.__ai.realHistoryGet = realGet;
    window.AIHistory.get = requestedId => requestedId === id
      ? new Promise(resolve => {
        window.__ai.resolveHistoryGet = () => realGet(id).then(resolve);
      })
      : realGet(requestedId);
    window.startAIWithSource("sparring", { id });
  }, source.id);
  await page.waitForFunction(() => typeof window.__ai.resolveHistoryGet === "function");
  await page.fill("#aiQuestion", "資料の読込中には送らない架空の質問");
  await page.press("#aiQuestion", "Control+Enter");
  ok(await page.locator("#aiConversation .ai-bubble.user").count() === 0, "資料の読込中はショートカットで利用者の吹き出しを追加しない");
  ok(await page.evaluate(() => window.__ai.calls.length) === callsBeforeSourceLoad, "資料の読込中はショートカットでAIへ送らない");
  await page.evaluate(() => {
    window.__ai.resolveHistoryGet();
    window.AIHistory.get = window.__ai.realHistoryGet;
  });
  await page.waitForFunction(() => !document.getElementById("aiSend").disabled);

  await page.click("#aiNewChat");
  await page.fill("#aiQuestion", "遅い答えを待つ架空の質問");
  await page.click("#aiSend");
  await page.waitForFunction(() => typeof window.__ai.resolveDelayed === "function");
  const delayedId = await page.evaluate(async () => (await window.AIHistory.list({ kind: "chat" }))[0].id);
  await page.press("#aiQuestion", "Control+Enter");
  ok(await page.locator("#aiConversation .ai-bubble.user").count() === 1, "回答待ち中の再送でも利用者の吹き出しは1つにする");
  await page.click("#aiNewChat");
  await page.evaluate(() => window.__ai.resolveDelayed());
  await waitAsync(page, async id => {
    const entry = await window.AIHistory.get(id);
    return entry && entry.messages.length === 2 && entry.messages.some(message => message.text.includes("遅れて届いた"));
  }, delayedId);
  ok(!(await page.locator("#aiConversation").innerText()).includes("遅れて届いた"), "新しい会話へ遅い答えを混ぜない");
  const delayedEntry = await page.evaluate(id => window.AIHistory.get(id), delayedId);
  ok(delayedEntry.messages.length === 2, "回答待ち中の再送でも履歴のメッセージは2件だけにする");
  ok(delayedEntry.messages.at(-1).text === "遅れて届いた架空の答え", "遅い答えを送信時の会話へ保存する");

  const linkedChat = await page.evaluate(async id => window.AIHistory.add({
    kind: "chat", title: "資料付きの架空会話", body: "", mode: "sparring", messages: [], sourceId: id, eventTitles: []
  }), source.id);
  await page.evaluate(id => window.AIHistory.remove(id), source.id);
  await page.evaluate(id => {
    window.setView("history");
    window.openHistory(id);
  }, linkedChat.id);
  await page.waitForFunction(() => document.getElementById("historyDetail").textContent.includes("削除された資料"));
  ok((await page.locator("#historyDetail").innerText()).includes("削除された資料"), "消した資料を使った会話を開くと削除済みと表示する");
  await page.click(`[data-history-continue="${linkedChat.id}"]`);
  await page.waitForFunction(() => document.getElementById("aiSourceName").textContent.includes("削除された資料"));
  ok((await page.locator("#aiSourceName").innerText()).includes("削除された資料"), "削除済み資料の会話を続けても表示を保つ");

  const continuing = await page.evaluate(async () => window.AIHistory.add({
    kind: "chat", title: "続ける架空会話", body: "", mode: "brainstorm",
    messages: [{ role: "user", text: "前の架空質問" }, { role: "ai", text: "前の架空回答" }], sourceId: "", eventTitles: []
  }));
  await page.evaluate(entry => window.continueAIChat(entry), continuing);
  await page.fill("#aiQuestion", "続きを出して");
  await page.click("#aiSend");
  await waitAsync(page, async id => (await window.AIHistory.get(id)).messages.length === 4, continuing.id);
  const continuedEntry = await page.evaluate(id => window.AIHistory.get(id), continuing.id);
  const continuedSummary = continuedEntry.messages.map(message => message.role + ":" + String(message.text || "").slice(0, 20)).join(" / ");
  ok(continuedEntry.messages.length === 4, "続きから同じ会話へ質問と回答を追記する（messages=" + continuedEntry.messages.length + "、内容=" + continuedSummary + "）");

  await page.click("#aiNewChat");
  await page.fill("#aiQuestion", "拒否して");
  await page.click("#aiSend");
  await page.waitForFunction(() => document.getElementById("toast").textContent.includes("言い方を変えて"));
  ok(await page.locator("#aiQuestion").inputValue() === "拒否して", "拒否時も入力欄を消さない");
  ok(await page.locator("#aiConversation .ai-bubble.user").count() === 0, "拒否された質問を画面の会話から外す");
  ok((await page.locator("#aiConversation").innerText()).includes("答えを作れませんでした。言い方を変えてみてください"), "失敗の案内を会話の中にも表示する");
  await waitAsync(page, async () => {
    const chat = (await window.AIHistory.list({ kind: "chat" }))[0];
    return chat && chat.messages.at(-1).text === "（答えを作れませんでした）";
  });
  await page.click("#aiSend");
  await page.waitForFunction(() => document.getElementById("aiConversation").textContent.includes("架空の答えです"));
  ok(await page.locator("#aiConversation .ai-bubble.user").count() === 1, "拒否後に同じ質問を送り直しても利用者の吹き出しは1つにする");

  const failedPast = await page.evaluate(async () => window.AIHistory.add({
    kind: "chat", title: "失敗を含む架空会話", body: "", mode: "brainstorm",
    messages: [
      { role: "user", text: "残す架空質問" }, { role: "ai", text: "残す架空回答" },
      { role: "user", text: "答えの無い架空質問" }, { role: "ai", text: "（答えを作れませんでした）" }
    ],
    sourceId: "", eventTitles: []
  }));
  await page.evaluate(entry => window.continueAIChat(entry), failedPast);
  ok(await page.locator("#aiConversation .ai-bubble").count() === 2, "続きから話す画面では失敗行と答えの無い質問を表示しない");
  ok(!(await page.locator("#aiConversation").innerText()).includes("答えの無い架空質問"), "答えの無い質問を過去の会話から外す");
  await page.fill("#aiQuestion", "失敗を除いて続ける架空質問");
  await page.click("#aiSend");
  await waitAsync(page, async id => (await window.AIHistory.get(id)).messages.length === 6, failedPast.id);
  const resumedCall = await page.evaluate(() => window.__ai.calls.at(-1));
  ok(resumedCall.prompt.includes("残す架空質問") && !resumedCall.prompt.includes("答えの無い架空質問") && !resumedCall.prompt.includes("答えを作れませんでした"), "AIへ渡す過去の会話から失敗した一往復を外す");

  const deletedCurrent = await page.evaluate(async () => window.AIHistory.add({
    kind: "chat", title: "削除する架空会話", body: "", mode: "secretary",
    messages: [{ role: "user", text: "削除前の架空質問" }, { role: "ai", text: "削除前の架空回答" }],
    sourceId: "", eventTitles: []
  }));
  await page.evaluate(entry => {
    window.continueAIChat(entry);
    window.setView("history");
    window.confirm = () => true;
  }, deletedCurrent);
  await page.waitForFunction(id => document.querySelector(`[data-history-id="${id}"] [data-history-remove]`), deletedCurrent.id);
  await page.click(`[data-history-id="${deletedCurrent.id}"] [data-history-remove]`);
  await waitAsync(page, async id => !(await window.AIHistory.get(id)), deletedCurrent.id);
  await page.click("#aiViewBtn");
  ok(await page.locator("#aiConversation .ai-bubble").count() === 0, "今使っている会話を削除したらAI画面を新しい会話にする");
  await page.fill("#aiQuestion", "一件削除後の架空質問");
  await page.click("#aiSend");
  await waitAsync(page, async () => (await window.AIHistory.list({ kind: "chat" })).some(entry => entry.title === "一件削除後の架空質問" && entry.messages.length === 2));
  ok(!(await page.locator("#toast").innerText()).includes("履歴を保存できません"), "今の会話を削除した後も新しい会話を保存できる");

  await page.click("#historyViewBtn");
  await page.click("#historyClearBtn");
  await waitAsync(page, async () => (await window.AIHistory.list({})).length === 0);
  await page.click("#aiViewBtn");
  ok(await page.locator("#aiConversation .ai-bubble").count() === 0, "履歴をすべて削除したらAI画面を新しい会話にする");
  await page.fill("#aiQuestion", "全削除後の架空質問");
  await page.click("#aiSend");
  await waitAsync(page, async () => {
    const chats = await window.AIHistory.list({ kind: "chat" });
    return chats.length === 1 && chats[0].messages.length === 2;
  });
  ok(!(await page.locator("#toast").innerText()).includes("履歴を保存できません"), "履歴をすべて削除した後も新しい会話を保存できる");

  await page.click("#aiNewChat");
  await page.fill("#aiQuestion", "危険な文字を返して");
  await page.click("#aiSend");
  await page.waitForFunction(() => document.getElementById("aiConversation").textContent.includes("<script>"));
  ok(await page.locator("#aiConversation script").count() === 0, "AI回答のscriptを要素にしない");
  ok((await page.locator("#aiConversation").innerText()).includes("<script>alert(1)</script>"), "AI回答のHTMLを文字のまま表示する");
  ok(await page.evaluate(() => window.__ai.alertCount) === 0, "AI回答でalertを呼ばない");
  ok(errors.length === 0, "AI画面でJSエラーがない " + errors.join(" / "));

  await page.close();
} finally {
  await browser.close();
  server.close();
}

process.exit(failures ? 1 : 0);
