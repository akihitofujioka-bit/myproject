import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import { createRequire } from "node:module";

const outputDirectory = path.resolve("apps/tests/fixtures");
fs.mkdirSync(outputDirectory, { recursive: true });

const meetingLines = [
  "架空市 第3回 架空検討委員会の開催について",
  "日時 令和8年10月22日（木）午後1時30分から",
  "場所 架空市役所 第1会議室",
  "当日は資料を持参してください。",
  "出欠を10月20日（火）までに提出してください。",
  "問い合わせ 架空課 電話 03-0000-0000",
];

const scheduleRows = [
  ["月日", "曜", "行事", "時間", "会場"],
  ["10月22日", "木", "架空の定例会", "10:00〜12:00", "議場"],
  ["10/28", "水", "架空の研修", "13時30分", "第1会議室"],
  ["", "", "（備考）", "", ""],
];

function crc32(buffer) {
  let crc = 0xffffffff;
  for (const byte of buffer) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function makeZip(entries) {
  const localParts = [];
  const centralParts = [];
  let offset = 0;

  for (const [name, text] of Object.entries(entries)) {
    const nameBytes = Buffer.from(name);
    const contents = Buffer.from(text);
    const compressed = zlib.deflateRawSync(contents);
    const checksum = crc32(contents);

    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0x0800, 6);
    local.writeUInt16LE(8, 8);
    local.writeUInt32LE(checksum, 14);
    local.writeUInt32LE(compressed.length, 18);
    local.writeUInt32LE(contents.length, 22);
    local.writeUInt16LE(nameBytes.length, 26);
    localParts.push(local, nameBytes, compressed);

    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(0x0800, 8);
    central.writeUInt16LE(8, 10);
    central.writeUInt32LE(checksum, 16);
    central.writeUInt32LE(compressed.length, 20);
    central.writeUInt32LE(contents.length, 24);
    central.writeUInt16LE(nameBytes.length, 28);
    central.writeUInt32LE(offset, 42);
    centralParts.push(central, nameBytes);

    offset += local.length + nameBytes.length + compressed.length;
  }

  const centralDirectory = Buffer.concat(centralParts);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(Object.keys(entries).length, 8);
  end.writeUInt16LE(Object.keys(entries).length, 10);
  end.writeUInt32LE(centralDirectory.length, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...localParts, centralDirectory, end]);
}

function xmlEscape(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function wordParagraph(text) {
  return `<w:p><w:r><w:t xml:space="preserve">${xmlEscape(text)}</w:t></w:r></w:p>`;
}

function wordTable(rows) {
  const body = rows.map((row) => {
    const cells = row.map((cell) => `<w:tc>${wordParagraph(cell)}</w:tc>`).join("");
    return `<w:tr>${cells}</w:tr>`;
  }).join("");
  return `<w:tbl>${body}</w:tbl>`;
}

function writeDocx(fileName, body) {
  const documentXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>${body}<w:sectPr/></w:body></w:document>`;
  const entries = {
    "[Content_Types].xml": `<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>`,
    "_rels/.rels": `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>`,
    "word/document.xml": documentXml,
  };
  fs.writeFileSync(path.join(outputDirectory, fileName), makeZip(entries));
}

function columnName(index) {
  let value = index + 1;
  let result = "";
  while (value > 0) {
    value -= 1;
    result = String.fromCharCode(65 + (value % 26)) + result;
    value = Math.floor(value / 26);
  }
  return result;
}

function excelSerial(isoDate) {
  return (Date.parse(`${isoDate}T00:00:00Z`) - Date.parse("1899-12-30T00:00:00Z")) / 86400000;
}

function writeXlsx() {
  const shared = [
    "月日", "曜", "行事", "時間", "会場", "木", "架空の定例会", "10:00〜12:00", "議場",
    "水", "架空の研修", "13時30分", "第1会議室", "（備考）",
  ];
  const sharedIndex = new Map(shared.map((value, index) => [value, index]));
  const excelRows = [
    scheduleRows[0],
    [{ date: "2026-10-22" }, ...scheduleRows[1].slice(1)],
    [{ date: "2026-10-28" }, ...scheduleRows[2].slice(1)],
    scheduleRows[3],
  ];
  const sheetRows = excelRows.map((row, rowIndex) => {
    const cells = row.map((cell, columnIndex) => {
      if (cell === "") return "";
      const reference = `${columnName(columnIndex)}${rowIndex + 1}`;
      if (typeof cell === "object") {
        return `<c r="${reference}" s="1"><v>${excelSerial(cell.date)}</v></c>`;
      }
      return `<c r="${reference}" t="s"><v>${sharedIndex.get(cell)}</v></c>`;
    }).join("");
    return `<row r="${rowIndex + 1}">${cells}</row>`;
  }).join("");
  const entries = {
    "[Content_Types].xml": `<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>`,
    "_rels/.rels": `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>`,
    "xl/workbook.xml": `<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="予定表" sheetId="1" r:id="rId1"/></sheets></workbook>`,
    "xl/_rels/workbook.xml.rels": `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>`,
    "xl/sharedStrings.xml": `<?xml version="1.0" encoding="UTF-8"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="${shared.length}" uniqueCount="${shared.length}">${shared.map((value) => `<si><t>${xmlEscape(value)}</t></si>`).join("")}</sst>`,
    "xl/styles.xml": `<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="1"><font/></fonts><fills count="1"><fill/></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14" applyNumberFormat="1"/></cellXfs></styleSheet>`,
    "xl/worksheets/sheet1.xml": `<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>${sheetRows}</sheetData></worksheet>`,
  };
  fs.writeFileSync(path.join(outputDirectory, "doc-table.xlsx"), makeZip(entries));
}

