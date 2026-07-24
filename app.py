"""통합 PDF·CSV·TXT 원문을 출처와 함께 보여주는 Streamlit 검색 화면."""

from __future__ import annotations

import atexit
import logging
from collections.abc import Sequence

import streamlit as st

from src.config import ConfigurationError, get_settings
from src.logging_config import configure_logging, get_logger
from src.retrieval.document_models import (
    DocumentSearchResult,
    OUTDATED_DOCUMENT_WARNING,
)
from src.retrieval.document_search_service import (
    CorpusLoadError,
    DocumentSearchService,
)
from src.retrieval.document_vector_store import DocumentVectorStoreError
from src.retrieval.embeddings import EmbeddingError


DISCLAIMER = "본 서비스의 답변은 참고용이며, 공식 학사 행정 답변을 대신하지 않습니다."
NO_RESULTS_MESSAGE = (
    "등록된 학사 자료에서 확인할 수 없습니다. "
    "학교 학사 담당 부서에 문의해 주세요."
)


def _render_configuration_error(error: ConfigurationError) -> None:
    st.set_page_config(page_title="설정 오류", page_icon="⚠️", layout="wide")
    st.error("애플리케이션 설정을 불러오지 못했습니다.")
    st.code(str(error), language=None)
    st.info(".env와 config/defaults.toml의 값을 확인한 뒤 다시 실행하세요.")


@st.cache_resource(show_spinner=False)
def _get_search_service() -> DocumentSearchService:
    """Streamlit 재실행 간 모델과 Chroma client를 재사용한다."""

    service = DocumentSearchService.from_settings(get_settings())
    atexit.register(service.close)
    return service


def _document_type_label(document_type: str | None) -> str:
    return "전체 문서 유형" if document_type is None else document_type


def _result_location(result: DocumentSearchResult) -> tuple[str, str]:
    if result.page_number is not None:
        return "페이지 번호", f"{result.page_number}쪽"
    if result.row_number is not None:
        return "CSV 행 번호", f"{result.row_number}행"
    return "문서 위치", "문서 전체"


def _current_status_label(result: DocumentSearchResult) -> str:
    if result.is_current is True:
        return "최신 자료"
    if result.is_current is False:
        return "확인 필요"
    return "미지정"


def _render_search_results(results: Sequence[DocumentSearchResult]) -> None:
    if not results:
        st.info(NO_RESULTS_MESSAGE)
        return

    st.subheader("검색 결과")
    st.caption(f"관련 원문 {len(results)}건을 찾았습니다.")
    for index, result in enumerate(results, start=1):
        with st.container(border=True):
            st.markdown(f"### {index}. {result.title}")
            location_label, location_value = _result_location(result)
            metadata_columns = st.columns(5)
            metadata_columns[0].metric(location_label, location_value)
            metadata_columns[1].metric("Cosine 검색 점수", f"{result.score:.3f}")
            metadata_columns[2].metric("문서 유형", result.document_type)
            metadata_columns[3].metric(
                "기준연도",
                result.source_year or "미지정",
            )
            metadata_columns[4].metric(
                "최신 자료 여부",
                _current_status_label(result),
            )
            st.caption(
                f"학과: {result.department} · "
                f"출처 파일: {result.file_name} · "
                f"자료 형식: {result.file_type.upper()}"
            )
            if result.is_current is False:
                st.warning(
                    result.currentness_warning
                    or OUTDATED_DOCUMENT_WARNING
                )
            with st.expander("원문 펼쳐보기"):
                st.code(result.text, language=None, wrap_lines=True)


def _render_search_page(
    service: DocumentSearchService,
    *,
    app_name: str,
    logger: logging.Logger | None = None,
) -> None:
    logger = logger or get_logger(__name__)
    indexed_chunk_count = service.indexed_chunk_count
    departments = service.available_departments()
    document_types = service.available_document_types()

    st.title(app_name)
    st.caption(
        "AI 답변을 생성하지 않고, 등록된 PDF·CSV·TXT 학사 자료에서 질문과 "
        "관련된 원문과 출처 위치를 함께 보여드립니다."
    )
    st.warning(DISCLAIMER)

    with st.form("document_search_form", clear_on_submit=False):
        question = st.text_input(
            "질문",
            placeholder="예: 졸업하려면 전공학점을 몇 학점 들어야 해?",
        )
        filter_columns = st.columns(2)
        with filter_columns[0]:
            selected_department = st.selectbox(
                "학과 선택",
                options=[None, *departments],
                format_func=lambda value: "전체 학과" if value is None else value,
            )
        with filter_columns[1]:
            selected_document_type = st.selectbox(
                "문서 유형 선택",
                options=[None, *document_types],
                format_func=_document_type_label,
            )
        submitted = st.form_submit_button(
            "검색",
            type="primary",
            use_container_width=True,
        )

    with st.sidebar:
        st.header("검색 상태")
        st.metric("검색 가능한 청크", f"{indexed_chunk_count:,}개")
        st.write("실행 모드: `검색 전용`")
        st.caption("LLM 답변 생성 없이 관련 원문만 표시합니다.")

    if not submitted:
        if indexed_chunk_count == 0:
            st.info(
                "현재 등록된 검색 문서가 없습니다. "
                "documents.jsonl 통합 색인을 먼저 생성해 주세요."
            )
        return
    if not question.strip():
        st.warning("검색할 질문을 입력해 주세요.")
        return
    if indexed_chunk_count == 0:
        st.info(NO_RESULTS_MESSAGE)
        return

    try:
        with st.spinner("관련 학사 자료를 검색하고 있습니다..."):
            results = service.search(
                question,
                department=selected_department,
                document_type=selected_document_type,
            )
    except (
        CorpusLoadError,
        DocumentVectorStoreError,
        EmbeddingError,
        ValueError,
    ):
        logger.exception("document_search_failed")
        st.error("검색 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")
        return

    _render_search_results(results)


def main() -> None:
    try:
        settings = get_settings()
    except ConfigurationError as error:
        _render_configuration_error(error)
        return

    st.set_page_config(
        page_title=settings.app_name,
        page_icon="🎓",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    configure_logging(
        settings.log_level,
        secrets=(settings.llm_api_key or "",),
    )
    logger = get_logger(__name__)

    logger.info(
        "application_started mode=retrieval-only environment=%s",
        settings.environment,
    )

    try:
        service = _get_search_service()
        _render_search_page(
            service,
            app_name=settings.app_name,
            logger=logger,
        )
    except Exception:
        logger.exception("search_ui_initialization_failed")
        st.error(
            "검색 서비스를 시작하지 못했습니다. 설정과 벡터 DB 상태를 확인해 주세요."
        )


if __name__ == "__main__":
    main()
