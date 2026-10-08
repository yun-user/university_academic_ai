from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[2]


def test_plan_start_year_supports_2018():
    app = AppTest.from_file(str(ROOT / "pages/7_졸업로드맵.py"), default_timeout=30).run()
    field = app.number_input(key="planner_start_year")
    field.set_value(2018).run()
    assert not app.exception
    assert app.number_input(key="planner_start_year").value == 2018
    assert not app.error


def test_llm_opt_in_render_and_no_repeat_calls_on_rerun(monkeypatch):
    from src.planning import llm, llm_ui
    monkeypatch.setattr(llm_ui,"saved_connection",lambda _:llm.Connection())
    calls=[]
    def fake(context,connection):
        calls.append(context)
        return {"summary":"가상 LLM: 부족한 전공과 교양을 준비하세요.","priorities":[],
                "next_steps":["학교에서 필수목록을 확인하세요."]}
    monkeypatch.setattr(llm,"request_advice",fake)
    app=AppTest.from_file(str(ROOT/"pages/7_졸업로드맵.py"),default_timeout=30).run()
    next(b for b in app.button if b.label=="가상 예제로 시작").click().run()
    app.checkbox(key="planner_llm_enabled").check().run()
    assert next(b for b in app.button if b.label=="LLM 맞춤 로드맵 생성").disabled
    assert not calls
    app.text_input(key="planner_llm_model").set_value("test-model")
    app.text_input(key="planner_llm_key").set_value("not-a-real-key")
    app.checkbox(key="planner_llm_consent").check().run()
    next(b for b in app.button if b.label=="LLM 맞춤 로드맵 생성").click().run()
    assert not app.exception and len(calls)==1
    assert any("가상 LLM" in x.value for x in app.text)
    app.run()
    assert len(calls)==1 and any("가상 LLM" in x.value for x in app.text)
    app.text_area(key="planner_llm_goal").set_value("백엔드 개발").run()
    assert len(calls)==1 and not any("가상 LLM" in x.value for x in app.text)
    assert not app.exception


def test_llm_failure_shows_basic_mode_without_provider_error(monkeypatch):
    from src.planning import llm, llm_ui
    monkeypatch.setattr(llm_ui,"saved_connection",lambda _:llm.Connection("test-secret","test-model"))
    def fail(*_):
        raise RuntimeError("test-secret private request")
    monkeypatch.setattr(llm,"request_advice",fail)
    app=AppTest.from_file(str(ROOT/"pages/7_졸업로드맵.py"),default_timeout=30).run()
    next(b for b in app.button if b.label=="가상 예제로 시작").click().run()
    app.checkbox(key="planner_llm_enabled").check().run()
    app.checkbox(key="planner_llm_consent").check().run()
    next(b for b in app.button if b.label=="LLM 맞춤 로드맵 생성").click().run()
    assert not app.exception
    assert any("기본 계산 결과" in x.value for x in app.warning)
    assert not any("test-secret" in x.value for x in app.warning)
    assert any("2027년" in x.value for x in app.markdown)


def test_planner_page_empty_sample_both_tracks_and_roadmap():
    app = AppTest.from_file(str(ROOT / "pages/7_졸업로드맵.py"),default_timeout=30).run()
    assert not app.exception
    assert app.title[0].value == "나의 졸업 로드맵"
    next(b for b in app.button if b.label=="가상 예제로 시작").click().run()
    assert not app.exception
    assert app.metric[0].value == "21"
    next(b for b in app.button if b.label=="로드맵 계산").click().run()
    assert not app.exception
    assert any("2027년" in x.value for x in app.markdown)
    app.radio[0].set_value("일반").run()
    assert not app.exception
    assert not any("2027년" in x.value for x in app.markdown)
    next(b for b in app.button if b.label=="로드맵 계산").click().run()
    assert not app.exception
    next(b for b in app.button if b.label=="이수내역 비우기").click().run()
    assert app.metric[0].value == "0"


def test_planner_manual_entry_rejects_empty_then_accepts_valid():
    app = AppTest.from_file(str(ROOT / "pages/7_졸업로드맵.py"),default_timeout=30).run()
    next(b for b in app.button if b.label=="이수내역에 추가").click().run()
    assert len(app.error) == 1
    next(x for x in app.text_input if x.label=="학수번호").set_value("704814")
    next(x for x in app.text_input if x.label=="과목명").set_value("종합설계(2)")
    next(b for b in app.button if b.label=="이수내역에 추가").click().run()
    assert not app.exception
    assert app.metric[0].value == "3"


