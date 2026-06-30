// プロジェクトの生成・直列化・検証（純粋関数）。
// fs/Electron に依存させず、Node 単体テストで検証できるようにする（P1 完了条件）。
import {
  PROJECT_SCHEMA_VERSION,
  type Project,
  type ProjectMeta,
  type Template,
  type Article,
} from './types.js';

/** プロジェクトフォルダ内の固定ファイル名 */
export const PROJECT_FILE = 'project.json';
/** 画像素材を格納するサブフォルダ */
export const ASSETS_DIR = 'assets';

/**
 * 衝突しにくいIDを生成する。
 * crypto.randomUUID があれば使い、無ければ時刻＋乱数で代替する。
 * （注: 乱数の種は呼び出し側環境に依存。テストでは固定IDを渡せるよう引数化）
 */
export function generateId(prefix = 'id'): string {
  const g = globalThis as { crypto?: { randomUUID?: () => string } };
  if (g.crypto?.randomUUID) return `${prefix}_${g.crypto.randomUUID()}`;
  return `${prefix}_${Date.now().toString(36)}${Math.floor(Math.random() * 1e6).toString(36)}`;
}

/** 既定テンプレート（縦書き・A4）。R-2 に従い縦書きを既定にする。 */
export function createDefaultTemplate(id: string): Template {
  return {
    id,
    name: '標準（縦書き・A4）',
    pageSize: 'A4',
    writingMode: 'vertical',
    margins: { top: 16, right: 16, bottom: 16, left: 16 },
    columns: 3,
    fonts: { heading: '游明朝', body: '游明朝', headingSizePt: 18, bodySizePt: 11 },
    frames: [],
  };
}

export interface CreateProjectOptions {
  id?: string;
  templateId?: string;
  meta?: Partial<ProjectMeta>;
  now?: string; // ISO文字列。テストで固定するため引数化。
}

/** 空のプロジェクトを生成する（P1: 新規作成）。 */
export function createEmptyProject(opts: CreateProjectOptions = {}): Project {
  const now = opts.now ?? new Date().toISOString();
  const id = opts.id ?? generateId('prj');
  const templateId = opts.templateId ?? generateId('tpl');
  const template = createDefaultTemplate(templateId);
  return {
    schemaVersion: PROJECT_SCHEMA_VERSION,
    id,
    meta: {
      issueNumber: null,
      publishDate: '',
      municipality: '',
      pageSize: 'A4',
      ...opts.meta,
    },
    councilMembers: [],
    articles: [],
    images: [],
    layout: { pages: [] },
    templates: [template],
    activeTemplateId: templateId,
    createdAt: now,
    updatedAt: now,
  };
}

/** 本文の文字数を数える（空白・改行を除く）。F-IMP-6 / F-EDIT-6 の基礎。 */
export function countArticleChars(article: Pick<Article, 'body'>): number {
  return article.body.join('').replace(/\s/g, '').length;
}

/** プロジェクトを JSON 文字列へ直列化する。 */
export function serializeProject(project: Project): string {
  return JSON.stringify(project, null, 2);
}

export class ProjectLoadError extends Error {}

/**
 * JSON 文字列からプロジェクトを復元し、最低限の妥当性を検証する。
 * 互換性のないスキーマバージョンはエラーにする。
 */
export function deserializeProject(json: string): Project {
  let data: unknown;
  try {
    data = JSON.parse(json);
  } catch {
    throw new ProjectLoadError('プロジェクトファイルの JSON を解析できませんでした。');
  }
  if (typeof data !== 'object' || data === null) {
    throw new ProjectLoadError('プロジェクトファイルの形式が不正です。');
  }
  const p = data as Partial<Project>;
  if (p.schemaVersion !== PROJECT_SCHEMA_VERSION) {
    throw new ProjectLoadError(
      `対応していないプロジェクト形式です（version=${String(p.schemaVersion)}、対応=${PROJECT_SCHEMA_VERSION}）。`
    );
  }
  for (const key of ['councilMembers', 'articles', 'images', 'templates'] as const) {
    if (!Array.isArray(p[key])) {
      throw new ProjectLoadError(`プロジェクトファイルに ${key} がありません。`);
    }
  }
  if (typeof p.layout !== 'object' || p.layout === null || !Array.isArray(p.layout.pages)) {
    throw new ProjectLoadError('プロジェクトファイルの layout が不正です。');
  }
  return p as Project;
}

/** 過去号を複製して次号のひな型にする（F-PRJ-4）。新IDを採番し時刻を更新。 */
export function duplicateProject(src: Project, opts: { id?: string; now?: string } = {}): Project {
  const now = opts.now ?? new Date().toISOString();
  return {
    ...structuredCloneSafe(src),
    id: opts.id ?? generateId('prj'),
    createdAt: now,
    updatedAt: now,
  };
}

/** structuredClone が無い環境向けのフォールバック付きディープコピー。 */
function structuredCloneSafe<T>(value: T): T {
  const g = globalThis as { structuredClone?: <U>(v: U) => U };
  if (g.structuredClone) return g.structuredClone(value);
  return JSON.parse(JSON.stringify(value)) as T;
}
