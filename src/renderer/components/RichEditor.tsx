import { useCallback, useRef } from 'react';
import { escapeHtml } from '../../shared/richtext.js';

interface Props {
  /** 初期HTML。value は非制御（記事切替時は key で再マウントする想定）。 */
  value: string;
  onChange: (html: string) => void;
}

/**
 * 本文リッチエディタ。対象は Electron の Chromium 単一環境なので
 * contentEditable + execCommand で十分に安定して動く。
 * 対応: 太字 / 見出し(h3) / 本文(p) / 箇条書き / ルビ。
 *
 * 非制御にして cursor 飛びを防ぐ。呼び出し側は記事IDを key に渡して切替時に再マウントする。
 */
export function RichEditor({ value, onChange }: Props): JSX.Element {
  const ref = useRef<HTMLDivElement>(null);

  const emit = useCallback(() => {
    if (ref.current) onChange(ref.current.innerHTML);
  }, [onChange]);

  const exec = useCallback(
    (command: string, arg?: string) => {
      document.execCommand(command, false, arg);
      emit();
    },
    [emit]
  );

  // 選択文字にルビ（ふりがな）を付ける。
  const addRuby = useCallback(() => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed) {
      window.alert('ルビを付ける文字を選択してください。');
      return;
    }
    const base = sel.toString();
    const reading = window.prompt(`「${base}」のふりがな`, '');
    if (reading == null || reading === '') return;
    document.execCommand(
      'insertHTML',
      false,
      `<ruby>${escapeHtml(base)}<rt>${escapeHtml(reading)}</rt></ruby>`
    );
    emit();
  }, [emit]);

  // ツールバー押下でエディタの選択が外れないよう mousedown を抑止する。
  const keep = (e: React.MouseEvent) => e.preventDefault();

  return (
    <div className="rich-editor">
      <div className="editor-toolbar">
        <button onMouseDown={keep} onClick={() => exec('bold')} title="太字">
          <b>太字</b>
        </button>
        <button onMouseDown={keep} onClick={() => exec('formatBlock', '<h3>')} title="見出し">
          見出し
        </button>
        <button onMouseDown={keep} onClick={() => exec('formatBlock', '<p>')} title="本文に戻す">
          本文
        </button>
        <button onMouseDown={keep} onClick={() => exec('insertUnorderedList')} title="箇条書き">
          ・箇条書き
        </button>
        <button onMouseDown={keep} onClick={addRuby} title="ふりがな">
          ルビ
        </button>
      </div>
      <div
        ref={ref}
        className="editor-area"
        contentEditable
        suppressContentEditableWarning
        dangerouslySetInnerHTML={{ __html: value }}
        onInput={emit}
        onBlur={emit}
      />
    </div>
  );
}
