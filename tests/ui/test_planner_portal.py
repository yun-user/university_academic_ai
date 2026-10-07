from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.planning.portal_import import HEADERS, parse_portal_tables

ROOT = Path(__file__).resolve().parents[2]


def test_review_before_replace_and_revoke_llm_consent():
    app = AppTest.from_file(str(ROOT / "pages/7_졸업로드맵.py"), default_timeout=30).run()
    next(b for b in app.button if b.label == "가상 예제로 시작").click().run()
    before = app.session_state["planner_rows"]
    app.session_state["planner_llm_consent"] = True
    app.session_state["planner_portal_preview"] = parse_portal_tables([{
        "caption": "2021학년도 2학년 1학기", "headers": list(HEADERS),
        "rows": [["TEST123", "가상 연동 과목", "", "3", "P", ""]]}], [])
    app.run()
    assert app.session_state["planner_rows"] == before
    assert next(b for b in app.button if b.label == "가져온 이수내역 적용").disabled
    app.checkbox(key="planner_portal_checked_0").check().run()
    next(b for b in app.button if b.label == "가져온 이수내역 적용").click().run()
    assert not app.exception
    assert len(app.session_state["planner_rows"]) == 1
    assert app.session_state["planner_rows"][0]["학수번호"] == "TEST123"
    assert not app.session_state["planner_llm_consent"]
    assert app.metric[0].value == "0"  # Unknown category must not count toward graduation.


def test_bad_import_preserves_existing_input():
    app = AppTest.from_file(str(ROOT / "pages/7_졸업로드맵.py"), default_timeout=30).run()
    next(b for b in app.button if b.label == "가상 예제로 시작").click().run()
    before = app.session_state["planner_rows"]
    app.session_state["planner_portal_preview"] = parse_portal_tables([], [])
    app.run()
    assert not app.exception and app.error
    assert app.session_state["planner_rows"] == before
    assert not any(b.label == "가져온 이수내역 적용" for b in app.button)


def test_pasted_transcript_is_previewed_before_replacing():
    app = AppTest.from_file(str(ROOT / "pages/7_졸업로드맵.py"), default_timeout=30).run()
    text = "2020학년도 1학년 1학기\n" + "\t".join(HEADERS) + "\nTEST111\t가상 표\tTEST\t3\tP\t"
    app.text_area(key="planner_portal_paste").set_value(text)
    next(b for b in app.button if b.label == "붙여넣은 성적표 확인").click().run()
    assert not app.exception and not app.session_state["planner_rows"]
    assert app.session_state["planner_portal_preview"].ready
    assert next(b for b in app.button if b.label == "가져온 이수내역 적용").disabled
