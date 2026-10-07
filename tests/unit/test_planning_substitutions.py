"""Synthetic recognition scenarios; these are not Hongik substitution rules."""
import pytest
from pydantic import ValidationError

from src.config import PROJECT_ROOT
from src.planning.audit import audit
from src.planning.models import Attempt, Candidate, PlanOptions, Profile, Substitution
from src.planning.planner import build_roadmap
from src.planning.rules import load_rules


def relation(**changes):
    return Substitution(**{"required_code":"OLD", "replacement_code":"NEW", "track":"일반",
        "start_year":2024, "start_term":2, "end_year":2025, "end_term":1,
        "source":"가상 시험 규칙 — 실제 학교 인정 자료 아님", "confirmed":True, **changes})


def earned(code="NEW", **changes):
    return Attempt(**{"code":code,"name":code,"credits":3,"category":"전공","year":2024,
        "term":2,"grade":"B0",**changes})


def inspect(rows, *relations, track="일반", required=("OLD",)):
    return audit(rows, Profile(track=track,required_codes=required,substitutions=relations), load_rules(PROJECT_ROOT,track))


@pytest.mark.parametrize("year,term,accepted",[(2024,1,False),(2024,3,False),(2024,2,True),
    (2024,4,True),(2025,1,True),(2025,3,False),(2025,2,False)])
def test_recognition_period_includes_boundaries_and_orders_summer(year,term,accepted):
    result = inspect([earned(year=year,term=term)],relation())
    assert ("OLD" in result.requirement_codes) == accepted
    assert bool(result.substitutions_applied) == accepted


def test_substitution_is_directional_without_credit_or_prerequisite_identity_changes():
    result = inspect([earned()],relation())
    assert result.recognized_codes == {"NEW"}
    assert result.requirement_codes == {"NEW","OLD"}
    assert next(c for c in result.checks if c.key=="총 졸업인정학점").current == 3
    check = next(c for c in result.checks if c.key=="개인 필수 OLD")
    assert check.status == "충족"
    assert "가상 시험 규칙" in check.detail
    reverse = inspect([earned("OLD")],relation(),required=("NEW",))
    assert "NEW" not in reverse.requirement_codes
    both = inspect([earned(),earned("OLD")],relation())
    assert len(both.counted) == 2


def test_no_transitive_or_equivalent_expansion_of_confirmation():
    result = inspect([earned()],relation(),relation(required_code="OLDER",replacement_code="OLD"),required=("OLDER",))
    assert "OLDER" not in result.requirement_codes
    result = inspect([earned("ALIAS",equivalent_code="NEW")],relation())
    assert "OLD" not in result.requirement_codes


def test_unconfirmed_or_other_track_does_not_apply():
    result = inspect([earned()],relation(confirmed=False))
    assert "OLD" not in result.requirement_codes
    assert any("확인 표시" in w for w in result.warnings)
    assert "OLD" not in inspect([earned()],relation(),track="심화").requirement_codes


@pytest.mark.parametrize("changes",[{"grade":"F"},{"grade":"미확정"},{"status":"수강중"},
                                    {"status":"인정제외"},{"category":"미확인"}])
def test_only_recognized_earned_attempts_can_satisfy_a_substitution(changes):
    assert "OLD" not in inspect([earned(**changes)],relation()).requirement_codes


def test_duplicate_attempts_cannot_satisfy_a_substitution():
    assert "OLD" not in inspect([earned(),earned(year=2025,term=1)],relation()).requirement_codes


@pytest.mark.parametrize("changes",[{"source":" "},{"required_code":" "},{"required_code":"NEW"},
    {"end_year":2024,"end_term":3},{"end_year":None},{"end_term":None}])
def test_invalid_confirmation_records_fail(changes):
    with pytest.raises(ValidationError):
        relation(**changes)


def test_future_replacement_is_planned_and_does_not_waive_prerequisites():
    profile = Profile(track="일반",required_codes=("OLD",),substitutions=(relation(end_year=None,end_term=None),))
    rules = load_rules(PROJECT_ROOT,"일반")
    courses = [Candidate(code="NEW",name="가상대체과목",credits=3,category="전공",semesters=(1,2)),
               Candidate(code="NEXT",name="가상후속과목",credits=3,category="전공",semesters=(1,2),prerequisites=("OLD",))]
    plan = build_roadmap([],profile,rules,courses,PlanOptions(start_year=2027,semesters=2))
    assert [c.code for s in plan.semesters for c in s.courses] == ["NEW"]
    assert "OLD" in plan.projected.requirement_codes
    assert not any(s.startswith("필수 OLD:") for s in plan.unresolved)
    assert "가상 시험 규칙" in plan.as_dict()["projected"]["substitutions_applied"][0]["source"]


def test_expired_rule_does_not_satisfy_future_plan():
    profile = Profile(track="일반",required_codes=("OLD",),substitutions=(relation(),))
    course = Candidate(code="NEW",name="가상대체과목",credits=3,category="전공",semesters=(1,))
    plan = build_roadmap([],profile,load_rules(PROJECT_ROOT,"일반"),[course],PlanOptions(start_year=2027,semesters=1))
    assert "OLD" not in plan.projected.requirement_codes
    assert any(s.startswith("필수 OLD:") for s in plan.unresolved)


def test_whitespace_course_identifier_is_invalid():
    with pytest.raises(ValidationError):
        earned(" ")
