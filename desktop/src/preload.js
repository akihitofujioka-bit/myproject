const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  runInstall: (options) => ipcRenderer.invoke('run-install', options)
});
