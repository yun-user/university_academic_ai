import { useState } from "react";
import { api } from "./api";
import type { ChatFeedback, CounselingPreferences, Input, Message } from "./types";

export const emptyPreferences: CounselingPreferences = {
  interests: "", credit_limit: null, final_credit_limit: null,
  graduation_year: null, graduation_term: null, notes: "",
};

export function CounselingGoals({ data, change, save, saved }: {
  data: Input; change: (patch: Partial<Input>) => void; save: () => void; saved: boolean;
}) {
  const prefs = data.counseling_preferences ?? emptyPreferences;
  const [message, setMessage] = useState("");
  const update = (patch: Partial<CounselingPreferences>) => { setMessage(""); change({ counseling_preferences: { ...prefs, ...patch } }); };
  function applyLimits() {
    const limit = prefs.credit_limit ?? data.options.credit_limit;
    const caps = prefs.credit_limit === null ? [...(data.options.semester_limits ?? Array(data.options.semesters).fill(limit))] : Array(data.options.semesters).fill(limit);
    if (prefs.final_credit_limit !== null) caps[caps.length - 1] = prefs.final_credit_limit;
    change({ options: { ...data.options, credit_limit: Math.max(limit, ...caps), semester_limits: caps }, placements: null });
    setMessage("학점 한도를 계획에 적용했습니다. 학기별 로드맵에서 다시 계산해 주세요. 직접 배치는 자동 계획으로 전환했습니다.");
  }
  return <section className="panel counseling-goals">
    <h2>기억할 나의 목표</h2>
    <p className="muted">이 계획의 상담에 사용할 목표입니다. 저장하거나 질문을 보내면 현재 계획과 함께 보관하며, 언제든 수정할 수 있습니다.</p>
    <div className="form-grid">
      <label>관심 분야·희망 진로<input maxLength={300} value={prefs.interests} onChange={(e) => update({ interests: e.target.value })} placeholder="예: 백엔드 개발, 데이터 분석" /></label>
      <label>희망 학기당 최대 학점<input type="number" min={1} max={30} value={prefs.credit_limit ?? ""} onChange={(e) => update({ credit_limit: e.target.value === "" ? null : Number(e.target.value) })} /></label>
      <label>마지막 학기 최대 학점<input type="number" min={0} max={30} value={prefs.final_credit_limit ?? ""} onChange={(e) => update({ final_credit_limit: e.target.value === "" ? null : Number(e.target.value) })} /></label>
      <label>마지막 수강 희망 연도<input type="number" min={2018} max={2100} value={prefs.graduation_year ?? ""} onChange={(e) => update({ graduation_year: e.target.value === "" ? null : Number(e.target.value), graduation_term: e.target.value === "" ? null : (prefs.graduation_term ?? 2) })} /></label>
      <label>마지막 수강 희망 학기<select disabled={prefs.graduation_year === null} value={prefs.graduation_term ?? 2} onChange={(e) => update({ graduation_term: Number(e.target.value) })}><option value={1}>1학기 (8월 졸업 희망)</option><option value={2}>2학기 (다음 해 2월 졸업 희망)</option></select></label>
      <label>기억할 요청<textarea maxLength={500} value={prefs.notes} onChange={(e) => update({ notes: e.target.value })} placeholder="예: 마지막 학기는 졸업작품에 집중하고 싶어요." /></label>
    </div>
    <p className="muted">예: 2027년 2학기까지 수강 → 2028년 2월 졸업 희망. 희망 시점은 졸업 가능 판정이 아니며, 목표 입력만으로 계획의 학점 한도가 바뀌지는 않습니다.</p>
    <div className="button-row"><button className="primary" onClick={save}>{saved ? "목표·현재 계획 저장" : "목표와 새 계획 저장"}</button><button disabled={prefs.credit_limit === null && prefs.final_credit_limit === null} onClick={applyLimits}>희망 학점 한도를 계획에 적용</button><button onClick={() => { change({ counseling_preferences: { ...emptyPreferences } }); setMessage("목표를 비웠습니다. 저장하면 기억에서도 지워집니다."); }}>목표 비우기</button></div>
    {message && <p role="status">{message}</p>}
  </section>;
}

