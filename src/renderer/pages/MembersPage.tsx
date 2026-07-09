import { useCallback } from 'react';
import type { Project, CouncilMember, OrderPreset } from '../../shared/types.js';
import {
  memberFromDraft,
  createEmptyMember,
  sortMembersByPreset,
} from '../../shared/project.js';

interface Props {
  project: Project;
  onChange: (project: Project) => void;
  notify: (message: string) => void;
}

const PRESETS: { key: OrderPreset; label: string }[] = [
  { key: 'seat', label: '議席番号順' },
  { key: 'faction', label: '党派順' },
  { key: 'kana', label: '五十音順' },
];

/** P3: 議員名簿の管理と掲載順の決定。 */
export function MembersPage({ project, onChange, notify }: Props): JSX.Element {
  // 表示は order 昇順
  const ordered = [...project.councilMembers].sort((a, b) => a.order - b.order);

  const setMembers = useCallback(
    (members: CouncilMember[]) => onChange({ ...project, councilMembers: members }),
    [project, onChange]
  );

  const updateMember = useCallback(
    (id: string, patch: Partial<CouncilMember>) => {
      setMembers(project.councilMembers.map((m) => (m.id === id ? { ...m, ...patch } : m)));
    },
    [project.councilMembers, setMembers]
  );

  const onImportRoster = useCallback(async () => {
    const res = await window.api.import.importRoster();
    if (!res.ok) {
      if (!res.canceled) notify(`エラー: ${res.error}`);
      return;
    }
    if (
      project.councilMembers.length > 0 &&
      !window.confirm('既存の議員名簿を、取り込んだ内容で置き換えます。よろしいですか？')
    ) {
      return;
    }
    const members = res.value.map((d, i) => memberFromDraft(d, { order: i }));
    setMembers(members);
    notify(`${members.length} 名の議員を取り込みました。`);
  }, [project.councilMembers.length, setMembers, notify]);

  const applyPreset = useCallback(
    (preset: OrderPreset) => setMembers(sortMembersByPreset(project.councilMembers, preset)),
    [project.councilMembers, setMembers]
  );

  const addMember = useCallback(() => {
    setMembers([...project.councilMembers, createEmptyMember({ order: project.councilMembers.length })]);
  }, [project.councilMembers, setMembers]);

  const removeMember = useCallback(
    (id: string) => {
      const kept = project.councilMembers.filter((m) => m.id !== id);
      // 手動並び順で order を振り直し
      const reindexed = [...kept]
        .sort((a, b) => a.order - b.order)
        .map((m, i) => ({ ...m, order: i }));
      setMembers(reindexed);
    },
    [project.councilMembers, setMembers]
  );

  // 手動並べ替え（上下移動）。order を入れ替える。
  const move = useCallback(
    (id: string, dir: -1 | 1) => {
      const list = ordered.slice();
      const idx = list.findIndex((m) => m.id === id);
      const next = idx + dir;
      if (idx < 0 || next < 0 || next >= list.length) return;
      [list[idx], list[next]] = [list[next], list[idx]];
      setMembers(list.map((m, i) => ({ ...m, order: i })));
    },
    [ordered, setMembers]
  );

  return (
    <div className="members">
      <div className="mem-actions">
        <button className="primary" onClick={onImportRoster}>
          名簿を取り込む（Excel）
        </button>
        <button onClick={addMember}>議員を追加</button>
        <div className="mem-presets">
          掲載順:
          {PRESETS.map((p) => (
            <button key={p.key} onClick={() => applyPreset(p.key)}>
              {p.label}
            </button>
          ))}
          <span className="mem-hint">（上下の ▲▼ で手動並べ替え）</span>
        </div>
      </div>

      {ordered.length === 0 ? (
        <p className="wb-empty">
          議員がいません。「名簿を取り込む（Excel）」で名簿ファイルを読み込むか、「議員を追加」で1名ずつ登録してください。
        </p>
      ) : (
        <div className="mem-table-wrap">
          <table className="mem-table">
            <thead>
              <tr>
                <th>順</th>
                <th>議席</th>
                <th>氏名</th>
                <th>ふりがな</th>
                <th>党派/会派</th>
                <th>期別</th>
                <th>役職名</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {ordered.map((m, i) => (
                <tr key={m.id}>
                  <td className="mem-order">
                    <button onClick={() => move(m.id, -1)} disabled={i === 0} title="上へ">
                      ▲
                    </button>
                    <span>{i + 1}</span>
                    <button
                      onClick={() => move(m.id, 1)}
                      disabled={i === ordered.length - 1}
                      title="下へ"
                    >
                      ▼
                    </button>
                  </td>
                  <td>
                    <input
                      className="c-seat"
                      type="number"
                      value={m.seatNumber ?? ''}
                      onChange={(e) =>
                        updateMember(m.id, {
                          seatNumber: e.target.value === '' ? null : Number(e.target.value),
                        })
                      }
                    />
                  </td>
                  <td>
                    <input
                      value={m.name}
                      onChange={(e) => updateMember(m.id, { name: e.target.value })}
                    />
                  </td>
                  <td>
                    <input
                      value={m.nameKana}
                      placeholder="やまだ たろう"
                      onChange={(e) => updateMember(m.id, { nameKana: e.target.value })}
                    />
                  </td>
                  <td>
                    <input
                      className="c-faction"
                      value={m.faction}
                      onChange={(e) => updateMember(m.id, { faction: e.target.value })}
                    />
                  </td>
                  <td>
                    <input
                      className="c-term"
                      value={m.term}
                      onChange={(e) => updateMember(m.id, { term: e.target.value })}
                    />
                  </td>
                  <td>
                    <input
                      value={m.role}
                      onChange={(e) => updateMember(m.id, { role: e.target.value })}
                    />
                  </td>
                  <td>
                    <button className="danger sm" onClick={() => removeMember(m.id)}>
                      削除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
