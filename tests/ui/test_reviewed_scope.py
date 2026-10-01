from streamlit.testing.v1 import AppTest


def scoped_app():
    from pathlib import Path
    from app import _render_search_page
    from src.retrieval.reviewed_rules import reviewed_rule_search
    class Search:
        indexed_chunk_count = 1
        def available_departments(self):
            return ["소프트웨어융합학과"]
        def available_document_types(self):
            return ["검토된 학사규정"]
        def search_with_context(self, question, **kwargs):
            import src
            return reviewed_rule_search(question, kwargs['department'], Path(src.__file__).resolve().parents[1])
    _render_search_page(Search(), app_name="범위 테스트")


def test_selected_admission_year_reaches_answer():
    app = AppTest.from_function(scoped_app).run()
    app.text_input[0].set_value("졸업요건이 뭐야?")
    app.selectbox[2].select(2023)
    app.selectbox[3].select("심화과정")
    app.button[0].click().run()
    assert not app.exception
    assert any("2023학번" in m.value and "확정할 수 없습니다" in m.value for m in app.markdown)


def test_explicit_question_track_overrides_ui_selection():
    app = AppTest.from_function(scoped_app).run()
    app.text_input[0].set_value("2020학번 일반과정 졸업요건")
    app.selectbox[3].select("심화과정")
    app.button[0].click().run()
    assert not app.exception
    assert any("일반과정에 그대로 적용할 수 없습니다" in m.value for m in app.markdown)