const emptyFeedback: ChatFeedback = { rating: "unrated", correction: "", source: "", verified: false };
export function AnswerFeedback({ message, profileId, onUpdate, onDelete, work }: {
  message: Message; profileId: string; onUpdate: (message: Message) => void; onDelete: () => void;
  work: (label: string, action: () => Promise<void>) => Promise<void>;
}) {
  const [feedback, setFeedback] = useState<ChatFeedback>({ ...emptyFeedback, ...message.feedback });
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [notice, setNotice] = useState("");
  const path = `/profiles/${profileId}/chat/${message.id}`;
  return <div className="answer-feedback">
    {message.mode === "llm" && <details><summary>답변 평가·정정 {message.feedback?.verified ? "· 근거 대조 완료" : message.feedback?.rating === "helpful" ? "· 도움 됨" : message.feedback?.rating === "unhelpful" ? "· 개선 필요" : ""}</summary>
      <div className="form-grid">
        <label>답변 평가<select value={feedback.rating} onChange={(e) => setFeedback({ ...feedback, rating: e.target.value as ChatFeedback["rating"] })}><option value="unrated">아직 평가하지 않음</option><option value="helpful">도움 됨</option><option value="unhelpful">개선 필요</option></select></label>
        <label>정정 내용<textarea value={feedback.correction} maxLength={3000} onChange={(e) => setFeedback({ ...feedback, correction: e.target.value, verified: false })} placeholder="어떤 설명을 어떻게 고쳐야 하는지 적어 주세요." /></label>
        <label>대조한 근거<input value={feedback.source} maxLength={500} onChange={(e) => setFeedback({ ...feedback, source: e.target.value, verified: false })} placeholder="예: 학과 공지 제목·날짜·URL 또는 담당자 확인 내용" /></label>
      </div>
      <label className="check-label"><input type="checkbox" checked={feedback.verified} disabled={!feedback.correction.trim() || !feedback.source.trim()} onChange={(e) => setFeedback({ ...feedback, verified: e.target.checked })} />정정 내용을 근거 자료와 직접 대조했습니다.</label>
      <p className="muted">개선 필요·정정 중인 원답변은 다음 상담에서 제외합니다. 근거 대조가 완료된 정정만 같은 계산 조건에서 참고하며, 최신 졸업 계산을 덮어쓰지 않습니다.</p>
      <button onClick={() => void work("답변 평가를 저장하고 있어요…", async () => {
        const updated = await api<Message>(`${path}/feedback`, "PUT", { ...feedback, updated_at: undefined, revision: message.revision });
        onUpdate(updated); setNotice("답변 평가·정정을 저장했습니다.");
      })}>평가·정정 저장</button>
      {notice && <p role="status">{notice}</p>}
    </details>}
    {!confirmDelete ? <button className="text-button danger" onClick={() => setConfirmDelete(true)}>이 상담 기록 삭제</button> : <div className="notice-card"><p>이 질문·답변과 평가 이력을 DB에서 삭제합니다.</p><button className="danger" onClick={() => void work("상담 기록을 삭제하고 있어요…", async () => { await api(`${path}?revision=${message.revision}`, "DELETE"); onDelete(); })}>삭제 확인</button><button onClick={() => setConfirmDelete(false)}>취소</button></div>}
  </div>;
}

interface EvaluationExport { messages: Message[]; by_model: Record<string, { answers: number; rated: number; helpful: number; unhelpful: number; verified_corrections: number }>; notice: string }
export function CounselingEvaluation({ profileId, work }: { profileId: string; work: (label: string, action: () => Promise<void>) => Promise<void> }) {
  const [summary, setSummary] = useState<EvaluationExport | null>(null);
  return <details className="counseling-evaluation"><summary>상담 평가 현황·기록 다운로드</summary>
    <p className="muted">같은 질문의 원답변·정정·다음 답변을 대조할 수 있습니다. 평가 비율만으로 정확도나 성능 향상을 판단하지 않습니다.</p>
    <div className="button-row"><button onClick={() => void work("상담 평가 현황을 읽고 있어요…", async () => setSummary(await api<EvaluationExport>(`/profiles/${profileId}/chat-export`)))}>평가 현황 보기</button>
      <button onClick={() => void work("상담 기록을 내보내고 있어요…", async () => {
        const data = await api<EvaluationExport>(`/profiles/${profileId}/chat-export`); setSummary(data);
        const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
        const link = document.createElement("a"); link.href = url; link.download = "path-counseling.json"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      })}>상담·평가 JSON 다운로드</button></div>
    {summary && <><p>저장된 상담 {summary.messages.length}개</p><div className="table-scroll"><table><thead><tr><th>모델</th><th>답변</th><th>평가됨</th><th>도움 됨</th><th>개선 필요</th><th>대조한 정정</th></tr></thead><tbody>{Object.entries(summary.by_model).map(([model, s]) => <tr key={model}><td>{model}</td><td>{s.answers}</td><td>{s.rated}</td><td>{s.helpful}</td><td>{s.unhelpful}</td><td>{s.verified_corrections}</td></tr>)}</tbody></table></div></>}
    <p className="muted">다운로드에는 질문·답변·정정 메모가 포함됩니다. 별도로 저장한 파일은 앱에서 기록을 삭제해도 남습니다.</p>
  </details>;
}
