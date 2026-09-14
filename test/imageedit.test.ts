// P5: 画像 非破壊編集ヘルパーの単体テスト。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  cssFilterFor,
  cssTransformFor,
  clampCrop,
  cropBackgroundStyle,
  effectiveLongEdge,
  isLowResolution,
} from '../src/shared/imageedit.ts';

test('cssFilterFor: 基準0で係数1.0', () => {
  assert.equal(cssFilterFor({ brightness: 0, contrast: 0, saturation: 0 }), 'brightness(1) contrast(1) saturate(1)');
  assert.equal(cssFilterFor({ brightness: 20, contrast: -10, saturation: 50 }), 'brightness(1.2) contrast(0.9) saturate(1.5)');
});

test('cssTransformFor: 回転と反転', () => {
  assert.equal(cssTransformFor({ rotate: 0, flipH: false, flipV: false }), 'none');
  assert.equal(cssTransformFor({ rotate: 90, flipH: false, flipV: false }), 'rotate(90deg)');
  assert.equal(cssTransformFor({ rotate: -90, flipH: true, flipV: false }), 'rotate(270deg) scale(-1, 1)');
});

test('clampCrop: 範囲内に丸める / null は全体', () => {
  assert.equal(clampCrop(null), null);
  assert.deepEqual(clampCrop({ x: -0.1, y: 0.5, width: 2, height: 0.9 }), {
    x: 0,
    y: 0.5,
    width: 1, // 1 - x = 1
    height: 0.5, // 1 - y = 0.5
  });
});

test('cropBackgroundStyle: 全体と部分切り抜き', () => {
  const full = cropBackgroundStyle(null, 1600, 1200);
  assert.equal(full.backgroundSize, '100% 100%');
  assert.equal(full.aspectRatio, '1600 / 1200');

  // 中央 50% を切り抜き
  const s = cropBackgroundStyle({ x: 0.25, y: 0.25, width: 0.5, height: 0.5 }, 1600, 1200);
  assert.equal(s.backgroundSize, '200% 200%');
  assert.equal(s.backgroundPosition, '50% 50%'); // 0.25/(1-0.5)=0.5
  assert.equal(s.aspectRatio, '800 / 600');
});

test('effectiveLongEdge / isLowResolution', () => {
  assert.equal(effectiveLongEdge(1600, 1200, null), 1600);
  assert.equal(effectiveLongEdge(1600, 1200, { x: 0, y: 0, width: 0.5, height: 0.5 }), 800);
  assert.equal(isLowResolution(800), true);
  assert.equal(isLowResolution(1600), false);
});
