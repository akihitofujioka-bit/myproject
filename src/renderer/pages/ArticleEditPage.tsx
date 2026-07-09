import { useCallback, useState } from 'react';
import type { Project, Article } from '../../shared/types.js';
import { countArticleChars } from '../../shared/project.js';
import { RichEditor } from '../components/RichEditor.js';

interface Props {
  project: Project;
  onChange: (project: Project) => void;
}

const SOURCE_LABEL: Record<Article['source'], string> = {
  handwritten: '手書き',
  word: 'Word',
  excel: 'Excel',
  pdf: 'PDF',
  text: 'テキスト',
  manual: '手入力',
};

/** P4: 記事編集。本文をリッチ編集（見出し/太字/箇条書き/ルビ）し、文字数超過を警告する。 */
export function ArticleEditPage({ project, onChange }: Props): JSX.Element {
  const [selectedId, setSelectedId] = useState<string | null>(
    project.articles[0]?.id ?? null
  );
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

  const over =
    selected && selected.charLimit != null && selected.charCount > selected.charLimit;

  return (
    <div className="workbench">
      <div className="wb-body">
        <aside className="wb-list">
          <div className="wb-list-head">記事一覧（{project.articles.length}）</div>
          {project.articles.length === 0 && (
            <p className="wb-empty">記事がありません。「取り込み・正規化」で取り込んでください。</p>
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

        <section className="wb-form">
          {!selected ? (
            <p className="wb-empty">記事を選ぶと本文を編集できます。</p>
          ) : (
            <>
              <label>記事タイトル</label>
              <input
                type="text"
                value={selected.title}
                onChange={(e) => updateArticle(selected.id, { title: e.target.value })}
              />

              <label>小見出し</label>
              <input
                type="text"
                value={selected.subtitle}
                onChange={(e) => updateArticle(selected.id, { subtitle: e.target.value })}
              />

              <label>本文</label>
              <RichEditor
                key={selected.id}
                value={selected.bodyHtml}
                onChange={(html) => updateArticle(selected.id, { bodyHtml: html })}
              />

              <div className="edit-meta">
                <div className={over ? 'count over' : 'count'}>
                  文字数: {selected.charCount}
                  {selected.charLimit != null ? ` / ${selected.charLimit}` : ''} 字
                  {over ? '（超過）' : ''}
                </div>
                <label className="limit-label">
                  枠の上限
                  <input
                    type="number"
                    className="c-limit"
                    value={selected.charLimit ?? ''}
                    placeholder="未設定"
                    onChange={(e) =>
                      updateArticle(selected.id, {
                        charLimit: e.target.value === '' ? null : Number(e.target.value),
                      })
                    }
                  />
                </label>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
