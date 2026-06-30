// Electron メインプロセス エントリ。
import { app, BrowserWindow, shell, protocol, net } from 'electron';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { registerProjectIpc } from './ipc/project.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rendererDir = path.join(__dirname, '../renderer');

// renderer は file:// ではなく独自スキーム app:// で配信する。
// 理由: file:// だと CSP 'self' / Vite が付与する crossorigin と相性が悪く
// モジュールスクリプトが実行されない場合がある。標準オリジンを与えて回避する。
protocol.registerSchemesAsPrivileged([
  { scheme: 'app', privileges: { standard: true, secure: true, supportFetchAPI: true } },
]);

function createWindow(): void {
  const win = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 960,
    minHeight: 640,
    title: '議会だより作成支援',
    show: false,
    webPreferences: {
      // セキュリティ: ノード統合は無効、コンテキスト分離は有効（仕様書 §8）
      preload: path.join(__dirname, '../preload/index.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  win.once('ready-to-show', () => win.show());

  // 外部リンクは既定ブラウザで開く
  win.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url);
    return { action: 'deny' };
  });

  // electron-vite の開発サーバ or ビルド済み（app://）
  const devUrl = process.env['ELECTRON_RENDERER_URL'];
  if (devUrl) {
    void win.loadURL(devUrl);
  } else {
    void win.loadURL('app://local/index.html');
  }
}

app.whenReady().then(() => {
  // app:// を実ファイルにマッピングする。ディレクトリ外への参照は拒否する。
  protocol.handle('app', async (request) => {
    const { pathname } = new URL(request.url);
    const rel = decodeURIComponent(pathname).replace(/^\/+/, '');
    const target = path.join(rendererDir, rel || 'index.html');
    if (!target.startsWith(rendererDir)) {
      return new Response('forbidden', { status: 403 });
    }
    const res = await net.fetch(pathToFileURL(target).href);
    // 本番の CSP をヘッダで付与（画像は data:/blob: を許可。外部送信はしない方針）。
    const headers = new Headers(res.headers);
    headers.set(
      'Content-Security-Policy',
      "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:"
    );
    return new Response(res.body, { status: res.status, headers });
  });

  registerProjectIpc();
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
