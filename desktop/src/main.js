const { app, BrowserWindow, ipcMain } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const os = require('os');

let mainWindow;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 400,
    height: 420,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      enableRemoteModule: false,
      nodeIntegration: false
    }
  });

  const isDev = process.env.NODE_ENV === 'development';
  const startUrl = isDev
    ? 'http://localhost:3000'
    : `file://${path.join(__dirname, '../renderer/index.html')}`;

  mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'));

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

app.on('ready', createWindow);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (mainWindow === null) {
    createWindow();
  }
});

// 再インストールコマンド実行（iPhone / Apple Watch）
const TARGETS = {
  iphone: { script: 'iphone', label: 'iPhone' },
  watch: { script: 'apple-watch', label: 'Apple Watch' },
  both: { script: 'iphone && npm run apple-watch', label: 'iPhone と Apple Watch' }
};

ipcMain.handle('run-install', async (event, options = {}) => {
  return new Promise((resolve) => {
    const target = TARGETS[options.target];
    if (!target) {
      resolve({ success: false, message: '対象が不明です', error: String(options.target) });
      return;
    }

    const projectPath = path.join(os.homedir(), 'myproject', 'mobile');
    const wifiMode = options.wifi ? 'export WIFI=1 && ' : '';
    const command = `cd "${projectPath}" && ${wifiMode}npm run ${target.script}`;

    // ログインシェルで起動する（Finder から開いたアプリは PATH が最小限で npm が見つからないため）
    const proc = spawn('bash', ['-lc', command]);

    let output = '';
    let errorOutput = '';

    proc.stdout.on('data', (data) => {
      output += data.toString();
    });

    proc.stderr.on('data', (data) => {
      errorOutput += data.toString();
    });

    proc.on('close', (code) => {
      if (code === 0) {
        resolve({
          success: true,
          message: `${target.label} へのインストールが完了しました`,
          output: output
        });
      } else {
        resolve({
          success: false,
          message: 'エラーが発生しました',
          error: (errorOutput + output) || `終了コード ${code}`
        });
      }
    });

    proc.on('error', (err) => {
      resolve({
        success: false,
        message: 'コマンド実行に失敗しました',
        error: err.message
      });
    });
  });
});
