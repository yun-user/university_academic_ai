"""Per-session, opt-in model controls. Credentials never enter workspace exports."""
import streamlit as st

from src.planning.llm import Connection, saved_connection


def controls(root):
    enabled = st.checkbox("LLM 맞춤 추천 사용", key="planner_llm_enabled")
    goal = st.text_area("희망 진로·수강 선호 (선택)", max_chars=1000,
                        placeholder="예: 웹 개발에 관심이 있고, 프로젝트 과목을 우선하고 싶어요.",
                        key="planner_llm_goal")
    st.caption("희망 사항은 LLM 맞춤 추천에 반영됩니다. 이름·학번·연락처 등 개인정보는 적지 마세요.")
    connection, consent = Connection(), False
    if enabled:
        saved = saved_connection(root)
        with st.expander("LLM 연결 설정", expanded=not (saved.api_key and saved.model)):
            st.caption("OpenAI API를 사용합니다. ChatGPT 로그인과 별개로 API 키와 사용 가능한 모델명이 필요하며 호출 비용이 발생할 수 있습니다.")
            model = st.text_input("OpenAI 모델명", value=saved.model, max_chars=100, key="planner_llm_model")
            api_key = st.text_input("OpenAI API 키 (이 세션에서만 사용)", type="password",
                                    help="비워두면 기존 OpenAI 환경설정의 키를 사용합니다. 백업·보고서에 저장하지 않습니다.",
                                    key="planner_llm_key")
            if saved.api_key:
                st.caption("기존 OpenAI 키 설정이 있습니다. 값은 표시하지 않습니다.")
            connection = Connection(api_key.strip() or saved.api_key, model.strip())
        consent = st.checkbox("이수 학수번호·수강시점, 요건 점검값, 후보 과목, 계획 조건과 희망 사항을 OpenAI에 보내는 데 동의합니다.",
                              key="planner_llm_consent")
        st.caption("원 성적등급·이름·학번·대체인정 메모는 보내지 않습니다. 버튼을 누를 때만 요청하며 자동 재호출하지 않습니다. 응답 저장은 store=false로 요청합니다.")
    else:
        st.caption("현재는 외부 전송 없이 기본 계산기로 로드맵을 만듭니다.")
    return enabled, goal, connection, consent


def show_advice(assisted):
    if assisted.status != "llm":
        if assisted.notice:
            st.warning(assisted.notice)
        st.caption("처리 방식: 기본 계산 · LLM 설명 없음")
        return
    st.success("처리 방식: LLM 맞춤 추천 + 조건 검증")
    st.caption(assisted.notice + " 모델: " + assisted.model)
    # Plain text, not model-authored Markdown links or embedded external media.
    st.text(assisted.advice.summary)
    placed = {c.code for s in assisted.roadmap.semesters for c in s.courses}
    with st.expander("LLM이 제안한 추천 이유와 다음 행동", expanded=True):
        for suggestion in assisted.advice.priorities:
            label = "배치 반영" if suggestion.code in placed else "조건·부족 요건에 따라 미배치"
            st.text(f"{suggestion.code} ({label}): {suggestion.reason}")
        for step in assisted.advice.next_steps:
            st.text("• " + step)
