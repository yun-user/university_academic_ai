"""Validate a student-edited plan without silently repairing invalid choices."""
from pydantic import Field, field_validator

from src.planning.audit import audit, equivalence_map
from src.planning.models import Course, StrictModel
from src.planning.planner import PlannedCourse, Roadmap, Semester, _attempt, build_roadmap


class Placement(StrictModel):
    code: str = Field(min_length=1, max_length=30)
    semester: int = Field(ge=0, le=11)

    @field_validator("code")
    @classmethod
    def code_format(cls, value):
        return Course.nonblank_code(Course.valid_code(value))


def validate_plan(attempts, profile, rules, candidates, options, placements):
    baseline = build_roadmap(attempts, profile, rules, candidates, options)
    rows = [a.model_copy(update={"status": "취득", "grade": "P"})
            if options.assume_in_progress_passed and a.status == "수강중" else a for a in attempts]
    aliases = equivalence_map([*rows, *candidates])
    identity = lambda code: aliases.get(code, code)
    current = audit(rows, profile, rules, equivalences=candidates)
    completed = {identity(code) for code in current.recognized_codes}
    reserved = {identity(a.code) for a in rows if a.status == "수강중" or
                (a.status == "취득" and a.grade not in {"F", "F0", "NP"})}
    excluded = {identity(code.strip().upper()) for code in options.excluded_codes}
    by_code = {c.code: c for c in candidates}
    periods = [Semester(s.year, s.term, []) for s in baseline.semesters]
    violations, seen, chosen = [], set(reserved), []
    for placement in placements:
        course = by_code.get(placement.code)
        if course is None:
            violations.append(f"{placement.code}: 후보 목록에 없는 과목입니다.")
            continue
        if placement.semester >= options.semesters:
            violations.append(f"{course.code}: 계획 범위 밖 학기입니다.")
            continue
        code = identity(course.code)
        if code in seen:
            violations.append(f"{course.code}: 이미 이수·수강중이거나 중복 배치된 과목입니다.")
        if code in excluded:
            violations.append(f"{course.code}: 추천에서 제외한 과목입니다.")
        if course.category == "미확인":
            violations.append(f"{course.code}: 이수구분을 먼저 확인하세요.")
        if periods[placement.semester].term not in course.semesters:
            violations.append(f"{course.code}: 선택한 학기는 입력된 개설 학기가 아닙니다.")
        taken = reserved | {identity(c.code) for _, c in chosen}
        if {identity(x) for x in course.alternatives} & taken or any(
                identity(c.code) in taken and code in {identity(x) for x in c.alternatives} for c in candidates):
            violations.append(f"{course.code}: 이수·배치한 선택 대안과 충돌합니다.")
        seen.add(code)
        chosen.append((placement.semester, course))
    for offset, period in enumerate(periods):
        this_term = [c for index, c in chosen if index == offset]
        concurrent_completed = completed | {identity(c.code) for c in this_term}
        credits = sum(c.credits for c in this_term)
        if credits > options.limit_for(offset) + 1e-9:
            violations.append(f"{period.year}년 {period.term}학기: {credits:g}학점으로 한도 {options.limit_for(offset):g}학점을 초과합니다.")
        for course in this_term:
            missing = [p for p in course.prerequisites if identity(p) not in completed]
            if missing:
                violations.append(f"{course.code}: 앞 학기에 이수해야 할 선수과목 {', '.join(missing)}을 확인하세요.")
            missing_concurrent = [p for p in course.concurrent if identity(p) not in concurrent_completed]
            if missing_concurrent:
                violations.append(f"{course.code}: 선이수 또는 같은 학기 병수 과목 {', '.join(missing_concurrent)}이 필요합니다.")
            period.courses.append(PlannedCourse(course.code, course.name, course.credits,
                                               "사용자 배치 · 입력된 제약 검사", course.source))
            rows.append(_attempt(course, period.year, period.term))
        completed.update(identity(c.code) for c in this_term)
    if violations:
        return None, list(dict.fromkeys(violations))
    projected = audit(rows, profile, rules, equivalences=candidates)
    unresolved = list(projected.warnings) + [f"{c.key}: {c.status} (남은 값 {c.missing:g})"
                                           for c in projected.checks if c.status != "충족"]
    return Roadmap(periods, projected, unresolved, baseline.assumptions +
                   ["사용자가 직접 조정한 계획입니다. 입력된 제약만 검사했으며 공식 개설·선수조건과 별도 대조해야 합니다."]), []
