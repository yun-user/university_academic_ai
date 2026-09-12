import json
import streamlit as st
from src.admin_auth import require_admin
from src.config import get_settings

st.set_page_config(page_title="검색 평가", page_icon="📊", layout="wide")
st.title("검색 평가 결과")
st.caption("같은 질문으로 의미 검색과 하이브리드 검색의 출처 정확도를 비교합니다.")
require_admin()
folder = get_settings().project_root / "evals/reports"
reports = sorted(folder.glob("*.json"), reverse=True)
if not reports:
    st.info("python -m scripts.evaluate --split dev 명령으로 평가를 실행하세요.")
    st.stop()
selected = st.selectbox("평가 실행", reports, format_func=lambda p: p.name)
report = json.loads(selected.read_text(encoding="utf-8"))
st.info(report["limitation"])
st.caption(f'질문 구분: {report["split"]} · 상위 {report["top_k"]}개 · 유사도 기준 {report["threshold"]}')
st.dataframe([{"검색 방식": mode, **entry["metrics"]} for mode, entry in report["modes"].items()], hide_index=True)
for mode, entry in report["modes"].items():
    with st.expander(mode + " 질문별 결과"):
        st.dataframe(entry["details"], hide_index=True)
st.download_button("평가 JSON 저장", selected.read_bytes(), selected.name, "application/json")
