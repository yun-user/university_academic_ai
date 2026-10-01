from pathlib import Path
from types import SimpleNamespace
from streamlit.testing.v1 import AppTest
from src.evaluation.natural import Case, load_cases
from src.evaluation.question_bank import bank_path
from src.retrieval.document_models import DocumentSearchResponse


def app_fixture(tmp_path, monkeypatch):
    import src.admin_auth
    import src.config
    import src.runtime
    root = Path(__file__).resolve().parents[2]
    path = tmp_path / "evals/natural_dev.jsonl"
    path.parent.mkdir()
    path.write_text(Case(id="N1", group="example", category="예시", question="기본 개발 질문").model_dump_json(), encoding="utf-8")
    service = SimpleNamespace(_search_mode="dense", search_with_context=lambda *a, **k: DocumentSearchResponse())
    monkeypatch.setattr(src.admin_auth, "require_admin", lambda: None)
    monkeypatch.setattr(src.config, "get_settings", lambda: SimpleNamespace(project_root=tmp_path))
    monkeypatch.setattr(src.runtime, "get_search_service", lambda: service)
    # Exercise actual multipage navigation, including the link to the review page.
    ui = tmp_path / "ui"
    (ui / "pages").mkdir(parents=True)
    (ui / "app.py").write_text("import streamlit as st\nst.title('테스트 시작')", encoding="utf-8")
    for name in ("6_평가질문관리.py", "5_자연어답변평가.py"):
        (ui / "pages" / name).write_bytes((root / "pages" / name).read_bytes())
    app = AppTest.from_file(str(ui / "app.py")).run().switch_page("pages/6_평가질문관리.py").run()
    return app, service


def test_question_registration_then_capture(tmp_path, monkeypatch):
    import json
    app, service = app_fixture(tmp_path, monkeypatch)
    assert not app.exception
    app.text_area(key="new_question").set_value("실제 입력한 설계 질문")
    app.text_input(key="new_category").set_value("설계")
    app.text_input(key="new_group").set_value("design")
    app.text_input(key="new_year").set_value("2020")
    app.text_area(key="new_note").set_value("기대 행동: 수강 시기 확인")
    app.button[0].click().run()
    assert not bank_path(tmp_path).exists()  # no origin silently assigned
    assert app.error
    app.selectbox(key="new_origin").select("student")
    app.button[0].click().run()
    assert not app.exception
    cases, _ = load_cases(bank_path(tmp_path))
    assert cases[0].origin == "student"
    assert cases[0].admission_year == 2020
    app.selectbox(key="capture_dataset").select("registered")
    app.button(key="capture_answers").click().run()
    assert not app.exception
    paths = list((tmp_path / "evals/local_runs").glob("*.json"))
    assert len(paths) == 1
    run = json.loads(paths[0].read_text(encoding="utf-8"))
    assert run["rows"][0]["case"] == cases[0].model_dump()
    assert run["llm_requested"] is False
    assert service._search_mode == "dense"
    assert not list((tmp_path / "evals/local_runs").glob("*.reviews.json"))
    app.switch_page("pages/5_자연어답변평가.py").run()
    assert not app.exception
    assert app.metric[2].value == "1"
    assert any(t.value == "기대 행동: 수강 시기 확인" for t in app.text)


def test_empty_test_split_does_not_save_run(tmp_path, monkeypatch):
    app, _ = app_fixture(tmp_path, monkeypatch)
    app.selectbox(key="capture_split").select("test")
    app.button(key="capture_answers").click().run()
    assert not app.exception
    assert app.error
    assert not list((tmp_path / "evals/local_runs").glob("*.json"))


def test_admin_gate_precedes_question_access(tmp_path, monkeypatch):
    import src.admin_auth
    import streamlit as st
    monkeypatch.setattr(src.admin_auth, "require_admin", lambda: st.stop())
    root = Path(__file__).resolve().parents[2]
    app = AppTest.from_file(str(root / "pages/6_평가질문관리.py")).run()
    assert not app.exception
    assert not app.text_area
    assert not app.button
