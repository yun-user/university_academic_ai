import { useState } from "react";
import { api } from "./api";
import type { Attempt, Profile } from "./types";

interface Suggestion {
  index: number;
  code: string;
  name: string;
  before: { category: string; area: number };
  patch: Partial<Attempt> | null;
  changed: boolean;
  selected: boolean;
  reason: string;
  source: string;
}
interface Review {
  suggestions: Suggestion[];
  matched: number;
  unmatched: number;
  notes: string[];
}

export default function ClassificationReview({ rows, profile, onChange, work }: {
  rows: Attempt[];
  profile: Profile;
  onChange: (rows: Attempt[]) => void;
  work: (name: string, action: () => Promise<void>) => Promise<void>;
}) {
  const [preview, setPreview] = useState<{ key: string; data: Review } | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [undo, setUndo] = useState<{ before: Attempt[]; after: string } | null>(null);
  const key = JSON.stringify({ rows, profile });
  const current = preview?.key === key ? preview.data : null;
  return <div className="classification-review">
    <div className="table-toolbar">
      <button className="secondary" disabled={!rows.length} onClick={() => void work(
        "학과 자료와 이수구분을 대조하고 있어요…", async () => {
          const data = await api<Review>("/courses/classify", "POST", { attempts: rows, profile });
          setPreview({ key, data });
          setSelected(data.suggestions.filter(s => s.selected).map(s => s.index));
        })}>학과 자료로 분류 확인</button>
      {undo?.after === JSON.stringify(rows) && <button className="text-button" onClick={() => {
        onChange(undo.before); setUndo(null); setPreview(null);
      }}>분류 적용 되돌리기</button>}
    </div>
    <p className="muted">전공필수·전공선택은 전공 합계에 함께 반영합니다. 교양영어·전공영어의 추가 1학점은 일반선택이며, 전공기초영어와 별개입니다.</p>
    {preview && !current && <p role="status" className="muted">입력 또는 학번이 바뀌었습니다. 분류 확인을 다시 실행해 주세요.</p>}
    {current && <div className="edit-card">
      <h3>분류 근거 확인 · 일치 {current.matched}개 / 자료 미일치 {current.unmatched}개</h3>
      <p className="muted">미확인·기존 ‘전공’ 항목의 변경 제안을 먼저 선택했습니다. 직접 지정한 분류는 자동 선택하지 않습니다. 현재 자료에 따른 참고 제안이므로 수강 당시 인정 여부를 확인해 주세요. 설계·동일과목·SW 학점은 자동 부여하지 않습니다.</p>
      <div className="table-wrap">
        <table>
          <thead><tr><th>적용</th><th>과목</th><th>현재 → 제안</th><th>근거</th></tr></thead>
          <tbody>{current.suggestions.map(s => <tr key={s.index}>
            <td><input type="checkbox" aria-label={`${s.index + 1}행 분류 적용`} disabled={!s.changed}
              checked={selected.includes(s.index)} onChange={e => setSelected(previous =>
                e.target.checked ? [...previous, s.index] : previous.filter(i => i !== s.index))} /></td>
            <td><b>{s.name}</b><small>{s.code}</small></td>
            <td>{s.before.category}{s.before.area ? ` (${s.before.area}영역)` : ""} → {s.patch?.category ?? "현재 값 유지"}
              {s.patch?.area ? ` (${s.patch.area}영역)` : ""}{s.patch && !s.changed && <small>변경 없음</small>}</td>
            <td className="classification-evidence">{s.reason}{s.source && <small><a href={s.source} target="_blank" rel="noreferrer">공식 자료 열기</a></small>}</td>
          </tr>)}</tbody>
        </table>
      </div>
      <div className="table-toolbar">
        <button className="primary" disabled={!selected.length} onClick={() => {
          const next = rows.map((a, i) => selected.includes(i) ? { ...a, ...current.suggestions[i].patch } : a);
          setUndo({ before: rows, after: JSON.stringify(next) });
          onChange(next); setPreview(null);
        }}>선택한 {selected.length}개 분류 적용</button>
        <button className="text-button" onClick={() => setPreview(null)}>닫기</button>
      </div>
    </div>}
  </div>;
}
