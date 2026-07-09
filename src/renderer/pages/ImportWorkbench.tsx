import { useCallback, useEffect, useState } from 'react';
import type { Project, Article } from '../../shared/types.js';
import { articleFromDraft, createImageAsset, countArticleChars } from '../../shared/project.js';
import { htmlToPlainText, paragraphsToHtml } from '../../shared/richtext.js';

interface Props {
  project: Project;
  dirPath: string | null;
  onChange: (project: Project) => void;
  notify: (message: string) => void;
}

const SOURCE_LABEL: Record<Article['source'], string> = {
  handwritten: '手書き',
  word: 'Word',
  excel: 'Excel',
  pdf: 'PDF',
  text: 'テキスト',
  manual: '手入力',
};

/** P2: 取り込み・正規化ワークベンチ。どの形式でも同じ記事データに整える。 */
export function ImportWorkbench({ project, dirPath, onChange, notify }: Props): JSX.Element {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // 手書きスキャンの表示用 data URL（imageId -> dataUrl）
  const [scanUrls, setScanUrls] = useState<Record<string, string>>({});

  const selected = project.articles.find((a) => a.id === selectedId) ?? null;

  const updateArticle = useCallback(
    (id: string, patch: Partial<Article>) => {
      const articles = project.articles.map((a) => {
        if (a.id !== id) return a;
        const next = { ...a, ...patch };
        next.charCount = countArticleChars(next);
        return next;
      });
      onChange({ ...project, articles });
    },
    [project, onChange]
  );

  // 文書（Word/Excel/テキスト）を取り込む
  const onImportDocuments = useCallback(async () => {
    const res = await window.api.import.extractDocuments();
    if (!res.ok) {
      if (!res.canceled) notify(`エラー: ${res.error}`);
      return;
    }
    const newArticles = res.value.map((d) => articleFromDraft(d));
    onChange({ ...project, articles: [...project.articles, ...newArticles] });
    notify(`${newArticles.length} 件の記事を取り込みました。`);
    if (newArticles.length > 0) setSelectedId(newArticles[newArticles.length - 1].id);
  }, [project, onChange, notify]);

  // 手書きスキャンを取り込む（要保存済み）
  const onImportScan = useCallback(async () => {
    if (!dirPath) {
      notify('スキャンを取り込む前に「名前を付けて保存」でプロジェクトを保存してください。');
      return;
    }
    const res = await window.api.import.addScan(dirPath);
    if (!res.ok) {
      if (!res.canceled) notify(`エラー: ${res.error}`);
      return;
    }
    const image = createImageAsset(res.value.relativePath);
    const article = articleFromDraft(
      {
        source: 'handwritten',
        sourceFile: res.value.sourceFile,
        title: '',
        subtitle: '',
        authorName: '',
        body: [],
        sourceScanRelativePath: res.value.relativePath,
      },
      { sourceScanImageId: image.id }
    );
    onChange({
      ...project,
      images: [...project.images, image],
      articles: [...project.articles, article],
    });
    setScanUrls((m) => ({ ...m, [image.id]: res.value.dataUrl }));
    setSelectedId(article.id);
    notify('スキャンを取り込みました。右のフォームに書き起こしてください。');
  }, [project, dirPath, onChange, notify]);

  const onDelete = useCallback(
    (id: string) => {
      onChange({ ...project, articles: project.articles.filter((a) => a.id !== id) });
      if (selectedId === id) setSelectedId(null);
    },
    [project, onChange, selectedId]
  );

  // 選択中の記事が手書きで、スキャン画像がまだ未読なら読み込む（再オープン対応）
  useEffect(() => {
    const imgId = selected?.sourceScanImageId;
    if (!selected || !imgId || scanUrls[imgId] || !dirPath) return;
    const img = project.images.find((i) => i.id === imgId);
    if (!img) return;
    let aborted = false;
    void window.api.import.readAsset(dirPath, img.relativePath).then((res) => {
      if (!aborted && res.ok) setScanUrls((m) => ({ ...m, [imgId]: res.value }));
    });
    return () => {
      aborted = true;
    };
  }, [selected, dirPath, project.images, scanUrls]);

  const scanUrl = selected?.sourceScanImageId ? scanUrls[selected.sourceScanImageId] : undefined;
  const isPdfScan = scanUrl?.startsWith('data:application/pdf');

  return (
    <div className="workbench">
      <div className="wb-actions">
        <button className="primary" onClick={onImportDocuments}>
          文書を取り込む（Word / Excel / テキスト）
        </button>
        <button onClick={onImportScan}>手書きスキャンを取り込む（画像 / PDF）</button>
        <span className="wb-hint">
          {dirPath ? '' : '※ スキャン取り込みには先に保存が必要です'}
        </span>
      </div>

      <div className="wb-body">
        {/* 左: 記事一覧 */}
        <aside className="wb-list">
          <div className="wb-list-head">記事一覧（{project.articles.length}）</div>
          {project.articles.length === 0 && (
            <p className="wb-empty">まだ記事がありません。上のボタンで取り込んでください。</p>
          )}
          <ul>
            {project.articles.map((a) => (
              <li
                key={a.id}
                className={a.id === selectedId ? 'selected' : ''}
                onClick={() => setSelectedId(a.id)}
              >
                <span className={`src src-${a.source}`}>{SOURCE_LABEL[a.source]}</span>
                <span className="wb-title">{a.title || '（無題）'}</span>
                <span className="wb-count">{a.charCount}字</span>
              </li>
            ))}
          </ul>
        </aside>

        {/* 右: 正規化フォーム */}
        <section className="wb-form">
          {!selected ? (
            <p className="wb-empty">記事を選ぶと、ここで正規化（編集）できます。</p>
          ) : (
            <>
              {selected.source === 'handwritten' && (
                <div className="scan-preview">
                  <div className="scan-label">スキャン原稿（参照）</div>
                  {scanUrl ? (
                    isPdfScan ? (
                      <div className="scan-pdf">PDF を取り込みました（プレビューは非対応）。</div>
                    ) : (
                      <img src={scanUrl} alt="スキャン原稿" />
                    )
                  ) : (
                    <div className="scan-pdf">読み込み中…</div>
                  )}
                </div>
              )}

              <div className="form-fields">
                <label>記事タイトル</label>
                <input
                  type="text"
                  value={selected.title}
                  onChange={(e) => updateArticle(selected.id, { title: e.target.value })}
                />

                <label>議員</label>
                <select
                  value={selected.memberId ?? ''}
                  onChange={(e) =>
                    updateArticle(selected.id, { memberId: e.target.value || null })
                  }
                >
                  <option value="">（未割り当て）</option>
                  {project.councilMembers.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))}
                </select>

                <label>本文（1行1段落。手書きは書き起こし。装飾やルビは「記事編集」タブで）</label>
                <textarea
                  value={htmlToPlainText(selected.bodyHtml)}
                  rows={12}
                  onChange={(e) =>
                    updateArticle(selected.id, {
                      bodyHtml: paragraphsToHtml(e.target.value.split('\n')),
                    })
                  }
                />
                <div className="wb-count-line">
                  {selected.charCount} 字
                  {selected.sourceFile && <span className="src-file">元: {selected.sourceFile}</span>}
                </div>

                <button className="danger" onClick={() => onDelete(selected.id)}>
                  この記事を削除
                </button>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