def test_confirmed_substitution_changes_requirement_only_and_is_track_scoped():
    app = AppTest.from_file(str(ROOT / "pages/7_졸업로드맵.py"),default_timeout=30).run()
    next(b for b in app.button if b.label=="가상 예제로 시작").click().run()
    next(x for x in app.text_input if x.label=="공식 확인한 필수과목 학수번호 (쉼표로 구분)").set_value("TEST_OLD").run()
    next(x for x in app.text_input if x.label=="원래 필수과목 학수번호").set_value("TEST_OLD")
    next(x for x in app.text_input if x.label=="대체 이수과목 학수번호").set_value("704818")
    next(x for x in app.text_input if x.label=="대체인정 확인 근거").set_value("가상 UI 시험 자료 — 학교 규정 아님")
    next(x for x in app.checkbox if x.label=="선택한 과정·입학연도·수강기간의 대체인정을 학교 자료나 학과에서 확인했습니다").check()
    next(b for b in app.button if b.label=="대체인정 추가").click().run()
    assert not app.exception
    assert not app.error
    assert app.metric[0].value == "21"

    def personal_status():
        frame = next(d.value for d in app.dataframe if "점검 항목" in d.value.columns)
        return frame.loc[frame["점검 항목"]=="개인 필수 TEST_OLD","상태"].iloc[0]

    assert personal_status() == "충족"
    app.radio[0].set_value("일반").run()
    assert not app.exception
    assert personal_status() == "미충족"
    assert len(app.session_state["planner_substitutions"]) == 1
    next(b for b in app.button if b.label=="이 대체인정 삭제").click().run()
    assert not app.session_state["planner_substitutions"]


def test_substitution_form_rejects_missing_evidence():
    app = AppTest.from_file(str(ROOT / "pages/7_졸업로드맵.py"),default_timeout=30).run()
    next(x for x in app.text_input if x.label=="원래 필수과목 학수번호").set_value("OLD")
    next(x for x in app.text_input if x.label=="대체 이수과목 학수번호").set_value("NEW")
    next(b for b in app.button if b.label=="대체인정 추가").click().run()
    assert app.error
    assert not app.session_state["planner_substitutions"]


def test_workspace_restore_populates_widgets_candidates_and_manual_checks():
    from src.planning.workspace import PlannerWorkspace, source_fingerprint
    from src.planning.models import Profile, PlanOptions
    from src.planning.io import sample_transcript
    from src.planning.catalog import load_catalog
    app = AppTest.from_file(str(ROOT / "pages/7_졸업로드맵.py"),default_timeout=30).run()
    app.session_state["planner_pending_workspace"] = PlannerWorkspace(saved_on="2026-10-05",
        rules_fingerprint=source_fingerprint(ROOT),attempts=sample_transcript(),
        profile=Profile(track="일반",general_approval="충족"),candidates=load_catalog(ROOT),
        options=PlanOptions(start_year=2028,start_term=2,semesters=2,credit_limit=15,excluded_codes=("704814",)))
    app.run()
    assert not app.exception
    assert app.radio[0].value == "일반"
    assert app.metric[0].value == "21"
    assert next(x for x in app.number_input if x.label=="계획 시작 연도").value == 2028
    assert next(x for x in app.selectbox if x.label=="일반과정 적용·변경 승인 확인").value == "충족"
    assert next(row for row in app.session_state["planner_candidate_rows"] if row["학수번호"]=="704814")["추천"] is False
    next(b for b in app.button if b.label=="로드맵 계산").click().run()
    assert not app.exception
    assert any("2028년 2학기" in x.value for x in app.markdown)


def test_cohort_switch_keeps_courses_and_resets_old_confirmations():
    app = AppTest.from_file(str(ROOT / "pages/7_졸업로드맵.py"), default_timeout=30).run()
    app.selectbox(key="planner_admission_year").set_value(2018).run()
    next(b for b in app.button if b.label == "가상 예제로 시작").click().run()
    app.selectbox(key="planner_thesis").set_value("충족").run()
    before = app.session_state["planner_rows"]
    assert all(row["수강연도"] == 2018 for row in before)
    def keys():
        return next(d.value for d in app.dataframe if "점검 항목" in d.value.columns)["점검 항목"].tolist()
    assert "특성화교양" not in keys() and "SW·데이터활용" not in keys()
    app.selectbox(key="planner_admission_year").set_value(2022).run()
    assert not app.exception
    assert app.session_state["planner_rows"] == before
    assert app.selectbox(key="planner_thesis").value == "확인 필요"
    assert "SW·데이터활용" in keys() and "특성화교양" in keys()
    assert app.metric[0].value == "21"
