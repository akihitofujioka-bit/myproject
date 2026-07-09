// プロジェクトの生成・直列化・検証（純粋関数）。
// fs/Electron に依存させず、Node 単体テストで検証できるようにする（P1 完了条件）。
import {
  PROJECT_SCHEMA_VERSION,
  type Project,
  type ProjectMeta,
  type Template,
  type Article,
  type ArticleDraft,
  type ImageAsset,
  type ImageEdits,
  type CouncilMember,
  type MemberDraft,
  type OrderPreset,
} from './types.js';
import { paragraphsToHtml, countCharsFromHtml } from './richtext.js';

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

/** 記事本文の文字数を数える（空白・改行・ルビの読みを除く）。F-IMP-6 / F-EDIT-6。 */
export function countArticleChars(article: Pick<Article, 'bodyHtml'>): number {
  return countCharsFromHtml(article.bodyHtml);
}

/** 名簿の下書き(MemberDraft)から CouncilMember を作る。 */
export function memberFromDraft(
  draft: MemberDraft,
  opts: { id?: string; order?: number } = {}
): CouncilMember {
  return {
    id: opts.id ?? generateId('mem'),
    name: draft.name,
    nameKana: draft.nameKana,
    faction: draft.faction,
    seatNumber: draft.seatNumber,
    term: draft.term,
    role: draft.role,
    portraitImageId: null,
    order: opts.order ?? 0,
  };
}

/** 空の議員を1名作る（手動追加用）。 */
export function createEmptyMember(opts: { id?: string; order?: number } = {}): CouncilMember {
  return memberFromDraft(
    { seatNumber: null, name: '', nameKana: '', faction: '', term: '', role: '' },
    opts
  );
}

/**
 * プリセットに従って議員を並べ替え、order を振り直して返す（F-ORD-3/4）。
 * manual は現在の並び順を保持したまま order を正規化する。
 */
export function sortMembersByPreset(
  members: CouncilMember[],
  preset: OrderPreset
): CouncilMember[] {
  const seat = (m: CouncilMember): number => m.seatNumber ?? Number.MAX_SAFE_INTEGER;
  const arr = members.slice();
  if (preset === 'seat') {
    arr.sort((a, b) => seat(a) - seat(b));
  } else if (preset === 'kana') {
    arr.sort((a, b) => (a.nameKana || '').localeCompare(b.nameKana || '', 'ja') || seat(a) - seat(b));
  } else if (preset === 'faction') {
    arr.sort((a, b) => a.faction.localeCompare(b.faction, 'ja') || seat(a) - seat(b));
  }
  // manual は並びを保持
  return arr.map((m, i) => ({ ...m, order: i }));
}

/** 画像編集パラメータの初期値（非破壊編集の起点）。 */
export function createDefaultImageEdits(): ImageEdits {
  return {
    crop: null,
    rotate: 0,
    flipH: false,
    flipV: false,
    brightness: 0,
    contrast: 0,
    saturation: 0,
  };
}

/** assets 内の相対パスから ImageAsset を作る。 */
export function createImageAsset(relativePath: string, opts: { id?: string } = {}): ImageAsset {
  return {
    id: opts.id ?? generateId('img'),
    relativePath,
    edits: createDefaultImageEdits(),
    caption: '',
    dpiWarning: false,
  };
}

/** 取り込み下書き(ArticleDraft)から Article を確定する。段落配列→本文HTML、文字数を自動計算。 */
export function articleFromDraft(
  draft: ArticleDraft,
  opts: { id?: string; sourceScanImageId?: string | null } = {}
): Article {
  const bodyHtml = paragraphsToHtml(draft.body);
  return {
    id: opts.id ?? generateId('art'),
    memberId: null,
    sectionId: '',
    title: draft.title,
    subtitle: draft.subtitle,
    bodyHtml,
    images: [],
    source: draft.source,
    sourceFile: draft.sourceFile,
    sourceScanImageId: opts.sourceScanImageId ?? null,
    charCount: countCharsFromHtml(bodyHtml),
    charLimit: null,
  };
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
