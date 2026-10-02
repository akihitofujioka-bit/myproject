/*
 * apps/shared/planner.js（手帳のページから日付ごとの予定を取り出す）のテスト。ブラウザ不要。
 *
 *   node apps/tests/planner.test.mjs
 *
 * 手帳の写真は使わず、Vision が返す形（文字と位置）を合成して試す。
 * 予定の中身はすべて架空のもの。
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const g = {};
new Function("window", fs.readFileSync(path.join(ROOT, "apps/shared/planner.js"), "utf8"))(g);
const P = g.Planner;

let failures = 0;
const ok = (cond, label, extra) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label + (cond || extra === undefined ? "" : "  → " + JSON.stringify(extra)));
  if (!cond) failures++;
};

const TODAY = new Date(2026, 9, 1); // 2026-10-01（木）

/**
 * 月間のマス目を合成する。
 *   year, month   … 並べる月
 *   start         … 0 = 日曜始まり / 1 = 月曜始まり
 *   align         … "left" = 日付の数字がマスの左上 / "right" = 右上
 *   header        … 曜日の見出しを入れるか
 *   title         … 見出しの文字（null なら入れない）
 *   notes         … { 日: ["1行目", "2行目"] } マスの中の手書き
 *   spill         … 前月・翌月の日付もマスに印刷するか
 */
function monthPage({ year = 2026, month = 10, start = 0, align = "left", header = true, title = "2026年10月", notes = {}, spill = true, mini = false } = {}) {
  const frags = [];
  const x0 = 0.02, y0 = 0.16, cw = 0.137, rh = 0.135;
  if (title) frags.push({ text: title, x: 0.35, y: 0.03, width: 0.3, height: 0.05 });
  const names = ["日", "月", "火", "水", "木", "金", "土"];
  if (header) {
    for (let c = 0; c < 7; c++) {
      const wd = (c + start) % 7;
      frags.push({ text: names[wd], x: x0 + cw * c + cw / 2 - 0.01, y: 0.12, width: 0.02, height: 0.02 });
    }
  }
  const first = new Date(year, month - 1, 1).getDay();
  const lead = (first - start + 7) % 7;
  const dim = new Date(year, month, 0).getDate();
  const prevDim = new Date(year, month - 1, 0).getDate();
  for (let i = 0; i < 42; i++) {
    const r = Math.floor(i / 7), c = i % 7;
    let day = i - lead + 1, inMonth = true;
    if (day < 1) { day = prevDim + day; inMonth = false; }
    else if (day > dim) { day = day - dim; inMonth = false; }
    if (!inMonth && (!spill || r >= 5)) continue;
    if (inMonth && r >= 6) continue;
    const left = x0 + cw * c, top = y0 + rh * r;
    const w = String(day).length * 0.012;
    const x = align === "left" ? left + 0.006 : left + cw - 0.006 - w;
    frags.push({ text: String(day), x, y: top + 0.004, width: w, height: 0.018 });
    if (inMonth && notes[day]) {
      notes[day].forEach((line, k) => {
        frags.push({ text: line, x: left + 0.01, y: top + 0.03 + k * 0.025, width: Math.min(cw * 0.9, line.length * 0.012), height: 0.02 });
      });
    }
  }
  if (mini) {
    // 余白の小さな翌月カレンダー（予定ではない）
    for (let d = 1; d <= 30; d++) {
      const r = Math.floor((d - 1) / 7), c = (d - 1) % 7;
      frags.push({ text: String(d), x: 0.7 + c * 0.03, y: 0.95 + r * 0.008, width: 0.01, height: 0.006 });
    }
  }
  return frags;
}

const titles = (r) => r.entries.map((e) => e.date + " " + (e.startTime ? e.startTime + (e.endTime ? "~" + e.endTime : "") + " " : "") + e.title);

