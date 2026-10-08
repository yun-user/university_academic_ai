from datetime import date, timedelta
import json

from fastapi.testclient import TestClient

from backend.app import create_app
from src.planning.llm import Connection

HEADERS = {"x-planner-request": "1"}


def test_language_preview_audit_storage_backup_report_and_general_scope(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.service.saved_connection", lambda root: Connection())
    today = date.today()
    with TestClient(create_app(tmp_path / "language.sqlite3")) as client:
        boot = client.get("/api/bootstrap").json()
        assert len(boot["department_guidance"]["exams"]) == 9
        profile = boot["profile"] | {"language": dict(exam="TOEIC", score="600",
            expires_on=str(today+timedelta(days=365)), submitted_on=str(today-timedelta(days=1)), submission_confirmed=True)}
        result = client.post("/api/language/check", headers=HEADERS, json=profile)
        assert result.status_code == 200 and result.json()["status"] == "충족"
        data = dict(attempts=[], profile=profile, options=boot["options"], goal="", candidates=[])
        saved = client.post("/api/profiles", headers=HEADERS, json=data | {"label":"어학 테스트"})
        assert saved.status_code == 201
        loaded = client.get("/api/profiles/"+saved.json()["id"]).json()
        assert loaded["profile"]["language"] == profile["language"]
        result = client.post("/api/analysis", headers=HEADERS, json=data).json()
        assert next(c for c in result["audit"]["checks"] if c["key"]=="어학 인정·제출")["status"] == "충족"
        evidence = next(c for c in result["evidence"] if c["key"]=="어학 인정·제출")
        assert any("curriculum/standard" in s for s in evidence["sources"])
        backup = client.post("/api/export/backup", headers=HEADERS, json=data).json()
        restored = client.post("/api/import/backup", headers=HEADERS, json={"text":json.dumps(backup)}).json()
        assert restored["data"]["profile"]["language"] == profile["language"]
        report = client.post("/api/export/report", headers=HEADERS, json=data)
        assert report.status_code == 200 and "TOEIC" in report.text
        general = client.post("/api/language/check", headers=HEADERS, json=profile | {"track":"일반"}).json()
        assert general["status"] == "확인 필요" and general["score_status"] == "충족"
        profile["language"]["expires_on"] = "not-a-date"
        invalid = client.post("/api/language/check", headers=HEADERS, json=profile)
        assert invalid.status_code == 422 and "not-a-date" not in invalid.text
