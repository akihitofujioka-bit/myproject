// 画像素材（スキャン・写真）の取り込みと読み出し。プロジェクトフォルダの assets/ に格納する。
import { promises as fs } from 'node:fs';
import path from 'node:path';
import { ASSETS_DIR } from '../shared/project.js';

const MIME_BY_EXT: Record<string, string> = {
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.pdf': 'application/pdf',
};

export function mimeForExt(ext: string): string {
  return MIME_BY_EXT[ext.toLowerCase()] ?? 'application/octet-stream';
}

/** 一意なファイル名を作る（既存があれば連番を付す）。 */
async function uniqueName(dir: string, base: string): Promise<string> {
  const ext = path.extname(base);
  const stem = path.basename(base, ext);
  let candidate = base;
  let i = 1;
  // 衝突する限り連番
  // eslint-disable-next-line no-constant-condition
  while (true) {
    try {
      await fs.access(path.join(dir, candidate));
      candidate = `${stem}_${i++}${ext}`;
    } catch {
      return candidate;
    }
  }
}

/** 画像/PDF を assets/ にコピーし、相対パスを返す。 */
export async function copyIntoAssets(dirPath: string, srcPath: string): Promise<string> {
  const assetsDir = path.join(dirPath, ASSETS_DIR);
  await fs.mkdir(assetsDir, { recursive: true });
  const name = await uniqueName(assetsDir, path.basename(srcPath));
  await fs.copyFile(srcPath, path.join(assetsDir, name));
  return `${ASSETS_DIR}/${name}`;
}

/** assets の相対パスの中身を data URL として読み出す（表示用）。 */
export async function readAssetDataUrl(dirPath: string, relativePath: string): Promise<string> {
  // relativePath は assets/ 配下に限定（ディレクトリ横断を防ぐ）
  const normalized = path.normalize(relativePath);
  if (normalized.startsWith('..') || path.isAbsolute(normalized)) {
    throw new Error('不正なパスです。');
  }
  const full = path.join(dirPath, normalized);
  const buf = await fs.readFile(full);
  const mime = mimeForExt(path.extname(full));
  return `data:${mime};base64,${buf.toString('base64')}`;
}
