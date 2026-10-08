"""Admission boundaries, legacy DB migration and cross-layer cohort isolation."""
from dataclasses import replace
import json
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from backend.app import create_app
from backend.database import Database
from backend.schemas import SaveProfile
from backend.service import ChatAnswer
from src.planning.audit import audit
from src.planning.io import read_transcript, sample_transcript, write_transcript
from src.planning.llm import Connection, make_context
from src.planning.models import Attempt, Candidate, PlanOptions, Profile
from src.planning.planner import build_roadmap
from src.planning.rules import load_rules

ROOT = Path(__file__).resolve().parents[2]
HEADERS = {"x-planner-request": "1"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.service.saved_connection", lambda _: Connection())
    with TestClient(create_app(tmp_path / "cohorts.sqlite3")) as result:
        yield result


def payload(year, track="일반"):
    return {"profile": Profile(admission_year=year, track=track).model_dump(),
            "attempts": [a.model_dump() for a in sample_transcript(year)],
            "options": {"start_year": 2027, "semesters": 2}, "candidates": []}


def post(client, path, data):
    response = client.post(path, json=data, headers=HEADERS)
    assert response.status_code in (200, 201), response.text
    return response


@pytest.mark.parametrize("year,specialized,sw,science,computing", [
    (2018, None, None, 8, None), (2019, 3, None, 8, None),
    (2020, 3, None, 8, 2), (2021, 3, None, 8, 2),
    (2022, 3, 9, 8, 2), (2023, 3, 9, 8, 2),
    (2024, 3, 9, 4, 3), (2025, 3, 9, 4, 3), (2026, 3, 9, 4, 3),
])
@pytest.mark.parametrize("track", ["심화", "일반"])
def test_all_cohort_boundaries_reach_analysis_and_persistence(client, year, specialized, sw, science, computing, track):
    data = payload(year, track)
    result = post(client, "/api/analysis", data).json()
    checks = {c["key"]: c for c in result["audit"]["checks"]}
    assert result["rules"]["admission_year"] == year
    assert checks["총 졸업인정학점"]["current"] == 21
    expected = {"총 졸업인정학점": 132, "전공": 54 if track == "심화" else 50,
                "MSC 합계": 30 if track == "심화" else 27, "특성화교양": specialized,
                "SW·데이터활용": sw, "MSC과학": 4 if track == "심화" else science,
                "MSC전산": 3 if track == "심화" else computing}
    for key, value in expected.items():
        assert (checks[key]["required"] if key in checks else None) == value
    assert ("특성화교양 지정과목 확인" in checks) == (year >= 2019)
    assert ("SW·데이터 인정과목·중복인정 확인" in checks) == (year >= 2022)
    assert ("학과 과학 지정과목 확인" in checks) == (track == "심화" and year >= 2021)
    saved = post(client, "/api/profiles", {**data, "label": f"가상 {year} {track}"}).json()
    assert client.get(f"/api/profiles/{saved['id']}").json()["profile"]["admission_year"] == year
    assert client.get("/api/profiles").json()[0]["admission_year"] == year


def test_bootstrap_demo_and_invalid_years(client):
    bootstrap = client.get("/api/bootstrap").json()
    assert bootstrap["admission_years"] == list(range(2018, 2027))
    assert len(bootstrap["cohort_rules"]) == 18
    assert all(a["year"] == 2018 for a in client.get("/api/demo?admission_year=2018").json()["attempts"])
    for year in (2017, 2027, 2020.5, True):
        data = payload(2020)
        data["profile"]["admission_year"] = year
        assert client.post("/api/analysis", json=data, headers=HEADERS).status_code == 422
    assert client.get("/api/demo?admission_year=2027").status_code == 422
    with pytest.raises(ValueError):
        load_rules(ROOT, "일반", 2027)
    with pytest.raises(ValueError, match="입학연도"):
        audit([], Profile(admission_year=2018), load_rules(ROOT, "심화", 2020))


def course(code, **values):
    return Attempt(**{"code": code, "name": "가상 " + code, "credits": 3,
                     "category": "MSC과학", "year": 2025, "grade": "P", **values})


@pytest.mark.parametrize("codes,passed", [
    (["012102", "012103"], True), (["012108", "012109"], True),
    (["012102", "012109"], False), (["012108"], False), ([], False),
])
def test_general_2024_requires_complete_science_pair(codes, passed):
    result = audit([course(c) for c in codes], Profile(admission_year=2024, track="일반"), load_rules(ROOT, "일반", 2024))
    check = next(c for c in result.checks if c.key == "과학 실험 포함 1set")
    assert (check.status == "충족") is passed


def test_pair_is_planned_even_when_credit_minima_are_met():
    # All other credit requirements are deliberately outside this focused case.
    rules = replace(load_rules(ROOT, "일반", 2024), thresholds={})
    candidates = [Candidate(code=c, name=c, credits=3, category="MSC과학", semesters=(1, 2))
                  for c in ("012102", "012103")]
    plan = build_roadmap([], Profile(admission_year=2024, track="일반"), rules, candidates,
                         PlanOptions(start_year=2027, semesters=2, credit_limit=3))
    assert [[c.code for c in s.courses] for s in plan.semesters] == [["012102"], ["012103"]]
    assert next(c for c in plan.projected.checks if c.key == "과학 실험 포함 1set").status == "충족"


def test_sw_credits_do_not_double_count_and_survive_csv(client):
    rows = [course("SW1", category="전공", sw_data_credits=3),
            course("SW2", category="교양선택", sw_data_credits=3),
            course("FAIL", sw_data_credits=3, grade="F"),
            course("UNKNOWN", category="미확인", sw_data_credits=3)]
    result = audit(rows, Profile(admission_year=2022), load_rules(ROOT, "심화", 2022))
    checks = {c.key: c for c in result.checks}
    assert checks["총 졸업인정학점"].current == 6
    assert checks["SW·데이터활용"].current == 6
    assert read_transcript(write_transcript(rows)) == rows
    with pytest.raises(ValidationError):
        course("INVALID", sw_data_credits=4)
    data = payload(2022)
    data["attempts"] = [a.model_dump() for a in rows]
    saved = post(client, "/api/profiles", {**data, "label": "가상 SW 인정"}).json()
    assert saved["attempts"][0]["sw_data_credits"] == 3


def test_scope_reaches_backup_report_comparison_evaluation_and_ai(client, monkeypatch):
    data = payload(2018)
    backup = post(client, "/api/export/backup", data).json()
    restored = post(client, "/api/import/backup", {"text": json.dumps(backup)}).json()["data"]
    assert restored["profile"]["admission_year"] == 2018
    report = post(client, "/api/export/report", restored).text
    assert "2018학번" in report and "2020학번 ·" not in report
    comparisons = post(client, "/api/compare", data).json()["scenarios"]
    assert all(s["result"]["rules"]["admission_year"] == 2018 for s in comparisons)
    evaluation = post(client, "/api/evaluations", {"kind": "규정 대조", "case_label": "가상 2018",
                      "track": "일반", "admission_year": 2018}).json()
    assert evaluation["admission_year"] == 2018
    captured = {}
    def request(context, _):
        captured.update(context)
        return ChatAnswer(answer="가상 답변: 학번 기준을 확인했습니다.", referenced_checks=["전공"], recommended_codes=[])
    monkeypatch.setattr("backend.service.saved_connection", lambda _: Connection("fake", "test-model"))
    monkeypatch.setattr("backend.service.request_chat", request)
    assert post(client, "/api/chat", {**data, "question": "내 학번 기준은?", "consent": True}).json()["mode"] == "llm"
    assert captured["scope"]["admission_year"] == 2018
    profile, rules = Profile(admission_year=2026), load_rules(ROOT, "심화", 2026)
    options = PlanOptions(start_year=2027)
    baseline = build_roadmap([], profile, rules, [], options)
    context = make_context([], profile, rules, [], options, "", baseline)
    assert context["scope"]["admission_year"] == 2026
    assert next(c for c in context["checks"] if c["key"] == "SW·데이터활용")["required"] == 9


def test_legacy_backup_and_csv_default_new_optional_fields(client):
    backup = post(client, "/api/export/backup", payload(2020)).json()
    for key in ("sw_data_course", "science_course"):
        backup["data"]["profile"].pop(key)
    for row in backup["data"]["attempts"]:
        row.pop("sw_data_credits")
    restored = post(client, "/api/import/backup", {"text": json.dumps(backup)}).json()["data"]
    assert restored["profile"]["admission_year"] == 2020
    assert restored["profile"]["sw_data_course"] == "확인 필요"
    assert all(row["sw_data_credits"] == 0 for row in restored["attempts"])
    csv = "학수번호,과목명,학점,이수구분,수강연도,학기,성적,상태\n001012,가상 글쓰기,3,전문교양,2018,1,P,취득\n"
    row = read_transcript(csv.encode())[0]
    assert row.year == 2018 and row.sw_data_credits == 0


def test_real_version2_schema_migrates_preserving_children_owners_and_revisions(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    old = payload(2020)
    for key in ("sw_data_course", "science_course"):
        old["profile"].pop(key)
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE profiles (id TEXT PRIMARY KEY,label TEXT NOT NULL,revision INTEGER NOT NULL,
                admission_year INTEGER NOT NULL CHECK(admission_year=2020),track TEXT NOT NULL,
                profile_json TEXT NOT NULL,options_json TEXT NOT NULL,goal TEXT NOT NULL,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL,settings_json TEXT NOT NULL,owner_id TEXT NOT NULL);
            CREATE TABLE course_attempts (profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                position INTEGER NOT NULL,code TEXT NOT NULL,name TEXT NOT NULL,credits REAL NOT NULL,
                category TEXT NOT NULL,area INTEGER NOT NULL,design_credits REAL NOT NULL,equivalent_code TEXT NOT NULL,
                year INTEGER NOT NULL,term INTEGER NOT NULL,grade TEXT NOT NULL,status TEXT NOT NULL,
                PRIMARY KEY(profile_id,position));
            CREATE TABLE plan_runs (id TEXT PRIMARY KEY,profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                revision INTEGER NOT NULL,created_at TEXT NOT NULL,rules_fingerprint TEXT NOT NULL,result_json TEXT NOT NULL,
                UNIQUE(profile_id,revision));
            PRAGMA user_version=2;
        """)
        db.execute("INSERT INTO profiles VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
            "legacy", "기존 가상 계획", 4, 2020, "일반", json.dumps(old["profile"]), json.dumps(old["options"]),
            "유지할 목표", "old-created", "old-updated", '{"checklist":[],"candidates":[]}', "owner-test"))
        db.execute("INSERT INTO course_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            "legacy", 0, "001012", "가상 과목", 3, "전문교양", 0, 0, "", 2020, 1, "P", "취득"))
        db.execute("INSERT INTO plan_runs VALUES(?,?,?,?,?,?)", ("run", "legacy", 4, "old-created", "0" * 64, '{"legacy":true}'))
    database = Database(path)
    database.initialize()
    database.initialize()  # Reopening must not replay the migration.
    record = database.get_profile("legacy", "owner-test")
    assert (record["revision"], record["goal"], record["created_at"]) == (4, "유지할 목표", "old-created")
    assert record["attempts"][0]["sw_data_credits"] == 0
    assert record["profile"]["sw_data_course"] == "확인 필요"
    assert database.list_profiles() == []  # Owner access remains isolated.
    assert database.history("legacy", "owner-test")[0]["result"] == {"legacy": True}
    update = SaveProfile(**{**payload(2018), "label": "변경 가상 계획", "revision": 4})
    database.save(update, {"rules_fingerprint": "1" * 64}, "legacy", "owner-test")
    assert database.get_profile("legacy", "owner-test")["profile"]["admission_year"] == 2018
    assert len(database.history("legacy", "owner-test")) == 2
    with database.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    database.delete("legacy", 5, "owner-test")
    with database.connect() as db:
        assert db.execute("SELECT count(*) FROM course_attempts").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM plan_runs").fetchone()[0] == 0
