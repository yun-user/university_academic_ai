"""Conservative credit allocation: unknowns are never counted as completed."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass

from src.planning.models import Attempt, PASS_GRADES, Profile
from src.planning.rules import RuleSet


@dataclass
class Check:
    key: str
    current: float
    required: float
    status: str
    detail: str = ""

    @property
    def missing(self):
        return round(max(0, self.required - self.current), 2)


@dataclass
class Audit:
    checks: list[Check]
    counted: list[Attempt]
    warnings: list[str]
    pending_credits: float
    excluded_liberal_credits: float
    recognized_codes: set[str]
    requirement_codes: set[str]
    substitutions_applied: list[dict]

    def as_dict(self):
        return {"checks": [{**asdict(c), "missing": c.missing} for c in self.checks],
                "warnings": self.warnings, "pending_credits": self.pending_credits,
                "excluded_liberal_credits": self.excluded_liberal_credits,
                "substitutions_applied": self.substitutions_applied}


def equivalence_map(courses):
    """Union declared aliases, including transitive mappings and cycles."""
    parent = {}
    def find(code):
        parent.setdefault(code, code)
        while parent[code] != code:
            parent[code] = parent[parent[code]]
            code = parent[code]
        return code
    for course in courses:
        a,b = find(course.code),find(course.identity)
        if a != b:
            parent[max(a,b)] = min(a,b)
    return {code:find(code) for code in parent}


def audit(attempts: list[Attempt], profile: Profile, rules: RuleSet, *, equivalences=()) -> Audit:
    if profile.track != rules.track:
        raise ValueError("학생 과정과 규정 과정이 일치하지 않습니다.")
    if profile.admission_year != rules.admission_year:
        raise ValueError("학생 입학연도와 적용 규정의 입학연도가 일치하지 않습니다.")
    groups = defaultdict(list)
    aliases = equivalence_map([*attempts, *equivalences])
    warnings = []
    pending = sum(a.credits for a in attempts if a.status == "수강중")
    for a in attempts:
        if a.status != "취득":
            continue
        if a.grade == "미확정":
            warnings.append(f"{a.code} {a.name}: 성적 미확정으로 합계에서 제외했습니다.")
        if a.grade in PASS_GRADES:
            groups[aliases[a.code]].append(a)
    counted = []
    for key, rows in groups.items():
        if len(rows) > 1:
            warnings.append(f"{key}: 중복·재수강 내역 {len(rows)}건을 모두 보류했습니다. 인정할 한 건만 남기고 나머지는 인정제외로 표시하세요.")
        elif rows[0].category == "미확인":
            warnings.append(f"{key}: 이수구분 미확인으로 합계에서 제외했습니다.")
        else:
            counted.append(rows[0])
    totals = defaultdict(float)
    for a in counted:
        totals[a.category] += a.credits
        totals["설계 인정학점"] += a.design_credits
        totals["SW·데이터활용"] += a.sw_data_credits
    liberal = sum(totals[k] for k in ("전문교양", "교양선택", "특성화교양"))
    excess = max(0, liberal - rules.liberal_cap)
    totals["총 졸업인정학점"] = sum(a.credits for a in counted) - excess
    if rules.msc_computing_cap is not None:
        over = max(0, totals["MSC전산"] - rules.msc_computing_cap)
        if over:
            warnings.append(f"MSC전산 {over:g}학점은 학과 내규의 {rules.msc_computing_cap:g}학점 상한을 넘어 MSC 합계에서 제외했습니다. 총 졸업인정학점에는 포함합니다. 최신 내규는 학교 확인이 필요합니다.")
        totals["MSC전산"] = min(totals["MSC전산"], rules.msc_computing_cap)
    totals["MSC 합계"] = sum(totals[k] for k in ("MSC수학", "MSC과학", "MSC전산"))
    checks = [Check(key, round(totals[key], 2), value,
                    "충족" if totals[key] >= value else "미충족",
                    "입력한 인정 이수구분 기준" if key != "총 졸업인정학점" else f"교양 인정 상한 {rules.liberal_cap:g}학점 적용")
              for key, value in rules.thresholds.items()]
    if rules.msc_computing_cap is not None:
        for check in checks:
            if check.key in {"MSC전산", "MSC 합계"}:
                check.detail += f" · 2019.12 학과 내규: 전산 최대 {rules.msc_computing_cap:g}학점, 최신 개정 확인 필요"
    earned_groups = {aliases[a.code] for a in counted}
    identities = {code for code,group_id in aliases.items() if group_id in earned_groups}
    requirement_codes = set(identities)
    substitutions_applied = []
    for substitution in profile.substitutions:
        if substitution.track != profile.track:
            continue
        label = f"{substitution.replacement_code} → {substitution.required_code}"
        if not substitution.confirmed:
            warnings.append(f"대체인정 {label}: 학교 확인 표시가 없어 적용하지 않았습니다.")
            continue
        # Use the actual course code and earned attempt date. Neither equivalent
        # aliases nor another substitution expand the confirmed rule's scope.
        matching = [a for a in counted if a.code == substitution.replacement_code and substitution.covers(a)]
        if matching:
            requirement_codes.add(substitution.required_code)
            substitutions_applied.append({"required_code": substitution.required_code,
                "replacement_code": substitution.replacement_code, "year": matching[0].year,
                "term": matching[0].term, "source": substitution.source})

    def group(key, codes, detail):
        ok = bool(requirement_codes.intersection(codes))
        applied = [s for s in substitutions_applied if s["required_code"] in codes]
        if applied:
            detail += " · 사용자 확인 대체인정: " + "; ".join(f"{s['replacement_code']} → {s['required_code']} ({s['source']})" for s in applied)
        checks.append(Check(key, int(ok), 1, "충족" if ok else "미충족", detail))

    group("기초교양: 글쓰기", {"001012", "001020"}, "논리적사고와글쓰기(공학) 또는 공학글쓰기. 다른 대체과목은 동일과목 코드 확인 필요")
    group("기초교양: 영어", {"001009"}, "영어 또는 공식적으로 인정된 동일과목")
    areas = {a.area for a in counted if a.category == "전문교양" and a.area}
    checks.append(Check("교양 6개 영역", len(areas), 6, "충족" if len(areas) >= 6 else "미충족", "7개 영역 중 6개 이상, 4·5영역은 별도로 필수"))
    for area in (4, 5):
        checks.append(Check(f"교양 {area}영역", int(area in areas), 1,
                            "충족" if area in areas else "미충족", "예술과 디자인 / 제2외국어와 한문"))
    if rules.science_mode == "one_set":
        pairs = ({"012102", "012103"}, {"012108", "012109"})
        # Partial progress lets the planner start a missing pair even when all
        # numeric credit minima are already met. Mixing two subjects is not a set.
        progress = max(len(pair & requirement_codes) / len(pair) for pair in pairs)
        checks.append(Check("과학 실험 포함 1set", progress, 1,
                            "충족" if progress == 1 else "미충족",
                            "물리(1)+물리실험(1) 또는 화학(1)+화학실험(1). 같은 계열의 이론·실험 2과목 중 이수 비율(0/0.5/1); 다른 계열을 혼합하면 미충족"))
    else:
        science_codes = ["012102", "012103"] + (["012108", "012109"] if rules.science_mode == "both" else [])
        for code in science_codes:
            group(f"과학 필수 {code}", {code}, "선택한 학번의 과학 필수·실험 기준. 인정 대체과목은 학과 확인 필요")
    if profile.track == "심화":
        group("기초설계 포함", {"725843"}, "창의적공학설계입문 또는 인정 대체과목")
    group("종합설계(1) 포함", {"704711"}, "2026 이수체계도 1쪽: 과정과 상관없이 종합설계(1)·(2) 모두 이수. 예외·대체승인 별도 확인")
    group("종합설계 포함", {"704814"}, "2026 이수체계도 1쪽: 종합설계(2), 종합설계(1)과 병수 가능. 졸업작품 제출·승인은 별도 확인")
    for code in profile.required_codes:
        group(f"개인 필수 {code}", {code}, "학교에서 확인 후 사용자가 입력한 필수과목")
    checks.append(Check("개인 필수목록 확인", int(profile.required_list_checked), 1,
                        "충족" if profile.required_list_checked else "확인 필요",
                        "빈 목록만으로 필수과목을 모두 이수했다고 가정하지 않습니다."))
    for key, state in [("졸업논문·졸업작품", profile.thesis), *([("어학 인정·제출", profile.english)] if profile.track == "심화" else [])]:
        checks.append(Check(key, int(state == "충족"), 1, state, "사용자 확인 상태. 교과목 취득과 제출·승인은 별개입니다."))
    manual = [("전공기초영어 지정과목 확인", profile.basic_english_course, "전공기초영어 I/II 중 인정 과목인지 확인. 학점 합계와 별개")]
    if "특성화교양" in rules.thresholds:
        manual.append(("특성화교양 지정과목 확인", profile.specialized_course, "디자인씽킹·창업과실용법률 중 인정 과목인지 확인. 학점 합계와 별개"))
    if "SW·데이터활용" in rules.thresholds:
        manual.append(("SW·데이터 인정과목·중복인정 확인", profile.sw_data_course, "대상 과목과 다른 영역의 중복 인정 범위를 학교에 확인. 총학점에는 같은 과목을 한 번만 합산"))
    if profile.track == "심화" and profile.admission_year >= 2021:
        manual.append(("학과 과학 지정과목 확인", profile.science_course, "대학 공통 1set 외 해당 학번의 학과 지정 과학과목·실험을 확인. 학과 표 직접 확인 범위는 2020학번까지"))
    if profile.track == "심화":
        manual += [("설계 이수순서·프로그램 이수체계 확인",profile.design_sequence,"2026 공통 내규 제12·13조: 기초→요소→종합 순서 또는 승인 예외"),
                   ("교양·MSC 인정 범위 확인",profile.recognized_course_scope,"2026 공통 내규 제8조: 사이버·서울캠퍼스 강좌 인정 제한 및 승인 예외")]
    else:
        manual.append(("일반과정 적용·변경 승인 확인",profile.general_approval,"2026 공통 내규 제5조의 과정 변경 예외·승인 절차 확인. 비교 계산만으로 과정 변경이 되지 않음"))
        manual.append(("일반과정 어학요건 확인",profile.english,"2019.12 학과 내규 표5는 일반과정도 어학 제출 대상으로 기술. 현재 적용·예외를 학교에 확인해야 함"))
    for key, state, detail in manual:
        checks.append(Check(key, int(state == "충족"), 1, state, "사용자 확인: " + detail))
    checks.append(Check("학교 최종 졸업사정", 0, 1, "확인 필요", "등록학기·평점·과정별 세부 인정 등은 학교에서 최종 확인"))
    return Audit(checks, counted, warnings, round(pending, 2), round(excess, 2), identities,
                 requirement_codes, substitutions_applied)
