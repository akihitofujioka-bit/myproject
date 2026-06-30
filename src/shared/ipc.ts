// main / preload / renderer 間で共有する IPC 契約。
import type { Project } from './types.js';

/** IPC チャンネル名 */
export const IpcChannels = {
  projectNew: 'project:new',
  projectOpen: 'project:open',
  projectSave: 'project:save',
  projectSaveAs: 'project:saveAs',
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

/** preload が contextBridge 経由で renderer に公開する API の型 */
export interface ProjectApi {
  newProject(): Promise<IpcResult<OpenedProject>>;
  openProject(): Promise<IpcResult<OpenedProject>>;
  saveProject(project: Project, dirPath: string | null): Promise<IpcResult<OpenedProject>>;
  saveProjectAs(project: Project): Promise<IpcResult<OpenedProject>>;
}

declare global {
  interface Window {
    api: { project: ProjectApi };
  }
}
