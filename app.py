"""검색 근거를 결정적 한국어 답변과 함께 보여주는 Streamlit 화면."""

from __future__ import annotations

import atexit
import logging
import re
from urllib.parse import urlsplit
from collections.abc import Sequence

import streamlit as st
from src.runtime import get_search_service as _get_search_service

from src.answering import (
    AnswerMode,
    AnswerResponse,
    AnswerService,
    AnswerSource,
    LLMAnswerService,
    build_answer_service,
    deduplicate_answer_sources,
)
from src.answering.answer_service import (
    NO_ACADEMIC_RULE_MESSAGE,
    OUTDATED_ANSWER_WARNING,
)
from src.config import ConfigurationError, get_settings
from src.logging_config import configure_logging, get_logger
from src.retrieval.course_search import (
    format_course_codes,
    format_credit_hours,
    format_grade,
    format_semesters,
    parse_course_info,
    truncate_text,
)
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
from src.retrieval.query_intent import (
    QuestionIntent,
    classify_question_intent,
)


DISCLAIMER = "본 서비스의 답변은 참고용이며, 공식 학사 행정 답변을 대신하지 않습니다."
NO_RESULTS_MESSAGE = (
    "현재 등록된 자료에서는 질문에 대한 정확한 근거를 찾지 못했습니다."
)


def _render_configuration_error(error: ConfigurationError) -> None:
    st.set_page_config(page_title="설정 오류", page_icon="⚠️", layout="wide")
    st.error("애플리케이션 설정을 불러오지 못했습니다.")
    st.code(str(error), language=None)
    st.info(".env와 config/defaults.toml의 값을 확인한 뒤 다시 실행하세요.")


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


def _render_search_results(
    results: Sequence[DocumentSearchResult],
    *,
    structured_query: bool = False,
    exact_match_count: int = 0,
    semantic_fallback_used: bool = False,
    expand_raw_text: bool = True,
) -> None:
    displayed_results = list(results)
    if exact_match_count > 0:
        st.markdown(f"조건에 맞는 과목 {exact_match_count}개를 찾았습니다")
    elif semantic_fallback_used:
        st.markdown("정확한 교과과정 항목을 찾지 못해 관련 자료를 표시합니다")

    if not displayed_results:
        st.info(NO_RESULTS_MESSAGE)
        return

    st.subheader("검색 결과")
    if not structured_query or semantic_fallback_used:
        st.caption(f"질문과 관련성이 높은 상위 {len(displayed_results)}건입니다.")
    for index, result in enumerate(displayed_results, start=1):
        with st.container(border=True):
            course = (
                parse_course_info(result.text)
                if result.file_type == "csv"
                else None
            )
            card_title = course.course_name if course is not None else result.title
            _location_label, location_value = _result_location(result)
            grade = format_grade(course)
            completion_type = (
                course.completion_type or "미지정"
                if course is not None
                else "해당 없음"
            )
            match_detail = (
                ("일치 방식", "구조화 조건 정확 일치")
                if exact_match_count > 0
                else ("유사도 점수", f"{result.score:.3f}")
            )
            details = (
                ("문서 유형", result.document_type),
                ("학과", result.department),
                ("기준연도", result.source_year or "미지정"),
                ("학년과 학기", f"{grade} · {format_semesters(course)}"),
                ("이수구분", completion_type),
                ("학수번호", format_course_codes(course)),
                ("학점/시수", format_credit_hours(course)),
                ("PDF 페이지 또는 CSV 행", location_value),
                ("출처 파일명", result.file_name),
                match_detail,
            )
            st.markdown(f"### {index}. {card_title}")
            if _safe_source_url(result.source_url):
                st.link_button("공식 원문 열기", result.source_url)
            st.markdown(
                "\n".join(
                    f"- **{label}:** {value}" for label, value in details
                )
            )
            if result.file_type == "pdf":
                st.markdown("**미리보기**")
                st.write(truncate_text(result.text, limit=300))
            elif result.file_type == "txt":
                st.write(truncate_text(result.text, limit=300))
            if result.is_current is False:
                st.warning(
                    result.currentness_warning
                    or OUTDATED_DOCUMENT_WARNING
                )
            if expand_raw_text:
                with st.expander("원문 보기"):
                    st.code(result.text, language=None, wrap_lines=True)
            else:
                st.markdown("**원문**")
                st.code(result.text, language=None, wrap_lines=True)
                if result.context_text and result.context_text != result.text:
                    st.markdown("**같은 페이지의 적용 범위 문맥**")
                    st.code(
                        result.context_text,
                        language=None,
                        wrap_lines=True,
                    )


