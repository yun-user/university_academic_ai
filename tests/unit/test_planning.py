"""Meaningful audit and scheduling cases, independent of embeddings and LLMs."""
import math
from dataclasses import replace

import pytest
from pydantic import ValidationError

from src.config import PROJECT_ROOT
from src.planning.audit import audit
from src.planning.catalog import load_catalog
from src.planning.io import read_transcript, sample_transcript, write_transcript
from src.planning.models import Attempt, Candidate, PlanOptions, Profile
from src.planning.planner import build_roadmap
from src.planning.rules import load_rules


def attempt(code="TEST", **kwargs):
    return Attempt(**{"code":code,"name":code,"credits":3,"category":"전공","year":2020,"grade":"B0",**kwargs})


def candidate(code="TEST", **kwargs):
    return Candidate(**{"code":code,"name":code,"credits":3,"category":"전공","semesters":(1,2),**kwargs})


def checks(rows, track="심화", **kwargs):
    return {c.key:c for c in audit(rows,Profile(track=track,**kwargs),load_rules(PROJECT_ROOT,track)).checks}


def test_track_thresholds_and_design_does_not_double_count():
    rows = [attempt(design_credits=2)]
    advanced, general = checks(rows), checks(rows,"일반")
    assert advanced["전공"].required == 54
    assert general["전공"].required == 50
    assert advanced["MSC 합계"].required == 30
    assert general["MSC 합계"].required == 27
    assert advanced["총 졸업인정학점"].current == 3
    assert advanced["설계 인정학점"].current == 2
    assert "설계 인정학점" not in general
    assert "어학 인정·제출" not in general


def test_credit_cap_uses_liberal_electives_but_not_as_professional():
    rows = [attempt(f"L{i}",credits=10,category="교양선택") for i in range(6)]
    rows.append(attempt("MAJOR"))
    assert checks(rows)["총 졸업인정학점"].current == 43
    assert checks(rows,"일반")["총 졸업인정학점"].current == 53
    assert checks(rows)["전문교양"].current == 0


@pytest.mark.parametrize("year", range(2018, 2027))
@pytest.mark.parametrize("track", ["심화", "일반"])
def test_msc_sum_does_not_silently_apply_unverified_historical_cap(year, track):
    # Synthetic passed courses exercise independent category totals and exclusions.
    rows = [attempt(f"M{i}", category="MSC수학") for i in range(4)]
    rows += [attempt(f"S{i}", credits=4, category="MSC과학") for i in range(2)]
    rows += [attempt(f"C{i}", category="MSC전산") for i in range(4)]
    rows += [attempt("F", category="MSC전산", grade="F"),
             attempt("PENDING", category="MSC전산", status="수강중"),
             attempt("EXCLUDED", category="MSC전산", status="인정제외")]
    profile, rules = Profile(admission_year=year, track=track), load_rules(PROJECT_ROOT, track, year)
    assert rules.msc_computing_cap is None
    report = audit(rows, profile, rules)
    result = {c.key: c for c in report.checks}
    assert result["MSC 합계"].current == result["총 졸업인정학점"].current == 32
    assert "수학 12 + 과학 8 + 전산 12 = 32학점" in result["MSC 합계"].detail
    assert report.pending_credits == 3
    assert any("일괄 차감하지 않습니다" in w for w in report.warnings) == (track == "심화")
    # Explicit, separately scoped rules may still impose a known cap.
    capped = audit(rows, profile, replace(rules, msc_computing_cap=6))
    capped_checks = {c.key: c for c in capped.checks}
    assert capped_checks["MSC 합계"].current == 26
    assert capped_checks["총 졸업인정학점"].current == 32


@pytest.mark.parametrize("grade",["F","F0","NP","미확정"])
def test_failed_and_unknown_grades_are_not_earned(grade):
    assert checks([attempt(grade=grade)])["총 졸업인정학점"].current == 0


def test_pending_excluded_unknown_and_duplicates_are_not_counted():
    rows = [attempt("A"),attempt("A",year=2021),attempt("B",status="수강중"),
            attempt("C",status="인정제외"),attempt("D",category="미확인")]
    result = audit(rows,Profile(),load_rules(PROJECT_ROOT,"심화"))
    assert not result.counted
    assert result.pending_credits == 3
    assert len(result.warnings) == 2
    rows[0] = rows[0].model_copy(update={"status":"인정제외"})
    assert checks(rows)["총 졸업인정학점"].current == 3


def test_equivalent_codes_and_failed_attempt_then_pass():
    assert checks([attempt("A"),attempt("B",equivalent_code="A")])["총 졸업인정학점"].current == 0
    assert checks([attempt("A",grade="F"),attempt("A",year=2021)])["총 졸업인정학점"].current == 3


