"""Standalone planner. Basic mode is local; LLM recommendations are opt-in."""
import streamlit as st

st.navigation([st.Page("pages/7_졸업로드맵.py",title="졸업 로드맵",default=True)]).run()
