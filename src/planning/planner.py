"""Deterministic greedy planning with explicit constraints and residual gaps.

This is not an optimality or graduation guarantee. Only entered prerequisite
edges are enforced; the catalog's future semester offerings are assumptions.
"""
from dataclasses import asdict, dataclass

from src.planning.audit import Audit, audit, equivalence_map
from src.planning.models import Attempt, Candidate, PlanOptions, Profile, academic_period
from src.planning.rules import RuleSet


@dataclass
class PlannedCourse:
    code: str
    name: str
    credits: float
    reason: str
    source: str


@dataclass
class Semester:
    year: int
    term: int
    courses: list[PlannedCourse]

    @property
    def credits(self):
        return round(sum(c.credits for c in self.courses), 2)


@dataclass
class Roadmap:
    semesters: list[Semester]
    projected: Audit
    unresolved: list[str]
    assumptions: list[str]

    def as_dict(self):
        return {"semesters": [{**asdict(s), "credits": s.credits} for s in self.semesters],
                "projected": self.projected.as_dict(), "unresolved": self.unresolved,
                "assumptions": self.assumptions}


def _benefits(before, after):
    gains = []
    for old, new in zip(before.checks, after.checks, strict=True):
        if new.missing < old.missing:
            gains.append((old.key, (old.missing - new.missing) / max(old.required, 1)))
    # Required courses and missing areas take priority over freely chosen credits.
    return sum(v * (1 if k == "총 졸업인정학점" else 5) for k,v in gains), [k for k,v in gains]


def _attempt(course, year, term):
    data = course.model_dump(exclude={"semesters", "prerequisites", "concurrent", "alternatives", "source"})
    return Attempt(**data, year=year, term=term, status="취득", grade="P")


