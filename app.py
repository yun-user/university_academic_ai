"""Streamlit 애플리케이션의 1단계 기본 화면."""

from __future__ import annotations

import streamlit as st

from src.config import ConfigurationError, get_settings
from src.logging_config import configure_logging, get_logger
from src.models import RuntimeMode, RuntimeStatus


def _render_configuration_error(error: ConfigurationError) -> None:
    st.set_page_config(page_title="설정 오류", page_icon="⚠️", layout="wide")
    st.error("애플리케이션 설정을 불러오지 못했습니다.")
    st.code(str(error), language=None)
    st.info(".env와 config/defaults.toml의 값을 확인한 뒤 다시 실행하세요.")


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

    runtime_status = RuntimeStatus(
        app_name=settings.app_name,
        mode=(
            RuntimeMode.GENERATION_ENABLED
            if settings.llm_enabled
            else RuntimeMode.RETRIEVAL_ONLY
        ),
        configuration_loaded=True,
        llm_configured=settings.llm_enabled,
    )
    logger.info(
        "application_started mode=%s environment=%s",
        runtime_status.mode.value,
        settings.environment,
    )

    st.title(runtime_status.app_name)
    st.caption("학사 문서의 실제 근거와 출처를 함께 제시하기 위한 RAG 서비스")

    if runtime_status.mode is RuntimeMode.RETRIEVAL_ONLY:
        st.info(
            "현재는 검색 전용 모드입니다. LLM API 키가 없어도 이후 단계의 "
            "문서 등록·검색·출처 확인 기능은 사용할 수 있도록 설계되어 있습니다."
        )
    else:
        st.success("LLM 설정을 확인했습니다. 생성 기능은 5단계에서 연결합니다.")

    status_columns = st.columns(3)
    status_columns[0].metric("프로젝트 구조", "준비됨")
    status_columns[1].metric("설정 로딩", "정상")
    status_columns[2].metric(
        "실행 모드",
        "검색 전용" if not runtime_status.llm_configured else "생성 설정됨",
    )

    st.subheader("현재 구현 범위")
    st.write(
        "이번 단계에서는 프로젝트 구조, 설정, 데이터 모델, 로깅과 기본 화면만 "
        "구현했습니다. PDF 처리, 검색, 답변 생성 기능은 아직 연결하지 않았습니다."
    )

    st.text_input(
        "질문",
        placeholder="검색 기능은 후속 단계에서 활성화됩니다.",
        disabled=True,
    )
    st.button("질문하기", disabled=True, use_container_width=True)

    with st.sidebar:
        st.header("시스템 상태")
        st.write(f"환경: `{settings.environment}`")
        st.write(
            "LLM: `설정됨`" if runtime_status.llm_configured else "LLM: `미설정`"
        )
        st.divider()
        st.caption("내부 경로와 비밀값은 화면이나 로그에 표시하지 않습니다.")


if __name__ == "__main__":
    main()