console.log("== 月間のマス目 ==");
{
  const r = P.parse(monthPage({
    notes: { 5: ["10:00 歯医者"], 15: ["町内会の会議", "14時 打合せ"], 20: ["飲み会 3,000円"], 31: ["ハロウィン準備"] }
  }), { today: TODAY });
  ok(r.kind === "month", "格子として読める");
  ok(r.year === 2026 && r.month === 10 && r.monthConfidence === "high", "見出しから 2026年10月", r);
  const t = titles(r);
  ok(t.includes("2026-10-05 10:00 歯医者"), "5日のマスの時刻つき予定", t);
  ok(t.includes("2026-10-15 町内会の会議") && t.includes("2026-10-15 14:00 打合せ"), "同じマスの2行は2件", t);
  ok(t.includes("2026-10-20 飲み会 3,000円"), "金額が書いてあってもその日の予定", t);
  ok(t.includes("2026-10-31 ハロウィン準備"), "月末のマス", t);
  ok(r.entries.length === 5, "前月の日付（27〜30）や印刷の数字を予定にしない", t);
}
{
  const r = P.parse(monthPage({ start: 1, notes: { 1: ["健診"], 12: ["9:30~11:00 研修"] } }), { today: TODAY });
  const t = titles(r);
  ok(t.includes("2026-10-01 健診") && t.includes("2026-10-12 09:30~11:00 研修"), "月曜始まりでも合う", t);
}
{
  const r = P.parse(monthPage({ align: "right", notes: { 7: ["ごみ当番"], 23: ["旅行"] } }), { today: TODAY });
  const t = titles(r);
  ok(t.includes("2026-10-07 ごみ当番") && t.includes("2026-10-23 旅行"), "日付の数字がマスの右上でも合う", t);
}
{
  const r = P.parse(monthPage({ align: "right", header: false, notes: { 7: ["ごみ当番"], 23: ["旅行"] } }), { today: TODAY });
  const t = titles(r);
  ok(t.includes("2026-10-07 ごみ当番") && t.includes("2026-10-23 旅行"), "右上・曜日の見出しなしでも合う", t);
}
{
  const r = P.parse(monthPage({ title: null, notes: { 9: ["面談"] } }), { today: TODAY });
  ok(r.kind === "month" && r.year === 2026 && r.month === 10 && r.monthConfidence === "low", "見出しが無くても曜日の並びから10月と分かる", r);
  ok(titles(r).includes("2026-10-09 面談"), "その月の日付で返す", titles(r));
}
{
  const r = P.parse(monthPage({ year: 2026, month: 11, title: "11月", notes: { 3: ["文化祭"] } }), { today: TODAY });
  ok(r.year === 2026 && r.month === 11 && r.monthConfidence === "medium", "「11月」だけの見出しは今年の11月", r);
  ok(titles(r).includes("2026-11-03 文化祭"), "11月3日", titles(r));
}
{
  const r = P.parse(monthPage({ year: 2027, month: 1, title: "1月", notes: { 10: ["新年会"] } }), { today: new Date(2026, 11, 20) });
  ok(r.year === 2027 && r.month === 1, "12月に1月のページを撮れば来年の1月", r);
}
{
  const r = P.parse(monthPage({ title: "OCTOBER", mini: true, notes: { 2: ["実家"] } }), { today: TODAY });
  ok(r.kind === "month" && r.month === 10, "英語の月名・余白の小さなカレンダーがあっても読める", r);
  ok(titles(r).length === 1 && titles(r)[0] === "2026-10-02 実家", "小さなカレンダーの数字を予定にしない", titles(r));
}
{
  // 祝日・六曜の印刷
  const frags = monthPage({ notes: { 12: ["スポーツの日"], 13: ["大安", "通院"] } });
  const t = titles(P.parse(frags, { today: TODAY }));
  ok(!t.some((x) => /スポーツの日|大安/.test(x)) && t.includes("2026-10-13 通院"), "祝日・六曜の印刷は予定にしない", t);
}
{
  // 時刻だけの行の次に件名
  const t = titles(P.parse(monthPage({ notes: { 6: ["13:30", "美容院"] } }), { today: TODAY }));
  ok(t.includes("2026-10-06 13:30 美容院"), "時刻だけの行は次の行に引き継ぐ", t);
}
{
  // Vision が日付と手書きを1つの断片にまとめた場合
  const frags = monthPage({});
  const i = frags.findIndex((f) => f.text === "8" && f.y > 0.2);
  frags[i] = { ...frags[i], text: "8 ピアノ", width: 0.08 };
  ok(titles(P.parse(frags, { today: TODAY })).includes("2026-10-08 ピアノ"), "「8 ピアノ」は8日の予定", titles(P.parse(frags, { today: TODAY })));
}

