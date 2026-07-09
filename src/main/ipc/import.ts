// 取り込み関連の IPC ハンドラ。Word/Excel/テキストの抽出と、手書きスキャンの取り込み。
import { ipcMain, dialog, BrowserWindow } from 'electron';
import path from 'node:path';
import { IpcChannels, type IpcResult, type ImportedScan } from '../../shared/ipc.js';
import type { ArticleDraft } from '../../shared/types.js';
import { extractWordDraft } from '../importers/word.js';
import { extractExcelDraft } from '../importers/excel.js';
import { extractTextDraft } from '../importers/text.js';
import { copyIntoAssets, readAssetDataUrl } from '../assetStore.js';

function errMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function winOf(event: Electron.IpcMainInvokeEvent): BrowserWindow | undefined {
  return BrowserWindow.fromWebContents(event.sender) ?? undefined;
}

async function extractOne(filePath: string): Promise<ArticleDraft> {
  const ext = path.extname(filePath).toLowerCase();
  switch (ext) {
    case '.docx':
      return extractWordDraft(filePath);
    case '.xlsx':
    case '.xls':
      return extractExcelDraft(filePath);
    case '.txt':
      return extractTextDraft(filePath);
    default:
      throw new Error(`未対応の形式です: ${path.basename(filePath)}`);
  }
}

export function registerImportIpc(): void {
  // Word/Excel/テキストを複数選択して下書きを抽出
  ipcMain.handle(
    IpcChannels.importDocuments,
    async (event): Promise<IpcResult<ArticleDraft[]>> => {
      const res = await dialog.showOpenDialog(winOf(event)!, {
        title: '記事を取り込む（Word / Excel / テキスト）',
        properties: ['openFile', 'multiSelections'],
        filters: [
          { name: '記事ファイル', extensions: ['docx', 'xlsx', 'xls', 'txt'] },
          { name: 'すべて', extensions: ['*'] },
        ],
      });
      if (res.canceled || res.filePaths.length === 0) return { ok: false, canceled: true };
      try {
        const drafts: ArticleDraft[] = [];
        for (const fp of res.filePaths) drafts.push(await extractOne(fp));
        return { ok: true, value: drafts };
      } catch (e) {
        return { ok: false, canceled: false, error: errMessage(e) };
      }
    }
  );

  // 手書きスキャン（画像/PDF）を assets へ取り込む
  ipcMain.handle(
    IpcChannels.importScan,
    async (event, dirPath: string): Promise<IpcResult<ImportedScan>> => {
      if (!dirPath) {
        return {
          ok: false,
          canceled: false,
          error: 'スキャンを取り込む前にプロジェクトを保存してください。',
        };
      }
      const res = await dialog.showOpenDialog(winOf(event)!, {
        title: '手書き原稿のスキャンを取り込む',
        properties: ['openFile'],
        filters: [{ name: 'スキャン画像/PDF', extensions: ['jpg', 'jpeg', 'png', 'pdf'] }],
      });
      if (res.canceled || res.filePaths.length === 0) return { ok: false, canceled: true };
      try {
        const src = res.filePaths[0];
        const relativePath = await copyIntoAssets(dirPath, src);
        const dataUrl = await readAssetDataUrl(dirPath, relativePath);
        return {
          ok: true,
          value: { relativePath, dataUrl, sourceFile: path.basename(src) },
        };
      } catch (e) {
        return { ok: false, canceled: false, error: errMessage(e) };
      }
    }
  );

  // 保存済み assets の画像を data URL で読み出す（再オープン時の表示用）
  ipcMain.handle(
    IpcChannels.assetReadDataUrl,
    async (_event, dirPath: string, relativePath: string): Promise<IpcResult<string>> => {
      try {
        return { ok: true, value: await readAssetDataUrl(dirPath, relativePath) };
      } catch (e) {
        return { ok: false, canceled: false, error: errMessage(e) };
      }
    }
  );
}
