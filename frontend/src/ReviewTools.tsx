import { useEffect, useState } from "react";
import { api } from "./api";
import type { Input } from "./types";

type Work = (name: string, action: () => Promise<void>) => Promise<void>;
function download(raw: Blob, name: string) {
  const url = URL.createObjectURL(raw);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function ExportTools({
  data,
  restore,
  work,
}: {
  data: Input;
  restore: (data: Input) => void;
  work: Work;
}) {
  const [preview, setPreview] = useState<{
    data: Input;
    warnings: string[];
  } | null>(null);
  async function exportFile(kind: string) {
    await work("다운로드 파일을 만들고 있어요…", async () => {
      if (kind === "backup") {
        const r = await api("/export/backup", "POST", data);
        download(
          new Blob([JSON.stringify(r, null, 2)], { type: "application/json" }),
          "path-backup.json",
        );
        return;
      }
      const r = await fetch(`/api/export/${kind}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Planner-Request": "1",
        },
        body: JSON.stringify(data),
        signal: AbortSignal.timeout(65000),
      });
      if (!r.ok) {
        const e = await r.json();
        throw new Error(e.detail || "다운로드 실패");
      }
      download(
        await r.blob(),
        kind === "csv" ? "transcript.csv" : "graduation-report.html",
      );
    });
  }
  return (
    <section className="panel">
      <h2>보고서와 전체 입력 백업</h2>
      <p>
        보고서는 서버에서 다시 계산합니다. HTML을 열어 인쇄 메뉴에서 PDF로
        저장할 수 있습니다. 백업에는 성적과 개인 메모가 포함되므로 보관에
        유의하세요.
      </p>
      <div className="button-row">
        <button onClick={() => void exportFile("report")}>
          점검 보고서 다운로드
        </button>
        <button onClick={() => void exportFile("csv")}>이수 과목 CSV</button>
        <button onClick={() => void exportFile("backup")}>
          전체 입력 JSON 백업
        </button>
      </div>
      <label>
        전체 백업 불러오기 (웹앱 또는 기존 Streamlit v2)
        <input
          type="file"
          accept=".json"
          onChange={(e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            setPreview(null);
            if (f)
              void work("백업을 검증하고 있어요…", async () => {
                if (f.size > 2_000_000)
                  throw new Error("2MB 이하 JSON만 가능합니다.");
                setPreview(
                  await api("/import/backup", "POST", { text: await f.text() }),
                );
              });
          }}
        />
      </label>
      {preview && (
        <div className="notice-card">
          <p>
            {preview.data.profile.track}과정 · {preview.data.attempts.length}
            과목 · 체크리스트 {preview.data.checklist?.length ?? 0}개
          </p>
          {preview.warnings.map((w) => (
            <p key={w}>{w}</p>
          ))}
          <p>
            현재 입력 전체를 이 백업으로 교체합니다. DB 저장은 별도로 해야
            합니다.
          </p>
          <button
            onClick={() => {
              restore(preview.data);
              setPreview(null);
            }}
          >
            확인 후 현재 입력 교체
          </button>
          <button onClick={() => setPreview(null)}>취소</button>
        </div>
      )}
    </section>
  );
}
interface RecordItem {
  admission_year: number | null;
  id?: string;
  created_at?: string;
  kind: string;
  case_label: string;
  track: "심화" | "일반";
  expected: string;
  observed: string;
  evidence: string;
  verified: boolean;
  passed: boolean | null;
  seconds: number | null;
  rating: number | null;
}
interface Evaluation {
  synthetic: {
    total: number;
    passed: number;
    notice: string;
    results: {
      scenario: string;
      expected: unknown;
      actual: unknown;
      passed: boolean;
    }[];
  };
  records: RecordItem[];
}
const empty: RecordItem = {
  admission_year: null,
  kind: "규정 대조",
  case_label: "",
  track: "심화",
  expected: "",
  observed: "",
  evidence: "",
  verified: false,
  passed: null,
  seconds: null,
  rating: null,
};
export default function ReviewTools({
  work,
  years,
}: {
  work: Work;
  years: number[];
}) {
  const [sources, setSources] = useState<{
    status: string;
    reviewed_on: string;
    notes: string[];
    sources: { title: string; sha256: string }[];
  } | null>(null);
  const [evaluations, setEvaluations] = useState<Evaluation | null>(null);
  const [draft, setDraft] = useState<RecordItem>(empty);
  const [start, setStart] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  useEffect(() => {
    void work("검증 자료를 확인하고 있어요…", async () => {
      const [s, e] = await Promise.all([
        api<typeof sources>("/sources"),
        api<Evaluation>("/evaluations"),
      ]);
      setSources(s);
      setEvaluations(e);
    });
  }, []);
  const verified = evaluations?.records.filter((r) => r.verified) ?? [];
  return (
    <>
      <section className="panel">
        <h2>규정·자료 검토 상태</h2>
        {sources && (
          <>
            <p>
              <span className="tag amber">{sources.status}</span> · 검토{" "}
              {sources.reviewed_on}
            </p>
            <ul>
              {sources.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
            <details>
              <summary>원본 추적 정보</summary>
              {sources.sources.map((s) => (
                <p key={s.sha256}>
                  <b>{s.title}</b>
                  <small className="hash-text">SHA-256 {s.sha256}</small>
                </p>
              ))}
            </details>
          </>
        )}
      </section>
      <section className="panel">
        <h2>구현 검증과 실제 평가</h2>
        <p>
          합성 테스트 통과율과 실제 졸업판정 정확도는 다른 지표입니다. 실제
          학생·학교 기준 대조와 사용자 평가는 근거를 직접 기록해야 합니다.
        </p>
        {evaluations && (
          <>
            <div className="comparison-grid">
              <article className="semester-card">
                <h3>합성 시나리오</h3>
                <strong>
                  {evaluations.synthetic.passed} / {evaluations.synthetic.total}
                </strong>
                <p>{evaluations.synthetic.notice}</p>
              </article>
              <article className="semester-card">
                <h3>근거가 기록된 평가</h3>
                <strong>{verified.length}건</strong>
                <p>
                  {verified.length
                    ? `${verified.filter((r) => r.passed).length}건 통과 · 기록된 사례에 한정`
                    : "실제 학교 대조·사용자 평가 미실시"}
                </p>
              </article>
            </div>
            <details>
              <summary>합성 사례의 기대값과 실제값</summary>
              {evaluations.synthetic.results.map((r) => (
                <p key={r.scenario}>
                  {r.passed ? "통과" : "실패"} · {r.scenario}
                  <small>
                    기대 {JSON.stringify(r.expected)} / 실제{" "}
                    {JSON.stringify(r.actual)}
                  </small>
                </p>
              ))}
            </details>
          </>
        )}
        <h3>평가 기록 추가</h3>
        <p>
          이름·학번 대신 익명 사례 번호를 사용하세요. 학교 기준 대조는
          문서명·페이지 또는 확인 일자를 근거에 적어 주세요.
        </p>
        <div className="form-grid">
          <label>
            평가 대상 입학연도
            <select
              value={draft.admission_year ?? ""}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  admission_year: e.target.value
                    ? Number(e.target.value)
                    : null,
                })
              }
            >
              <option value="">미지정</option>
              {years.map((year) => (
                <option key={year} value={year}>
                  {year}학번
                </option>
              ))}
            </select>
          </label>
          <label>
            평가 종류
            <select
              value={draft.kind}
              onChange={(e) => setDraft({ ...draft, kind: e.target.value })}
            >
              {["규정 대조", "LLM 답변", "사용성"].map((k) => (
                <option key={k}>{k}</option>
              ))}
            </select>
          </label>
          <label>
            익명 사례 번호
            <input
              value={draft.case_label}
              maxLength={80}
              onChange={(e) =>
                setDraft({ ...draft, case_label: e.target.value })
              }
            />
          </label>
          <label>
            과정
            <select
              value={draft.track}
              onChange={(e) =>
                setDraft({ ...draft, track: e.target.value as "심화" | "일반" })
              }
            >
              <option>심화</option>
              <option>일반</option>
            </select>
          </label>
          {(["expected", "observed", "evidence"] as const).map((k, i) => (
            <label key={k}>
              {["기대 결과·평가 기준", "실제 결과", "확인 근거·문서·일자"][i]}
              <textarea
                rows={3}
                maxLength={k === "evidence" ? 500 : 2000}
                value={draft[k]}
                onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}
              />
            </label>
          ))}
          <label>
            판정
            <select
              value={draft.passed === null ? "" : String(draft.passed)}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  passed:
                    e.target.value === "" ? null : e.target.value === "true",
                })
              }
            >
              <option value="">미평가</option>
              <option value="true">통과</option>
              <option value="false">실패</option>
            </select>
          </label>
          <label>
            소요 시간 (초)
            <input
              type="number"
              min={0}
              max={86400}
              value={draft.seconds ?? ""}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  seconds: e.target.value ? Number(e.target.value) : null,
                })
              }
            />
          </label>
          <label>
            사용 만족도 (1~5)
            <input
              type="number"
              min={1}
              max={5}
              value={draft.rating ?? ""}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  rating: e.target.value ? Number(e.target.value) : null,
                })
              }
            />
          </label>
        </div>
        <div className="button-row">
          <button onClick={() => setStart(performance.now())}>측정 시작</button>
          <button
            disabled={start === null}
            onClick={() => {
              setDraft({
                ...draft,
                seconds: Math.round((performance.now() - start!) / 1000),
              });
              setStart(null);
            }}
          >
            측정 종료
          </button>
          {start !== null && (
            <span role="status">측정 중 · 과제 완료 후 종료하세요</span>
          )}
        </div>
        <label className="check-label">
          <input
            type="checkbox"
            checked={draft.verified}
            onChange={(e) => setDraft({ ...draft, verified: e.target.checked })}
          />
          기대·실제·근거를 대조하여 검증 완료로 기록
        </label>
        <button
          className="primary"
          onClick={() =>
            void work("평가 기록을 저장하고 있어요…", async () => {
              await api("/evaluations", "POST", draft);
              setEvaluations(await api("/evaluations"));
              setDraft(empty);
              setMessage("평가 기록을 저장했습니다.");
            })
          }
        >
          평가 저장
        </button>
        {message && <p role="status">{message}</p>}
        <h3>기록 목록</h3>
        {evaluations?.records.map((r) => (
          <article className="evidence-item" key={r.id}>
            <b>
              {r.case_label} ·{" "}
              {r.admission_year ? `${r.admission_year}학번` : "학번 미지정"} ·{" "}
              {r.kind} · {r.track}
            </b>
            <p>
              {r.verified ? "근거 대조 완료" : "작성 중"} ·{" "}
              {r.passed === null ? "미평가" : r.passed ? "통과" : "실패"} ·{" "}
              {r.seconds ?? "—"}초
            </p>
            <p>
              기대: {r.expected}
              <br />
              실제: {r.observed}
              <br />
              근거: {r.evidence}
            </p>
            <button
              onClick={() => {
                if (window.confirm("이 평가 기록을 삭제할까요?"))
                  void work("평가 기록을 삭제하고 있어요…", async () => {
                    await api(`/evaluations/${r.id}`, "DELETE");
                    setEvaluations(await api("/evaluations"));
                  });
              }}
            >
              삭제
            </button>
          </article>
        ))}
        <button
          onClick={() =>
            download(
              new Blob([JSON.stringify(evaluations, null, 2)], {
                type: "application/json",
              }),
              "path-evaluation.json",
            )
          }
        >
          평가 결과 JSON 다운로드
        </button>
      </section>
    </>
  );
}