def test_area_breadth_does_not_replace_mandatory_areas():
    rows = [attempt(f"L{i}",category="전문교양",area=i) for i in (1,2,3,4,6,7)]
    result = checks(rows)
    assert result["교양 6개 영역"].status == "충족"
    assert result["교양 5영역"].status == "미충족"


def test_transitive_equivalences_cannot_inflate_credits():
    rows = [attempt("A",equivalent_code="B"),attempt("B",equivalent_code="C"),attempt("C")]
    assert checks(rows)["총 졸업인정학점"].current == 0
    rows[0] = rows[0].model_copy(update={"status":"인정제외"})
    rows[1] = rows[1].model_copy(update={"status":"인정제외"})
    result = audit(rows,Profile(required_codes=("A",)),load_rules(PROJECT_ROOT,"심화"))
    assert result.recognized_codes == {"A","B","C"}
    assert next(c for c in result.checks if c.key=="개인 필수 A").status == "충족"


def test_empty_required_list_and_noncredit_conditions_stay_unknown():
    result = checks([])
    assert result["개인 필수목록 확인"].status == "확인 필요"
    assert result["졸업논문·졸업작품"].status == "확인 필요"
    assert result["학교 최종 졸업사정"].status == "확인 필요"


@pytest.mark.parametrize("kwargs",[{"credits":math.nan},{"credits":math.inf},{"credits":-1},
    {"design_credits":4},{"grade":"SOMETHING"},{"category":"전공","area":4},{"code":"../bad"}])
def test_invalid_inputs_fail(kwargs):
    with pytest.raises(ValidationError):
        attempt(**kwargs)


def test_csv_roundtrip_leading_zeros_and_reject_private_extra_columns():
    rows = sample_transcript()
    assert read_transcript(write_transcript(rows)) == rows
    assert read_transcript(write_transcript(rows))[0].code == "001012"
    raw = write_transcript(rows).decode("utf-8-sig").replace("학수번호,","학번,학수번호,",1)
    with pytest.raises(ValueError):
        read_transcript(raw.encode())


def test_csv_formula_escaped_and_duplicate_columns_rejected():
    output = write_transcript([attempt(name="=1+2")]).decode("utf-8-sig")
    assert "'=1+2" in output
    with pytest.raises(ValueError):
        read_transcript(b"code,code\n1,1\n")


def test_planner_respects_prior_term_prerequisite_and_limits():
    courses = [candidate("A",semesters=(2,)), candidate("B",semesters=(1,),prerequisites=("A",))]
    plan = build_roadmap([],Profile(required_codes=("B",)),load_rules(PROJECT_ROOT,"심화"),courses,
                        PlanOptions(start_year=2027,start_term=1,semesters=4,credit_limit=3))
    assert [c.code for s in plan.semesters for c in s.courses] == ["A","B"]
    assert [c.code for c in plan.semesters[1].courses] == ["A"]
    assert [c.code for c in plan.semesters[2].courses] == ["B"]
    assert all(s.credits <= 3 for s in plan.semesters)


def test_no_same_term_prerequisites_and_cycles_reported():
    courses = [candidate("A"),candidate("B",prerequisites=("A",))]
    options = PlanOptions(start_year=2027,semesters=1,credit_limit=6)
    p = build_roadmap([],Profile(required_codes=("B",)),load_rules(PROJECT_ROOT,"심화"),courses,options)
    assert [c.code for c in p.semesters[0].courses] == ["A"]
    cycles = [candidate("A",prerequisites=("B",)),candidate("B",prerequisites=("A",))]
    p = build_roadmap([],Profile(required_codes=("B",)),load_rules(PROJECT_ROOT,"심화"),cycles,options)
    assert p.semesters[0].courses == []
    assert any("순환" in s for s in p.unresolved)


def test_unknown_offering_exclusion_and_missing_catalog_do_not_fake_completion():
    profile = Profile(track="일반",required_codes=("A","B","C"))
    p = build_roadmap([],profile,load_rules(PROJECT_ROOT,"일반"),[candidate("A",semesters=()),candidate("B")],
        PlanOptions(start_year=2027,excluded_codes=("B",)))
    assert not any(s.courses for s in p.semesters)
    assert any("개설 학기 미확인" in x for x in p.unresolved)
    assert any("추천에서 제외" in x for x in p.unresolved)
    assert any("후보 목록에 없음" in x for x in p.unresolved)


def test_pending_projection_is_optional_and_does_not_mutate_inputs():
    rows = [attempt("A",status="수강중",grade="미확정")]
    profile, rules = Profile(required_codes=("B",)),load_rules(PROJECT_ROOT,"심화")
    courses = [candidate("B",prerequisites=("A",))]
    p = build_roadmap(rows,profile,rules,courses,PlanOptions(start_year=2027,semesters=1))
    assert not p.semesters[0].courses
    p = build_roadmap(rows,profile,rules,courses,PlanOptions(start_year=2027,semesters=1,assume_in_progress_passed=True))
    assert p.semesters[0].courses[0].code == "B"
    assert rows[0].status == "수강중"


