import hashlib
import os
from urllib.parse import urlsplit
import streamlit as st
from src.admin_auth import require_admin
from src.config import get_settings
from src.ingestion.web_collector import PublicCollector
from src.ingestion.registry import register_document, timestamp

st.set_page_config(page_title="공개 공지 수집", page_icon="🌐", layout="wide")
st.title("공개 공지 수집")
st.caption("공식 HTTPS 공지의 본문을 확인하고 출처 URL과 함께 등록합니다.")
require_admin()
root = get_settings().project_root
with st.form("collect"):
    domains = st.text_input("허용 도메인 (쉼표로 구분)", os.getenv("CRAWL_ALLOWED_HOSTS", "www.hongik.ac.kr"))
    url = st.text_input("공지 본문 URL", placeholder="https://...")
    selector = st.text_input("본문 CSS 선택자 (선택)", help="비우면 article 또는 main 영역을 찾습니다.")
    submitted = st.form_submit_button("본문 가져오기", type="primary")
if submitted:
    st.session_state.pop("web_preview", None)
    try:
        with st.spinner("공개 접근 여부와 수집 규칙을 확인하고 본문을 가져옵니다."):
            st.session_state.web_preview = PublicCollector(domains.split(",")).collect(url.strip(), selector=selector.strip())
    except Exception as exc:
        st.error(str(exc) if isinstance(exc, ValueError) else "사이트 연결에 실패했습니다. 주소와 HTTPS 인증서를 확인하세요.")
preview = st.session_state.get("web_preview")
if preview:
    st.subheader(preview.title)
    st.link_button("공식 원문 열기", preview.url)
    st.code(preview.text, language=None, wrap_lines=True)
    with st.form("save_web"):
        department = st.text_input("적용 학과", "전체")
        published = st.text_input("게시일 (원문에서 확인)", preview.published or "")
        year = st.text_input("적용 학년도", placeholder="예: 2026")
        verified = st.checkbox("공지 본문과 게시일을 원문에서 확인했습니다")
        save = st.form_submit_button("출처와 함께 등록")
    if save:
        try:
            if not verified or not published.strip() or not department.strip():
                raise ValueError("적용 학과와 게시일을 입력하고 원문을 확인하세요.")
            content = f"제목: {preview.title}\n게시일: {published}\n\n{preview.text}"
            doc_id = register_document(root, "공개공지_" + hashlib.sha256(preview.url.encode()).hexdigest()[:12] + ".txt",
                content.encode("utf-8"), {"title": preview.title, "document_type": "공개공지",
                "department": department, "source_url": preview.url, "source_year": year,
                "effective_from": published, "authority": urlsplit(preview.url).hostname,
                "collected_at": timestamp(), "is_current": ""})
            snapshots = root / "data/snapshots"
            snapshots.mkdir(parents=True, exist_ok=True)
            snapshot = snapshots / (doc_id + ".html")
            if not snapshot.exists():
                snapshot.write_text(preview.html, encoding="utf-8")
            st.success("등록했습니다. 문서 관리에서 ‘검색 데이터 반영’을 실행하세요.")
        except ValueError as exc:
            st.error(str(exc))
