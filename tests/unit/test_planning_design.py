import json

import pytest

from src.config import PROJECT_ROOT
from src.planning.audit import audit
from src.planning.catalog import load_catalog
from src.planning.design import load_design_policy
from src.planning.io import read_transcript, write_transcript
from src.planning.models import Attempt, Profile
from src.planning.rules import load_rules


def course(code="704805", **patch):
    policy = load_design_policy(PROJECT_ROOT)
    row = next(r for r in policy["rows"] if r["code"] == code)
    return Attempt(**(dict(code=code, name=row["name"], credits=row["credits"],
                          category="전공선택", year=2020, grade="B0") | patch))


def evaluate(rows, year=2020):
    return audit(rows, Profile(admission_year=year), load_rules(PROJECT_ROOT, "심화", year))


def test_live_table_all_allocations_without_inflating_total_credit():
    expected = {"725843": 2, "704828": 2, "704833": 1, "704822": 1, "704826": 1,
                "704612": 1, "704511": 1, "704836": 1, "704805": 1, "704811": 1,
                "704711": 3, "704814": 3}
    rows = [course(code) for code in expected]
    result = evaluate(rows)
    assert {r["code"]: r["counted_credits"] for r in result.design_allocations} == expected
    checks = {c.key: c.current for c in result.checks}
    assert checks["설계 인정학점"] == 18
    assert checks["총 졸업인정학점"] == sum(r.credits for r in rows) == 36
    assert all(r.design_credits == 0 for r in rows)  # Original transcript is preserved.
    assert all(r["source"].endswith("/curriculum/courses") for r in result.design_allocations)


def test_core_eight_plus_elements_four_meet_twelve():
    result = evaluate([course(c) for c in ("725843", "704711", "704814", "704828", "704826", "704805")])
    check = next(c for c in result.checks if c.key == "설계 인정학점")
    assert (check.current, check.status) == (12, "충족")


@pytest.mark.parametrize("year,expected", [(2018,0), (2019,1), (2026,1), (2027,0)])
def test_taken_year_scope_is_separate_from_admission_year(year, expected):
    row = evaluate([course(year=year)], year=2018).design_allocations[0]
    assert row["counted_credits"] == expected
    assert row["mode"] == ("auto" if expected else "held")


@pytest.mark.parametrize("patch", [{"code":"OTHER"}, {"name":"다른 과목"}, {"credits":2},
                                  {"category":"미확인"}, {"category":"일반선택"},
                                  {"code":"OTHER", "equivalent_code":"704805"}])
def test_unverified_identity_never_inherits_design(patch):
    assert evaluate([Attempt(**(course().model_dump() | patch))]).design_allocations[0]["counted_credits"] == 0


def test_known_portal_name_markers_and_data_spelling_only():
    row = course("704822", name="데이타베이스 및 실습(*) (C)")
    assert evaluate([row]).design_allocations[0]["counted_credits"] == 1
    assert evaluate([course("704836", name="통신시스템실험")]).design_allocations[0]["counted_credits"] == 0


@pytest.mark.parametrize("patch", [{"grade":"F"}, {"grade":"NP"}, {"grade":"미확정"},
                                  {"status":"수강중"}, {"status":"인정제외"}])
def test_unearned_design_does_not_count(patch):
    row = evaluate([course(**patch)]).design_allocations[0]
    assert row["credits"] == 1 and row["counted_credits"] == 0


def test_duplicates_and_manual_zero_survive_csv_roundtrip():
    assert sum(r["counted_credits"] for r in evaluate([course(), course(year=2021)]).design_allocations) == 0
    rows = [course(design_override=True), course("704828", design_credits=1.5)]
    result = evaluate(read_transcript(write_transcript(rows)))
    assert [(r["mode"], r["counted_credits"]) for r in result.design_allocations] == [("manual",0), ("manual",1.5)]
    restored = rows[0].model_copy(update={"design_override":False})
    assert evaluate([restored]).design_allocations[0]["counted_credits"] == 1


def test_catalog_uses_canonical_code_name_and_credits():
    catalog = {c.code:c for c in load_catalog(PROJECT_ROOT)}
    for row in load_design_policy(PROJECT_ROOT)["rows"]:
        assert catalog[row["code"]].design_credits == row["design_credits"]
    assert catalog["704836"].name == "통신프로그래밍"
    assert "725843" in catalog["704836"].prerequisites


def test_reference_source_change_is_detected(tmp_path):
    folder = tmp_path / "config/reviewed_rules"
    (folder / "sources").mkdir(parents=True)
    policy = load_design_policy(PROJECT_ROOT)
    (folder / "design_courses.json").write_text(json.dumps(policy), encoding="utf-8")
    (folder / "sources/design_courses.html").write_bytes(b"changed")
    with pytest.raises(ValueError, match="원본"):
        load_design_policy(tmp_path)
