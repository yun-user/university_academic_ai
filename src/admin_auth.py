"""Local administrator password gate shared by management pages."""
import hashlib
import hmac
import os
import time
import streamlit as st
from src.config import get_settings


def require_admin():
    get_settings()  # load .env before reading the administrator credential
    password = os.getenv("ADMIN_PASSWORD", "")
    if len(password) < 12:
        st.info("관리자 기능을 사용하려면 .env의 ADMIN_PASSWORD를 12자 이상으로 설정하세요. setup.ps1은 이 값을 자동 생성합니다.")
        st.stop()
    fingerprint = hashlib.sha256(password.encode()).hexdigest()
    if st.session_state.get("admin_auth") == fingerprint:
        if st.sidebar.button("관리자 로그아웃"):
            st.session_state.pop("admin_auth", None)
            st.rerun()
        return
    with st.form("admin_login"):
        entered = st.text_input("관리자 비밀번호", type="password")
        submitted = st.form_submit_button("로그인")
    if submitted:
        if time.time() < st.session_state.get("admin_retry_after", 0):
            st.error("잠시 후 다시 시도하세요.")
        elif hmac.compare_digest(entered.encode(), password.encode()):
            st.session_state["admin_auth"] = fingerprint
            st.rerun()
        else:
            st.session_state["admin_retry_after"] = time.time() + 5
            st.error("비밀번호를 확인하세요.")
    st.stop()
