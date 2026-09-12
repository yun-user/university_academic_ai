"""Administrator uploads, version replacement, activation and ingestion diagnostics."""
import json
import streamlit as st
from src.admin_auth import require_admin
from src.config import get_settings
from src.ingestion.registry import list_documents, register_document, set_active, database
from src.runtime import synchronize

st.set_page_config(page_title="문서 관리", page_icon="📚", layout="wide")
st.title("문서 관리")
st.caption("자료의 출처와 적용 대상을 등록하고 검색에 반영합니다.")
require_admin()
root = get_settings().project_root
documents = list_documents(root)
labels = {d["id"]: f'{d["name"]} · {d["id"][:16]}' for d in documents}

with st.expander("자료 등록 · 새 버전으로 교체", expanded=True):
    with st.form("upload_document"):
        upload = st.file_uploader("PDF / CSV / TXT", type=["pdf", "csv", "txt"])
        c1, c2 = st.columns(2)
        department = c1.text_input("학과", "소프트웨어융합학과")
        kind = c2.text_input("문서 유형", "학사안내")
        year = c1.text_input("기준연도", placeholder="예: 2026")
        authority = c2.text_input("발행 기관", placeholder="예: 학사지원팀")
        admission_from = c1.text_input("적용 입학연도 시작 (선택)")
        admission_to = c2.text_input("적용 입학연도 끝 (선택)")
        source_url = st.text_input("공식 출처 URL (선택)")
        current = st.selectbox("최신 여부", ["확인 필요", "최신 자료로 확인함", "과거 자료"])
        replaces = st.selectbox("교체할 이전 자료 (선택)", [None, *labels],
            format_func=lambda x: "신규 자료" if x is None else labels[x])
        submit = st.form_submit_button("원본 보존하여 등록", type="primary")
    if submit:
        try:
            if upload is None or not department.strip() or not kind.strip():
                raise ValueError("파일, 학과, 문서 유형을 입력하세요.")
            for value in (year, admission_from, admission_to):
                if value and (len(value) != 4 or not value.isdigit()):
                    raise ValueError("연도는 네 자리 숫자로 입력하세요.")
            if admission_from and admission_to and admission_from > admission_to:
                raise ValueError("입학연도 범위를 확인하세요.")
            register_document(root, upload.name, upload.getvalue(), {
                "department": department, "document_type": kind, "source_year": year,
                "authority": authority, "source_url": source_url,
                "admission_year_from": admission_from, "admission_year_to": admission_to,
                "is_current": {"확인 필요": "", "최신 자료로 확인함": "Y", "과거 자료": "N"}[current],
            }, replaces=replaces)
            st.success("등록했습니다. 아래 ‘검색 데이터 반영’을 실행하세요.")
        except Exception as exc:
            st.error(str(exc) if isinstance(exc, ValueError) else "등록에 실패했습니다. 파일 상태를 확인하세요.")

st.subheader("등록 자료")
documents = list_documents(root)
st.dataframe([{"문서": d["name"], "학과": d["metadata"].get("department"),
    "기준연도": d["metadata"].get("source_year"), "사용": d["active"], "ID": d["id"]}
    for d in documents], hide_index=True, use_container_width=True)
if documents:
    selected = st.selectbox("상태를 변경할 자료", documents, format_func=lambda d: d["name"] + " · " + d["id"][:16])
    if st.button("비활성화" if selected["active"] else "다시 활성화"):
        set_active(root, selected["id"], not selected["active"])
        st.success("상태를 저장했습니다. 검색 데이터 반영 후 검색 결과에 적용됩니다. 원본은 보존됩니다.")

st.divider()
if st.button("검색 데이터 반영", type="primary"):
    try:
        with st.spinner("문서를 처리하고 검색 색인을 갱신합니다. 첫 실행은 모델 다운로드로 시간이 걸릴 수 있습니다."):
            report = synchronize()
        st.success(f"반영 완료 · {report.indexed_document_count}개 문서 · {report.indexed_chunk_count}개 검색 문단")
    except Exception as exc:
        st.error(str(exc) if isinstance(exc, ValueError) else "색인 갱신에 실패했습니다. 설치 상태와 모델 연결을 확인하세요.")
report_path = root / "data/processed/ingestion_report.json"
if report_path.exists():
    with st.expander("문서 처리 보고서"):
        st.json(json.loads(report_path.read_text(encoding="utf-8")))
with st.expander("최근 관리 기록"):
    with database(root) as con:
        st.dataframe([dict(row) for row in con.execute("SELECT * FROM audit ORDER BY rowid DESC LIMIT 30")], hide_index=True)