{
  // 斜めに撮った月間ページ（右へ行くほど 8% 下がり、下へ行くほど 5% 右にずれる）
  const frags = monthPage({ notes: { 4: ["墓参り"], 17: ["10時 説明会"], 29: ["送別会"] } })
    .map((f) => ({ ...f, x: f.x + f.y * 0.05, y: f.y + f.x * 0.08 }));
  const t = titles(P.parse(frags, { today: TODAY }));
  ok(t.includes("2026-10-04 墓参り") && t.includes("2026-10-17 10:00 説明会") && t.includes("2026-10-29 送別会"), "斜めに撮っても日付を取り違えない", t);
}

{
  // 文字認識が日付の数字の4割を読み落とし、見出しも読めなかった場合
  const notes = { 2: ["実家"], 14: ["健診"], 27: ["研修"] };
  let k = 0;
  const frags = monthPage({ title: null, notes }).filter((f) => !(/^\d{1,2}$/.test(f.text) && (k++ % 5 < 2)));
  const r = P.parse(frags, { today: TODAY });
  const t = r.kind ? titles(r) : [];
  ok(r.kind === "month" && t.includes("2026-10-02 実家") && t.includes("2026-10-14 健診") && t.includes("2026-10-27 研修"), "日付の数字を読み落としても、残りの並びから割り出す", t);
}

{
  // 見開きの手帳: 月曜始まりで、水曜と木曜の間に綴じ目があり、そこだけ列の間隔が広い。
  // 曜日の見出しは英語で、左端に「MONTHLY」のような曜日と紛らわしい文字もある（実物の手帳に近い形）
  const f = [{ text: "10月", x: 0.02, y: 0.14, width: 0.04, height: 0.027 }, { text: "MONTHLY", x: 0.0, y: 0.118, width: 0.05, height: 0.018 }];
  const colX = [0.128, 0.241, 0.352, 0.512, 0.626, 0.741, 0.852];   // 3列目と4列目の間だけ広い
  ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"].forEach((w, c) => f.push({ text: w, x: colX[c] + 0.06, y: 0.105, width: 0.03, height: 0.017 }));
  const notes = { 2: ["14-15 打合せ"], 10: ["研修会"], 12: ["通院"], 21: ["町内清掃"] };
  for (let d = 1; d <= 31; d++) {
    const i = d + 2, r = Math.floor(i / 7), c = i % 7;   // 2026年10月1日は木曜（月曜始まりで4列目）
    f.push({ text: String(d), x: colX[c], y: 0.13 + r * 0.14, width: 0.012 * String(d).length, height: 0.025 });
    (notes[d] || []).forEach((t, k) => f.push({ text: t, x: colX[c] + 0.005, y: 0.18 + r * 0.14 + k * 0.03, width: 0.09, height: 0.03 }));
  }
  const r = P.parse(f, { today: TODAY });
  const t = r.kind ? titles(r) : [];
  ok(r.kind === "month" && r.year === 2026 && r.month === 10, "見開きの月曜始まりでも 2026年10月と分かる", r);
  ok(t.includes("2026-10-02 14:00~15:00 打合せ") && t.includes("2026-10-10 研修会") && t.includes("2026-10-12 通院") && t.includes("2026-10-21 町内清掃"),
    "綴じ目で列の間隔が広がっても、右ページのマスを隣の日と取り違えない", t);
}

{
  // 利用者の書き方（2026-10-02）:「14-15 ◯◯会議」は14〜15時、「9◯◯会議」は9時から。
  // 手書きの横棒は「一」「ー」と読まれることがある
  const r = P.parse(monthPage({ notes: { 2: ["14一15町内会議"], 8: ["9役員会議"], 16: ["9 定例会議", "13-14ー"], 22: ["14ー15 研修会"], 27: ["2人で食事"] } }), { today: TODAY });
  const t = titles(r);
  ok(t.includes("2026-10-02 14:00~15:00 町内会議"), "「14一15町内会議」は14〜15時", t);
  ok(t.includes("2026-10-08 09:00 役員会議") && t.includes("2026-10-16 09:00 定例会議"), "「9役員会議」「9 定例会議」は9時から", t);
  ok(t.includes("2026-10-22 14:00~15:00 研修会"), "「14ー15 研修会」は14〜15時", t);
  ok(t.includes("2026-10-27 2人で食事"), "「2人で食事」は時刻にしない", t);
  ok(r.anchors >= 28, "マスの中の手書きの数字があっても、日付の格子は崩れない（" + r.anchors + "）");
}

