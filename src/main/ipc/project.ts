// プロジェクト関連の IPC ハンドラ登録。
import { ipcMain, dialog, BrowserWindow } from 'electron';
import { IpcChannels, type IpcResult, type OpenedProject } from '../../shared/ipc.js';
import { createEmptyProject } from '../../shared/project.js';
import type { Project } from '../../shared/types.js';
import { saveProjectToDir, loadProjectFromDir, isProjectDir } from '../projectStore.js';

function errMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function registerProjectIpc(): void {
  // 新規プロジェクト（メモリ上に空プロジェクトを作るだけ。保存は別途）
  ipcMain.handle(IpcChannels.projectNew, (): IpcResult<OpenedProject> => {
    return { ok: true, value: { project: createEmptyProject(), dirPath: null } };
  });

  // 既存プロジェクトを開く（フォルダ選択 → project.json 読込）
  ipcMain.handle(IpcChannels.projectOpen, async (event): Promise<IpcResult<OpenedProject>> => {
    const win = BrowserWindow.fromWebContents(event.sender) ?? undefined;
    const res = await dialog.showOpenDialog(win!, {
      title: 'プロジェクトフォルダを開く',
      properties: ['openDirectory'],
    });
    if (res.canceled || res.filePaths.length === 0) return { ok: false, canceled: true };
    const dirPath = res.filePaths[0];
    try {
      if (!(await isProjectDir(dirPath))) {
        return {
          ok: false,
          canceled: false,
          error: 'このフォルダは議会だよりプロジェクトではありません（project.json が見つかりません）。',
        };
      }
      const project = await loadProjectFromDir(dirPath);
      return { ok: true, value: { project, dirPath } };
    } catch (e) {
      return { ok: false, canceled: false, error: errMessage(e) };
    }
  });

  // 上書き保存（保存先が未定なら名前を付けて保存にフォールバック）
  ipcMain.handle(
    IpcChannels.projectSave,
    async (event, project: Project, dirPath: string | null): Promise<IpcResult<OpenedProject>> => {
      if (!dirPath) return saveAs(event, project);
      try {
        await saveProjectToDir(dirPath, project);
        return { ok: true, value: { project, dirPath } };
      } catch (e) {
        return { ok: false, canceled: false, error: errMessage(e) };
      }
    }
  );

  // 名前を付けて保存（保存先フォルダを選択）
  ipcMain.handle(
    IpcChannels.projectSaveAs,
    (event, project: Project): Promise<IpcResult<OpenedProject>> => saveAs(event, project)
  );
}

async function saveAs(
  event: Electron.IpcMainInvokeEvent,
  project: Project
): Promise<IpcResult<OpenedProject>> {
  const win = BrowserWindow.fromWebContents(event.sender) ?? undefined;
  const res = await dialog.showOpenDialog(win!, {
    title: 'プロジェクトの保存先フォルダを選択',
    properties: ['openDirectory', 'createDirectory'],
    buttonLabel: 'ここに保存',
  });
  if (res.canceled || res.filePaths.length === 0) return { ok: false, canceled: true };
  const dirPath = res.filePaths[0];
  try {
    await saveProjectToDir(dirPath, project);
    return { ok: true, value: { project, dirPath } };
  } catch (e) {
    return { ok: false, canceled: false, error: errMessage(e) };
  }
}