async function writePdfs() {
  const require = createRequire(import.meta.url);
  const { chromium } = require("playwright");
  const browser = await chromium.launch({ headless: true });
  try {
    const textPage = await browser.newPage({ viewport: { width: 900, height: 1200 } });
    const paragraphs = meetingLines.map((line) => `<p>${xmlEscape(line)}</p>`).join("");
    await textPage.setContent(`<html lang="ja"><meta charset="utf-8"><style>body{font-family:sans-serif;font-size:22px;padding:48px}p{margin:0 0 18px}</style><body>${paragraphs}</body></html>`);
    await textPage.pdf({ path: path.join(outputDirectory, "doc-text.pdf"), format: "A4", printBackground: true });

    const imagePage = await browser.newPage({ viewport: { width: 900, height: 1200 }, deviceScaleFactor: 1 });
    await imagePage.setContent(`<html lang="ja"><meta charset="utf-8"><style>body{font-family:sans-serif;font-size:22px;padding:48px}p{margin:0 0 18px}</style><body>${paragraphs}</body></html>`);
    const image = await imagePage.screenshot({ type: "png", fullPage: true });
    const scanPage = await browser.newPage({ viewport: { width: 900, height: 1200 } });
    await scanPage.setContent(`<html><body style="margin:0"><img alt="" style="width:100%;display:block" src="data:image/png;base64,${image.toString("base64")}"></body></html>`);
    await scanPage.pdf({ path: path.join(outputDirectory, "doc-scan.pdf"), format: "A4", printBackground: true });
  } finally {
    await browser.close();
  }
}

writeDocx("doc-meeting.docx", meetingLines.map(wordParagraph).join(""));
writeDocx("doc-table.docx", wordTable(scheduleRows));
writeXlsx();
await writePdfs();

// 悪意のあるファイルを模した見本（アプリが固まったり落ちたりしないことの確認用）
// 展開すると 60MB になる Word（上限 50MB を超える）
fs.writeFileSync(path.join(outputDirectory, "doc-bomb.docx"), makeZip({
  "word/document.xml": "<w:document>" + " ".repeat(60 * 1024 * 1024) + "</w:document>",
}));
// 極端に右の列（XFD）と、桁あふれするほど長い列名のセルを持つ Excel
const inlineCell = (ref, text) => `<c r="${ref}" t="inlineStr"><is><t>${text}</t></is></c>`;
fs.writeFileSync(path.join(outputDirectory, "doc-wide.xlsx"), makeZip({
  "xl/worksheets/sheet1.xml": `<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1">${inlineCell("A1", "架空の行事")}${inlineCell("XFD1", "右端")}${inlineCell("ZZZZZZZZZZZZZZZZZZZZ1", "桁あふれ")}</row></sheetData></worksheet>`,
}));
console.log("見本ファイルを7件作成しました。");