{
  // 利用者の手帳（2026-10-02）:「11」が「H」と読まれる。「13.30」は13時30分のつもり
  const r = P.parse(monthPage({ notes: { 6: ["H-12 来客"], 13: ["13.30 研修"], 20: ["ll会議"], 21: ["HOME 掃除"] } }), { today: TODAY });
  const t = titles(r);
  ok(t.includes("2026-10-06 11:00~12:00 来客"), "「H-12」の H を 11 と読む", t);
  ok(t.includes("2026-10-13 13:30 研修"), "「13.30」を 13:30 と読む", t);
  ok(t.includes("2026-10-20 11:00 会議"), "縦棒2本（ll）も 11 と読む", t);
  ok(t.includes("2026-10-21 HOME 掃除"), "英単語の H は直さない", t);
}
{
  // 「9.◯◯会議」は9時。「13.30」の点が崩れて読まれた形（13,30 / 13・30 / 13 30 / 1330）も13時30分
  const r = P.parse(monthPage({ notes: { 1: ["9.役員会議"], 5: ["13,30研修"], 7: ["13・30 面談"], 14: ["13 30説明会"], 19: ["1330 打合せ"], 23: ["1500円 会費"] } }), { today: TODAY });
  const t = titles(r);
  ok(t.includes("2026-10-01 09:00 役員会議"), "「9.役員会議」は9時から", t);
  ok(["2026-10-05 13:30 研修", "2026-10-07 13:30 面談", "2026-10-14 13:30 説明会", "2026-10-19 13:30 打合せ"].every((x) => t.includes(x)),
    "崩れた「13.30」も13時30分と読む", t);
  ok(t.includes("2026-10-23 1500円 会費"), "金額は時刻にしない", t);
  ok(r.anchors >= 28, "マスの中の「13 30」があっても日付の格子は崩れない（" + r.anchors + "）");
}

{
  // 件名の後ろの括弧書きは件名に含める（次の行に書いても、括弧が行をまたいでも）
  const r = P.parse(monthPage({ notes: { 6: ["14-15 町内会議", "（公民館）"], 9: ["研修会(市役所", "3階)"], 15: ["歯医者 (定期)"] } }), { today: TODAY });
  const t = titles(r);
  ok(t.includes("2026-10-06 14:00~15:00 町内会議(公民館)"), "次の行の「（公民館）」を件名に含める", t);
  ok(t.includes("2026-10-09 研修会(市役所3階)"), "行をまたぐ括弧を1件にまとめる", t);
  ok(t.includes("2026-10-15 歯医者 (定期)"), "同じ行の括弧はそのまま", t);
  ok(r.entries.length === 3, "括弧書きを別の予定にしない", t);
}

console.log("== 日付ごとのメモ ==");
const rows = (texts, x = 0.05) => texts.map((t, i) => ({ text: t, x, y: 0.05 + i * 0.05, width: 0.6, height: 0.03 }));
{
  const r = P.parse(rows(["10/3(土)", "10:00 歯医者", "買い物", "10/4(日)", "家族で外食", "10/5(月)", "14時~15時 打合せ"]), { today: TODAY });
  ok(r.kind === "daily" && r.sections === 3, "日付の行で区切る", r);
  const t = titles(r);
  ok(t.includes("2026-10-03 10:00 歯医者") && t.includes("2026-10-03 買い物"), "日付の下の行はその日の予定", t);
  ok(t.includes("2026-10-05 14:00~15:00 打合せ"), "「14時~15時」を範囲で読む", t);
  ok(P.strength(r) === "strong", "3日ぶん以上なら手帳らしさは強い");
}
{
  const r = P.parse(rows(["2026年10月", "5日(月) ジム", "6日(火)", "午後2時 銀行", "7(水) 休み"]), { today: TODAY });
  const t = titles(r);
  ok(t.includes("2026-10-05 ジム") && t.includes("2026-10-06 14:00 銀行") && t.includes("2026-10-07 休み"), "見出しの月と「5日(月)」「7(水)」", t);
}
{
  const r = P.parse(rows(["12 MON 会議", "13 TUE", "歓送迎会"]), { today: TODAY });
  const t = titles(r);
  ok(t.includes("2026-10-12 会議") && t.includes("2026-10-13 歓送迎会"), "月が無くても曜日から近い月を当てる", t);
  ok(r.monthConfidence === "low", "そのときは確度を低にする");
}
{
  // 見開き（左右に日付が並ぶ）
  const left = rows(["10/5(月)", "通院", "10/6(火)", "会議"], 0.03);
  const right = rows(["10/8(木)", "出張", "10/9(金)", "研修"], 0.55);
  const t = titles(P.parse(left.concat(right), { today: TODAY }));
  ok(t.includes("2026-10-05 通院") && t.includes("2026-10-08 出張") && t.includes("2026-10-06 会議") && t.includes("2026-10-09 研修"), "見開きの左右を混ぜない", t);
}

