import json

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.database import Database
from src.planning.llm import Connection

HEADERS = {"x-planner-request":"1"}


def test_transcript_zero_gets_design_in_preview_analysis_storage_backup_and_report(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.service.saved_connection", lambda root: Connection())
    with TestClient(create_app(tmp_path / "design.sqlite3")) as client:
        boot = client.get("/api/bootstrap").json()
        csv = "학수번호,과목명,학점,이수구분,수강연도,학기,성적,상태\n704805,소프트웨어공학,3,전공선택,2020,1,B0,취득\n"
        imported = client.post("/api/import/csv", headers=HEADERS, json={"text":csv, "profile":boot["profile"]})
        assert imported.status_code == 200
        attempts = imported.json()["attempts"]
        assert attempts[0]["design_credits"] == 0
        data = dict(attempts=attempts, profile=boot["profile"], options=boot["options"], goal="", candidates=[])
        preview = client.post("/api/courses/design", headers=HEADERS, json={k:data[k] for k in ("attempts","profile","candidates")})
        assert preview.status_code == 200 and preview.json()["total"] == 1
        result = client.post("/api/analysis", headers=HEADERS, json=data).json()
        assert result["audit"]["design_allocations"] == preview.json()["allocations"]
        evidence = next(c for c in result["evidence"] if c["key"]=="설계 인정학점")
        assert evidence["current"] == 1 and any(s.endswith("/curriculum/courses") for s in evidence["sources"])
        saved = client.post("/api/profiles", headers=HEADERS, json=data | {"label":"가상 설계 검증"})
        assert saved.status_code == 201
        loaded = client.get("/api/profiles/"+saved.json()["id"]).json()
        assert loaded["attempts"] == attempts
        # Explicit zero must remain an override after DB reload and backup/CSV.
        data["attempts"][0]["design_override"] = True
        updated = client.put("/api/profiles/"+saved.json()["id"], headers=HEADERS,
                             json=data | {"label":"가상 설계 검증", "revision":saved.json()["revision"]})
        assert updated.status_code == 200 and updated.json()["attempts"][0]["design_override"] is True
        report = client.post("/api/export/report", headers=HEADERS, json=data)
        assert report.status_code == 200 and "사용자가 입력한 설계학점" in report.text
        backup = client.post("/api/export/backup", headers=HEADERS, json=data).json()
        restored = client.post("/api/import/backup", headers=HEADERS, json={"text":json.dumps(backup)}).json()
        assert restored["data"]["attempts"][0]["design_override"] is True


def test_schema_three_migration_preserves_zero_and_manual_values(tmp_path):
    path = tmp_path / "v3.sqlite3"
    db = Database(path)
    db.initialize()
    with db.connect() as conn:
        conn.execute("ALTER TABLE course_attempts DROP COLUMN design_override")
        conn.execute("PRAGMA user_version=3")
        conn.execute("INSERT INTO profiles VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
            "synthetic", "migration", 1, 2020, "심화", '{}', '{}', '', 'old', 'old', '{}', ''))
        for i, value in enumerate((0, 1.5)):
            conn.execute("INSERT INTO course_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                "synthetic", i, str(i), "가상", 3, "전공", 0, value, "", 2020, 1, "B0", "취득", 0))
    db.initialize()
    db.initialize()
    with db.connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
        assert [tuple(r) for r in conn.execute("SELECT design_credits,design_override FROM course_attempts ORDER BY position")] == [(0,0), (1.5,0)]
        assert conn.execute("SELECT created_at FROM profiles").fetchone()[0] == "old"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