def _render_answer(text: str) -> None:
    st.subheader("답변")
    st.markdown(_answer_body_for_display(text))


def _answer_body_for_display(text: str) -> str:
    """이전 답변 형식의 내장 출처 블록도 화면에서는 한 번만 보이게 한다."""

    body = text
    trailing_warning = OUTDATED_ANSWER_WARNING if OUTDATED_ANSWER_WARNING in text else ""
    for heading in ("\n답변에 사용된 출처:\n", "\n출처:\n"):
        if heading not in body:
            continue
        body = body.split(heading, 1)[0].rstrip()
        break
    if trailing_warning and trailing_warning not in body:
        body = f"{body}\n\n{trailing_warning}"
    citation_ids = list(dict.fromkeys(re.findall(r"\[근거:([^\]]+)\]", body)))
    for index, chunk_id in enumerate(citation_ids, 1):
        body = body.replace(f"[근거:{chunk_id}]", f"[출처 {index}]")
    # GFM can interpret paired single tildes as strikethrough. Display
    # numerical ranges with an en dash while preserving the source text.
    body = re.sub(r"(?<=\d)\s*~\s*(?=\d)", "–", body)
    return body


def _safe_source_url(value):
    if not value:
        return False
    try:
        parts = urlsplit(value)
        return parts.scheme == "https" and bool(parts.hostname) and not parts.username and not parts.password
    except ValueError:
        return False


def _answer_source_location(source: AnswerSource) -> str:
    if source.page_number is not None:
        return f"PDF {source.page_number}쪽"
    if source.row_number is not None:
        return f"CSV {source.row_number}행"
    return "TXT 문서 전체"


def _answer_source_currentness(source: AnswerSource) -> str:
    if source.is_current is True:
        return "최신 자료"
    if source.is_current is False:
        return "최신 자료가 아닐 수 있음"
    return "최신 여부 미지정"


def _render_answer_sources(sources: Sequence[AnswerSource]) -> None:
    """최종 답변에 사용된 출처를 전체 검색 근거와 분리해 표시한다."""

    if not sources:
        return
    st.markdown("**출처**")
    for source in deduplicate_answer_sources(sources):
        st.markdown(
            f"- {source.file_name} · {_answer_source_location(source)} · "
            f"기준연도 {source.source_year or '미지정'} · "
            f"{_answer_source_currentness(source)}"
        )
        if _safe_source_url(source.source_url):
            st.link_button("출처 웹페이지", source.source_url)


