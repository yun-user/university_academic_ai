import { useEffect, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  ChevronRight,
  Compass,
  Database,
  Download,
  FileText,
  Flag,
  LayoutDashboard,
  LoaderCircle,
  Map,
  MessageCircle,
  Plus,
  Save,
  Send,
  ShieldCheck,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import { api } from "./api";
import CourseEditor from "./CourseEditor";
import ClassificationReview from "./ClassificationReview";
import CohortSummary from "./CohortSummary";
import {
  PlanControls,
  CandidateTools,
  SubstitutionTools,
  Checklist,
  EvidenceList,
} from "./PlanningTools";
import ReviewTools, { ExportTools } from "./ReviewTools";
import type {
  Analysis,
  Attempt,
  Bootstrap,
  Check,
  ChatReply,
  History,
  Input,
  Message,
  Profile,
  Saved,
  SavedSummary,
} from "./types";

const tabs = [
  { id: "overview", label: "나의 졸업 현황", icon: LayoutDashboard },
  { id: "courses", label: "이수 과목", icon: BookOpen },
  { id: "roadmap", label: "학기별 로드맵", icon: Map },
  { id: "advisor", label: "AI 졸업 상담", icon: MessageCircle },
  { id: "saved", label: "저장한 계획", icon: Database },
  { id: "review", label: "규정과 평가", icon: ShieldCheck },
];
const manualFields = [
  ["thesis", "졸업논문·졸업작품"],
  ["english", "어학 인정·제출 및 적용 확인"],
  ["specialized_course", "특성화교양 지정과목"],
  ["basic_english_course", "전공기초영어 지정과목"],
  ["sw_data_course", "SW·데이터 과목·중복인정 확인 (2022학번부터)"],
  ["science_course", "학과 과학 지정과목 확인 (2021학번 이후 심화)"],
  ["design_sequence", "설계 이수순서 (심화)"],
  ["recognized_course_scope", "교양·MSC 인정 범위 (심화)"],
  ["general_approval", "일반과정 변경 승인"],
] as const;
const number = (n: number | undefined) =>
  n === undefined ? "—" : n.toLocaleString("ko-KR");
const date = (s: string) =>
  new Date(s).toLocaleString("ko-KR", {
    dateStyle: "short",
    timeStyle: "short",
  });

function Progress({ check }: { check: Check }) {
  return (
    <div className="progress-item">
      <div>
        <span>{check.key}</span>
        <span>
          <b>{number(check.current)}</b> / {number(check.required)}
        </span>
      </div>
      <div className="progress-track">
        <span
          style={{
            width: `${Math.min(100, (check.current / Math.max(check.required, 1)) * 100)}%`,
          }}
        />
      </div>
    </div>
  );
}
function CheckList({ checks }: { checks: Check[] }) {
  return (
    <div className="check-list">
      {checks.map((c) => (
        <div key={c.key} className="check-row">
          <div>
            <b>{c.key}</b>
            <small>{c.detail}</small>
          </div>
          <span
            className={`tag ${c.status === "충족" ? "green" : c.status === "확인 필요" ? "neutral" : "amber"}`}
          >
            {c.status}
            {c.status === "미충족" && c.required > 1
              ? ` · ${c.missing} 부족`
              : ""}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function App() {
  const [config, setConfig] = useState<Bootstrap | null>(null);
  const [data, setData] = useState<Input | null>(null);
  const [tab, setTab] = useState("overview");
  const [result, setResult] = useState<Analysis | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [consent, setConsent] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [records, setRecords] = useState<SavedSummary[]>([]);
  const [selected, setSelected] = useState<{
    id: string;
    revision: number;
  } | null>(null);
  const [label, setLabel] = useState("나의 졸업 준비");
  const [dirty, setDirty] = useState(false);
  const [history, setHistory] = useState<History[]>([]);
  const [paste, setPaste] = useState("");
  const [imported, setImported] = useState<{
    attempts: Attempt[];
    warnings: string[];
  } | null>(null);
  const [importConfirmed, setImportConfirmed] = useState(false);
  const [catalogSearch, setCatalogSearch] = useState("");
  const [pendingAction, setPendingAction] = useState<{
    text: string;
    run: () => Promise<void>;
  } | null>(null);

  useEffect(() => {
    Promise.all([
      api<Bootstrap>("/bootstrap"),
      api<SavedSummary[]>("/profiles"),
    ])
      .then(([c, list]) => {
        setConfig(c);
        setData({
          attempts: [],
          profile: c.profile,
          options: c.options,
          goal: "",
        });
        setRecords(list);
      })
      .catch(() =>
        setError(
          "앱을 시작할 수 없습니다. 백엔드 서버가 실행 중인지 확인하고 페이지를 새로고침해 주세요.",
        ),
      );
  }, []);
  useEffect(() => {
    const leave = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", leave);
    return () => window.removeEventListener("beforeunload", leave);
  }, [dirty]);
  async function work(name: string, action: () => Promise<void>) {
    setBusy(name);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "요청 처리 중 문제가 발생했습니다.",
      );
    } finally {
      setBusy("");
    }
  }
  function change(patch: Partial<Input>) {
    if (!data) return;
    setData({ ...data, ...patch });
    setResult(null);
    setMessages([]);
    setQuestion("");
    setConsent(false);
    setDirty(true);
    setNotice("");
  }
  async function changeScope(admission_year: number, track: Profile["track"]) {
    if (!data) return;
    setImported(null);
    setImportConfirmed(false);
    const profile = {
      ...data.profile,
      admission_year,
      track,
      required_list_checked: false,
      substitutions: data.profile.substitutions.map((s) => ({
        ...s,
        confirmed: false,
      })),
    };
    for (const [key] of manualFields) profile[key] = "확인 필요";
    await apply({ profile, placements: null });
    setNotice(
      `${admission_year}학번 ${track}과정으로 기준을 바꾸었습니다. 이수내역은 유지하며 승인 상태·대체인정은 다시 확인해 주세요. 수동 배치는 자동 계획으로 전환했습니다.`,
    );
  }
  async function apply(patch: Partial<Input>) {
    if (!data) return;
    const next = { ...data, ...patch };
    change(patch);
    await analyze(false, next);
  }
  function restoreBackup(next: Input) {
    change(next);
    setSelected(null);
    setHistory([]);
    setLabel("복원한 계획");
    setImported(null);
    setPaste("");
  }
  function guard(text: string, action: () => Promise<void>) {
    if (dirty) setPendingAction({ text, run: action });
    else void action();
  }
  async function analyze(llm = false, input = data) {
    if (!input) return;
    await work(
      llm ? "AI가 수강 방향을 정리하고 있어요…" : "졸업요건을 계산하고 있어요…",
      async () => {
        setResult(
          await api<Analysis>("/analysis", "POST", {
            ...input,
            consent: llm && consent,
          }),
        );
      },
    );
  }
  async function demo() {
    if (!data) return;
    await work("예시 과목을 불러오고 있어요…", async () => {
      const demo = await api<{ attempts: Attempt[] }>(
        `/demo?admission_year=${data.profile.admission_year}`,
      );
      const next = { ...data, ...demo, placements: null };
      change({ ...demo, placements: null });
      setSelected(null);
      setLabel("시연용 예시");
      setHistory([]);
      setResult(await api<Analysis>("/analysis", "POST", next));
      setNotice(
        "실제 학생과 관계없는 예시 8과목을 불러왔습니다. DB 저장 전까지는 이 화면에서만 사용합니다.",
      );
    });
  }
  async function save(copy = false) {
    if (!data) return;
    await work("이수 내역과 계획을 저장하고 있어요…", async () => {
      const target = copy ? null : selected;
      const saved = await api<Saved>(
        target ? `/profiles/${target.id}` : "/profiles",
        target ? "PUT" : "POST",
        { ...data, label, revision: target?.revision ?? null },
      );
      setSelected({ id: saved.id, revision: saved.revision });
      setDirty(false);
      setRecords(await api<SavedSummary[]>("/profiles"));
      setHistory(await api<History[]>(`/profiles/${saved.id}/history`));
      setNotice(
        `“${saved.label}” 저장 완료 · 버전 ${saved.revision}. DB에는 입력과 기본 계산 결과가 저장됩니다.`,
      );
    });
  }
  async function load(id: string) {
    await work("저장한 계획을 불러오고 있어요…", async () => {
      const saved = await api<Saved>(`/profiles/${id}`);
      const next = {
        attempts: saved.attempts,
        profile: saved.profile,
        options: saved.options,
        goal: saved.goal,
        candidates: saved.candidates ?? null,
        placements: saved.placements ?? null,
        checklist: saved.checklist ?? [],
      };
      setData(next);
      setLabel(saved.label);
      setSelected({ id: saved.id, revision: saved.revision });
      setDirty(false);
      setResult(null);
      setMessages([]);
      setQuestion("");
      setConsent(false);
      setImported(null);
      setPaste("");
      setHistory(await api<History[]>(`/profiles/${id}/history`));
      setResult(await api<Analysis>("/analysis", "POST", next));
      setTab("overview");
      setNotice(
        "저장한 이수 내역을 불러와 현재 규정 자료로 다시 계산했습니다.",
      );
    });
  }
  async function remove(record: SavedSummary) {
    await work("저장 항목을 삭제하고 있어요…", async () => {
      await api(`/profiles/${record.id}?revision=${record.revision}`, "DELETE");
      setRecords(await api<SavedSummary[]>("/profiles"));
      if (selected?.id === record.id) {
        setSelected(null);
        setHistory([]);
        setDirty(true);
      }
      setNotice(
        "DB의 해당 항목, 이수 내역과 계획 기록을 삭제했습니다. 현재 편집 화면은 유지됩니다.",
      );
    });
  }
  async function ask() {
    if (!data || !question.trim() || !consent) return;
    const asked = question.trim();
    await work("AI가 현재 이수 상태를 확인하고 있어요…", async () => {
      const reply = await api<ChatReply>("/chat", "POST", {
        ...data,
        question: asked,
        consent,
        history: messages
          .filter((m) => m.mode === "llm")
          .slice(-6)
          .map((m) => ({ question: m.question, answer: m.answer })),
      });
      setMessages([...messages, { ...reply, question: asked }]);
      setQuestion("");
    });
  }
  async function importText(kind: string, text: string) {
    await work("성적표를 읽고 있어요…", async () => {
      setImported(await api(`/import/${kind}`, "POST", { text, profile: data?.profile }));
      setImportConfirmed(false);
      setPaste("");
    });
  }
  if (!config || !data)
    return (
      <div className="loading-screen">
        <Compass size={42} />
        <h1>PATH</h1>
        <p role="status">{error || "나의 졸업 로드맵을 준비하고 있어요…"}</p>
      </div>
    );
  const total = result?.audit.checks.find((c) => c.key === "총 졸업인정학점");
  const unresolvedCount = result?.audit.checks.filter(
    (c) => c.status !== "충족",
  ).length;
  const unknown = data.attempts.filter((a) => a.category === "미확인").length;
  const nextSemester = result?.roadmap.semesters.find((s) => s.courses.length);
  const validConsensus = consent && config.llm.configured;
  const aiConsent = (
    <div className="consent-card">
      <ShieldCheck size={21} />
      <div>
        <b>AI 상담에 사용할 정보</b>
        <p>
          OpenAI로 과목 코드·이수 시기·요건 계산값·희망 사항·질문과 최근 대화
          6개를 보냅니다. 성적 등급과 학교 계정 정보는 보내지 않습니다. 질문에
          이름·학번·비밀번호를 쓰지 마세요.
        </p>
        <label className="check-label">
          <input
            type="checkbox"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
          />{" "}
          위 정보를 보내는 데 동의합니다.
        </label>
        <small>
          입력을 변경하거나 계획을 불러오면 동의가 해제됩니다.{" "}
          {config.llm.configured
            ? `사용 모델: ${config.llm.model}`
            : "서버의 API 키와 모델 설정이 필요합니다."}
        </small>
      </div>
    </div>
  );

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setTab("overview");
          }}
        >
          <span className="brand-icon">
            <Compass size={24} />
          </span>{" "}
          PATH<span className="brand-dot">.</span>
        </a>
        <div className="brand-caption">나의 다음 학기를 설계하다</div>
        <div className="nav-label">MY GRADUATION</div>
        <nav aria-label="주 메뉴">
          {tabs.map((t) => (
            <button
              key={t.id}
              className={tab === t.id ? "nav-item active" : "nav-item"}
              aria-current={tab === t.id ? "page" : undefined}
              onClick={() => setTab(t.id)}
            >
              <t.icon size={19} />
              {t.label}
              {t.id === "courses" && <span>{data.attempts.length}</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-note">
          <Flag size={20} />
          <strong>한 학기씩, 더 가까이.</strong>
          <p>
            이수 현황을 확인하고
            <br />
            나에게 맞는 다음 학기를 준비하세요.
          </p>
          <button
            disabled={Boolean(busy)}
            onClick={() =>
              guard(
                "현재 입력을 예시 과목으로 바꿀까요? 저장하지 않은 수정은 사라집니다.",
                demo,
              )
            }
          >
            예시로 둘러보기 <ArrowRight size={15} />
          </button>
        </div>
        <div className="school-label">
          홍익대학교 세종캠퍼스
          <small>소프트웨어융합학과 · {data.profile.admission_year}학번</small>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            마이 캠퍼스 <ChevronRight size={14} />{" "}
            <b>{tabs.find((t) => t.id === tab)?.label}</b>
          </div>
          <div className="topbar-right">
            <span className="save-state">
              <i className={dirty ? "dirty" : ""} />
              {dirty
                ? "저장하지 않은 변경"
                : selected
                  ? "DB 저장됨"
                  : "새 계획"}
            </span>
            <button className="secondary small" onClick={() => setTab("saved")}>
              <Save size={15} /> 저장 관리
            </button>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                {data.profile.admission_year} COHORT <span />{" "}
                {data.profile.track === "심화"
                  ? "ENGINEERING TRACK"
                  : "GENERAL TRACK"}
              </div>
              <h1>
                {tab === "overview" ? (
                  <>
                    졸업까지의 길을,
                    <br />
                    한눈에.
                  </>
                ) : (
                  tabs.find((t) => t.id === tab)?.label
                )}
              </h1>
              <p>
                {tab === "overview"
                  ? "지금까지의 이수를 돌아보고, 앞으로의 학기를 계획하세요."
                  : {
                      courses:
                        "이수 내역을 확인할수록, 로드맵은 더 정확해집니다.",
                      roadmap: "학점과 개설 조건을 고려한 나의 다음 학기.",
                      advisor:
                        "나의 이수 상태를 아는 AI에게 다음 단계를 물어보세요.",
                      saved: "이수 내역과 계획을 이 컴퓨터에 보관합니다.",
                    }[tab]}
              </p>
            </div>
            <span className="scope-tag">
              <ShieldCheck size={15} /> 참고 계산 · 학교 최종 확인 필요
            </span>
          </div>
          <div aria-live="polite">
            {error && (
              <div role="alert" className="banner error">
                {error}
                <button aria-label="오류 닫기" onClick={() => setError("")}>
                  <X size={17} />
                </button>
              </div>
            )}
            {notice && (
              <div className="banner success">
                {notice}
                <button aria-label="안내 닫기" onClick={() => setNotice("")}>
                  <X size={17} />
                </button>
              </div>
            )}
            {busy && (
              <div className="banner busy">
                <LoaderCircle size={18} className="spin" />
                {busy}
              </div>
            )}
          </div>
          <fieldset className="workspace" disabled={Boolean(busy)}>
            {tab === "overview" && (
              <>
                <CohortSummary
                  config={config}
                  profile={data.profile}
                  onChange={changeScope}
                />
                <div className="stats">
                  <div className="stat-card featured">
                    <span>현재 졸업인정학점</span>
                    <div>
                      <strong>{number(total?.current)}</strong>
                      <small>/ {number(total?.required)} 학점</small>
                    </div>
                    <p>
                      {result
                        ? "인정된 과목만 합산했어요"
                        : "과목 입력 후 계산해 주세요"}
                    </p>
                    <div className="stat-graphic">
                      <Compass size={85} />
                    </div>
                  </div>
                  <div className="stat-card">
                    <span>남은 학점</span>
                    <div>
                      <strong>{number(total?.missing)}</strong>
                      <small>학점</small>
                    </div>
                    <p>총학점 외 세부 요건도 확인하세요</p>
                  </div>
                  <div className="stat-card">
                    <span>확인이 필요한 과목</span>
                    <div>
                      <strong>{unknown}</strong>
                      <small>과목</small>
                    </div>
                    <button
                      className="text-button"
                      onClick={() => setTab("courses")}
                    >
                      이수구분 확인하기 <ArrowRight size={14} />
                    </button>
                  </div>
                </div>
                <div className="dashboard-grid">
                  <section className="panel">
                    <div className="section-heading">
                      <div>
                        <span className="eyebrow">CREDIT CHECK</span>
                        <h2>어디까지 왔을까요?</h2>
                      </div>
                      <button
                        className="text-button"
                        onClick={() => void analyze()}
                      >
                        현황 계산 <ArrowRight size={16} />
                      </button>
                    </div>
                    {result ? (
                      <>
                        {result.audit.checks
                          .filter((c) =>
                            [
                              "전공",
                              "전문교양",
                              "MSC 합계",
                              "설계 인정학점",
                            ].includes(c.key),
                          )
                          .map((c) => (
                            <Progress key={c.key} check={c} />
                          ))}
                        <div className="soft-note">
                          부족하거나 확인이 필요한 요건{" "}
                          <b>{unresolvedCount}개</b>
                          <small>
                            학점 충족만으로 졸업이 확정되지는 않아요.
                          </small>
                        </div>
                      </>
                    ) : (
                      <div className="empty">
                        <BookOpen size={34} />
                        <h3>나의 과목부터 시작해요</h3>
                        <p>
                          과목을 입력하거나 예시를 불러오면
                          <br />
                          여기에서 학점 현황을 볼 수 있어요.
                        </p>
                        <button
                          className="primary"
                          onClick={() => setTab("courses")}
                        >
                          이수 과목 입력 <ArrowRight size={16} />
                        </button>
                      </div>
                    )}
                  </section>
                  <section className="panel next-panel">
                    <span className="eyebrow">YOUR NEXT STEP</span>
                    <h2>다음 학기의 첫걸음</h2>
                    {nextSemester ? (
                      <>
                        <div className="semester-label">
                          {nextSemester.year}년 {nextSemester.term}학기{" "}
                          <span>{nextSemester.credits}학점</span>
                        </div>
                        {nextSemester.courses.slice(0, 3).map((c, i) => (
                          <div className="preview-course" key={c.code}>
                            <span>0{i + 1}</span>
                            <div>
                              <b>{c.name}</b>
                              <small>
                                {c.code} · {c.credits}학점
                              </small>
                            </div>
                          </div>
                        ))}
                        <button
                          className="primary full"
                          onClick={() => setTab("roadmap")}
                        >
                          전체 로드맵 보기 <ArrowRight size={16} />
                        </button>
                      </>
                    ) : (
                      <div className="empty">
                        <Map size={38} />
                        <p>
                          졸업요건을 계산하면
                          <br />
                          학기별 추천 과목이 나타나요.
                        </p>
                      </div>
                    )}
                  </section>
                </div>
                <div className="advisor-callout">
                  <span className="ai-orb">
                    <Sparkles size={23} />
                  </span>
                  <div>
                    <h3>“다음 학기에 무엇부터 들으면 좋을까요?”</h3>
                    <p>현재 학점과 진로 관심사를 바탕으로 AI에게 물어보세요.</p>
                  </div>
                  <button
                    className="secondary"
                    onClick={() => setTab("advisor")}
                  >
                    AI 상담 시작 <ArrowRight size={16} />
                  </button>
                </div>
                <section className="panel settings-panel">
                  <div className="section-heading">
                    <h2>나의 계획 조건</h2>
                    <span className="muted">
                      {data.profile.admission_year}학번 · 단일전공 신입학
                    </span>
                  </div>
                  <div className="form-grid">
                    <label>
                      계획 시작 연도
                      <input
                        type="number"
                        min={2018}
                        max={2100}
                        aria-label="계획 시작 연도"
                        aria-describedby="plan-start-year-help"
                        aria-invalid={!Number.isInteger(data.options.start_year) || data.options.start_year < 2018 || data.options.start_year > 2100}
                        value={data.options.start_year}
                        onChange={(e) =>
                          change({
                            options: {
                              ...data.options,
                              start_year: Number(e.target.value),
                            },
                          })
                        }
                      />
                      <small id="plan-start-year-help" className="muted">
                        로드맵을 시작할 연도입니다. 입학연도와 별도로 2018~2100 사이의 정수를 입력하세요. 이수 내역이 있다면 마지막 취득 학기 다음부터 계획합니다.
                      </small>
                    </label>
                    <label>
                      계획 시작 학기
                      <select
                        value={data.options.start_term}
                        onChange={(e) =>
                          change({
                            options: {
                              ...data.options,
                              start_term: Number(e.target.value),
                            },
                          })
                        }
                      >
                        <option value={1}>1학기</option>
                        <option value={2}>2학기</option>
                      </select>
                    </label>
                    <label>
                      계획 학기 수
                      <input
                        type="number"
                        min={1}
                        max={12}
                        value={data.options.semesters}
                        onChange={(e) =>
                          change({
                            options: {
                              ...data.options,
                              semesters: Math.min(
                                12,
                                Math.max(1, Number(e.target.value) || 1),
                              ),
                              semester_limits: [],
                            },
                          })
                        }
                      />
                    </label>
                    <label>
                      학기당 최대 학점
                      <input
                        type="number"
                        min={1}
                        max={30}
                        value={data.options.credit_limit}
                        onChange={(e) =>
                          change({
                            options: {
                              ...data.options,
                              credit_limit: Number(e.target.value),
                              semester_limits: [],
                            },
                          })
                        }
                      />
                    </label>
                  </div>
                  <label className="check-label">
                    <input
                      type="checkbox"
                      checked={data.options.assume_in_progress_passed}
                      onChange={(e) =>
                        change({
                          options: {
                            ...data.options,
                            assume_in_progress_passed: e.target.checked,
                          },
                        })
                      }
                    />{" "}
                    계획에서 현재 수강 중인 과목의 통과를 가정합니다.
                  </label>
                  <details>
                    <summary>필수과목·제출·승인 상태 입력</summary>
                    <p className="muted">
                      학교에서 확인한 항목만 ‘충족’으로 표시하세요. 과정 선택
                      자체가 변경 승인을 의미하지는 않습니다.
                    </p>
                    <label>
                      학교에서 확인한 개인 필수 학수번호 (쉼표 구분)
                      <input
                        value={data.profile.required_codes.join(",")}
                        onChange={(e) =>
                          change({
                            profile: {
                              ...data.profile,
                              required_codes: e.target.value.split(","),
                            },
                          })
                        }
                      />
                    </label>
                    <label className="check-label">
                      <input
                        type="checkbox"
                        checked={data.profile.required_list_checked}
                        onChange={(e) =>
                          change({
                            profile: {
                              ...data.profile,
                              required_list_checked: e.target.checked,
                            },
                          })
                        }
                      />{" "}
                      학교 기준으로 개인 필수목록을 확인했습니다.
                    </label>
                    <div className="form-grid">
                      {manualFields
                        .filter(
                          ([key]) =>
                            (key !== "specialized_course" ||
                              data.profile.admission_year >= 2019) &&
                            (key !== "sw_data_course" ||
                              data.profile.admission_year >= 2022) &&
                            (key !== "science_course" ||
                              (data.profile.admission_year >= 2021 &&
                                data.profile.track === "심화")),
                        )
                        .map(([key, text]) => (
                          <label key={key}>
                            {text}
                            <select
                              value={data.profile[key]}
                              onChange={(e) =>
                                change({
                                  profile: {
                                    ...data.profile,
                                    [key]: e.target.value,
                                  },
                                })
                              }
                            >
                              {["확인 필요", "미충족", "충족"].map((x) => (
                                <option key={x}>{x}</option>
                              ))}
                            </select>
                          </label>
                        ))}
                    </div>
                  </details>
                  <button className="primary" onClick={() => void analyze()}>
                    조건 적용하고 계산 <ArrowRight size={16} />
                  </button>
                </section>
                {result && (
                  <section className="panel">
                    <h2>전체 졸업요건 점검</h2>
                    <CheckList checks={result.audit.checks} />
                  </section>
                )}
              </>
            )}
            {tab === "courses" && (
              <>
                <SubstitutionTools data={data} change={change} />
                <section className="panel">
                  <div className="section-heading">
                    <h2>성적표 가져오기</h2>
                    <a
                      className="text-button"
                      href="/api/transcript/template"
                      download
                    >
                      <Download size={16} /> CSV 예시 양식
                    </a>
                  </div>
                  <p className="muted">
                    학교에서 직접 로그인한 뒤 전체성적조회 표를 복사해
                    붙여넣으세요. 학교 비밀번호는 입력하지 않습니다.
                  </p>
                  <div className="import-actions">
                    <a
                      href="https://cn.hongik.ac.kr/stud/"
                      target="_blank"
                      rel="noreferrer"
                      className="secondary"
                    >
                      <BookOpen size={16} /> 클래스넷 열기
                    </a>
                    <label className="secondary upload-label">
                      <Upload size={16} /> CSV 업로드
                      <input
                        type="file"
                        accept=".csv"
                        onChange={(e) => {
                          const file = e.target.files?.[0];
                          e.target.value = "";
                          if (!file) return;
                          if (file.size > 1_000_000) {
                            setError("CSV는 1MB 이하만 가져올 수 있습니다.");
                            return;
                          }
                          void work("CSV를 읽고 있어요…", async () => {
                            const bytes = await file.arrayBuffer();
                            let text;
                            try {
                              text = new TextDecoder("utf-8", {
                                fatal: true,
                              }).decode(bytes);
                            } catch {
                              text = new TextDecoder("euc-kr", {
                                fatal: true,
                              }).decode(bytes);
                            }
                            setImported(
                              await api("/import/csv", "POST", { text }),
                            );
                            setImportConfirmed(false);
                          });
                        }}
                      />
                    </label>
                    <button
                      className="text-button"
                      onClick={() =>
                        guard("현재 과목을 예시로 바꿀까요?", demo)
                      }
                    >
                      예시로 시작하기
                    </button>
                  </div>
                  <details>
                    <summary>학교 전체성적표 붙여넣기</summary>
                    <textarea
                      aria-label="학교 성적표 붙여넣기"
                      rows={5}
                      value={paste}
                      onChange={(e) => setPaste(e.target.value)}
                      placeholder={
                        "2020학년도 1학년 1학기\n학수번호\t과목명\t영문과목명\t학점\t성적\t재수강"
                      }
                    />
                    <button
                      className="secondary"
                      disabled={!paste.trim()}
                      onClick={() => void importText("portal", paste)}
                    >
                      가져올 과목 미리보기
                    </button>
                  </details>
                  {imported && (
                    <div className="import-preview">
                      <h3>{imported.attempts.length}과목을 읽었습니다.</h3>
                      <p>
                        미확인 분류{" "}
                        {
                          imported.attempts.filter(
                            (a) => a.category === "미확인",
                          ).length
                        }
                        개 · 적용 후 표에서 이수구분·재수강·교양영역·설계학점을
                        확인하세요.
                      </p>
                      {imported.warnings.map((w, i) => (
                        <p className="muted" key={i}>
                          {w}
                        </p>
                      ))}
                      <div className="preview-list">
                        {imported.attempts.map((a, i) => (
                          <div key={i}>
                            <b>{a.name}</b>
                            <span>
                              {a.code} · {a.credits}학점 · {a.category}
                            </span>
                          </div>
                        ))}
                      </div>
                      <label className="check-label">
                        <input
                          type="checkbox"
                          checked={importConfirmed}
                          onChange={(e) => setImportConfirmed(e.target.checked)}
                        />{" "}
                        선택한 {data.profile.admission_year}학번 기준을
                        확인했고, 현재 이수 표를 이 내역으로 바꿉니다.
                      </label>
                      <button
                        className="primary"
                        disabled={!importConfirmed}
                        onClick={() => {
                          change({ attempts: imported.attempts });
                          setImported(null);
                          setNotice(
                            "과목을 적용했습니다. 이수구분과 상세 인정 정보를 확인한 뒤 계산해 주세요.",
                          );
                        }}
                      >
                        이수 표에 적용
                      </button>
                      <button
                        className="text-button"
                        onClick={() => setImported(null)}
                      >
                        취소
                      </button>
                    </div>
                  )}
                </section>
                <section className="panel course-panel">
                  <div className="section-heading">
                    <div>
                      <span className="eyebrow">MY COURSES</span>
                      <h2>
                        이수 내역{" "}
                        <span className="count">{data.attempts.length}</span>
                      </h2>
                    </div>
                    <button
                      className="primary small"
                      onClick={() => void analyze()}
                    >
                      졸업요건 계산 <ArrowRight size={16} />
                    </button>
                  </div>
                  <p className="muted">
                    미확인 과목과 인정할 내역이 정해지지 않은 중복·재수강은 학점
                    합산에서 보류합니다.
                  </p>
                  <ClassificationReview
                    rows={data.attempts}
                    profile={data.profile}
                    onChange={(attempts) => change({ attempts })}
                    work={work}
                  />
                  <CourseEditor
                    rows={data.attempts}
                    config={config}
                    onChange={(attempts) => change({ attempts })}
                  />
                </section>
                {result && (
                  <div className="banner success">
                    현재 졸업인정학점 {total?.current}학점 ·{" "}
                    <button
                      className="text-button"
                      onClick={() => setTab("overview")}
                    >
                      전체 점검 보기 <ArrowRight size={16} />
                    </button>
                  </div>
                )}
              </>
            )}
            {tab === "roadmap" && (
              <>
                <PlanControls
                  key={`${data.profile.admission_year}-${data.profile.track}`}
                  data={data}
                  config={config}
                  result={result}
                  change={change}
                  apply={apply}
                  work={work}
                />
                <CandidateTools data={data} config={config} change={change} />
                <section className="panel">
                  <div className="section-heading">
                    <div>
                      <h2>
                        {data.options.start_year}년부터 {data.options.semesters}
                        학기
                      </h2>
                      <p className="muted">
                        학기당 최대 {data.options.credit_limit}학점 · 조건
                        변경은 ‘나의 졸업 현황’에서
                      </p>
                    </div>
                    <button className="primary" onClick={() => void analyze()}>
                      로드맵 계산 <ArrowRight size={16} />
                    </button>
                  </div>
                  {!result && (
                    <p>이수 과목과 계획 조건을 확인한 뒤 계산해 주세요.</p>
                  )}
                  {result && (
                    <>
                      <div className="timeline">
                        {result.roadmap.semesters.map((s, i) => (
                          <section
                            className="semester-card"
                            key={`${s.year}-${s.term}`}
                          >
                            <div className="semester-heading">
                              <span className="step-number">
                                {String(i + 1).padStart(2, "0")}
                              </span>
                              <h3>
                                {s.year}년 {s.term}학기
                              </h3>
                              <span className="tag green">{s.credits}학점</span>
                            </div>
                            {s.courses.length ? (
                              s.courses.map((c) => (
                                <div className="planned-course" key={c.code}>
                                  <div>
                                    <b>{c.name}</b>
                                    <span>{c.credits}학점</span>
                                  </div>
                                  <small>{c.code}</small>
                                  <p>{c.reason}</p>
                                </div>
                              ))
                            ) : (
                              <p className="muted">
                                현재 후보와 조건에서 배치 가능한 과목이
                                없습니다.
                              </p>
                            )}
                          </section>
                        ))}
                      </div>
                      <details>
                        <summary>
                          계획 이후에도 남는 확인 사항 (
                          {result.roadmap.unresolved.length})
                        </summary>
                        <ul>
                          {result.roadmap.unresolved.map((s, i) => (
                            <li key={i}>{s}</li>
                          ))}
                        </ul>
                      </details>
                      <details>
                        <summary>계획의 가정과 한계</summary>
                        <ul>
                          {result.roadmap.assumptions.map((s, i) => (
                            <li key={i}>{s}</li>
                          ))}
                        </ul>
                      </details>
                    </>
                  )}
                </section>
                <section className="panel">
                  <h2>나에게 맞게 추천받기</h2>
                  <label>
                    관심 진로와 희망 사항
                    <textarea
                      maxLength={1000}
                      rows={3}
                      value={data.goal}
                      onChange={(e) => change({ goal: e.target.value })}
                      placeholder="예: 백엔드 개발에 관심이 있고 마지막 학기는 졸업작품에 집중하고 싶어요."
                    />
                  </label>
                  {aiConsent}
                  <button
                    className="primary"
                    disabled={!validConsensus}
                    onClick={() => void analyze(true)}
                  >
                    <Sparkles size={17} /> AI 설명과 추천 받기
                  </button>
                  {result?.advice && (
                    <div className="ai-answer">
                      <span className="tag green">
                        LLM 생성 · {result.model}
                      </span>
                      <p>{result.advice.summary}</p>
                      {result.advice.priorities.map((p) => (
                        <p key={p.code}>
                          <b>
                            {(data.candidates ?? config.catalog).find(
                              (c) => c.code === p.code,
                            )?.name || p.code}{" "}
                            ({p.code})
                          </b>
                          <br />
                          {p.reason}
                        </p>
                      ))}
                      <ul>
                        {result.advice.next_steps.map((s, i) => (
                          <li key={i}>{s}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {result && <p className="muted">{result.notice}</p>}
                </section>
                <section className="panel">
                  <details>
                    <summary>
                      추천 후보 확인·제외 (
                      {(data.candidates ?? config.catalog).length}개)
                    </summary>
                    <p className="muted">
                      2026 교과과정 기준 후보입니다. 미래 개설과 선수조건은 수강
                      신청 전에 학교에 확인하세요.
                    </p>
                    <input
                      aria-label="추천 후보 검색"
                      placeholder="과목명 검색"
                      value={catalogSearch}
                      onChange={(e) => setCatalogSearch(e.target.value)}
                    />
                    <div className="candidate-list">
                      {(data.candidates ?? config.catalog)
                        .filter((c) =>
                          `${c.code} ${c.name}`.includes(catalogSearch),
                        )
                        .map((c) => (
                          <label className="candidate-row" key={c.code}>
                            <input
                              type="checkbox"
                              checked={
                                !data.options.excluded_codes.includes(c.code)
                              }
                              onChange={(e) =>
                                change({
                                  options: {
                                    ...data.options,
                                    excluded_codes: e.target.checked
                                      ? data.options.excluded_codes.filter(
                                          (x) => x !== c.code,
                                        )
                                      : [
                                          ...data.options.excluded_codes,
                                          c.code,
                                        ],
                                  },
                                })
                              }
                            />
                            <span>
                              <b>{c.name}</b>
                              <small>
                                {c.code} · {c.credits}학점 ·{" "}
                                {c.semesters.join("·")}학기 개설 가정
                              </small>
                            </span>
                          </label>
                        ))}
                    </div>
                  </details>
                </section>
              </>
            )}
            {tab === "advisor" && (
              <>
                <section className="panel advisor-intro">
                  <span className="ai-orb">
                    <Sparkles size={25} />
                  </span>
                  <div>
                    <h2>다음 한 걸음, 함께 정리해요.</h2>
                    <p>
                      최신 이수 내역으로 요건을 계산한 뒤 LLM이 질문에 답합니다.
                      <br />
                      답변은 참고용이며, 학점과 충족 상태는 ‘졸업 현황’에서
                      확인하세요.
                    </p>
                  </div>
                </section>
                {aiConsent}
                <section className="panel conversation">
                  <div className="section-heading">
                    <h2>나의 졸업 상담</h2>
                    <span className="tag neutral">
                      대화는 DB에 저장하지 않아요
                    </span>
                  </div>
                  {messages.length === 0 && (
                    <div className="chat-empty">
                      <MessageCircle size={32} />
                      <h3>궁금한 점을 물어보세요</h3>
                      <div className="suggestions">
                        {[
                          "졸업하려면 무엇부터 준비해야 하나요?",
                          "다음 학기 과목을 이렇게 추천한 이유가 뭔가요?",
                          "학점 말고 확인해야 할 졸업요건은 무엇인가요?",
                        ].map((q) => (
                          <button key={q} onClick={() => setQuestion(q)}>
                            {q}
                            <ArrowRight size={14} />
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  <div aria-live="polite">
                    {messages.map((m, i) => (
                      <div className="chat-turn" key={i}>
                        <div className="user-message">{m.question}</div>
                        <div className="assistant-message">
                          <span
                            className={`tag ${m.mode === "llm" ? "green" : "amber"}`}
                          >
                            {m.mode === "llm"
                              ? `LLM 답변 · ${m.model}`
                              : "AI 답변 미생성"}
                          </span>
                          <p>{m.answer}</p>
                          <EvidenceList items={m.evidence} />
                          {m.referenced_checks.length > 0 && (
                            <div className="references">
                              <small>참고한 계산 항목</small>
                              {m.referenced_checks.map((c) => (
                                <span key={c}>{c}</span>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                  <form
                    className="chat-composer"
                    onSubmit={(e) => {
                      e.preventDefault();
                      void ask();
                    }}
                  >
                    <textarea
                      aria-label="AI에게 질문"
                      value={question}
                      onChange={(e) => setQuestion(e.target.value)}
                      rows={3}
                      maxLength={1000}
                      placeholder="예: 지금 상태에서 다음 학기에 우선 들을 과목을 설명해 주세요."
                    />
                    <div>
                      <small>{question.length} / 1,000</small>
                      <button
                        className="primary"
                        type="submit"
                        disabled={!validConsensus || !question.trim()}
                      >
                        <Send size={16} /> AI에게 질문
                      </button>
                    </div>
                  </form>
                </section>
              </>
            )}
            {tab === "saved" && (
              <>
                <ExportTools data={data} restore={restoreBackup} work={work} />
                <Checklist data={data} change={change} />
                <section className="panel">
                  <div className="section-heading">
                    <h2>현재 계획 저장</h2>
                    <span className="tag green">
                      <Database size={13} /> 이 컴퓨터의 SQLite DB
                    </span>
                  </div>
                  <p className="muted">
                    저장하면 과목·성적·계획 조건과 기본 계산 결과가 이 컴퓨터의
                    DB에 남습니다. 이름·학번 대신 구분하기 쉬운 별칭을
                    사용하세요.
                  </p>
                  <div className="save-form">
                    <label>
                      저장 이름
                      <input
                        maxLength={80}
                        value={label}
                        onChange={(e) => {
                          setLabel(e.target.value);
                          setDirty(true);
                        }}
                      />
                    </label>
                    <button
                      className="primary"
                      disabled={!label.trim()}
                      onClick={() => void save()}
                    >
                      <Save size={16} />
                      {selected ? "변경 사항 저장" : "새 계획 저장"}
                    </button>
                    {selected && (
                      <button
                        className="secondary"
                        onClick={() => void save(true)}
                      >
                        <Plus size={16} /> 사본 저장
                      </button>
                    )}
                  </div>
                </section>
                <section className="panel">
                  <div className="section-heading">
                    <h2>
                      저장한 계획{" "}
                      <span className="count">{records.length}</span>
                    </h2>
                    <button
                      className="text-button"
                      onClick={() =>
                        void work("목록을 갱신하고 있어요…", async () =>
                          setRecords(await api("/profiles")),
                        )
                      }
                    >
                      목록 새로고침
                    </button>
                  </div>
                  {!records.length ? (
                    <div className="empty">
                      <Database size={34} />
                      <p>
                        저장한 계획이 없습니다.
                        <br />
                        입력한 과목을 다음에도 사용하려면 위에서 저장하세요.
                      </p>
                    </div>
                  ) : (
                    <div className="saved-list">
                      {records.map((r) => (
                        <div key={r.id}>
                          <span className="saved-icon">
                            <FileText size={23} />
                          </span>
                          <div>
                            <b>{r.label}</b>
                            <small>
                              {r.admission_year}학번 · {r.track}과정 ·{" "}
                              {r.course_count}과목 · 버전 {r.revision} ·{" "}
                              {date(r.updated_at)}
                            </small>
                          </div>
                          <button
                            className="secondary small"
                            onClick={() =>
                              guard(
                                "저장하지 않은 입력을 버리고 이 계획을 불러올까요?",
                                () => load(r.id),
                              )
                            }
                          >
                            불러오기
                          </button>
                          <button
                            className="text-button danger"
                            onClick={() =>
                              setPendingAction({
                                text: `“${r.label}”의 이수 내역과 모든 저장 기록을 DB에서 삭제할까요?`,
                                run: () => remove(r),
                              })
                            }
                          >
                            삭제
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </section>
                {history.length > 0 && (
                  <section className="panel">
                    <h2>현재 계획의 저장 기록</h2>
                    <p className="muted">
                      최근 20개 기록입니다. 과거 규정으로 계산한 스냅샷이며,
                      불러올 때는 현재 규정으로 다시 계산합니다.
                    </p>
                    {history.map((h) => (
                      <div className="history-row" key={h.id}>
                        <span>버전 {h.revision}</span>
                        <b>
                          {
                            h.result.audit.checks.find(
                              (c) => c.key === "총 졸업인정학점",
                            )?.current
                          }
                          학점
                        </b>
                        <small>
                          {date(h.created_at)} · 규정{" "}
                          {h.rules_fingerprint.slice(0, 8)}
                        </small>
                      </div>
                    ))}
                  </section>
                )}
              </>
            )}
            {result?.audit.warnings.length ? (
              <details className="panel warning-details">
                <summary>
                  이수 내역 확인 사항 ({result.audit.warnings.length})
                </summary>
                <ul>
                  {result.audit.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </details>
            ) : null}
            {result && (
              <details className="panel sources">
                <summary>사용한 규정과 확인이 필요한 범위</summary>
                <ul>
                  {result.rules.notices.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
                <h3>근거 자료</h3>
                {result.rules.sources.map((s, i) => (
                  <p key={i}>
                    {s.startsWith("https://") ? (
                      <a
                        href={s.split(" · ")[0]}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {s}
                      </a>
                    ) : (
                      s
                    )}
                  </p>
                ))}
              </details>
            )}
            <div hidden={tab !== "review"}>
              <ReviewTools work={work} years={config.admission_years} />
            </div>
          </fieldset>
          <footer>
            <span>PATH · 나의 졸업 로드맵</span>
            <span>
              {data.profile.admission_year}학번 참고 계획 · 공식 졸업사정은
              학교에서 확인
            </span>
          </footer>
        </main>
      </div>
      {pendingAction && (
        <div className="modal-backdrop">
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
            className="modal"
          >
            <h2 id="confirm-title">계속 진행할까요?</h2>
            <p>{pendingAction.text}</p>
            <div>
              <button
                className="secondary"
                autoFocus
                onClick={() => setPendingAction(null)}
              >
                취소
              </button>
              <button
                className="primary"
                onClick={() => {
                  const action = pendingAction.run;
                  setPendingAction(null);
                  void action();
                }}
              >
                확인
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
