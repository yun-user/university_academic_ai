import streamlit as st
import pymupdf
from src.admin_auth import require_admin
from src.config import get_settings
from src.ingestion.registry import list_documents, safe_path, database
from src.ingestion.ocr import recognize_page, review_page, page_preview

st.set_page_config(page_title="스캔 PDF 검토", page_icon="🔎", layout="wide")
st.title("스캔 PDF · OCR 검토")
st.caption("원본 페이지와 인식한 텍스트를 대조합니다. 승인한 결과만 다음 색인 갱신에 반영됩니다.")
require_admin()
settings = get_settings()
root = settings.project_root
pdfs = [d for d in list_documents(root) if d["path"].endswith(".pdf")]
if not pdfs:
    st.info("PDF를 먼저 등록하세요.")
    st.stop()
document = st.selectbox("PDF 선택", pdfs, format_func=lambda d: d["name"] + " · " + d["id"][:16])
with pymupdf.open(safe_path(root, document["path"])) as pdf:
    page_count = len(pdf)
page_number = st.number_input("PDF 실제 페이지 번호", min_value=1, max_value=page_count, value=1)
if st.button("이 페이지 OCR 실행", type="primary"):
    try:
        with st.spinner("페이지에서 문자를 인식합니다."):
            recognize_page(root, document, page_number, languages=settings.ocr_languages,
                           dpi=min(settings.ocr_dpi, 300))
        st.success("인식했습니다. 아래에서 원문과 대조 후 승인하세요.")
    except Exception as exc:
        st.error(str(exc) if isinstance(exc, ValueError) else "OCR 실행에 실패했습니다. 언어 데이터와 PDF 상태를 확인하세요.")
left, right = st.columns(2)
with left:
    st.image(page_preview(root, document, page_number), caption=f"원본 PDF {page_number}쪽")
with right:
    with database(root) as con:
        row = con.execute("SELECT * FROM ocr WHERE id=? AND page=?", (document["id"], page_number)).fetchone()
    if row:
        with st.form(f'ocr_review_{document["id"]}_{page_number}_{row["hash"]}'):
            text = st.text_area("검토·수정할 텍스트", row["text"], height=480)
            st.caption("표의 행·열 관계, 숫자, 학점, 예외 조건을 특히 확인하세요.")
            approved = st.checkbox("원본과 대조했습니다", value=bool(row["approved"]))
            save = st.form_submit_button("검토 결과 저장")
        if save:
            try:
                review_page(root, document, page_number, text, approved=approved)
                st.success("저장했습니다. 문서 관리에서 검색 데이터 반영을 실행하세요.")
            except ValueError as exc:
                st.error(str(exc))
    else:
        st.info("OCR을 실행하면 검토할 텍스트가 표시됩니다.")
