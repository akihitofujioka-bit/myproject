import { useCallback, useRef, useState } from 'react';
import type { ImageEdits } from '../../shared/types.js';
import {
  cssFilterFor,
  cssTransformFor,
  clampCrop,
  cropBackgroundStyle,
  effectiveLongEdge,
  isLowResolution,
} from '../../shared/imageedit.js';

interface Props {
  dataUrl: string;
  edits: ImageEdits;
  onChange: (edits: ImageEdits) => void;
  /** 元画像の実解像度が判明したら通知（低解像度警告のため） */
  onResolution?: (lowRes: boolean) => void;
}

interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** 画像の非破壊編集エディタ。切り抜きは正規化矩形で保持し、回転/反転/フィルタと合成する。 */
export function ImageEditor({ dataUrl, edits, onChange, onResolution }: Props): JSX.Element {
  const cropRef = useRef<HTMLDivElement>(null);
  const [nat, setNat] = useState<{ w: number; h: number } | null>(null);
  const [drag, setDrag] = useState<Rect | null>(null);

  const set = useCallback(
    (patch: Partial<ImageEdits>) => onChange({ ...edits, ...patch }),
    [edits, onChange]
  );

  const onImgLoad = useCallback(
    (e: React.SyntheticEvent<HTMLImageElement>) => {
      const w = e.currentTarget.naturalWidth;
      const h = e.currentTarget.naturalHeight;
      setNat({ w, h });
      onResolution?.(isLowResolution(effectiveLongEdge(w, h, edits.crop)));
    },
    [edits.crop, onResolution]
  );

  // 切り抜きドラッグ
  const norm = (clientX: number, clientY: number): { x: number; y: number } => {
    const r = cropRef.current!.getBoundingClientRect();
    return {
      x: Math.min(1, Math.max(0, (clientX - r.left) / r.width)),
      y: Math.min(1, Math.max(0, (clientY - r.top) / r.height)),
    };
  };
  const onPointerDown = (e: React.PointerEvent) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    const p = norm(e.clientX, e.clientY);
    setDrag({ x: p.x, y: p.y, width: 0, height: 0 });
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag) return;
    const p = norm(e.clientX, e.clientY);
    setDrag({
      x: Math.min(drag.x, p.x),
      y: Math.min(drag.y, p.y),
      width: Math.abs(p.x - drag.x),
      height: Math.abs(p.y - drag.y),
    });
  };
  const onPointerUp = () => {
    if (drag && drag.width > 0.02 && drag.height > 0.02) {
      set({ crop: clampCrop(drag) });
    }
    setDrag(null);
  };

  const preview = drag ?? edits.crop;
  const filter = cssFilterFor(edits);
  const bg = nat ? cropBackgroundStyle(edits.crop, nat.w, nat.h) : null;
  const lowRes =
    nat != null && isLowResolution(effectiveLongEdge(nat.w, nat.h, edits.crop));

  return (
    <div className="img-editor">
      <div className="img-edit-cols">
        {/* 切り抜き定義（元画像・回転前） */}
        <div className="img-crop-pane">
          <div className="pane-label">元画像（ドラッグで切り抜き範囲を指定）</div>
          <div
            className="crop-stage"
            ref={cropRef}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
          >
            <img src={dataUrl} alt="編集対象" style={{ filter }} onLoad={onImgLoad} draggable={false} />
            {preview && (
              <div
                className="crop-rect"
                style={{
                  left: `${preview.x * 100}%`,
                  top: `${preview.y * 100}%`,
                  width: `${preview.width * 100}%`,
                  height: `${preview.height * 100}%`,
                }}
              />
            )}
          </div>
          <button className="sm" onClick={() => set({ crop: null })} disabled={!edits.crop}>
            切り抜きを解除（全体に戻す）
          </button>
        </div>

        {/* 仕上がりプレビュー（切り抜き＋回転＋反転＋フィルタ） */}
        <div className="img-result-pane">
          <div className="pane-label">仕上がりプレビュー</div>
          {bg && (
            <div
              className="result-view"
              style={{
                aspectRatio: bg.aspectRatio,
                // data URL に括弧等が含まれても壊れないよう引用符で囲む
                backgroundImage: `url("${dataUrl}")`,
                backgroundSize: bg.backgroundSize,
                backgroundPosition: bg.backgroundPosition,
                filter,
                transform: cssTransformFor(edits),
              }}
            />
          )}
          {lowRes && (
            <div className="dpi-warn">⚠ 解像度が低い可能性があります（印刷でぼやける恐れ）。</div>
          )}
        </div>
      </div>

      {/* コントロール */}
      <div className="img-controls">
        <div className="ctl-row">
          <button className="sm" onClick={() => set({ rotate: (edits.rotate + 90) % 360 })}>
            ↻ 90°回転
          </button>
          <label className="chk">
            <input
              type="checkbox"
              checked={edits.flipH}
              onChange={(e) => set({ flipH: e.target.checked })}
            />
            左右反転
          </label>
          <label className="chk">
            <input
              type="checkbox"
              checked={edits.flipV}
              onChange={(e) => set({ flipV: e.target.checked })}
            />
            上下反転
          </label>
        </div>
        {(
          [
            ['brightness', '明るさ'],
            ['contrast', 'コントラスト'],
            ['saturation', '彩度'],
          ] as const
        ).map(([key, label]) => (
          <div className="slider-row" key={key}>
            <span className="slabel">{label}</span>
            <input
              type="range"
              min={-100}
              max={100}
              value={edits[key]}
              onChange={(e) => set({ [key]: Number(e.target.value) } as Partial<ImageEdits>)}
            />
            <span className="sval">{edits[key]}</span>
          </div>
        ))}
        <button
          className="sm"
          onClick={() =>
            set({ rotate: 0, flipH: false, flipV: false, brightness: 0, contrast: 0, saturation: 0 })
          }
        >
          調整をリセット
        </button>
      </div>
    </div>
  );
}
