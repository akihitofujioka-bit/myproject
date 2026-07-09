// 取り込んだ内容を「タイトル/小見出し/氏名/本文」へ正規化する純粋ロジック。
// 外部依存なし（Node標準のみ）。単体テストの対象。

/** 最小限の HTML エンティティ復号 */
export function decodeEntities(s: string): string {
  return s
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&#(\d+);/g, (_, n: string) => String.fromCodePoint(Number(n)));
}

/** タグを除去してテキストだけにする */
export function stripTags(s: string): string {
  return decodeEntities(s.replace(/<[^>]+>/g, '')).trim();
}

export interface NormalizedFields {
  title: string;
  subtitle: string;
  authorName: string;
  body: string[];
}

/**
 * mammoth が styleMap で付けたクラスを手掛かりに項目を判別する。
 * 推奨様式（§15）に従っていれば title/author/body/sub を拾える。
 * 従っていない（クラスなしの段落）場合は本文として扱い、
 * タイトルが取れなければ最初の本文段落をタイトルに繰り上げる。
 *
 * 想定クラス: gikai-title / gikai-author / gikai-sub / gikai-body
 */
export function parseStyledHtml(html: string): NormalizedFields {
  const fields: NormalizedFields = { title: '', subtitle: '', authorName: '', body: [] };
  const re = /<(h1|h2|h3|p)(?:\s+class="([^"]*)")?>([\s\S]*?)<\/\1>/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(html)) !== null) {
    const cls = m[2] ?? '';
    const text = stripTags(m[3]);
    if (!text) continue;
    if (cls.includes('gikai-title')) fields.title ||= text;
    else if (cls.includes('gikai-author')) fields.authorName ||= text;
    else if (cls.includes('gikai-sub')) fields.subtitle ||= text;
    else fields.body.push(text);
  }
  // タイトル未取得なら先頭の本文段落を繰り上げる
  if (!fields.title && fields.body.length > 0) {
    fields.title = fields.body.shift() as string;
  }
  return fields;
}

/** 素のテキスト（改行区切り）を段落配列にする。空行で段落を区切る。 */
export function splitTextToParagraphs(text: string): string[] {
  return text
    .replace(/\r\n?/g, '\n')
    .split(/\n{2,}/)
    .map((p) => p.replace(/\n/g, '').trim())
    .filter((p) => p.length > 0);
}

/** 段落配列から下書きフィールドを作る（先頭をタイトル、残りを本文）。 */
export function fieldsFromParagraphs(paragraphs: string[]): NormalizedFields {
  const ps = paragraphs.filter((p) => p.trim().length > 0);
  if (ps.length === 0) return { title: '', subtitle: '', authorName: '', body: [] };
  return { title: ps[0], subtitle: '', authorName: '', body: ps.slice(1) };
}
