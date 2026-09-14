// プロジェクトフォルダの読み書き（Node fs）。IPC から呼ばれる。
import { promises as fs } from 'node:fs';
import path from 'node:path';
import {
  serializeProject,
  deserializeProject,
  PROJECT_FILE,
  ASSETS_DIR,
} from '../shared/project.js';
import type { Project } from '../shared/types.js';

/**
 * プロジェクトをフォルダ形式で保存する（F-PRJ-2）。
 * dirPath/
 *   project.json
 *   assets/        ← 画像素材（後フェーズで使用）
 */
export async function saveProjectToDir(dirPath: string, project: Project): Promise<void> {
  await fs.mkdir(dirPath, { recursive: true });
  await fs.mkdir(path.join(dirPath, ASSETS_DIR), { recursive: true });
  const toSave: Project = { ...project, updatedAt: new Date().toISOString() };
  await fs.writeFile(path.join(dirPath, PROJECT_FILE), serializeProject(toSave), 'utf8');
}

/** プロジェクトフォルダから読み込む。 */
export async function loadProjectFromDir(dirPath: string): Promise<Project> {
  const json = await fs.readFile(path.join(dirPath, PROJECT_FILE), 'utf8');
  return deserializeProject(json);
}

/** 指定フォルダが既にプロジェクトフォルダか（project.json を持つか）。 */
export async function isProjectDir(dirPath: string): Promise<boolean> {
  try {
    await fs.access(path.join(dirPath, PROJECT_FILE));
    return true;
  } catch {
    return false;
  }
}
