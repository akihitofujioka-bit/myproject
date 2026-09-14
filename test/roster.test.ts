// P3: 名簿(Excel)取り込みの正規化と、掲載順プリセットの単体テスト。
// ※ 実データ(個人情報)は使わず、実ファイルと同じ構造の擬似データで検証する。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseRosterRows } from '../src/main/importers/roster.ts';
import {
  memberFromDraft,
  createEmptyMember,
  sortMembersByPreset,
} from '../src/shared/project.ts';
import type { CouncilMember } from '../src/shared/types.ts';

// 実ファイル（日高村議会 名簿）と同じ列構成・ヘッダ改行・凡例行を模した擬似データ
const ROWS: (string | number)[][] = [
  ['○○村議会　議員名簿'],
  ['（議員任期 …）'],
  ['基本情報', '', '', '', '', '', '', '', '', '', '常任委員会'],
  ['議席\r\n番号', '氏名', '生年月日', '党派', '期別', '役職名', '住所', '職業', 'TEL', '備考'],
  [1, '甲野　太郎', 'S46.10.23', '無所属', '1期', '', '住所A', '会社顧問', '090-0000-0000', ''],
  [2, '乙山　次郎', 'S31. 6. 8', '共産党', '1期', '議会運営副委員長', '住所B', '農業', '', ''],
  [3, '丙川　花子', 'S35.10.18', '公明党', '2期', '広報特別委員長\r\n議会改革副委員長', '住所C', '', '', ''],
  ['※ ◎＝委員長　○＝委員 …（凡例行はスキップ）'],
];

test('parseRosterRows: ヘッダを検出し、議員行だけを正規化', () => {
  const drafts = parseRosterRows(ROWS);
  assert.equal(drafts.length, 3, '凡例・タイトル行はスキップ');
  assert.deepEqual(
    drafts.map((d) => d.seatNumber),
    [1, 2, 3]
  );
  assert.equal(drafts[0].name, '甲野　太郎');
  assert.equal(drafts[1].faction, '共産党');
  assert.equal(drafts[1].term, '1期');
  // 複数役職は改行 → ／ に正規化
  assert.equal(drafts[2].role, '広報特別委員長／議会改革副委員長');
  // ふりがなは名簿に無いので空
  assert.equal(drafts[0].nameKana, '');
});

test('parseRosterRows: 氏名列が無ければ空配列', () => {
  assert.deepEqual(parseRosterRows([['a', 'b'], [1, 2]]), []);
});

test('memberFromDraft: 下書きから議員を作る', () => {
  const drafts = parseRosterRows(ROWS);
  const m = memberFromDraft(drafts[0], { id: 'mem_1', order: 0 });
  assert.equal(m.id, 'mem_1');
  assert.equal(m.seatNumber, 1);
  assert.equal(m.portraitImageId, null);
  assert.equal(m.order, 0);
});

// 並べ替えプリセット
function member(part: Partial<CouncilMember>): CouncilMember {
  return {
    id: part.id ?? 'x',
    name: part.name ?? '',
    nameKana: part.nameKana ?? '',
    faction: part.faction ?? '',
    seatNumber: part.seatNumber ?? null,
    term: part.term ?? '',
    role: part.role ?? '',
    portraitImageId: null,
    order: part.order ?? 0,
  };
}

test('sortMembersByPreset: 議席番号順', () => {
  const ms = [
    member({ id: 'b', seatNumber: 3, order: 0 }),
    member({ id: 'a', seatNumber: 1, order: 1 }),
    member({ id: 'c', seatNumber: 2, order: 2 }),
  ];
  const sorted = sortMembersByPreset(ms, 'seat');
  assert.deepEqual(
    sorted.map((m) => m.id),
    ['a', 'c', 'b']
  );
  assert.deepEqual(
    sorted.map((m) => m.order),
    [0, 1, 2]
  );
});

test('sortMembersByPreset: 五十音順（ふりがな）', () => {
  const ms = [
    member({ id: 'ta', nameKana: 'たなか', seatNumber: 2 }),
    member({ id: 'a', nameKana: 'あべ', seatNumber: 5 }),
    member({ id: 'sa', nameKana: 'さとう', seatNumber: 1 }),
  ];
  const sorted = sortMembersByPreset(ms, 'kana');
  assert.deepEqual(
    sorted.map((m) => m.id),
    ['a', 'sa', 'ta']
  );
});

test('sortMembersByPreset: manual は並びを保持し order を正規化', () => {
  const ms = [
    member({ id: 'x', order: 5 }),
    member({ id: 'y', order: 2 }),
  ];
  // 入力配列の順を保持（order は 0,1 に振り直し）
  const sorted = sortMembersByPreset(ms, 'manual');
  assert.deepEqual(
    sorted.map((m) => [m.id, m.order]),
    [
      ['x', 0],
      ['y', 1],
    ]
  );
});

test('createEmptyMember: 空議員を作れる', () => {
  const m = createEmptyMember({ id: 'mem_e', order: 3 });
  assert.equal(m.name, '');
  assert.equal(m.seatNumber, null);
  assert.equal(m.order, 3);
});
