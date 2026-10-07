import { useState } from "react";
import { Plus, Search, Trash2, ChevronDown } from "lucide-react";
import type { Attempt, Bootstrap } from "./types";

export default function CourseEditor({
  rows,
  config,
  onChange,
}: {
  rows: Attempt[];
  config: Bootstrap;
  onChange: (rows: Attempt[]) => void;
}) {
  const [search, setSearch] = useState("");
  const [onlyUnknown, setOnlyUnknown] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  function update(index: number, patch: Partial<Attempt>) {
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }
  const visible = rows
    .map((row, index) => ({ row, index }))
    .filter(
      ({ row }) =>
        `${row.code} ${row.name}`
          .toLowerCase()
          .includes(search.toLowerCase()) &&
        (!onlyUnknown || row.category === "미확인"),
    );
  return (
    <>
      <div className="table-toolbar">
        <label className="search">
          <Search size={16} />
          <input
            aria-label="이수 과목 검색"
            placeholder="과목명 또는 학수번호 검색"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <label className="check-label">
          <input
            type="checkbox"
            checked={onlyUnknown}
            onChange={(e) => setOnlyUnknown(e.target.checked)}
          />{" "}
          미확인만 보기
        </label>
        <button
          className="secondary small"
          onClick={() => {
            onChange([
              ...rows,
              {
                code: "",
                name: "",
                credits: 3,
                category: "미확인",
                area: 0,
                design_credits: 0,
                equivalent_code: "",
                year: 2026,
                term: 1,
                grade: "미확정",
                status: "취득",
              },
            ]);
            setEditing(rows.length);
            setSearch("");
            setOnlyUnknown(false);
          }}
          disabled={rows.length >= 500}
        >
          <Plus size={16} /> 과목 추가
        </button>
      </div>
      {!rows.length ? (
        <div className="empty">
          <h3>먼저 이수 과목을 가져와 주세요.</h3>
          <p>학교 성적표 붙여넣기, CSV 업로드, 직접 입력을 사용할 수 있어요.</p>
        </div>
      ) : (
        <div className="table-scroll">
          <table className="courses">
            <thead>
              <tr>
                <th>과목 / 학수번호</th>
                <th>이수구분</th>
                <th>학점</th>
                <th>수강 시기</th>
                <th>성적</th>
                <th>상태</th>
                <th>편집</th>
              </tr>
            </thead>
            <tbody>
              {visible.map(({ row, index }) => (
                <tr
                  key={index}
                  className={row.category === "미확인" ? "unclassified" : ""}
                >
                  <td>
                    <b>{row.name || "새 과목"}</b>
                    <small>{row.code || "학수번호 입력 필요"}</small>
                  </td>
                  <td>
                    <select
                      aria-label={`${index + 1}행 이수구분`}
                      value={row.category}
                      onChange={(e) =>
                        update(index, {
                          category: e.target.value,
                          area: 0,
                          design_credits: 0,
                        })
                      }
                    >
                      {config.categories.map((x) => (
                        <option key={x}>{x}</option>
                      ))}
                    </select>
                  </td>
                  <td>{row.credits}</td>
                  <td>
                    {row.year} ·{" "}
                    {["", "1학기", "2학기", "여름", "겨울"][row.term]}
                  </td>
                  <td>{row.grade}</td>
                  <td>
                    <span className="tag neutral">{row.status}</span>
                  </td>
                  <td>
                    <button
                      className="icon-button"
                      aria-label={`${index + 1}행 상세 편집`}
                      onClick={() =>
                        setEditing(editing === index ? null : index)
                      }
                    >
                      <ChevronDown size={17} />
                    </button>
                    <button
                      className="icon-button danger"
                      aria-label={`${index + 1}행 삭제`}
                      onClick={() => {
                        onChange(rows.filter((_, i) => i !== index));
                        setEditing(null);
                      }}
                    >
                      <Trash2 size={15} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {visible.length === 0 && (
            <p className="empty">검색 결과가 없습니다.</p>
          )}
        </div>
      )}
      {editing !== null && rows[editing] && (
        <div className="edit-card">
          <div className="section-heading">
            <h3>{editing + 1}행 상세 편집</h3>
            <button className="text-button" onClick={() => setEditing(null)}>
              닫기
            </button>
          </div>
          <div className="form-grid">
            {(
              ["code", "name", "credits", "year", "equivalent_code"] as const
            ).map((key, i) => (
              <label key={key}>
                {
                  [
                    "학수번호",
                    "과목명",
                    "학점",
                    "수강연도",
                    "공식 동일과목 코드",
                  ][i]
                }
                <input
                  value={rows[editing][key]}
                  type={["credits", "year"].includes(key) ? "number" : "text"}
                  onChange={(e) =>
                    update(editing, {
                      [key]: ["credits", "year"].includes(key)
                        ? Number(e.target.value)
                        : e.target.value,
                    })
                  }
                />
              </label>
            ))}
            <label>
              학기
              <select
                value={rows[editing].term}
                onChange={(e) =>
                  update(editing, { term: Number(e.target.value) })
                }
              >
                <option value={1}>1학기</option>
                <option value={2}>2학기</option>
                <option value={3}>하계</option>
                <option value={4}>동계</option>
              </select>
            </label>
            <label>
              성적
              <select
                value={rows[editing].grade}
                onChange={(e) => update(editing, { grade: e.target.value })}
              >
                {config.grades.map((x) => (
                  <option key={x}>{x}</option>
                ))}
              </select>
            </label>
            <label>
              인정 상태
              <select
                value={rows[editing].status}
                onChange={(e) => update(editing, { status: e.target.value })}
              >
                {config.statuses.map((x) => (
                  <option key={x}>{x}</option>
                ))}
              </select>
            </label>
            <label>
              교양영역 (0 = 미확인)
              <input
                type="number"
                min={0}
                max={7}
                disabled={rows[editing].category !== "전문교양"}
                value={rows[editing].area}
                onChange={(e) =>
                  update(editing, { area: Number(e.target.value) })
                }
              />
            </label>
            <label>
              설계 인정학점
              <input
                type="number"
                min={0}
                max={rows[editing].credits}
                step={0.5}
                disabled={rows[editing].category !== "전공"}
                value={rows[editing].design_credits}
                onChange={(e) =>
                  update(editing, { design_credits: Number(e.target.value) })
                }
              />
            </label>
          </div>
          <p className="muted">
            동일과목·교양영역·설계학점은 수강 당시 학교 인정 기준을 확인한 값만
            입력하세요. F/NP와 인정제외 과목은 졸업학점에서 제외됩니다.
          </p>
        </div>
      )}
    </>
  );
}
