"""Public course examples and synthetic results only; never student fixtures."""
from pathlib import Path
from shutil import copytree

import pytest
from src.planning.audit import audit
from src.planning.catalog import load_catalog
from src.planning.classification import classify_attempts, classify_import, load_classification
from src.planning.io import read_transcript, write_transcript
from src.planning.models import Attempt, Profile
from src.planning.rules import load_rules

ROOT = Path(__file__).resolve().parents[2]


def attempt(code, name, credits=3, **kw):
    return Attempt(**dict(code=code, name=name, credits=credits, year=2021, grade="P", **kw))


@pytest.mark.parametrize("code,name,credits,category,area", [
    ("704818", "자료구조 및 프로그래밍 실습", 3, "전공필수", 0),
    ("704612", "머신러닝및실습(2)(*)", 3, "전공필수", 0),
    ("704512", "운영체제", 3, "전공선택", 0),
    ("001012", "논리적사고와글쓰기(공학)", 3, "전문교양", 0),
    ("004176", "컴퓨터정보통신공학개론", 3, "전문교양", 7),
    ("012108", "대학화학(1)", 3, "MSC과학", 0),
    ("012109", "대학화학실험(1)", 1, "MSC과학", 0),
    ("012203", "응용수학(1)", 3, "MSC수학", 0),
    ("002530", "협상의기술", 3, "전문교양", 1),
    ("002587", "한국사의이해", 3, "전문교양", 3),
    ("002248", "예술과건축", 3, "전문교양", 4),
    ("002598", "교양독일어(2)", 2, "전문교양", 5),
    ("002134", "소비자보호와법(C)", 3, "교양선택", 0),
    ("002205", "독일의문화와예술(C)(*)", 3, "교양선택", 0),
    ("007114", "전공기초영어(Ⅰ)", 2, "전공기초영어", 0),
    ("008752", "창업과실용법률(LEGAL THINKING)(C)", 3, "특성화교양", 0),
    ("007001", "교양영어(1)", 1, "일반선택", 0),
    ("007006", "전공영어(1)", 1, "일반선택", 0),
])
def test_reviewed_classification(code, name, credits, category, area):
    rows, review = classify_import([attempt(code, name, credits)], Profile(), ROOT)
    assert (rows[0].category, rows[0].area) == (category, area)
    assert rows[0].design_credits == rows[0].sw_data_credits == 0
    assert rows[0].equivalent_code == ""
    assert review["suggestions"][0]["source"].startswith("https://")


@pytest.mark.parametrize("code,name,credits", [
    ("704818", "자료구조 및 프로그래밍 실습", 4),
    ("OTHER", "자료구조 및 프로그래밍 실습", 3),
    ("704818", "다른 과목", 3),
    ("009998", "예술과건축", 3),
    ("007001", "교양영어(1)", 3),
])
def test_no_fuzzy_identity_or_invented_credits(code, name, credits):
    row = attempt(code, name, credits)
    rows, review = classify_import([row], Profile(), ROOT)
    assert rows == [row] and review["unmatched"] == 1


def test_cohort_boundary_and_historical_conflict():
    assert classify_attempts([attempt("002248", "예술과건축")], Profile(admission_year=2022), ROOT)["unmatched"] == 1
    rows = [attempt("002129", "정보사회와저작권"), attempt("704406", "신호및시스템")]
    old, _ = classify_import(rows, Profile(admission_year=2021), ROOT)
    new, _ = classify_import(rows, Profile(admission_year=2022), ROOT)
    assert (old[0].category, old[0].area) == ("전문교양", 6)
    assert (new[0].category, new[0].area) == ("교양선택", 0)
    assert old[1].category == "전공"  # Sources differ; do not assert elective for historical attempts.
    current, _ = classify_import([rows[1].model_copy(update={"year": 2026})], Profile(), ROOT)
    assert current[0].category == "전공선택"


def test_preview_preserves_manual_data_and_does_not_select_overwrite():
    original = attempt("004176", "컴퓨터정보통신공학개론", category="MSC전산")
    result = classify_attempts([original], Profile(), ROOT)["suggestions"][0]
    assert original.category == "MSC전산"
    assert result["patch"] == {"category": "전문교양", "area": 7}
    assert result["changed"] and not result["selected"]


def test_major_subcategories_aggregate_once_and_survive_csv():
    rows = [attempt(str(i), "가상과목", category=c, design_credits=1)
            for i, c in enumerate(("전공", "전공필수", "전공선택"))]
    assert read_transcript(write_transcript(rows)) == rows
    checks = {c.key: c.current for c in audit(rows, Profile(), load_rules(ROOT, "심화")).checks}
    assert checks["전공"] == checks["총 졸업인정학점"] == 9
    assert checks["설계 인정학점"] == 3


def test_bonus_is_independent_of_english_requirement_original_retake_and_cap():
    rows = [attempt("B"+str(i), f"{kind}영어({i})", 1, category="일반선택")
            for kind in ("전공", "교양") for i in (1, 2, 3)]
    # Distinct award codes, even with misleading manually supplied categories.
    rows = [a.model_copy(update={"code": f"BONUS{i}", "category": "전공필수",
                                 "design_credits": 1, "sw_data_credits": 1}) for i,a in enumerate(rows)]
    rows.append(attempt("704305", "회로이론(*)", category="전공선택", status="인정제외"))
    report = audit(rows, Profile(), load_rules(ROOT, "심화"))
    checks = {c.key: c.current for c in report.checks}
    assert checks["총 졸업인정학점"] == 5
    assert checks["전공"] == checks["설계 인정학점"] == checks["기초교양: 영어"] == 0
    assert any("상한 초과" in w for w in report.warnings)
    one = attempt("704305", "회로이론(*)", category="전공선택")
    assert len(classify_import([one], Profile(), ROOT)[0]) == 1  # Never synthesize awards from (*).


def test_current_catalog_identity_and_requiredness():
    catalog = {c.code: c for c in load_catalog(ROOT)}
    assert catalog["704818"].category == "전공필수"
    assert catalog["725843"].category == "전공선택" and catalog["725843"].design_credits == 2
    assert catalog["001012"].name == "논리적사고와글쓰기(공학)"
    assert catalog["001020"].name == "공학글쓰기"
    assert {"001023", "704839", "704840"}.issubset(catalog)
    assert catalog["001023"].alternatives == ("001009",)
    assert not {"704812", "704838", "777016"}.intersection(catalog)
    english = attempt("001023", "대학영어", category="전문교양")
    report = audit([english], Profile(), load_rules(ROOT, "심화"))
    assert next(c for c in report.checks if c.key == "기초교양: 영어").status == "충족"


def test_source_integrity(tmp_path):
    copytree(ROOT / "config/reviewed_rules", tmp_path / "config/reviewed_rules")
    path = tmp_path / "config/reviewed_rules/sources/english_credit_faq_20261008.html"
    path.write_text("corrupted", encoding="utf-8")
    with pytest.raises(ValueError, match="원본"):
        load_classification(tmp_path)
