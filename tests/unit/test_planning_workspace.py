import json

import pytest
from pydantic import ValidationError

from src.config import PROJECT_ROOT
from src.planning.audit import audit
from src.planning.catalog import candidate_rows, load_catalog, parse_candidates
from src.planning.io import sample_transcript
from src.planning.models import Attempt, PlanOptions, Profile, Substitution
from src.planning.planner import build_roadmap
from src.planning.report import render_report
from src.planning.rules import load_rules
from src.planning.workspace import PlannerWorkspace, read_workspace, restore_session, source_fingerprint, write_workspace


def workspace():
    return PlannerWorkspace(saved_on="2026-10-05",rules_fingerprint=source_fingerprint(PROJECT_ROOT),
        attempts=sample_transcript(),profile=Profile(track="일반",required_codes=("TEST",),general_approval="충족",
        substitutions=(Substitution(required_code="TEST",replacement_code="704818",track="일반",start_year=2020,
                                    source="가상 검증",confirmed=True),)),
        candidates=load_catalog(PROJECT_ROOT),options=PlanOptions(start_year=2027,excluded_codes=("704814",)))


def test_full_workspace_roundtrip_and_atomic_restore():
    expected = workspace()
    restored = read_workspace(write_workspace(expected))
    assert restored == expected
    state = {"planner_revision":5,"unrelated":"keep"}
    restore_session(state,restored)
    assert state["planner_track"] == "일반"
    assert state["planner_general_approval"] == "충족"
    assert state["planner_rows"][0]["학수번호"] == "001012"
    assert state["planner_substitutions"][0]["confirmed"] is True
    assert state["unrelated"] == "keep"
    assert state["planner_revision"] == 6
    candidates, excluded = parse_candidates(state["planner_candidate_rows"])
    assert candidates == restored.candidates
    assert excluded == ("704814",)


@pytest.mark.parametrize("raw",[b'{"version":2,"version":2}',b'[]',b'{',b'\xff',b'x'*2_000_001,
                                 b'{"version":1,"roadmap":{}}'],ids=["duplicate-key","array","broken","encoding","oversize","legacy"])
def test_invalid_backups_fail_without_partial_loading(raw):
    with pytest.raises(ValueError):
        read_workspace(raw)


def test_unknown_fields_computed_results_and_nonfinite_values_rejected():
    data = workspace().model_dump(mode="json")
    data["result"] = {"graduated":True}
    with pytest.raises(ValueError):
        read_workspace(json.dumps(data).encode())
    del data["result"]
    data["attempts"][0]["credits"] = float("nan")
    with pytest.raises(ValueError):
        read_workspace(json.dumps(data).encode())


def test_duplicates_and_overlong_backup_lists_rejected():
    data = workspace().model_dump(mode="json")
    data["candidates"].append(data["candidates"][0])
    with pytest.raises(ValueError):
        read_workspace(json.dumps(data).encode())
    data = workspace().model_dump(mode="json")
    data["attempts"] *= 64
    with pytest.raises(ValueError):
        read_workspace(json.dumps(data).encode())


def test_report_escapes_user_content_without_remote_assets():
    w = workspace()
    w.candidates[0].name = '<img src=x onerror="alert(1)">'
    rules = load_rules(PROJECT_ROOT,w.profile.track)
    plan = build_roadmap(w.attempts,w.profile,rules,w.candidates,w.options)
    plan.semesters[0].courses[0].name = '<script>alert(1)</script>'
    report = render_report(w.profile,audit(w.attempts,w.profile,rules),plan,rules).decode()
    assert '<script>' not in report
    assert '&lt;script&gt;' in report
    assert 'Content-Security-Policy' in report
    assert '계획 후에도 남는 항목' in report
    assert '공식 졸업판정이 아닙니다' in report


def test_future_completed_courses_cannot_unlock_an_earlier_plan():
    row = Attempt(code="A",name="A",credits=3,category="전공",year=2027,term=2,grade="P")
    with pytest.raises(ValueError,match="마지막 학기"):
        build_roadmap([row],Profile(),load_rules(PROJECT_ROOT,"심화"),[],PlanOptions(start_year=2027))
    with pytest.raises(ValidationError):
        PlanOptions(start_year=2100,semesters=3)


def test_new_manual_conditions_do_not_become_complete_from_credits():
    general = audit(sample_transcript(),Profile(track="일반"),load_rules(PROJECT_ROOT,"일반"))
    assert next(c for c in general.checks if c.key=="일반과정 적용·변경 승인 확인").status == "확인 필요"
    advanced = audit(sample_transcript(),Profile(),load_rules(PROJECT_ROOT,"심화"))
    assert next(c for c in advanced.checks if c.key=="설계 이수순서·프로그램 이수체계 확인").status == "확인 필요"


def test_acceptance_scenarios_report_does_not_claim_real_student_accuracy():
    from src.planning.evaluation import evaluate_scenarios
    report = evaluate_scenarios(PROJECT_ROOT)
    assert report["total"] == report["passed"] == 32
    assert report["real_student_accuracy"] is None
