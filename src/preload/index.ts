// preload: contextBridge で限定したAPIだけを renderer に公開する（仕様書 §8 セキュリティ）。
import { contextBridge, ipcRenderer } from 'electron';
import { IpcChannels, type ProjectApi, type ImportApi } from '../shared/ipc.js';
import type { Project } from '../shared/types.js';

const projectApi: ProjectApi = {
  newProject: () => ipcRenderer.invoke(IpcChannels.projectNew),
  openProject: () => ipcRenderer.invoke(IpcChannels.projectOpen),
  saveProject: (project: Project, dirPath: string | null) =>
    ipcRenderer.invoke(IpcChannels.projectSave, project, dirPath),
  saveProjectAs: (project: Project) => ipcRenderer.invoke(IpcChannels.projectSaveAs, project),
};

const importApi: ImportApi = {
  extractDocuments: () => ipcRenderer.invoke(IpcChannels.importDocuments),
  addScan: (dirPath: string) => ipcRenderer.invoke(IpcChannels.importScan, dirPath),
  readAsset: (dirPath: string, relativePath: string) =>
    ipcRenderer.invoke(IpcChannels.assetReadDataUrl, dirPath, relativePath),
};

contextBridge.exposeInMainWorld('api', { project: projectApi, import: importApi });
