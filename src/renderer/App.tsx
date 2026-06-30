import { useCallback, useEffect, useState } from 'react';
import type { Project } from '../shared/types.js';
import type { IpcResult, OpenedProject } from '../shared/ipc.js';
import { HomePage } from './pages/HomePage.js';

/** 現在開いているプロジェクトの状態 */
interface Session {
  project: Project;
  dirPath: string | null;
  dirty: boolean; // 未保存の変更があるか
}

export function App(): JSX.Element {
  const [session, setSession] = useState<Session | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const handleResult = useCallback(
    (res: IpcResult<OpenedProject>, savedMsg?: string): boolean => {
      if (res.ok) {
        setSession({ project: res.value.project, dirPath: res.value.dirPath, dirty: false });
        if (savedMsg) setMessage(savedMsg);
        return true;
      }
      if (!res.canceled) setMessage(`エラー: ${res.error}`);
      return false;
    },
    []
  );

  const onNew = useCallback(async () => {
    handleResult(await window.api.project.newProject());
    setMessage('新しいプロジェクトを作成しました（未保存）。');
  }, [handleResult]);

  const onOpen = useCallback(async () => {
    handleResult(await window.api.project.openProject(), 'プロジェクトを開きました。');
  }, [handleResult]);

  const onSave = useCallback(async () => {
    if (!session) return;
    const res = await window.api.project.saveProject(session.project, session.dirPath);
    handleResult(res, '保存しました。');
  }, [session, handleResult]);

  const onSaveAs = useCallback(async () => {
    if (!session) return;
    const res = await window.api.project.saveProjectAs(session.project);
    handleResult(res, '名前を付けて保存しました。');
  }, [session, handleResult]);

  const onChangeProject = useCallback((project: Project) => {
    setSession((s) => (s ? { ...s, project, dirty: true } : s));
  }, []);

  // メッセージは数秒で消す
  useEffect(() => {
    if (!message) return;
    const t = setTimeout(() => setMessage(null), 4000);
    return () => clearTimeout(t);
  }, [message]);

  return (
    <div className="app">
      <header className="toolbar">
        <strong>議会だより作成支援</strong>
        <div className="spacer" />
        <button onClick={onNew}>新規</button>
        <button onClick={onOpen}>開く</button>
        <button onClick={onSave} disabled={!session}>
          保存
        </button>
        <button onClick={onSaveAs} disabled={!session}>
          名前を付けて保存
        </button>
      </header>

      {message && <div className="message">{message}</div>}

      <main className="content">
        {session ? (
          <HomePage
            project={session.project}
            dirPath={session.dirPath}
            dirty={session.dirty}
            onChange={onChangeProject}
          />
        ) : (
          <div className="empty">
            <h1>議会だより作成支援</h1>
            <p>「新規」で号を作成するか、「開く」で既存のプロジェクトフォルダを選んでください。</p>
            <div className="empty-actions">
              <button className="primary" onClick={onNew}>
                新しい号を作成
              </button>
              <button onClick={onOpen}>既存の号を開く</button>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
