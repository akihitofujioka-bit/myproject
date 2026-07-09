import { useCallback, useEffect, useState } from 'react';
import type { Project, ImageAsset, ImageEdits } from '../../shared/types.js';
import { createImageAsset } from '../../shared/project.js';
import { ImageEditor } from '../components/ImageEditor.js';

interface Props {
  project: Project;
  dirPath: string | null;
  onChange: (project: Project) => void;
  notify: (message: string) => void;
}

/** P5: 画像編集。記事に写真を追加し、切り抜き・回転・明るさを非破壊で調整する。 */
export function ImagesPage({ project, dirPath, onChange, notify }: Props): JSX.Element {
  const [articleId, setArticleId] = useState<string | null>(project.articles[0]?.id ?? null);
  const [imageId, setImageId] = useState<string | null>(null);
  const [urls, setUrls] = useState<Record<string, string>>({});

  const article = project.articles.find((a) => a.id === articleId) ?? null;
  const image = project.images.find((i) => i.id === imageId) ?? null;

  const patchImage = useCallback(
    (id: string, patch: Partial<ImageAsset>) =>
      onChange({ ...project, images: project.images.map((im) => (im.id === id ? { ...im, ...patch } : im)) }),
    [project, onChange]
  );

  const onAddImage = useCallback(async () => {
    if (!article) return;
    if (!dirPath) {
      notify('画像を追加する前に「名前を付けて保存」でプロジェクトを保存してください。');
      return;
    }
    const res = await window.api.import.addImage(dirPath);
    if (!res.ok) {
      if (!res.canceled) notify(`エラー: ${res.error}`);
      return;
    }
    const asset = createImageAsset(res.value.relativePath);
    onChange({
      ...project,
      images: [...project.images, asset],
      articles: project.articles.map((a) =>
        a.id === article.id ? { ...a, images: [...a.images, { imageId: asset.id, caption: '' }] } : a
      ),
    });
    setUrls((m) => ({ ...m, [asset.id]: res.value.dataUrl }));
    setImageId(asset.id);
  }, [article, dirPath, project, onChange, notify]);

  const onRemoveImage = useCallback(
    (imgId: string) => {
      if (!article) return;
      onChange({
        ...project,
        articles: project.articles.map((a) =>
          a.id === article.id ? { ...a, images: a.images.filter((r) => r.imageId !== imgId) } : a
        ),
        images: project.images.filter((im) => im.id !== imgId),
      });
      if (imageId === imgId) setImageId(null);
    },
    [article, project, onChange, imageId]
  );

  // 選択画像/記事画像の data URL を必要に応じて読み込む（再オープン対応）
  useEffect(() => {
    if (!article || !dirPath) return;
    let aborted = false;
    for (const ref of article.images) {
      if (urls[ref.imageId]) continue;
      const im = project.images.find((i) => i.id === ref.imageId);
      if (!im) continue;
      void window.api.import.readAsset(dirPath, im.relativePath).then((res) => {
        if (!aborted && res.ok) setUrls((m) => ({ ...m, [ref.imageId]: res.value }));
      });
    }
    return () => {
      aborted = true;
    };
  }, [article, dirPath, project.images, urls]);

  return (
    <div className="workbench">
      <div className="wb-body">
        <aside className="wb-list">
          <div className="wb-list-head">記事一覧（{project.articles.length}）</div>
          {project.articles.length === 0 && (
            <p className="wb-empty">記事がありません。先に「取り込み・正規化」で取り込んでください。</p>
          )}
          <ul>
            {project.articles.map((a) => (
              <li
                key={a.id}
                className={a.id === articleId ? 'selected' : ''}
                onClick={() => {
                  setArticleId(a.id);
                  setImageId(null);
                }}
              >
                <span className="wb-title">{a.title || '（無題）'}</span>
                <span className="wb-count">写真{a.images.length}</span>
              </li>
            ))}
          </ul>
        </aside>

        <section className="wb-form">
          {!article ? (
            <p className="wb-empty">記事を選んでください。</p>
          ) : (
            <>
              <div className="img-toolbar">
                <button className="primary" onClick={onAddImage}>
                  写真を追加
                </button>
                <span className="wb-hint">{dirPath ? '' : '※ 追加には先に保存が必要です'}</span>
              </div>

              {article.images.length === 0 ? (
                <p className="wb-empty">この記事にはまだ写真がありません。</p>
              ) : (
                <div className="thumb-row">
                  {article.images.map((ref) => {
                    const url = urls[ref.imageId];
                    return (
                      <div
                        key={ref.imageId}
                        className={ref.imageId === imageId ? 'thumb selected' : 'thumb'}
                        onClick={() => setImageId(ref.imageId)}
                      >
                        {url ? <img src={url} alt="" /> : <div className="thumb-ph">…</div>}
                      </div>
                    );
                  })}
                </div>
              )}

              {image && urls[image.id] && (
                <>
                  <ImageEditor
                    key={image.id}
                    dataUrl={urls[image.id]}
                    edits={image.edits}
                    onChange={(edits: ImageEdits) => patchImage(image.id, { edits })}
                    onResolution={(lowRes) => {
                      if (image.dpiWarning !== lowRes) patchImage(image.id, { dpiWarning: lowRes });
                    }}
                  />
                  <label className="cap-label">キャプション（写真説明）</label>
                  <input
                    type="text"
                    className="cap-input"
                    value={image.caption}
                    placeholder="例: 防災訓練のようす"
                    onChange={(e) => patchImage(image.id, { caption: e.target.value })}
                  />
                  <button className="danger sm" onClick={() => onRemoveImage(image.id)}>
                    この写真を削除
                  </button>
                </>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