def _render_search_page(
    service: DocumentSearchService,
    *,
    app_name: str,
    logger: logging.Logger | None = None,
    answer_service: AnswerService | LLMAnswerService | None = None,
    answer_mode_label: str = "기본 근거 기반 답변",
    llm_requested: bool = False,
) -> None:
    logger = logger or get_logger(__name__)
    selected_answer_service = answer_service or AnswerService(service)
    indexed_chunk_count = service.indexed_chunk_count
    departments = service.available_departments()
    department_options = [None, *[d for d in departments if d != "전체"]]
    document_types = service.available_document_types()

    st.title(app_name)
    st.caption("ACADEMIC EVIDENCE · 문서로 확인하는 학사정보")
    if answer_mode_label == "LLM 보조 답변":
        st.caption(
            "등록된 PDF·CSV·TXT 검색 근거 안에서만 LLM이 답변을 정리하며, "
            "사용할 수 없으면 기본 답변으로 자동 전환합니다."
        )
    else:
        st.caption(
            "등록된 PDF·CSV·TXT 학사 자료의 검색 근거만으로 "
            "결정적 답변과 출처 위치를 함께 보여드립니다."
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
                options=department_options,
                index=1 if len(department_options) == 2 else 0,
                format_func=lambda value: "전체 학과" if value is None else value,
            )
        with filter_columns[1]:
            selected_document_type = st.selectbox(
                "문서 유형 선택",
                options=[None, *document_types],
                format_func=_document_type_label,
            )
        from datetime import date
        scope_columns = st.columns(2)
        with scope_columns[0]:
            admission_year = st.selectbox("입학연도 (선택)",
                options=[None, *range(date.today().year, 1989, -1)],
                format_func=lambda value: "모름 / 미선택" if value is None else f"{value}년")
        with scope_columns[1]:
            graduation_track = st.selectbox("졸업 과정 (선택)",
                options=[None, "심화과정", "일반과정"],
                format_func=lambda value: "모름 / 미선택" if value is None else value)
        st.caption("졸업요건 질문에 적용합니다. 질문에 직접 적은 입학연도와 과정이 우선합니다.")
        submitted = st.form_submit_button(
            "검색",
            type="primary",
            use_container_width=True,
        )

    with st.sidebar:
        st.header("검색 상태")
        st.metric("검색 가능한 청크", f"{indexed_chunk_count:,}개")
        st.caption("유사도는 정답 확률이 아닙니다. 적용연도와 원문을 함께 확인하세요.")
        st.markdown("**답변 모드**")
        st.write(answer_mode_label)
        if answer_mode_label == "LLM 보조 답변":
            st.caption("LLM 사용 설정이 켜져 있습니다. 질문에 따라 기본 근거 기반 답변을 제공할 수 있습니다.")
        elif llm_requested:
            st.caption("LLM을 사용할 수 없어 기본 답변 모드로 전환했습니다.")
        else:
            st.caption("외부 LLM을 호출하지 않고 검색 근거만으로 답변합니다.")
        with st.expander("LLM 사용 안내"):
            st.markdown(
                "LLM을 연결해도 모든 질문에서 외부 LLM을 호출하지는 않습니다. "
                "다음 경우에는 기본 근거 기반 답변을 사용합니다.\n\n"
                "- **검토된 규정:** 졸업요건·설계학점 등 사람이 원문과 대조한 답변\n"
                "- **정확한 표 조회:** 학수번호·학점 등 등록된 표에서 직접 확인하는 답변\n"
                "- **근거 부족:** 질문에 답할 자료가 부족해 추가 확인이 필요한 경우\n"
                "- **호출·검증 실패:** API 오류가 발생하거나 LLM 답변이 근거 검증을 통과하지 못한 경우"
            )
            st.caption(
                "위의 ‘답변 모드’는 사용 설정이고, 질문 후 표시되는 ‘현재 응답 모드’는 "
                "해당 답변의 처리 방식입니다. 기본 답변이 나왔다는 이유만으로 연결 실패는 아닙니다."
            )

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
        empty_message = (
            NO_ACADEMIC_RULE_MESSAGE
            if classify_question_intent(question) is QuestionIntent.ACADEMIC_RULE
            else NO_RESULTS_MESSAGE
        )
        _render_answer(empty_message)
        return

    try:
        from src.retrieval.query_intent import is_graduation_question
        from src.retrieval.reviewed_rules import add_scope_to_question
        if is_graduation_question(question):
            question = add_scope_to_question(question, admission_year, graduation_track)
        with st.spinner("관련 학사 자료를 검색하고 답변을 정리하고 있습니다..."):
            answer: AnswerResponse = selected_answer_service.answer_question(
                question,
                top_k=3,
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

    _render_answer(answer.text)
    _render_answer_sources(answer.sources)
    actual_mode_label = (
        "LLM 보조 답변"
        if answer.answer_mode is AnswerMode.LLM
        else "기본 근거 기반 답변"
    )
    st.sidebar.caption(f"현재 응답 모드: {actual_mode_label}")
    if llm_requested and answer.answer_mode is AnswerMode.DETERMINISTIC:
        st.info(
            "이번 답변은 기본 근거 기반 답변 모드로 제공됩니다. "
            "검토된 규정이나 표 조회 등에서는 LLM이 연결되어 있어도 이 모드를 사용합니다. "
            "자세한 조건은 왼쪽 ‘LLM 사용 안내’를 확인하세요."
        )
    response = answer.search_response
    if response.results:
        with st.expander("검색 근거 보기"):
            _render_search_results(
                response.results,
                structured_query=response.structured_query,
                exact_match_count=response.exact_match_count,
                semantic_fallback_used=response.semantic_fallback_used,
                expand_raw_text=False,
            )


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
        "application_started mode=%s environment=%s",
        settings.runtime_mode,
        settings.environment,
    )

    try:
        service = _get_search_service()
        answer_service = build_answer_service(
            service,
            settings,
            logger=logger,
        )
        _render_search_page(
            service,
            app_name=settings.app_name,
            logger=logger,
            answer_service=answer_service,
            answer_mode_label=(
                "LLM 보조 답변"
                if settings.llm_available
                else "기본 근거 기반 답변"
            ),
            llm_requested=settings.llm_enabled,
        )
    except Exception:
        logger.exception("search_ui_initialization_failed")
        st.error(
            "검색 서비스를 시작하지 못했습니다. 설정과 벡터 DB 상태를 확인해 주세요."
        )


if __name__ == "__main__":
    main()
