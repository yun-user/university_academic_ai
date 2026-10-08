"""Real HTTP/SQLite integration using synthetic records; no provider calls."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import pytest

from backend.app import create_app
from backend.schemas import SaveProfile
from backend.service import ChatAnswer
from src.planning.llm import Connection

ROOT = Path(__file__).resolve().parents[2]
HEADERS = {"x-planner-request": "1"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Every test must explicitly stub a provider before opting in.
    monkeypatch.setattr("backend.service.saved_connection", lambda root: Connection())
    with TestClient(create_app(tmp_path / "planner.sqlite3")) as client:
        yield client


@pytest.fixture
def payload(client):
    defaults = client.get("/api/bootstrap").json()
    return {"attempts": client.get("/api/demo").json()["attempts"], "profile": defaults["profile"],
            "options": {**defaults["options"], "start_year": 2027}, "goal": "백엔드 개발"}


def post(client, path, data):
    return client.post(path, json=data, headers=HEADERS)


@pytest.mark.parametrize("track", ["심화", "일반"])
def test_calculate_both_tracks_without_persistence(client, payload, track):
    payload["profile"]["track"] = track
    response = post(client, "/api/analysis", payload)
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "local" and body["advice"] is None
    assert body["audit"]["checks"][0]["current"] == 21
    assert all(s["credits"] <= payload["options"]["credit_limit"] for s in body["roadmap"]["semesters"])
    assert "학교 최종 졸업사정" in [c["key"] for c in body["audit"]["checks"]]
    assert client.get("/api/profiles").json() == []


def test_full_crud_survives_restart_and_deletes_children(client, payload):
    created = post(client, "/api/profiles", {**payload, "label": "Synthetic record"})
    assert created.status_code == 201
    record = created.json()
    profile_id = record["id"]
    assert record["revision"] == 1
    path = f"/api/profiles/{profile_id}"
    assert client.get(path).json()["attempts"] == payload["attempts"]
    modified = deepcopy(payload)
    modified["attempts"][0]["status"] = "인정제외"
    response = client.put(path, headers=HEADERS, json={**modified, "label": "수정한 예시", "revision": 1})
    assert response.status_code == 200 and response.json()["revision"] == 2
    dbpath = client.app.state.database.path
    with TestClient(create_app(dbpath)) as restarted:
        assert restarted.get(path).json()["attempts"][0]["status"] == "인정제외"
        history = restarted.get(path + "/history").json()
        assert [h["revision"] for h in history] == [2, 1]
        assert [h["result"]["audit"]["checks"][0]["current"] for h in history] == [18, 21]
        assert restarted.delete(path + "?revision=2", headers=HEADERS).status_code == 204
    assert client.get(path).status_code == 404
    with sqlite3.connect(dbpath) as db:
        assert db.execute("SELECT count(*) FROM course_attempts").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM plan_runs").fetchone()[0] == 0


def test_stale_update_delete_and_missing_revision_conflict(client, payload):
    record = post(client, "/api/profiles", {**payload, "label": "original"}).json()
    path = f"/api/profiles/{record['id']}"
    new = {**payload, "label": "new", "revision": 1}
    assert client.put(path, headers=HEADERS, json=new).status_code == 200
    assert client.put(path, headers=HEADERS, json=new).status_code == 409
    assert client.put(path, headers=HEADERS, json={**payload, "label": "no revision"}).status_code == 409
    assert client.delete(path + "?revision=1", headers=HEADERS).status_code == 409
    assert client.get(path).json()["label"] == "new"
    assert len(client.get(path + "/history").json()) == 2


def test_concurrent_updates_only_one_wins(client, payload):
    record = post(client, "/api/profiles", {**payload, "label": "parallel"}).json()
    path = f"/api/profiles/{record['id']}"
    def update(label):
        return client.put(path, headers=HEADERS, json={**payload, "label": label, "revision": 1}).status_code
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(update, ["left", "right"])) == [200, 409]
    assert client.get(path).json()["revision"] == 2


def test_database_rolls_back_all_tables_if_snapshot_fails(client, payload):
    record = post(client, "/api/profiles", {**payload, "label": "keep"}).json()
    database = client.app.state.database
    data = SaveProfile(**{**payload, "label": "discard", "revision": 1})
    with pytest.raises(KeyError):
        database.save(data, {}, record["id"])
    assert database.get_profile(record["id"])["label"] == "keep"
    assert database.get_profile(record["id"])["revision"] == 1


def test_private_inputs_not_echoed_and_bad_records_do_not_persist(client, payload):
    raw = deepcopy(payload)
    raw["attempts"][0]["credits"] = "PRIVATE BAD CREDIT"
    response = post(client, "/api/profiles", {**raw, "label": "invalid"})
    assert response.status_code == 422
    assert "PRIVATE BAD CREDIT" not in response.text
    assert "attempts.0.credits" in response.json()["detail"]
    assert client.get("/api/profiles").json() == []
    assert post(client, "/api/profiles", {**payload, "label": "invalid", "api_key": "PRIVATE KEY"}).status_code == 422


@pytest.mark.parametrize("year", [2020, 2025, 0, 2101, 2026.5, None, "PRIVATE YEAR"])
def test_plan_start_year_error_explains_field_without_echoing_input(client, payload, year):
    payload["options"]["start_year"] = year
    response = post(client, "/api/analysis", payload)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "계획 시작 연도" in detail and "2026~2100" in detail
    assert "입학연도" in detail
    assert "options.start_year" not in detail and "PRIVATE YEAR" not in detail
    assert client.get("/api/profiles").json() == []


def test_unknown_duplicate_and_future_inputs_remain_conservative(client, payload):
    raw = deepcopy(payload)
    raw["attempts"][0]["category"] = "미확인"
    raw["attempts"].append(raw["attempts"][1])
    response = post(client, "/api/analysis", raw).json()
    assert response["audit"]["checks"][0]["current"] == 15
    assert len(response["audit"]["warnings"]) >= 2
    raw["attempts"][0]["year"] = 2030
    assert post(client, "/api/analysis", raw).status_code == 422


def test_local_origin_request_header_host_and_size_limits(client, payload):
    assert client.post("/api/analysis", json=payload).status_code == 403
    assert client.post("/api/analysis", json=payload, headers={**HEADERS, "Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/profiles", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400
    assert client.post("/api/import/csv", content=b"x" * 2_000_001, headers=HEADERS).status_code == 413
    assert client.get("/api/profiles").headers["cache-control"] == "no-store"
    assert "api_key" not in client.get("/api/bootstrap").text


def test_portal_and_csv_preview_never_save(client):
    text = "PRIVATE ID\n2020학년도 1학년 1학기\n학수번호\t과목명\t영문과목명\t학점\t성적\t재수강\n001009\t영어\tEnglish\t3\tB0\t\n취득학점 3"
    response = post(client, "/api/import/portal", {"text": text})
    assert response.status_code == 200 and len(response.json()["attempts"]) == 1
    assert "PRIVATE ID" not in response.text
    csv = client.get("/api/transcript/template").content.decode("utf-8-sig")
    assert len(post(client, "/api/import/csv", {"text": csv}).json()["attempts"]) == 8
    assert client.get("/api/profiles").json() == []
    assert post(client, "/api/import/portal", {"text": "not a transcript"}).status_code == 422


def test_chat_no_consent_no_provider(client, payload, monkeypatch):
    def forbidden(*args):
        pytest.fail("provider must not be called")
    monkeypatch.setattr("backend.service.request_chat", forbidden)
    response = post(client, "/api/chat", {**payload, "question": "무엇을 들어야 하나요?"}).json()
    assert response["mode"] == "local"


def test_chat_uses_minimized_fresh_context_and_validates_references(client, payload, monkeypatch):
    captured = {}
    monkeypatch.setattr("backend.service.saved_connection", lambda root: Connection("private-key", "test-model"))
    def request(context, connection):
        captured.update(context)
        return ChatAnswer(answer="전공 학점을 먼저 준비하세요.", referenced_checks=["전공"], recommended_codes=[])
    monkeypatch.setattr("backend.service.request_chat", request)
    raw = deepcopy(payload)
    raw["attempts"][0]["name"] = "PRIVATE COURSE NAME"
    response = post(client, "/api/chat", {**raw, "question": "다음 학기?", "consent": True}).json()
    assert response["mode"] == "llm" and response["model"] == "test-model"
    serialized = json.dumps(captured, ensure_ascii=False)
    assert all(private not in serialized for private in ['"grade"', '"B0"', "PRIVATE COURSE NAME", "private-key"])
    assert any(c["key"] == "총 졸업인정학점" and c["current"] == 21 for c in captured["checks"])
    monkeypatch.setattr("backend.service.request_chat", lambda *_: ChatAnswer(answer="틀린 응답", referenced_checks=["가짜 요건"], recommended_codes=["FAKE"]))
    assert post(client, "/api/chat", {**payload, "question": "추천?", "consent": True}).json()["mode"] == "fallback"


def test_chat_provider_failure_hides_prompt_and_key(client, payload, monkeypatch):
    monkeypatch.setattr("backend.service.saved_connection", lambda root: Connection("private-key", "test-model"))
    def fail(*_):
        raise RuntimeError("private-key PRIVATE RECORDS")
    monkeypatch.setattr("backend.service.request_chat", fail)
    response = post(client, "/api/chat", {**payload, "question": "질문", "consent": True})
    assert response.json()["mode"] == "fallback"
    assert "private-key" not in response.text and "PRIVATE RECORDS" not in response.text


def test_sql_like_label_is_plain_data(client, payload):
    label = "'); DROP TABLE profiles; --"
    record = post(client, "/api/profiles", {**payload, "label": label}).json()
    assert client.get(f"/api/profiles/{record['id']}").json()["label"] == label
    assert len(client.get("/api/profiles").json()) == 1


def test_openapi_exposes_typed_rest_contract(client):
    spec = client.get("/openapi.json").json()
    assert {"get", "put", "delete"} <= spec["paths"]["/api/profiles/{profile_id}"].keys()
    assert "SaveProfile" in spec["components"]["schemas"]
