const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  runAppleWatch: (options) => ipcRenderer.invoke('run-apple-watch', options)
});
