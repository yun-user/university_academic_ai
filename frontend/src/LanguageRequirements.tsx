import { useState } from "react";
import { api } from "./api";
import type { DepartmentGuidance, Input, LanguageRecord } from "./types";

type Result = { status: string; score_status: string; detail: string };
export default function LanguageRequirements({ data, guidance, change, work }: {
  data: Input; guidance: DepartmentGuidance; change: (patch: Partial<Input>) => void;
  work: (name: string, action: () => Promise<void>) => Promise<void>;
}) {
  const [result, setResult] = useState<{ record: string; value: Result } | null>(null);
  const record = data.profile.language;
  const fingerprint = JSON.stringify(data.profile);
  const shown = result?.record === fingerprint ? result.value : null;
  function update(value: LanguageRecord | null) {
    change({ profile: { ...data.profile, language: value, english: "확인 필요" } });
  }
  const exam = guidance.exams.find((e) => e.id === record?.exam);
  return <section className="panel language-panel" aria-labelledby="language-heading">
    <div className="section-heading"><h2 id="language-heading" tabIndex={-1}>어학 성적과 제출 확인</h2><span className="tag neutral">학과 자료 · {guidance.reviewed_on}</span></div>
    <p className="muted">공인시험 점수와 성적표 제출을 함께 확인하세요. 교양영어 추가학점과는 별도 요건입니다.</p>
    {data.profile.track === "일반" && <p className="callout">아래는 심화프로그램 기준입니다. 일반과정의 적용·면제 여부는 학과에 확인한 뒤 ‘필수과목·제출·승인 상태’에 기록하세요.</p>}
    <div className="table-scroll"><table className="language-table"><caption>공인어학 시험별 최소 기준</caption><thead><tr><th>시험</th><th>학과 기준</th><th>시험</th><th>학과 기준</th></tr></thead><tbody>
      {Array.from({length: Math.ceil(guidance.exams.length / 2)}, (_, i) => <tr key={i}>
        {[guidance.exams[i * 2], guidance.exams[i * 2 + 1]].map((e, j) => e ? <FragmentCells key={e.id} label={e.label} requirement={e.requirement} /> : <td key={j} colSpan={2}>—</td>)}
      </tr>)}
    </tbody></table></div>
    <p className="muted"><a href={guidance.sources[0].url} target="_blank" rel="noreferrer">학과 공학인증 졸업기준 원문 보기 ↗</a> · 점수 척도 개정·다른 급수는 학과 확인이 필요합니다.</p>
    {!record ? <button className="secondary" onClick={() => update({exam: "TOEIC", score: "", expires_on: null, submitted_on: null, submission_confirmed: false})}>어학성적 입력하기</button> : <>
      <div className="form-grid">
        <label>공인어학 시험<select value={record.exam} onChange={(e) => update({...record, exam: e.target.value, score: ""})}>
          {guidance.exams.map((e) => <option key={e.id} value={e.id}>{e.label}</option>)}<option value="OTHER">기타 시험·새 척도·다른 급수 (학과 확인)</option>
        </select></label>
        <label>취득 점수·등급{exam?.levels ? <select value={record.score} onChange={(e) => update({...record, score: e.target.value})}><option value="">등급 선택</option>{exam.levels.map((s) => <option key={s}>{s}</option>)}</select> : <input value={record.score} maxLength={30} inputMode={record.exam === "OTHER" ? "text" : "numeric"} placeholder={exam ? `기준 ${exam.requirement}` : "학과 확인이 필요한 점수"} onChange={(e) => update({...record, score: e.target.value})} />}</label>
        <label>성적표 유효기한<input type="date" value={record.expires_on ?? ""} onChange={(e) => update({...record, expires_on: e.target.value || null})} /></label>
        <label>실제 성적표 제출일<input type="date" value={record.submitted_on ?? ""} onChange={(e) => update({...record, submitted_on: e.target.value || null})} /></label>
      </div>
      <label className="check-label"><input type="checkbox" checked={record.submission_confirmed} onChange={(e) => update({...record, submission_confirmed: e.target.checked})} />이번 졸업에 사용할 성적표의 제출·접수·인정을 학과에서 확인했습니다.</label>
      <p className="muted">제출·접수가 확인되면 제출일의 유효기간을 대조합니다. 입력한 내용은 계획 저장·백업에 포함됩니다.</p>
      <div className="button-row"><button className="primary" onClick={() => void work("어학요건 확인 중", async () => {const value = await api<Result>("/language/check", "POST", data.profile); setResult({record: fingerprint, value});})}>어학 기준 확인</button><button className="text-button" onClick={() => update(null)}>성적 입력 초기화</button></div>
      {shown && <div className="language-result" role="status"><b>어학 요건: {shown.status} · 점수: {shown.score_status}</b><p>{shown.detail}</p><small>입력 기준 참고 결과입니다. 전체 졸업현황은 ‘조건 적용하고 계산’으로 갱신하세요.</small></div>}
    </>}
    <details className="department-notes"><summary>학과 홈페이지에서 추가로 확인한 내용</summary><ul>{guidance.notes.map((n) => <li key={n}>{n}</li>)}</ul><div className="source-links">{guidance.sources.slice(1).map((s) => <a key={s.id} href={s.url} target="_blank" rel="noreferrer">{s.title} ↗</a>)}</div></details>
  </section>;
}
function FragmentCells({label, requirement}: {label: string; requirement: string}) {
  return <><th scope="row">{label}</th><td>{requirement}</td></>;
}
