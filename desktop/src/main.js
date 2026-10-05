const { app, BrowserWindow, ipcMain } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const os = require('os');

let mainWindow;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 400,
    height: 300,
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

// Apple Watch 再インストールコマンド実行
ipcMain.handle('run-apple-watch', async (event, options = {}) => {
  return new Promise((resolve) => {
    const projectPath = path.join(os.homedir(), 'myproject', 'mobile');
    const wifiMode = options.wifi ? 'WIFI=1' : '';

    let command = `cd ${projectPath} && npm run apple-watch`;
    if (wifiMode) {
      command = `cd ${projectPath} && ${wifiMode} npm run apple-watch`;
    }

    const proc = spawn('bash', ['-c', command]);

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
          message: 'Apple Watch へのインストールが完了しました',
          output: output
        });
      } else {
        resolve({
          success: false,
          message: 'エラーが発生しました',
          error: errorOutput || output
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
