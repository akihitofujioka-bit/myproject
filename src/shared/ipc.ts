// main / preload / renderer 間で共有する IPC 契約。
import type { Project, ArticleDraft } from './types.js';

/** IPC チャンネル名 */
export const IpcChannels = {
  projectNew: 'project:new',
  projectOpen: 'project:open',
  projectSave: 'project:save',
  projectSaveAs: 'project:saveAs',
  importDocuments: 'import:documents',
  importScan: 'import:scan',
  assetReadDataUrl: 'asset:readDataUrl',
} as const;

/** 開いているプロジェクトと、その保存先フォルダ */
export interface OpenedProject {
  project: Project;
  /** 保存先フォルダの絶対パス（未保存なら null） */
  dirPath: string | null;
}

/** IPC 呼び出しの共通結果型。キャンセルやエラーを表現する。 */
export type IpcResult<T> =
  | { ok: true; value: T }
  | { ok: false; canceled: true }
  | { ok: false; canceled: false; error: string };

/** 手書きスキャン取り込みの結果 */
export interface ImportedScan {
  /** assets 内の相対パス */
  relativePath: string;
  /** 表示用の data URL */
  dataUrl: string;
  /** 取り込み元ファイル名 */
  sourceFile: string;
}

/** preload が contextBridge 経由で renderer に公開する API の型 */
export interface ProjectApi {
  newProject(): Promise<IpcResult<OpenedProject>>;
  openProject(): Promise<IpcResult<OpenedProject>>;
  saveProject(project: Project, dirPath: string | null): Promise<IpcResult<OpenedProject>>;
  saveProjectAs(project: Project): Promise<IpcResult<OpenedProject>>;
}

export interface ImportApi {
  /** Word/Excel/テキストを複数選択して取り込み、正規化前の下書きを返す */
  extractDocuments(): Promise<IpcResult<ArticleDraft[]>>;
  /** 手書きスキャン（画像/PDF）を1つ選び assets へ取り込む。要保存済みプロジェクト（dirPath） */
  addScan(dirPath: string): Promise<IpcResult<ImportedScan>>;
  /** 保存済み assets の画像を表示用 data URL として読み出す（再オープン時のスキャン表示用） */
  readAsset(dirPath: string, relativePath: string): Promise<IpcResult<string>>;
}

declare global {
  interface Window {
    api: { project: ProjectApi; import: ImportApi };
  }
}
