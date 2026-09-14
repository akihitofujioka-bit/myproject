import type { Project, ProjectMeta } from '../../shared/types.js';

interface Props {
  project: Project;
  dirPath: string | null;
  dirty: boolean;
  onChange: (project: Project) => void;
}

/** P1 のホーム画面: 号のメタ情報を編集し、状態を表示する。 */
export function HomePage({ project, dirPath, dirty, onChange }: Props): JSX.Element {
  const setMeta = (patch: Partial<ProjectMeta>): void => {
    onChange({ ...project, meta: { ...project.meta, ...patch } });
  };

  return (
    <div className="home">
      <section className="card">
        <h2>
          号の基本情報
          {dirty && <span className="badge-dirty">未保存</span>}
        </h2>

        <label>号数</label>
        <input
          type="number"
          value={project.meta.issueNumber ?? ''}
          placeholder="例: 128"
          onChange={(e) =>
            setMeta({ issueNumber: e.target.value === '' ? null : Number(e.target.value) })
          }
        />

        <label>発行日</label>
        <input
          type="date"
          value={project.meta.publishDate}
          onChange={(e) => setMeta({ publishDate: e.target.value })}
        />

        <label>自治体名</label>
        <input
          type="text"
          value={project.meta.municipality}
          placeholder="例: ○○市"
          onChange={(e) => setMeta({ municipality: e.target.value })}
        />

        <label>紙面サイズ</label>
        <select
          value={project.meta.pageSize}
          onChange={(e) => setMeta({ pageSize: e.target.value as ProjectMeta['pageSize'] })}
        >
          <option value="A4">A4</option>
          <option value="B5">B5</option>
          <option value="B4">B4</option>
          <option value="A3">A3</option>
        </select>
      </section>

      <section className="card">
        <h2>このプロジェクトの状態</h2>
        <dl className="status">
          <dt>保存先</dt>
          <dd>{dirPath ?? '（未保存）'}</dd>
          <dt>議員</dt>
          <dd>{project.councilMembers.length} 名</dd>
          <dt>記事</dt>
          <dd>{project.articles.length} 件</dd>
          <dt>画像</dt>
          <dd>{project.images.length} 点</dd>
          <dt>テンプレート</dt>
          <dd>
            {project.templates.find((t) => t.id === project.activeTemplateId)?.name ?? '未設定'}
          </dd>
          <dt>更新</dt>
          <dd>{project.updatedAt}</dd>
        </dl>
        <p className="note">
          次フェーズで「取り込み・正規化」「議員・掲載順」「記事編集」「画像編集」「レイアウト」「出力」を追加します。
        </p>
      </section>
    </div>
  );
}
