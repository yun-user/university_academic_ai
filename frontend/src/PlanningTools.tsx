import { useEffect, useState } from "react";
import { api } from "./api";
import { maxSemesters, resizeSemesters } from "./planOptions";
import type {
  Analysis,
  Bootstrap,
  Candidate,
  Evidence,
  Input,
  Options,
  Placement,
  Substitution,
} from "./types";

type Props = {
  data: Input;
  config: Bootstrap;
  result: Analysis | null;
  change: (patch: Partial<Input>) => void;
  apply: (patch: Partial<Input>) => Promise<void>;
  work: (name: string, action: () => Promise<void>) => Promise<void>;
};
const codes = (s: string) =>
  s
    .split(",")
    .map((x) => x.trim().toUpperCase())
    .filter(Boolean);
function semester(options: Options, i: number) {
  const n = options.start_term - 1 + i;
  return `${options.start_year + Math.floor(n / 2)}년 ${(n % 2) + 1}학기`;
}
export function EvidenceList({ items }: { items?: Evidence[] }) {
  return items?.length ? (
    <details>
      <summary>답변·계산의 근거 ({items.length})</summary>
      {items.map((e) => (
        <article className="evidence-item" key={e.key}>
          <b>
            {e.key}: {e.current} / {e.required} · {e.status}
          </b>
          <p>{e.detail}</p>
          <small>
            {e.scope} · {e.verification}
          </small>
          <ul>
            {e.sources.map((s, i) => (
              <li key={i}>
                {/^https:\/\/[^\s]+$/.test(s) ? (
                  <a href={s} target="_blank" rel="noreferrer">
                    {s}
                  </a>
                ) : (
                  s
                )}
              </li>
            ))}
          </ul>
        </article>
      ))}
    </details>
  ) : null;
}

