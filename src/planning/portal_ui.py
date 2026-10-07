"""Review portal data in the current Streamlit session before replacing input."""
import pandas as pd
import streamlit as st

from src.planning.io import COLUMNS, parse_rows, to_rows
from src.planning.models import CATEGORIES, STATUSES
from src.planning.portal import PortalError, PortalSession, local_portal_enabled
from src.planning.portal_import import parse_portal_tables, parse_portal_text


def _browser_connection(catalog):
    with st.expander("별도 Chrome / Edge 연결 (접속 불안정)", expanded=False):
        st.warning("별도 창에서는 학교 로그인 새로고침이 반복되는 현상이 확인되었습니다. 이 경우 연결을 종료하고 Codex 내부 브라우저의 성적표를 아래에 붙여넣으세요.")
        st.caption("이 PC에서 start_planner.cmd로 실행할 때 사용할 수 있습니다. 별도 브라우저 창에서 학교 아이디와 비밀번호를 입력하세요. 프로그램은 비밀번호를 입력받거나 로그인 쿠키를 저장하지 않습니다. 가져오기 성공 후 창이 닫히며, 사용하지 않으면 10분 뒤 연결이 종료됩니다.")
        enabled = local_portal_enabled(st.get_option("server.address"))
        if not enabled:
            st.info("학교 연결은 로컬 전용 실행에서 사용할 수 있습니다. start_planner.cmd로 실행해 주세요.")
        session = st.session_state.get("planner_portal_session")
        active = session is not None and session.active
        browser_name = st.selectbox("학교 로그인에 사용할 브라우저", ["Google Chrome", "Microsoft Edge"],
                                    key="planner_portal_browser", disabled=active)
        a, b, c = st.columns(3)
        if a.button("학교 로그인 창 열기", disabled=not enabled or active):
            try:
                with st.spinner("학교 로그인 창을 여는 중입니다…"):
                    channel = "chrome" if browser_name == "Google Chrome" else "msedge"
                    st.session_state.planner_portal_session = PortalSession(browser_channel=channel).start()
            except PortalError as exc:
                st.error(str(exc))
            else:
                st.rerun()
        if b.button("로그인 후 성적 가져오기", disabled=not enabled or not active):
            # A failed refresh must not leave an older preview available for application.
            st.session_state.pop("planner_portal_preview", None)
            try:
                with st.spinner("학교 전체성적조회를 읽고 과목을 대조합니다…"):
                    imported = parse_portal_tables(session.read(), catalog)
            except PortalError as exc:
                st.error(str(exc))
            else:
                st.session_state.planner_portal_preview = imported
                st.session_state.planner_portal_revision = st.session_state.get("planner_portal_revision", 0) + 1
                if imported.ready:
                    session.close()
                st.rerun()
        if c.button("학교 연결 종료", disabled=not active):
            session.close()
            st.rerun()
        if active:
            st.info(f"별도로 열린 {browser_name} 창에서 학교에 로그인하세요. 클래스넷 → 성적정보 → 전체성적조회를 연 다음 ‘로그인 후 성적 가져오기’를 누르세요.")


def controls(catalog, replace_rows):
    with st.expander("학교에서 이수내역 가져오기", expanded=False):
        st.write("**Codex 내부 브라우저에서 성적표 가져오기**")
        st.caption("Codex 내부 브라우저 등에서 전체성적조회 내용을 첫 학기 제목부터 마지막 학기까지 한 번에 복사해 붙여넣으세요. 학수번호를 하나씩 입력할 필요가 없습니다. 원문은 변환 후 입력창에서 지우고, 아래 미리보기에서 확인합니다.")
        with st.form("planner_portal_paste_form", clear_on_submit=True):
            copied = st.text_area("전체성적조회 내용 붙여넣기", height=140, max_chars=500000,
                                  key="planner_portal_paste")
            if st.form_submit_button("붙여넣은 성적표 확인"):
                st.session_state.planner_portal_preview = parse_portal_text(copied, catalog)
                st.session_state.planner_portal_revision = st.session_state.get("planner_portal_revision", 0) + 1
                st.rerun()
        _browser_connection(catalog)
        imported = st.session_state.get("planner_portal_preview")
        if imported is None:
            return
        for error in imported.errors:
            st.error(error)
        if not imported.ready:
            st.caption("일부만 가져온 자료로 기존 입력을 바꾸지 않습니다. 학교 화면을 확인한 뒤 다시 시도하세요.")
            return
        st.success(f"{imported.semester_count}개 학기 · {len(imported.attempts)}개 수강내역을 가져왔습니다. 아래에서 확인 후 적용하세요.")
        for warning in imported.warnings:
            st.warning(warning)
        revision = st.session_state.get("planner_portal_revision", 0)
        suggested = sum(a.category != "미확인" for a in imported.attempts)
        st.caption(f"교과과정 일치에 따른 분류 제안 {suggested}과목 · 이수구분 미확인 {len(imported.attempts) - suggested}과목")
        with st.expander("가져온 과목 확인·수정", expanded=False):
            preview = st.data_editor(pd.DataFrame(imported.reviews), hide_index=True, width="stretch",
                key=f"planner_portal_review_{revision}",
                disabled=["학수번호", "과목명", "학점", "수강연도", "학기", "성적", "분류 근거", "재수강 표시"],
                column_config={
                    "이수구분": st.column_config.SelectboxColumn(options=CATEGORIES, required=True),
                    "상태": st.column_config.SelectboxColumn(options=STATUSES, required=True),
                    "교양영역": st.column_config.NumberColumn(min_value=0, max_value=7, step=1),
                    "설계인정학점": st.column_config.NumberColumn(min_value=0, max_value=30, step=0.5),
                })
        checked = st.checkbox("2020학번 적용 대상이며, 가져온 학기·과목 수와 이수구분·재수강·설계학점을 확인했습니다",
                              key=f"planner_portal_checked_{revision}")
        st.caption("적용하면 현재 이수내역 전체가 이 표로 바뀝니다. 미확인 과목은 적용 후에도 수정할 수 있습니다. 학교 성적을 가져오는 것만으로 LLM에 전송하지 않으며, 전송 동의는 다시 받습니다.")
        if st.button("가져온 이수내역 적용", disabled=not checked):
            try:
                attempts = parse_rows([{k: row[k] for k in COLUMNS} for row in preview.to_dict("records")])
            except ValueError:
                st.error("이수구분·설계학점·교양영역·상태를 확인하세요. 기존 이수내역은 유지됩니다.")
            else:
                st.session_state.pop("planner_portal_preview", None)
                replace_rows(to_rows(attempts))
        if st.button("가져온 미리보기 지우기"):
            st.session_state.pop("planner_portal_preview", None)
            st.rerun()
