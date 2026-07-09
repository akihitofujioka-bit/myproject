// 議員名簿(Excel)の取り込み。「議員名簿」シートのヘッダ行を検出し、行を MemberDraft に正規化する。
// 想定様式: 議席番号 / 氏名 / 生年月日 / 党派 / 期別 / 役職名 / … の表（日高村議会 名簿など）。
import * as xlsxNs from 'xlsx';
import type { MemberDraft } from '../../shared/types.js';

// xlsx は Vite(ESM)/tsx(CJS)で形が異なるため両対応（excel.ts と同様）。
const XLSX = (xlsxNs as unknown as { default?: typeof xlsxNs }).default ?? xlsxNs;

type Cell = string | number | boolean | null | undefined;

/** ヘッダ照合用に空白・改行を除去する。 */
function norm(v: Cell): string {
  return String(v ?? '').replace(/[\r\n\s　]+/g, '');
}

/**
 * シート行（2次元配列）から議員の下書きを抽出する（純粋関数・テスト対象）。
 * - '氏名' を含む行をヘッダ行とみなす。
 * - ヘッダのラベルで列位置を特定（列がずれても追従）。
 * - 以降、議席番号が数値の行だけを議員として読む（凡例・空行はスキップ）。
 */
export function parseRosterRows(rows: Cell[][]): MemberDraft[] {
  const headerIdx = rows.findIndex((r) => r.some((c) => norm(c) === '氏名'));
  if (headerIdx < 0) return [];
  const header = rows[headerIdx].map(norm);

  const seatCol = header.findIndex((h) => h.includes('議席'));
  const nameCol = header.indexOf('氏名');
  const factionCol = header.indexOf('党派');
  const termCol = header.indexOf('期別');
  const roleCol = header.indexOf('役職名');
  if (nameCol < 0) return [];

  const get = (r: Cell[], i: number): string => (i >= 0 ? String(r[i] ?? '').trim() : '');
  const out: MemberDraft[] = [];
  for (let i = headerIdx + 1; i < rows.length; i++) {
    const r = rows[i];
    if (!r) continue;
    const seatRaw = seatCol >= 0 ? r[seatCol] : undefined;
    const seatNumber =
      typeof seatRaw === 'number'
        ? seatRaw
        : /^\d+$/.test(String(seatRaw ?? '').trim())
          ? Number(seatRaw)
          : null;
    const name = get(r, nameCol);
    // 議席番号が無い or 氏名が空の行（凡例・見出し・空行）はスキップ
    if (seatNumber === null || !name) continue;

    out.push({
      seatNumber,
      name,
      nameKana: '', // 名簿に無いのでアプリで手入力
      faction: get(r, factionCol),
      term: get(r, termCol),
      // 複数役職は改行区切り → ／ に
      role: get(r, roleCol).replace(/[\r\n]+/g, '／'),
    });
  }
  return out;
}

/** 名簿ファイルから議員下書きを抽出する。「名簿」を含むシートを優先、無ければ先頭シート。 */
export function extractMembersFromRoster(filePath: string): MemberDraft[] {
  const wb = XLSX.readFile(filePath);
  const sheetName =
    wb.SheetNames.find((n: string) => n.includes('名簿')) ?? wb.SheetNames[0];
  if (!sheetName) return [];
  const ws = wb.Sheets[sheetName];
  const rows = XLSX.utils.sheet_to_json<Cell[]>(ws, {
    header: 1,
    blankrows: false,
    defval: '',
  });
  return parseRosterRows(rows);
}