export function PlanControls({
  data,
  config,
  result,
  change,
  apply,
  work,
}: Props) {
  const [comparison, setComparison] = useState<
    {
      limit: number;
      options: Options;
      planned_credits: number;
      result: Analysis;
    }[]
  >([]);
  const [last, setLast] = useState("9");
  const [add, setAdd] = useState("");
  const candidates = data.candidates ?? config.catalog;
  useEffect(() => setComparison([]), [data]);
  const placements: Placement[] =
    data.placements ??
    result?.roadmap.semesters.flatMap((s, i) =>
      s.courses.map((c) => ({ code: c.code, semester: i })),
    ) ??
    [];
  const edit = (rows: Placement[]) => void apply({ placements: rows });
  const canAddSemester = data.options.semesters < maxSemesters(data.options);
  return (
    <section className="panel">
      <div className="section-heading">
        <h2>계획 비교와 직접 수정</h2>
        <button type="button" className="secondary small" disabled={!canAddSemester}
          aria-describedby="semester-add-help"
          onClick={() => {
            if (canAddSemester) void apply({ options: resizeSemesters(data.options, data.options.semesters + 1) });
          }}>+ 한 학기 추가</button>
      </div>
      <p id="semester-add-help" className="muted" role="status">
        현재 {data.options.semesters}학기 · {canAddSemester
          ? `추가하면 ${semester(data.options, data.options.semesters)}까지 계획합니다. 기존 한도와 직접 배치는 유지됩니다.`
          : "계획은 최대 12학기, 2100년 2학기까지 추가할 수 있습니다. 시작 연도도 확인해 주세요."}
      </p>
      <p className="muted">
        학기별 부담을 정하고 과목을 옮겨 보세요. 이동할 때
        선수·병수·개설학기·중복·학점 한도를 다시 검사합니다.
      </p>
      <div className="form-grid">
        {Array.from(
          { length: Math.min(12, Math.max(1, data.options.semesters)) },
          (_, i) => (
            <label key={i}>
              {semester(data.options, i)} 한도
              <input
                type="number"
                min={0}
                max={30}
                value={
                  data.options.semester_limits?.[i] ?? data.options.credit_limit
                }
                onChange={(e) => {
                  const caps = Array.from(
                    { length: data.options.semesters },
                    (_, j) =>
                      data.options.semester_limits?.[j] ??
                      data.options.credit_limit,
                  );
                  caps[i] = Number(e.target.value);
                  change({
                    options: { ...data.options, semester_limits: caps },
                  });
                }}
              />
            </label>
          ),
        )}
      </div>
      <p className="muted">
        0학점은 쉬어 가는 학기입니다. 한도를 변경한 후 ‘로드맵 계산’을 누르세요.
      </p>
      <div className="button-row">
        <label>
          비교 시 마지막 학기 한도
          <input
            type="number"
            min={0}
            max={30}
            value={last}
            placeholder="비워 두면 동일 한도"
            onChange={(e) => setLast(e.target.value)}
          />
        </label>
        <button
          onClick={() =>
            void work("두 계획을 비교하고 있어요…", async () => {
              const r = await api<{ scenarios: typeof comparison }>(
                "/compare",
                "POST",
                {
                  ...data,
                  limits: [15, 18],
                  last_limit: last === "" ? null : Number(last),
                },
              );
              setComparison(r.scenarios);
            })
          }
        >
          15학점 / 18학점 비교
        </button>
        <button onClick={() => void apply({ placements: null })}>
          자동 배치로 다시 계산
        </button>
      </div>
      {comparison.length > 0 && (
        <div className="comparison-grid">
          {comparison.map((s) => (
            <article className="semester-card" key={s.limit}>
              <h3>학기당 {s.limit}학점 계획</h3>
              <p>
                예정 {s.planned_credits}학점 · 학기별{" "}
                {s.result.roadmap.semesters.map((t) => t.credits).join(" / ")}
              </p>
              <p>
                계획 후 총학점 부족:{" "}
                {
                  s.result.roadmap.projected.checks.find(
                    (c) => c.key === "총 졸업인정학점",
                  )?.missing
                }
              </p>
              <p>
                남은 확인·미충족 항목{" "}
                {
                  s.result.roadmap.projected.checks.filter(
                    (c) => c.status !== "충족",
                  ).length
                }
                개
              </p>
              <details>
                <summary>학기별 과목 보기</summary>
                {s.result.roadmap.semesters.map((t) => (
                  <p key={`${t.year}-${t.term}`}>
                    {t.year}-{t.term}:{" "}
                    {t.courses.map((c) => c.name).join(", ") || "배치 없음"}
                  </p>
                ))}
              </details>
              <button
                onClick={() =>
                  void apply({ options: s.options, placements: null })
                }
              >
                이 계획 적용
              </button>
            </article>
          ))}
        </div>
      )}
      <details>
        <summary>과목 이동·추가·제거 ({placements.length}개)</summary>
        <p>
          수정한 배치는 저장·백업에 포함됩니다. 조건을 위반하면 계산 결과를
          표시하지 않고 수정할 항목을 안내합니다.
        </p>
        <div className="plan-edit-list">
          {placements.map((p, i) => (
            <div className="edit-row" key={`${p.code}-${i}`}>
              <span>
                {candidates.find((c) => c.code === p.code)?.name ?? p.code}{" "}
                <small>{p.code}</small>
              </span>
              <select
                aria-label={`${p.code} 배치 학기`}
                value={p.semester}
                onChange={(e) =>
                  edit(
                    placements.map((v, j) =>
                      j === i ? { ...v, semester: Number(e.target.value) } : v,
                    ),
                  )
                }
              >
                {Array.from({ length: data.options.semesters }, (_, j) => (
                  <option value={j} key={j}>
                    {semester(data.options, j)}
                  </option>
                ))}
              </select>
              <button
                aria-label={`${p.code} 배치 제거`}
                onClick={() => edit(placements.filter((_, j) => i !== j))}
              >
                제거
              </button>
            </div>
          ))}
        </div>
        <div className="button-row">
          <select
            aria-label="배치할 과목"
            value={add}
            onChange={(e) => setAdd(e.target.value)}
          >
            <option value="">후보 선택</option>
            {candidates
              .filter((c) => !placements.some((p) => p.code === c.code))
              .map((c) => (
                <option key={c.code} value={c.code}>
                  {c.code} · {c.name}
                </option>
              ))}
          </select>
          <button
            disabled={!add}
            onClick={() => {
              edit([...placements, { code: add, semester: 0 }]);
              setAdd("");
            }}
          >
            첫 학기에 추가
          </button>
        </div>
      </details>
      <EvidenceList items={result?.evidence} />
      {result?.candidate_reasons && (
        <details>
          <summary>
            배치되지 않은 후보와 이유 ({result.candidate_reasons.length})
          </summary>
          {result.candidate_reasons.map((c) => (
            <p key={c.code}>
              <b>
                {c.name} ({c.code})
              </b>
              <br />
              {c.reason}
              <small>{c.source}</small>
            </p>
          ))}
        </details>
      )}
    </section>
  );
}

