// 本文リッチテキスト(HTML)の純粋ヘルパー。main/renderer/テストから共用する。
// 本文の保存形式は最小限のHTML（p / h3 / ul>li / strong / ruby>rt）を想定。

/** テキストを HTML に埋め込む際のエスケープ。 */
export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

/** 最小限の HTML エンティティ復号。 */
export function decodeEntities(s: string): string {
  return s
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, ' ')
    .replace(/&#(\d+);/g, (_, n: string) => String.fromCodePoint(Number(n)));
}

/** 段落配列を本文HTMLにする（1段落 = 1つの p）。 */
export function paragraphsToHtml(paragraphs: string[]): string {
  return paragraphs.map((p) => `<p>${escapeHtml(p)}</p>`).join('');
}

/**
 * 本文HTMLをプレーンテキストにする。
 * - ルビの読み（rt）は除去し、親文字だけ残す（文字数・Word/テキスト出力向け）。
 * - ブロック終端（p/h/li/br）は改行に変換。
 */
export function htmlToPlainText(html: string): string {
  const text = html
    .replace(/<rt\b[^>]*>.*?<\/rt>/gis, '') // ルビの読みを除去
    .replace(/<rp\b[^>]*>.*?<\/rp>/gis, '')
    .replace(/<\/(p|div|h[1-6]|li)>/gi, '\n')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]+>/g, '');
  return decodeEntities(text).replace(/\n{3,}/g, '\n\n').replace(/\s+$/g, '');
}

/** 本文HTMLの文字数（空白・改行を除く。ルビの読みは数えない）。 */
export function countCharsFromHtml(html: string): number {
  return htmlToPlainText(html).replace(/\s/g, '').length;
}
