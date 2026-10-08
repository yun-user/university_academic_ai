import type { Bootstrap, Profile } from "./types";

export default function CohortSummary({
  config,
  profile,
  onChange,
}: {
  config: Bootstrap;
  profile: Profile;
  onChange: (year: number, track: Profile["track"]) => Promise<void>;
}) {
  const rule = config.cohort_rules.find(
    (r) =>
      r.admission_year === profile.admission_year && r.track === profile.track,
  );
  if (!rule) return null;
  return (
    <section
      className="panel cohort-summary"
      aria-label="선택한 학번의 적용 기준"
    >
      <div className="section-heading">
        <h2>
          {profile.admission_year}학번 · {profile.track}과정 적용 기준
        </h2>
        <span className="tag amber">학교 최종 확인 필요</span>
      </div>
      <div className="form-grid cohort-selectors">
        <label>
          입학연도 (학번)
          <select
            value={profile.admission_year}
            onChange={(e) =>
              void onChange(Number(e.target.value), profile.track)
            }
          >
            {config.admission_years.map((year) => (
              <option key={year} value={year}>
                {year}학번
              </option>
            ))}
          </select>
        </label>
        <label>
          이수 과정
          <select
            value={profile.track}
            onChange={(e) =>
              void onChange(
                profile.admission_year,
                e.target.value as Profile["track"],
              )
            }
          >
            <option>심화</option>
            <option>일반</option>
          </select>
        </label>
      </div>
      <p>
        총 {rule.thresholds["총 졸업인정학점"]}학점 · 전공{" "}
        {rule.thresholds["전공"]}학점 · MSC {rule.thresholds["MSC 합계"]}학점 ·
        교양 인정 상한 {rule.liberal_cap}학점
      </p>
      <p>
        특성화교양:{" "}
        {rule.thresholds["특성화교양"]
          ? `${rule.thresholds["특성화교양"]}학점`
          : "이 학번의 별도 필수요건 없음"}{" "}
        · SW·데이터:{" "}
        {rule.thresholds["SW·데이터활용"]
          ? `${rule.thresholds["SW·데이터활용"]}학점`
          : "이 학번의 별도 필수요건 없음"}
      </p>
      <details>
        <summary>영역별 기준과 원본 확인</summary>
        {Object.entries(rule.thresholds).map(([key, value]) => (
          <p key={key}>
            {key}: {value}학점
          </p>
        ))}
        <p>{rule.msc_detail}</p>
        {profile.track === "심화" && (
          <p>
            {profile.admission_year <= 2020
              ? "학과 지정 기준: 물리(1)와 물리실험(1)을 함께 점검합니다."
              : "대학 공통 기준을 적용한 참고값입니다. 이 학번의 학과 지정 과학과목은 추가 확인이 필요합니다."}
          </p>
        )}
        <p>{rule.source}</p>
        <p className="muted">
          학번은 입학연도, 선수·설계 조건은 수강연도와 학과 내규를 함께
          적용합니다. 과정 선택만으로 변경 승인이 성립하지 않습니다.
        </p>
      </details>
    </section>
  );
}