export function CandidateTools({
  data,
  config,
  change,
}: Pick<Props, "data" | "config" | "change">) {
  const [selected, setSelected] = useState("");
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState<Candidate | null>(null);
  const [error, setError] = useState("");
  const candidates = data.candidates ?? config.catalog;
  function open(code: string) {
    setSelected(code);
    setDraft(candidates.find((c) => c.code === code) ?? null);
    setError("");
  }
  function save() {
    if (!draft) return;
    if (
      !draft.code.trim() ||
      !draft.name.trim() ||
      !(draft.credits > 0 && draft.credits <= 30) ||
      !draft.source.trim() ||
      draft.design_credits > draft.credits ||
      (draft.sw_data_credits ?? 0) < 0 ||
      (draft.sw_data_credits ?? 0) > draft.credits
    ) {
      setError(
        "학수번호·이름·학점·출처와 설계/SW·데이터 인정학점을 확인하세요.",
      );
      return;
    }
    if (candidates.some((c) => c.code === draft.code && c.code !== selected)) {
      setError("학수번호가 중복됩니다.");
      return;
    }
    change({
      candidates: [...candidates.filter((c) => c.code !== selected), draft],
    });
    setSelected(draft.code);
    setError("");
  }
  return (
    <section className="panel">
      <details>
        <summary>추천 후보·선수조건 편집</summary>
        <p>
          학교 확인 근거가 있는 과목을 추가하거나 보완하세요. 변경하면 사용자
          후보 목록으로 저장됩니다.
        </p>
        <label>
          후보 검색
          <input value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <div className="button-row">
          <select
            aria-label="편집할 후보"
            value={selected}
            onChange={(e) => open(e.target.value)}
          >
            <option value="">후보 선택</option>
            {candidates
              .filter((c) => `${c.code} ${c.name}`.includes(query))
              .map((c) => (
                <option key={c.code} value={c.code}>
                  {c.code} · {c.name}
                </option>
              ))}
          </select>
          <button
            onClick={() => {
              setSelected("");
              setDraft({
                code: "",
                name: "",
                credits: 3,
                category: "전공",
                area: 0,
                design_credits: 0,
                equivalent_code: "",
                semesters: [1, 2],
                prerequisites: [],
                concurrent: [],
                alternatives: [],
                source: "사용자 추가: 학교 확인 필요",
              });
            }}
          >
            새 후보
          </button>
        </div>
        {error && <p role="alert">{error}</p>}
        {draft && (
          <div className="editor-box">
            <div className="form-grid">
              {(["code", "name", "source", "equivalent_code"] as const).map(
                (key, i) => (
                  <label key={key}>
                    {
                      ["학수번호", "과목명", "출처·적용 시기", "동일과목 코드"][
                        i
                      ]
                    }
                    <input
                      value={draft[key] ?? 0}
                      maxLength={key === "source" ? 500 : 150}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          [key]: key.includes("code")
                            ? e.target.value.toUpperCase()
                            : e.target.value,
                        })
                      }
                    />
                  </label>
                ),
              )}
              <label>
                이수구분
                <select
                  value={draft.category}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      category: e.target.value,
                      area: 0,
                      design_credits: 0,
                    })
                  }
                >
                  {config.categories.map((c) => (
                    <option key={c}>{c}</option>
                  ))}
                </select>
              </label>
              {(
                [
                  "credits",
                  "area",
                  "design_credits",
                  "sw_data_credits",
                ] as const
              ).map((key, i) => (
                <label key={key}>
                  {
                    [
                      "학점",
                      "전문교양 영역 (0~7)",
                      "설계 인정학점",
                      "SW·데이터 인정학점",
                    ][i]
                  }
                  <input
                    type="number"
                    value={draft[key] ?? 0}
                    min={0}
                    max={key === "area" ? 7 : 30}
                    step={key === "area" ? 1 : 0.5}
                    onChange={(e) =>
                      setDraft({ ...draft, [key]: Number(e.target.value) })
                    }
                  />
                </label>
              ))}
              <label>
                개설학기
                <select
                  value={draft.semesters.join(",")}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      semesters: e.target.value
                        ? e.target.value.split(",").map(Number)
                        : [],
                    })
                  }
                >
                  <option value="">미확인</option>
                  <option value="1">1학기</option>
                  <option value="2">2학기</option>
                  <option value="1,2">1·2학기</option>
                </select>
              </label>
              {(["prerequisites", "concurrent", "alternatives"] as const).map(
                (key, i) => (
                  <label key={key}>
                    {
                      [
                        "선수 학수번호 (쉼표)",
                        "선이수 또는 병수 학수번호",
                        "선택 대안 학수번호",
                      ][i]
                    }
                    <input
                      value={draft[key].join(",")}
                      onChange={(e) =>
                        setDraft({ ...draft, [key]: e.target.value.split(",") })
                      }
                      onBlur={() =>
                        setDraft({
                          ...draft,
                          [key]: codes(draft[key].join(",")),
                        })
                      }
                    />
                  </label>
                ),
              )}
            </div>
            <div className="button-row">
              <button onClick={save}>후보 변경 적용</button>
              {selected && (
                <button
                  onClick={() => {
                    change({
                      candidates: candidates.filter((c) => c.code !== selected),
                    });
                    setDraft(null);
                    setSelected("");
                  }}
                >
                  이 후보 제거
                </button>
              )}
            </div>
          </div>
        )}
      </details>
    </section>
  );
}

