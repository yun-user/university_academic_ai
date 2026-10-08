from datetime import date
from pathlib import Path
import json
import shutil

import pytest

from src.planning.audit import audit
from src.planning.language import assess_language
from src.planning.llm import make_context
from src.planning.models import LanguageRecord, Profile, PlanOptions
from src.planning.planner import build_roadmap
from src.planning.rules import load_department_guidance, load_rules

ROOT = Path(__file__).resolve().parents[2]
TODAY = date(2026, 10, 8)


def record(**patch):
    return LanguageRecord.model_validate(dict(exam="TOEIC", score="600", expires_on="2027-01-01",
        submitted_on="2026-10-01", submission_confirmed=True) | patch)


def check(value):
    return assess_language(value, load_department_guidance(ROOT), today=TODAY)


@pytest.mark.parametrize("exam,below,minimum,above", [
    ("TOEIC", "599", "600", "990"), ("TEPS", "481", "482", "990"),
    ("NEW_TEPS", "226", "227", "600"), ("TOEFL_IBT", "68", "69", "120"),
    ("TOEIC_SPEAKING", "109", "110", "200"), ("OPIC", "IL", "IM1", "AL"),
    ("TEPS_SPEAKING", "42", "43", "99"), ("HSK4", "209", "210", "300"), ("JPT", "599", "600", "990")])
def test_all_published_score_boundaries(exam, below, minimum, above):
    assert check(record(exam=exam, score=below))["status"] == "미충족"
    assert check(record(exam=exam, score=minimum))["status"] == "충족"
    assert check(record(exam=exam, score=above))["status"] == "충족"


@pytest.mark.parametrize("patch", [
    {"score":""}, {"score":"9999"}, {"score":"600점"}, {"score":"NaN"}, {"score":"６００"},
    {"score":"-1"}, {"score":"600.5"}, {"exam":"OPIC","score":"IM"}, {"exam":"OTHER","score":"6"},
    {"expires_on":None}, {"submitted_on":None}, {"submission_confirmed":False}, {"submitted_on":"2026-11-01"}])
def test_unknown_or_incomplete_never_passes(patch):
    assert check(record(**patch))["status"] == "확인 필요"


def test_expiry_is_checked_at_confirmed_submission_not_arbitrary_two_years():
    assert check(record(expires_on="2026-09-30"))["status"] == "미충족"
    assert check(record(expires_on="2026-10-01"))["status"] == "충족"
    assert check(record(expires_on="2026-10-01", submission_confirmed=False))["status"] == "미충족"


def test_missing_record_and_policy_never_pass():
    assert check(None)["status"] == "확인 필요"
    assert assess_language(record(), None, today=TODAY)["status"] == "확인 필요"


@pytest.mark.parametrize("year", [2018, 2020, 2026])
def test_audit_uses_scores_over_stale_legacy_manual_completion(year):
    profile = Profile(admission_year=year, english="충족", language=record(score="590"))
    outcome = audit([], profile, load_rules(ROOT, "심화", year))
    assert next(c for c in outcome.checks if c.key == "어학 인정·제출").status == "미충족"


def test_general_score_does_not_resolve_applicability():
    profile = Profile(track="일반", language=record())
    result = audit([], profile, load_rules(ROOT, "일반"))
    assert next(c for c in result.checks if c.key == "일반과정 어학요건 확인").status == "확인 필요"


def test_legacy_profile_loads_and_preserves_school_confirmed_manual_state():
    profile = Profile.model_validate({"english":"충족"})
    assert profile.language is None
    assert next(c for c in audit([], profile, load_rules(ROOT, "심화")).checks if c.key == "어학 인정·제출").status == "충족"


def test_llm_gets_source_thresholds_and_submission_explanation_without_dates():
    profile = Profile(language=record(submission_confirmed=False))
    rules, options = load_rules(ROOT,"심화"), PlanOptions(start_year=2027, semesters=1)
    context = make_context([], profile, rules, [], options, "", build_roadmap([], profile, rules, [], options))
    row = next(c for c in context["checks"] if c["key"] == "어학 인정·제출")
    assert row["status"] == "확인 필요" and "접수" in row["detail"]
    assert len(context["language_requirements"]["exams"]) == 9
    assert "2026-10-01" not in json.dumps(context)


def test_guidance_source_integrity_fails_closed(tmp_path):
    shutil.copytree(ROOT/"config/reviewed_rules", tmp_path/"config/reviewed_rules")
    (tmp_path/"config/reviewed_rules/sources/department_language_20261008.html").write_text("changed")
    with pytest.raises(ValueError, match="규정 원본"):
        load_department_guidance(tmp_path)
