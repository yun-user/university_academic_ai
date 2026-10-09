import type { DesignAllocation } from "./types";

export const designMode = (row: DesignAllocation) =>
  ({ auto: "학과 표 대조", manual: "직접 입력", held: "확인 필요", unmatched: "해당 없음" })[row.mode];

export default function DesignBreakdown({ rows }: { rows: DesignAllocation[] }) {
  const relevant = rows.filter((r) => r.mode === "auto" || r.mode === "manual" || (r.mode === "held" && r.kind));
  const automatic = rows.filter((r) => r.mode === "auto").reduce((s, r) => s + r.counted_credits, 0);
  const manual = rows.filter((r) => r.mode === "manual").reduce((s, r) => s + r.counted_credits, 0);
  return (
    <details className="design-breakdown">
      <summary>설계학점 근거: {automatic + manual}학점 · 학과 표 {automatic} + 직접 입력 {manual}</summary>
      <p className="muted">현재 학과 공개표와 학수번호·과목명·교과학점이 일치하는 2019~2026년 수강내역을 참고 대조합니다. 총 졸업학점에 다시 더하지 않습니다. 수강 당시 인정과 기초→요소→종합 이수순서·학교 승인 예외는 별도로 확인하세요.</p>
      <a href="https://software.hongik.ac.kr/home/templates/curriculum/courses" target="_blank" rel="noreferrer">학과 설계/대체 교과목 표 보기</a>
      {relevant.length ? <div className="table-scroll"><table className="courses">
        <thead><tr><th>과목</th><th>수강연도</th><th>설계 배분</th><th>현재 합산</th><th>적용 근거</th></tr></thead>
        <tbody>{relevant.map((r) => <tr key={r.index}>
          <td>{r.name}<small>{r.code} · {r.kind}</small></td><td>{r.year}</td><td>{r.credits}</td><td>{r.counted_credits}</td>
          <td>{designMode(r)}<small>{r.reason}</small></td>
        </tr>)}</tbody>
      </table></div> : <p>자동 대조되거나 직접 입력한 설계과목이 없습니다. 이수구분과 과목 정보를 확인해 주세요.</p>}
      <p className="muted">F/NP·미확정·수강중·중복·인정제외는 현재 합계에서 제외합니다. 학교에서 확인한 값은 이수내역의 상세 편집에서 직접 입력할 수 있습니다. 직접 입력을 해제하면 자동 대조로 돌아갑니다.</p>
    </details>
  );
}