export function SubstitutionTools({
  data,
  change,
}: Pick<Props, "data" | "change">) {
  const items = data.profile.substitutions;
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState<Substitution>({
    required_code: "",
    replacement_code: "",
    track: data.profile.track,
    start_year: data.profile.admission_year,
    start_term: 1,
    end_year: null,
    end_term: null,
    source: "",
    confirmed: false,
  });
  const [error, setError] = useState("");
  return (
    <section className="panel">
      <details>
        <summary>대체인정 편집 ({items.length}건)</summary>
        <p>
          방향·과정·수강시기·공식 근거가 일치하는 필수과목에만 적용합니다.
          학점이나 선수조건을 대신 충족시키지 않습니다.
        </p>
        {items.map((s, i) => (
          <div className="edit-row" key={i}>
            <span>
              {s.required_code} ← {s.replacement_code} · {s.track} ·{" "}
              {s.start_year}-{s.start_term} ~{" "}
              {s.end_year ? `${s.end_year}-${s.end_term}` : "종료 미정"}
              <small>{s.source}</small>
            </span>
            <label>
              <input
                type="checkbox"
                checked={s.confirmed}
                onChange={(e) =>
                  change({
                    profile: {
                      ...data.profile,
                      substitutions: items.map((v, j) =>
                        i === j ? { ...v, confirmed: e.target.checked } : v,
                      ),
                    },
                  })
                }
              />
              학교 확인
            </label>
            <button
              onClick={() => {
                setDraft(s);
                setEditing(i);
              }}
            >
              수정
            </button>
            <button
              onClick={() =>
                change({
                  profile: {
                    ...data.profile,
                    substitutions: items.filter((_, j) => j !== i),
                  },
                })
              }
            >
              제거
            </button>
          </div>
        ))}
        <div className="form-grid">
          <label>
            원래 필수 학수번호
            <input
              value={draft.required_code}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  required_code: e.target.value.toUpperCase(),
                })
              }
            />
          </label>
          <label>
            대체 이수 학수번호
            <input
              value={draft.replacement_code}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  replacement_code: e.target.value.toUpperCase(),
                })
              }
            />
          </label>
          <label>
            적용 과정
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
          <label>
            시작 연도
            <input
              type="number"
              value={draft.start_year}
              min={2000}
              max={2100}
              onChange={(e) =>
                setDraft({ ...draft, start_year: Number(e.target.value) })
              }
            />
          </label>
          <label>
            시작 학기
            <select
              value={draft.start_term}
              onChange={(e) =>
                setDraft({ ...draft, start_term: Number(e.target.value) })
              }
            >
              {[1, 2, 3, 4].map((n) => (
                <option key={n} value={n}>
                  {n === 3 ? "여름" : n === 4 ? "겨울" : `${n}학기`}
                </option>
              ))}
            </select>
          </label>
          <label>
            종료 연도 (선택)
            <input
              type="number"
              value={draft.end_year ?? ""}
              min={2000}
              max={2100}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  end_year: e.target.value ? Number(e.target.value) : null,
                  end_term: e.target.value ? (draft.end_term ?? 2) : null,
                })
              }
            />
          </label>
          {draft.end_year && (
            <label>
              종료 학기
              <select
                value={draft.end_term ?? 2}
                onChange={(e) =>
                  setDraft({ ...draft, end_term: Number(e.target.value) })
                }
              >
                {[1, 2, 3, 4].map((n) => (
                  <option key={n} value={n}>
                    {n === 3 ? "여름" : n === 4 ? "겨울" : `${n}학기`}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            승인 근거·문서·페이지
            <input
              value={draft.source}
              maxLength={500}
              onChange={(e) => setDraft({ ...draft, source: e.target.value })}
            />
          </label>
        </div>
        <label className="check-label">
          <input
            type="checkbox"
            checked={draft.confirmed}
            onChange={(e) =>
              setDraft({ ...draft, confirmed: e.target.checked })
            }
          />
          학교의 대체인정을 확인했습니다.
        </label>
        {error && <p role="alert">{error}</p>}
        <button
          onClick={() => {
            if (
              !draft.required_code ||
              !draft.replacement_code ||
              !draft.source.trim() ||
              draft.required_code === draft.replacement_code
            ) {
              setError("서로 다른 학수번호와 근거를 입력하세요.");
              return;
            }
            change({
              profile: {
                ...data.profile,
                substitutions:
                  editing === null
                    ? [...items, draft]
                    : items.map((s, i) => (i === editing ? draft : s)),
              },
            });
            setEditing(null);
            setDraft({
              ...draft,
              required_code: "",
              replacement_code: "",
              source: "",
              confirmed: false,
            });
            setError("");
          }}
        >
          {editing === null ? "대체인정 추가" : "대체인정 수정 적용"}
        </button>
      </details>
    </section>
  );
}

export function Checklist({ data, change }: Pick<Props, "data" | "change">) {
  const [title, setTitle] = useState("");
  const items = data.checklist ?? [];
  const today = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  return (
    <section className="panel">
      <h2>졸업 준비 체크리스트</h2>
      <p>
        개인 준비 일정입니다. 완료 체크는 학교 승인이나 졸업판정에 영향을 주지
        않습니다.
      </p>
      {items.map((t, i) => (
        <div className="task-row" key={t.id}>
          <label className="check-label">
            <input
              type="checkbox"
              checked={t.done}
              onChange={(e) =>
                change({
                  checklist: items.map((v, j) =>
                    j === i ? { ...v, done: e.target.checked } : v,
                  ),
                })
              }
            />
            <input
              aria-label="할 일 제목"
              value={t.title}
              maxLength={150}
              onChange={(e) =>
                change({
                  checklist: items.map((v, j) =>
                    j === i ? { ...v, title: e.target.value } : v,
                  ),
                })
              }
            />
          </label>
          <label>
            기한
            <input
              type="date"
              value={t.due ?? ""}
              onChange={(e) =>
                change({
                  checklist: items.map((v, j) =>
                    j === i ? { ...v, due: e.target.value || null } : v,
                  ),
                })
              }
            />
          </label>
          <input
            aria-label={`${t.title} 메모`}
            placeholder="제출처·준비 내용"
            value={t.note}
            maxLength={500}
            onChange={(e) =>
              change({
                checklist: items.map((v, j) =>
                  j === i ? { ...v, note: e.target.value } : v,
                ),
              })
            }
          />
          {!t.done && t.due && t.due < today && (
            <span className="tag amber">기한 지남</span>
          )}
          <button
            onClick={() =>
              change({ checklist: items.filter((_, j) => j !== i) })
            }
          >
            제거
          </button>
        </div>
      ))}
      <div className="button-row">
        <input
          aria-label="새 할 일"
          placeholder="예: 졸업작품 발표자료 제출"
          value={title}
          maxLength={150}
          onChange={(e) => setTitle(e.target.value)}
        />
        <button
          disabled={!title.trim() || items.length >= 100}
          onClick={() => {
            change({
              checklist: [
                ...items,
                {
                  id: crypto.randomUUID(),
                  title: title.trim(),
                  due: null,
                  done: false,
                  note: "",
                },
              ],
            });
            setTitle("");
          }}
        >
          할 일 추가
        </button>
      </div>
    </section>
  );
}