def build_roadmap(attempts: list[Attempt], profile: Profile, rules: RuleSet,
                  candidates: list[Candidate], options: PlanOptions, *, preferences: tuple[str, ...] = ()) -> Roadmap:
    if len({c.code for c in candidates}) != len(candidates):
        raise ValueError("수강 후보 학수번호가 중복됩니다. 한 과목에 개설 학기를 함께 적으세요.")
    rows = list(attempts)
    if options.assume_in_progress_passed:
        rows = [a.model_copy(update={"status":"취득", "grade":"P"}) if a.status == "수강중" else a for a in rows]
    start = academic_period(options.start_year, options.start_term)
    if any(a.status == "취득" and academic_period(a.year, a.term) >= start for a in rows):
        raise ValueError("계획 시작 학기는 취득 내역(수강중 통과 가정 포함)의 마지막 학기보다 뒤여야 합니다.")
    def evaluate(values):
        return audit(values, profile, rules, equivalences=candidates)

    initial = evaluate(rows)
    aliases = equivalence_map([*rows,*candidates])
    completed = set(initial.recognized_codes)
    completed.update(aliases.get(code,code) for code in tuple(completed))
    unresolved = list(initial.warnings)
    # Ambiguous duplicate/unknown attempts must not trigger automatic retakes.
    reserved = {x for a in rows if a.status == "취득" and a.grade not in {"F", "F0", "NP"}
                for x in (a.code, a.identity)}
    reserved.update(x for a in rows if a.status == "수강중" for x in (a.code, a.identity))
    reserved.update(aliases.get(code,code) for code in tuple(reserved))
    excluded = {x.strip().upper() for x in options.excluded_codes}
    excluded.update(aliases.get(code,code) for code in tuple(excluded))
    alternative_edges = {}
    for c in candidates:
        identity = aliases[c.code]
        for code in c.alternatives:
            other = aliases.get(code, code)
            alternative_edges.setdefault(identity, set()).add(other)
            alternative_edges.setdefault(other, set()).add(identity)
    def alternatives_taken(course, taken):
        return bool(alternative_edges.get(aliases[course.code], set()) & taken)

    remaining = {c.code:c for c in candidates if c.code not in reserved | completed | excluded
                 and aliases[c.code] not in reserved | completed | excluded and c.category != "미확인"
                 and not alternatives_taken(c, reserved | completed)}
    # Model preferences only adjust useful choices. They cannot bypass any constraint.
    preference_weights = {code: 1 + .5 * (len(preferences) - i) / len(preferences)
                          for i, code in enumerate(preferences)}
    semesters = []
    current = initial
    for offset in range(options.semesters):
        ordinal = options.start_term - 1 + offset
        year, term = options.start_year + ordinal // 2, ordinal % 2 + 1
        period = Semester(year, term, [])
        start_completed = set(completed)
        while True:
            # Find dependencies of useful courses so an otherwise neutral prerequisite can be scheduled.
            needed = set()
            by_identity = {}
            for course in remaining.values():
                by_identity.setdefault(aliases[course.code], []).append(course)

            def visit(code, seen):
                identity = aliases.get(code, code)
                if identity in seen or identity not in by_identity:
                    return
                seen.add(identity)
                for course in by_identity[identity]:
                    for prerequisite in (*course.prerequisites, *course.concurrent):
                        prerequisite = aliases.get(prerequisite, prerequisite)
                        if prerequisite not in completed:
                            needed.add(prerequisite)
                            visit(prerequisite, seen)
            for course in remaining.values():
                if _benefits(current, evaluate(rows + [_attempt(course, year, term)]))[0] > 0:
                    visit(course.code, set())
            choices = []
            for course in remaining.values():
                if term not in course.semesters or period.credits + course.credits > options.limit_for(offset) + 1e-9:
                    continue
                if not {aliases.get(code,code) for code in course.prerequisites}.issubset(start_completed):
                    continue
                if not {aliases.get(code,code) for code in course.concurrent}.issubset(completed):
                    continue
                next_audit = evaluate(rows + [_attempt(course, year, term)])
                score, reasons = _benefits(current, next_audit)
                if aliases[course.code] in needed:
                    score += 3
                    reasons.append("후속 과목의 입력된 선수조건")
                if score > 0:
                    weight = preference_weights.get(course.code, 1)
                    if weight > 1:
                        reasons.append("LLM 제안 우선순위 반영")
                    choices.append((score * weight / course.credits, course.code, course, next_audit, reasons))
            if not choices:
                break
            _, _, chosen, current, reasons = sorted(choices, key=lambda x:(-x[0],x[1]))[0]
            rows.append(_attempt(chosen, year, term))
            completed.update((chosen.code, chosen.identity, aliases[chosen.code]))
            period.courses.append(PlannedCourse(chosen.code, chosen.name, chosen.credits, " · ".join(reasons), chosen.source))
            remaining = {k:c for k,c in remaining.items() if aliases[c.code] != aliases[chosen.code]
                         and c.code not in completed and not alternatives_taken(c, completed)
                         and c.code not in chosen.alternatives}
        semesters.append(period)
    for check in current.checks:
        if check.status != "충족":
            unresolved.append(f"{check.key}: {check.status}" + (f" (남은 값 {check.missing:g})" if check.status == "미충족" else ""))
    for code in profile.required_codes:
        identity = aliases.get(code, code)
        if code in current.requirement_codes:
            continue
        candidate = next((c for c in candidates if aliases[c.code] == identity), None)
        if identity in excluded:
            reason = "사용자가 추천에서 제외함"
        elif candidate is None:
            reason = "후보 목록에 없음: 공식 과목 정보 추가 필요"
        elif alternatives_taken(candidate, reserved | completed):
            reason = "선택 대안이 이미 이수·수강중이므로 자동 추천 제외: 개인 필수와 대안 설정을 대조하세요"
        elif not candidate.semesters:
            reason = "개설 학기 미확인"
        elif not {aliases.get(p, p) for p in candidate.prerequisites}.issubset(completed):
            reason = "선수과목 미이수·누락·순환 조건 확인 필요"
        else:
            reason = "선택한 기간·학점 한도 안에 배치하지 못함"
        unresolved.append(f"필수 {code}: {reason}")
    assumptions = ["후보 과목이 입력된 학기에 실제 개설되고 모두 이수된다는 가정입니다.",
                   "선택 대안 중 이미 이수·수강중인 과목이 있으면 다른 대안은 자동 추천하지 않습니다. 이 설정은 기존 취득학점의 중복 인정 여부를 결정하지 않습니다.",
                   "입력된 선수조건만 검사합니다. 조건이 비어 있는 과목의 선수조건이 없다고 검증한 것은 아닙니다.",
                   "학점 한도는 사용자가 정한 계획값입니다. 클래스넷의 실제 수강가능학점과 대조하세요.",
                   "빠른 휴리스틱 배치이며 최단 졸업·최적 계획을 보장하지 않습니다. 시간표 충돌·정원·계절학기는 반영하지 않습니다."]
    if any(c.equivalent_code for c in candidates):
        assumptions.append("예상 점검에는 후보 표에 입력한 동일과목 관계도 적용합니다. 현재 이수내역에도 공식 확인된 관계를 반영해야 두 점검의 인정 기준이 일치합니다.")
    if profile.substitutions:
        assumptions.append("대체인정은 사용자가 확인한 과정·수강연도·학기에 한해 필수요건에 적용합니다. 학점·이수구분·설계학점·선수조건을 변경하거나 대체관계를 연쇄 적용하지 않습니다.")
    if options.assume_in_progress_passed:
        assumptions.append("현재 수강중 과목을 모두 취득한 것으로 가정했습니다. 현재 취득학점과 구분하세요.")
    if preferences:
        assumptions.append("LLM의 과목 우선순위를 최대 1.5배 가중치로 반영하고 개설·선수·중복·학점 조건은 기존 계산기로 검사했습니다. LLM 제안 순서가 실제 배치 순서와 다를 수 있습니다.")
    return Roadmap(semesters, current, list(dict.fromkeys(unresolved)), assumptions)
