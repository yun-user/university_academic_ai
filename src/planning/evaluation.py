"""Reproducible synthetic acceptance scenarios, distinct from rule accuracy."""
from src.planning.audit import audit
from src.planning.models import Attempt, Candidate, PlanOptions, Profile, Substitution
from src.planning.planner import build_roadmap
from src.planning.rules import load_rules


def evaluate_scenarios(root):
    results = []
    def record(name, expected, actual):
        results.append({"scenario":name,"expected":expected,"actual":actual,"passed":expected==actual})
    def course(code, **values):
        return Attempt(**{"code":code,"name":"가상 "+code,"credits":3,"category":"전공","year":2020,"grade":"P",**values})
    def value(result, key):
        return next(c.current for c in result.checks if c.key==key)
    for track in ("심화","일반"):
        profile, rules = Profile(track=track), load_rules(root,track)
        result = audit([course("A"),course("B",grade="F"),course("C",status="수강중")],profile,rules)
        record(track+": F·수강중 제외",[3,3],[value(result,"총 졸업인정학점"),result.pending_credits])
        result = audit([course("A"),course("A",year=2021)],profile,rules)
        record(track+": 재수강 중복 보류",0,value(result,"총 졸업인정학점"))
        rows = [course(f"L{i}",credits=10,category="교양선택") for i in range(6)]+[course("M")]
        result = audit(rows,profile,rules)
        record(track+": 교양 상한 적용",43 if track=="심화" else 53,value(result,"총 졸업인정학점"))
        rows = [course(f"AREA{i}",category="전문교양",area=i) for i in (1,2,3,4,6,7)]
        result = audit(rows,profile,rules)
        record(track+": 6영역과 필수5영역 구분",[6,0],[value(result,"교양 6개 영역"),value(result,"교양 5영역")])
        candidates = [Candidate(code="A",name="가상 선수",credits=3,category="전공",semesters=(1,)),
                      Candidate(code="B",name="가상 후속",credits=3,category="전공",semesters=(2,),prerequisites=("A",))]
        plan = build_roadmap([],profile,rules,candidates,PlanOptions(start_year=2027,semesters=2,credit_limit=3))
        record(track+": 선수·개설학기·한도",[["A"],["B"]],[[c.code for c in s.courses] for s in plan.semesters])
        candidates[0] = candidates[0].model_copy(update={"prerequisites":("B",)})
        plan = build_roadmap([],profile,rules,candidates,PlanOptions(start_year=2027,semesters=2))
        record(track+": 순환 선수조건 보류",[[],[]],[[c.code for c in s.courses] for s in plan.semesters])
        rule = Substitution(required_code="OLD",replacement_code="NEW",track=track,start_year=2024,start_term=2,
                            end_year=2025,end_term=1,source="합성 평가 사례: 학교 규정 아님",confirmed=True)
        profile = Profile(track=track,required_codes=("OLD",),substitutions=(rule,))
        accepted = audit([course("NEW",year=2024,term=2)],profile,rules)
        rejected = audit([course("NEW",year=2024,term=3)],profile,rules)
        record(track+": 대체인정 시작 경계",[True,False],["OLD" in accepted.requirement_codes,"OLD" in rejected.requirement_codes])
    for year, specialized, sw, science, computing in (
        (2018, 0, 0, 8, 0), (2019, 3, 0, 8, 0), (2020, 3, 0, 8, 2),
        (2021, 3, 0, 8, 2), (2022, 3, 9, 8, 2), (2023, 3, 9, 8, 2),
        (2024, 3, 9, 4, 3), (2025, 3, 9, 4, 3), (2026, 3, 9, 4, 3)):
        for track in ("심화", "일반"):
            rules = load_rules(root, track, year)
            keys = ("특성화교양", "SW·데이터활용", "MSC과학", "MSC전산")
            record(f"{year}학번 {track}: 학번별 영역 기준", [specialized, sw, 4 if track == "심화" else science,
                   3 if track == "심화" else computing], [rules.thresholds.get(key, 0) for key in keys])
    return {"kind":"synthetic-implementation-evaluation","real_student_accuracy":None,
            "notice":"합성 사례의 구현 검증입니다. 실제 학생·학교 규정의 정확도 평가가 아닙니다.",
            "total":len(results),"passed":sum(r["passed"] for r in results),"results":results}