def test_real_catalog_does_not_treat_secondary_term_marker_as_offering():
    courses = load_catalog(PROJECT_ROOT)
    assert next(c for c in courses if c.code=="704814").semesters == (2,)
    assert next(c for c in courses if c.code=="704711").semesters == (1,)
    assert not any(c.code in {"부학기","02742"} for c in courses)
    assert all(not c.equivalent_code for c in courses)


def test_candidate_alias_satisfies_required_course_without_false_gap():
    courses = [candidate("NEW", equivalent_code="OLD")]
    p = build_roadmap([], Profile(required_codes=("OLD",)), load_rules(PROJECT_ROOT,"심화"),
                      courses, PlanOptions(start_year=2027, semesters=1))
    assert [c.code for c in p.semesters[0].courses] == ["NEW"]
    assert next(c for c in p.projected.checks if c.key == "개인 필수 OLD").status == "충족"
    assert not any("필수 OLD:" in s for s in p.unresolved)


def test_choice_alternatives_do_not_merge_credits_or_recommend_both():
    courses = [candidate("A", alternatives=("B",)), candidate("B", alternatives=("A",))]
    rules = load_rules(PROJECT_ROOT,"일반")
    profile = Profile(track="일반")
    options = PlanOptions(start_year=2027, semesters=2)
    plan = build_roadmap([], profile, rules, courses, options)
    assert len([c for s in plan.semesters for c in s.courses]) == 1
    plan = build_roadmap([attempt("A"),attempt("B")], profile, rules, courses, options)
    assert len(plan.projected.counted) == 2
    plan = build_roadmap([attempt("A",status="수강중")], profile, rules, courses, options)
    assert not any(s.courses for s in plan.semesters)


def test_real_catalog_does_not_recommend_other_writing_choice_after_pass():
    plan = build_roadmap(sample_transcript(), Profile(track="일반"), load_rules(PROJECT_ROOT,"일반"),
                        load_catalog(PROJECT_ROOT), PlanOptions(start_year=2027))
    assert not {c.code for s in plan.semesters for c in s.courses} & {"001012","001020"}


def test_alias_prerequisite_with_no_credit_gain_is_still_scheduled():
    from dataclasses import replace
    rules = replace(load_rules(PROJECT_ROOT,"심화"), thresholds={"총 졸업인정학점":3,"전공":3})
    courses = [candidate("NEW_A", equivalent_code="OLD_A", category="일반선택"),
               candidate("B", prerequisites=("OLD_A",))]
    p = build_roadmap([attempt("DONE")], Profile(required_codes=("B",)), rules, courses,
                      PlanOptions(start_year=2027, semesters=2, credit_limit=3))
    assert [[c.code for c in s.courses] for s in p.semesters] == [["NEW_A"],["B"]]


def test_candidate_alias_cannot_recommend_retake_or_hide_duplicate_attempts():
    rules = load_rules(PROJECT_ROOT,"심화")
    courses = [candidate("NEW", equivalent_code="OLD")]
    p = build_roadmap([attempt("OLD")], Profile(required_codes=("NEW",)), rules, courses,
                      PlanOptions(start_year=2027, semesters=1))
    assert not p.semesters[0].courses
    assert next(c for c in p.projected.checks if c.key == "개인 필수 NEW").status == "충족"
    assert not any("필수 NEW:" in s for s in p.unresolved)
    p = build_roadmap([attempt("OLD"),attempt("NEW")], Profile(), rules, courses,
                      PlanOptions(start_year=2027, semesters=1))
    assert not p.projected.counted
    assert any("중복·재수강" in s for s in p.unresolved)


def test_excluded_alias_is_reported_as_excluded():
    courses = [candidate("NEW", equivalent_code="OLD")]
    p = build_roadmap([], Profile(required_codes=("OLD",)), load_rules(PROJECT_ROOT,"심화"),
                      courses, PlanOptions(start_year=2027, excluded_codes=("NEW",)))
    assert not any(s.courses for s in p.semesters)
    assert "필수 OLD: 사용자가 추천에서 제외함" in p.unresolved


def test_rule_source_tampering_fails_closed(tmp_path):
    import shutil
    shutil.copytree(PROJECT_ROOT / "config/reviewed_rules",tmp_path / "config/reviewed_rules")
    (tmp_path / "config/reviewed_rules/sources/aid_graduation_credits_2026_p8-16.pdf").write_bytes(b"changed")
    with pytest.raises(ValueError,match="원본이 바뀌"):
        load_rules(tmp_path,"일반")
