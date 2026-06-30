// preload: contextBridge で限定したAPIだけを renderer に公開する（仕様書 §8 セキュリティ）。
import { contextBridge, ipcRenderer } from 'electron';
import { IpcChannels, type ProjectApi } from '../shared/ipc.js';
import type { Project } from '../shared/types.js';

const projectApi: ProjectApi = {
  newProject: () => ipcRenderer.invoke(IpcChannels.projectNew),
  openProject: () => ipcRenderer.invoke(IpcChannels.projectOpen),
  saveProject: (project: Project, dirPath: string | null) =>
    ipcRenderer.invoke(IpcChannels.projectSave, project, dirPath),
  saveProjectAs: (project: Project) => ipcRenderer.invoke(IpcChannels.projectSaveAs, project),
};

contextBridge.exposeInMainWorld('api', { project: projectApi });
