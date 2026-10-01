from pathlib import Path
from types import SimpleNamespace
from streamlit.testing.v1 import AppTest
from src.evaluation.natural import Case, capture_run, save_run, load_reviews
from src.retrieval.document_models import DocumentSearchResponse


def test_review_page_starts_ungraded_and_persists_complete_review(tmp_path, monkeypatch):
    import src.admin_auth
    import src.config
    root = Path(__file__).resolve().parents[2]
    service = SimpleNamespace(_search_mode="hybrid", search_with_context=lambda *a, **k: DocumentSearchResponse())
    run = capture_run(service, [Case(id="Q", group="G", category="범위", question="졸업요건")],
                      dataset_hash="abc", root=tmp_path)
    path = save_run(tmp_path / "evals/local_runs", run)
    monkeypatch.setattr(src.admin_auth, "require_admin", lambda: None)
    monkeypatch.setattr(src.config, "get_settings", lambda: SimpleNamespace(project_root=tmp_path))
    app = AppTest.from_file(str(root / "pages/5_자연어답변평가.py")).run()
    assert not app.exception
    assert all(s.value is None for s in app.selectbox[2:])
    assert app.metric[1].value == "0"
    app.selectbox[2].select("correct")
    app.selectbox[3].select("not_applicable")
    app.selectbox[4].select("appropriate")
    app.selectbox[5].select("abstain")
    app.text_input[0].set_value("reviewer-A")
    app.text_area[0].set_value("질문에 필요한 자료가 등록되지 않음")
    app.text_area[1].set_value("근거 부족으로 답변을 보류함")
    app.button[0].click().run()
    assert not app.exception
    assert load_reviews(path, run)["Q"]["correctness"] == "correct"
    assert app.metric[1].value == "1"