{
  const r = P.parse(rows(["10/3(土)", "歯医者", "(駅前)", "10/4(日)", "買い物"]), { today: TODAY });
  ok(titles(r).includes("2026-10-03 歯医者(駅前)"), "日付ごとのメモでも括弧書きを件名に含める", titles(r));
}

console.log("== 手書きの日付の読み違い ==");
{
  // 2026年10月: 3日=土 4日=日 5日=月 6日=火 7日=水
  const cases = [
    [["lO/3(土)", "歯医者", "10/4(日)", "買い物"], "2026-10-03 歯医者", "「lO/3」（l と O の読み違い）を 10/3 と読む"],
    [["10ノ5(月)", "会議"], "2026-10-05 会議", "「10ノ5」の「ノ」を「/」とみなす"],
    [["10/3(土)", "歯医者", "1014(日)", "買い物", "10/5(月)", "会議"], "2026-10-04 買い物", "「/」を読み落とした「1014(日)」を、曜日と前後から 10/4 と読む"],
    [["10/3(土)", "歯医者", "10/8(日)", "買い物", "10/5(月)", "会議"], "2026-10-04 買い物", "並びと曜日に合わない「10/8(日)」を 10/4 に直す"],
    [["10/9(土)", "歯医者", "10/4(日)", "買い物", "10/5(月)", "会議"], "2026-10-03 歯医者", "最初の日付が読み違えられても、2番目以降を巻き込まない"],
    [["10/3", "歯医者", "10/9", "買い物", "10/5", "会議"], "2026-10-04 買い物", "曜日が無くても、前後が2日違いならその間の日にする"]
  ];
  cases.forEach(([lines, want, label]) => {
    const r = P.parse(rows(lines), { today: TODAY });
    const t = r.kind ? titles(r) : [];
    ok(t.includes(want), label, t);
  });
  const r = P.parse(rows(["10/3(土)", "歯医者", "10/8(日)", "買い物", "10/5(月)", "会議"]), { today: TODAY });
  const fixed = r.entries.find((e) => e.title === "買い物");
  ok(fixed && fixed.dateGuess === true, "直した日付には「推測」の印を付ける");
  ok(!r.entries.find((e) => e.title === "歯医者").dateGuess, "読めた日付には印を付けない");
}

console.log("== 読み違えやすいもの ==");
{
  ok(P.dateHead("10月") === null, "「10月」の見出しを10日（月曜）と読まない");
  ok(P.dateHead("1.5L 248") === null, "「1.5L」を1月5日と読まない");
  ok(P.dateHead("10:30 会議") === null, "時刻を日付と読まない");
  ok(P.dateHead("3 月曜 会議") && P.dateHead("3 月曜 会議").weekday === 1, "「3 月曜」は3日・月曜");
  const s = P.splitTime("10時半~11時 面談");
  ok(s.start === "10:30" && s.end === "11:00" && s.rest === "面談", "「10時半~11時」", s);
  const s2 = P.splitTime("1~3 草刈り");
  ok(s2.start === "" , "「1~3」のような小さな数の範囲は時刻にしない（日付の範囲かもしれない）", s2);
  const s3 = P.splitTime("歯医者 16:00");
  ok(s3.start === "16:00" && s3.rest === "歯医者", "行の後ろの時刻", s3);
}
{
  // レシート・会議の通知は手帳とみなさない
  const receipt = rows(["サンプルスーパー", "2026/09/18(金) 12:30", "牛乳 ¥248", "パン ¥180", "合計 ¥428"]);
  ok(P.strength(P.parse(receipt, { today: TODAY })) === "", "レシートは手帳ではない");
  const notice = rows(["令和8年9月25日", "○○地区会議開催のお知らせ", "1 日 時 令和8年10月15日(木) 13:30~", "2 場 所 ○○コミュニティセンター"]);
  ok(P.strength(P.parse(notice, { today: TODAY })) === "", "会議の通知は手帳ではない");
}

console.log(failures ? `\n${failures} 件失敗` : "\nすべて成功");
process.exit(failures ? 1 : 0);
