/*
 * apps/shared/meishi.js（名刺の文字の振り分け）のテスト。ブラウザ不要。
 *
 *   node apps/tests/meishi.test.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const g = {};
const contactsSrc = fs.readFileSync(path.join(ROOT, "apps/shared/contacts.js"), "utf8");
new Function("window", contactsSrc)(g);

const meishiPath = path.join(ROOT, "apps/shared/meishi.js");
if (fs.existsSync(meishiPath)) {
  const meishiSrc = fs.readFileSync(meishiPath, "utf8");
  new Function("window", meishiSrc)(g);
}
const M = g.Meishi;

let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};

ok(!!M, "Meishi が読み込める");

if (M) {
  const office = M.parse([
    { text: "日高町役場", x: 0, y: 0, width: 0.3, height: 0.03 },
    { text: "総務課 係長", x: 0, y: 0.1, width: 0.3, height: 0.03 },
    { text: "山田 太郎", x: 0, y: 0.2, width: 0.3, height: 0.08 },
    { text: "〒000-0000", x: 0, y: 0.3, width: 0.3, height: 0.03 },
    { text: "架空県架空郡日高町1-2-3", x: 0, y: 0.4, width: 0.3, height: 0.03 },
    { text: "TEL 0000-11-2222 FAX 0000-11-2223", x: 0, y: 0.5, width: 0.3, height: 0.03 },
    { text: "yamada@example.jp", x: 0, y: 0.6, width: 0.3, height: 0.03 }
  ]);
  ok(office.company === "日高町役場", "役所: 会社");
  ok(office.department.indexOf("総務課") !== -1, "役所: 部署");
  ok(office.title === "係長", "役所: 役職");
  ok(office.name === "山田 太郎", "役所: 氏名");
  ok(JSON.stringify(office.phones) === JSON.stringify(["0000-11-2222"]), "役所: FAX を電話から外す");
  ok(office.memo.indexOf("FAX: 0000-11-2223") !== -1, "役所: FAX をメモに入れる");
  ok(office.address.indexOf("〒000-0000") !== -1 && office.address.indexOf("架空県") !== -1, "役所: 住所をつなぐ");
  ok(office.email === "yamada@example.jp", "役所: メール");

  const company = M.parse([
    { text: "株式会社架空商事", height: 0.03 },
    { text: "営業部 部長", height: 0.03 },
    { text: "佐藤花子", height: 0.08 },
    { text: "携帯 090-0000-0000", height: 0.03 },
    { text: "https://example.com", height: 0.03 }
  ]);
  ok(company.company === "株式会社架空商事", "会社: 会社名");
  ok(company.department.indexOf("営業部") !== -1 && company.title === "部長", "会社: 部署と役職");
  ok(company.name === "佐藤花子", "会社: 氏名");
  ok(JSON.stringify(company.phones) === JSON.stringify(["090-0000-0000"]), "会社: 携帯電話");
  ok(company.url === "https://example.com", "会社: URL");

  const member = M.parse(["架空市議会議員　鈴木 一郎"]);
  ok(member.company === "架空市議会", "議員: 議会を会社として取り出す");
  ok(member.title === "議員" && member.name === "鈴木 一郎", "議員: 同じ行の役職と氏名");

  const address = M.parse(["東京都架空区1-2-3", "架空ビル5F", "田中 三郎"]);
  ok(address.address === "東京都架空区1-2-3\n架空ビル5F", "住所: 建物名の行までつなぐ");

  const mixed = M.parse(["企画課", "Taro YAMADA", "小林 四郎"]);
  ok(mixed.company === "" && mixed.name === "小林 四郎", "会社名なし・英字行を氏名にしない");
  ok(mixed.memo.indexOf("Taro YAMADA") !== -1, "英字行はメモへ入れる");

  const vertical = M.parse([
    { text: "伊藤 五郎", height: 0.04 },
    { text: "渡辺 六郎", height: 0.04 }
  ]);
  ok(vertical.name === "伊藤 五郎", "縦書き風: 同じ高さなら最初の氏名候補");

  const strings = M.parse(["株式会社架空", "高橋 次郎"]);
  ok(strings.name === "高橋 次郎", "文字列だけの配列でも氏名を取り出す");

  const departmentSurname = M.parse(["株式会社架空", "服部 太郎"]);
  ok(departmentSurname.department === "" && departmentSurname.name === "服部 太郎", "部署: 2 文字の姓を部署にしない");

  const longDepartmentSurname = M.parse(["株式会社架空", "長谷部 太郎"]);
  ok(longDepartmentSurname.department === "" && longDepartmentSurname.name === "長谷部 太郎", "部署: 3 文字以上でも姓と名の行を部署にしない");

  const joinedDepartmentTitle = M.parse(["株式会社架空", "総務課係長", "山田 太郎"]);
  ok(joinedDepartmentTitle.department === "総務課" && joinedDepartmentTitle.title === "係長" && joinedDepartmentTitle.name === "山田 太郎" && joinedDepartmentTitle.memo === "", "部署: 空白なしの役職と分け、氏名にしない");

  const tallestName = M.parse([
    { text: "佐藤 花子", height: 0.04 },
    { text: "株式会社架空", height: 0.03 },
    { text: "山田 太郎", height: 0.08 }
  ]);
  ok(tallestName.name === "山田 太郎" && tallestName.memo === "佐藤 花子", "氏名: 後ろでも文字の高さが最大の行を選ぶ");

  const empty = M.parse([]);
  ok(JSON.stringify(empty) === JSON.stringify({
    name: "", company: "", department: "", title: "", phones: [],
    email: "", address: "", url: "", memo: ""
  }), "空配列は全項目が空");
  ok(JSON.stringify(M.parse(null)) === JSON.stringify(empty), "null は全項目が空");

  const spaces = M.parse(["中村　   七郎"]);
  ok(spaces.name === "中村 七郎", "氏名の全角・連続空白を半角 1 つにそろえる");

  const memo = M.parse(["斎藤 八郎", "いつもお世話になっております"]);
  ok(memo.memo === "いつもお世話になっております", "振り分けられない行はメモへ入れる");

  const sameLine = M.parse(["合同会社架空", "代表取締役　井上 九郎"]);
  ok(sameLine.title === "代表取締役" && sameLine.name === "井上 九郎", "役職と氏名が同じ行でも分ける");

  const candidates = M.meetingCandidates("2026-10-14", [
    { id: "s-late", title: "午後の架空会議", dueOn: "2026-10-14", time: "15:00", calEventId: "" },
    { id: "s-all", title: "終日の架空行事", dueOn: "2026-10-14", time: "", calEventId: "" },
    { id: "s-linked", title: "連携した架空会議", dueOn: "2026-10-14", time: "10:00", calEventId: "c-linked" },
    { id: "s-other", title: "別日の架空会議", dueOn: "2026-10-15", time: "09:00", calEventId: "" }
  ], [
    { id: "c-linked", title: "カレンダー側の架空会議", date: "2026-10-14", startTime: "10:00" },
    { id: "c-early", title: "朝の架空会議", date: "2026-10-14", startTime: "9:00" },
    { id: "c-other", title: "別日の予定", date: "2026-10-13", startTime: "08:00" }
  ]);
  ok(candidates.length === 4, "予定候補: 別の日を外し、連携済みを 1 つにまとめる");
  ok(candidates[0].scheduleId === "s-all" && candidates[0].time === "", "予定候補: 終日を先頭にする");
  ok(candidates[1].calEventId === "c-early" && candidates[2].scheduleId === "s-linked" && candidates[3].scheduleId === "s-late", "予定候補: 時刻順にする");
  ok(candidates[2].scheduleId === "s-linked" && candidates[2].calEventId === "c-linked", "予定候補: 両方の ID を持たせる");
  ok(candidates.every((item) => item.date === "2026-10-14" && "title" in item && "time" in item), "予定候補: 公開する形をそろえる");
}

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて成功");
process.exit(failures ? 1 : 0);
