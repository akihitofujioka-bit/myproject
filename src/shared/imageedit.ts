// 画像の非破壊編集パラメータ(ImageEdits)を、表示用のCSSへ変換する純粋ヘルパー。
// 元画像は変えず、表示・出力時にこれらを適用する（F-IMG-5 非破壊）。
import type { ImageEdits } from './types.js';

const round = (n: number, d = 3): number => {
  const p = 10 ** d;
  return Math.round(n * p) / p;
};
const clamp = (n: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, n));
const clamp01 = (n: number): number => clamp(n, 0, 1);

/** 明るさ・コントラスト・彩度を CSS filter に。基準0 → 係数1.0。 */
export function cssFilterFor(edits: Pick<ImageEdits, 'brightness' | 'contrast' | 'saturation'>): string {
  const b = round(1 + edits.brightness / 100);
  const c = round(1 + edits.contrast / 100);
  const s = round(1 + edits.saturation / 100);
  return `brightness(${b}) contrast(${c}) saturate(${s})`;
}

/** 回転・左右/上下反転を CSS transform に。無変換なら 'none'。 */
export function cssTransformFor(edits: Pick<ImageEdits, 'rotate' | 'flipH' | 'flipV'>): string {
  const parts: string[] = [];
  const rot = ((edits.rotate % 360) + 360) % 360;
  if (rot !== 0) parts.push(`rotate(${rot}deg)`);
  const sx = edits.flipH ? -1 : 1;
  const sy = edits.flipV ? -1 : 1;
  if (sx !== 1 || sy !== 1) parts.push(`scale(${sx}, ${sy})`);
  return parts.length ? parts.join(' ') : 'none';
}

/** 切り抜き矩形（正規化 0..1）を安全な範囲に丸める。null は全体。 */
export function clampCrop(crop: ImageEdits['crop']): ImageEdits['crop'] {
  if (!crop) return null;
  const x = clamp01(crop.x);
  const y = clamp01(crop.y);
  const width = clamp(crop.width, 0.02, 1 - x);
  const height = clamp(crop.height, 0.02, 1 - y);
  return { x, y, width, height };
}

export interface CropBackgroundStyle {
  aspectRatio: string;
  backgroundSize: string;
  backgroundPosition: string;
}

/**
 * 切り抜きを background-image で再現するスタイルを返す（回転/フィルタと合成可能）。
 * natW/natH は元画像の実ピクセル。crop=null は全体表示。
 */
export function cropBackgroundStyle(
  crop: ImageEdits['crop'],
  natW: number,
  natH: number
): CropBackgroundStyle {
  if (!crop) {
    return {
      aspectRatio: `${natW} / ${natH}`,
      backgroundSize: '100% 100%',
      backgroundPosition: '0% 0%',
    };
  }
  const posX = crop.width >= 1 ? 0 : round((crop.x / (1 - crop.width)) * 100, 2);
  const posY = crop.height >= 1 ? 0 : round((crop.y / (1 - crop.height)) * 100, 2);
  return {
    aspectRatio: `${round(crop.width * natW, 2)} / ${round(crop.height * natH, 2)}`,
    backgroundSize: `${round((100 / crop.width), 2)}% ${round((100 / crop.height), 2)}%`,
    backgroundPosition: `${posX}% ${posY}%`,
  };
}

/** 切り抜き後の長辺ピクセル（解像度判定用）。 */
export function effectiveLongEdge(
  natW: number,
  natH: number,
  crop: ImageEdits['crop']
): number {
  const w = crop ? natW * crop.width : natW;
  const h = crop ? natH * crop.height : natH;
  return Math.max(w, h);
}

/** 印刷に耐えるか（長辺の目安未満なら低解像度と判定）。 */
export function isLowResolution(longEdgePx: number, minLongEdge = 1200): boolean {
  return longEdgePx < minLongEdge;
}
