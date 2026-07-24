"""외부 모델 없이 통합 Streamlit 검색 화면을 검증한다."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest


def _result_search_app():
    from app import _render_search_page
    from src.retrieval.document_models import (
        DocumentSearchResult,
        OUTDATED_DOCUMENT_WARNING,
    )

    class FakeSearchService:
        indexed_chunk_count = 2

        def available_departments(self):
            return ["테스트학과A", "테스트학과B"]

        def available_document_types(self):
            return ["장학금선정기준", "학년별교과과정"]

        def search(self, question, **filters):
            if (
                question == "장학금 선발 기준"
                and filters.get("department") == "테스트학과B"
                and filters.get("document_type") == "장학금선정기준"
            ):
                return [
                    DocumentSearchResult(
                        document_id="scholarship-2024",
                        chunk_id="test-chunk-1",
                        file_name="2024_장학금선정기준.pdf",
                        file_type="pdf",
                        document_type="장학금선정기준",
                        source_year="2024",
                        department="테스트학과B",
                        is_current=False,
                        page_number=7,
                        title="장학금선정기준",
                        source_path="C:/internal/secret.pdf",
                        text="장학금 선발은 등록된 성적 기준에 따릅니다.",
                        score=0.87654,
                        content_hash="a" * 64,
                        currentness_warning=OUTDATED_DOCUMENT_WARNING,
                    )
                ]
            return []

    _render_search_page(
        FakeSearchService(),
        app_name="테스트 학사정보 검색 서비스",
    )


def _mixed_source_search_app():
    from app import _render_search_page
    from src.retrieval.document_models import DocumentSearchResult

    class MixedSearchService:
        indexed_chunk_count = 2

        def available_departments(self):
            return ["소프트웨어융합학과"]

        def available_document_types(self):
            return ["학년별교과과정", "학교기본정보"]

        def search(self, question, **filters):
            if question != "교과목과 학교 정보":
                return []
            return [
                DocumentSearchResult(
                    document_id="curriculum-2026",
                    chunk_id="csv-row-12",
                    file_name="교과과정.csv",
                    file_type="csv",
                    document_type="학년별교과과정",
                    source_year="2026",
                    department="소프트웨어융합학과",
                    is_current=True,
                    row_number=12,
                    title="교과과정",
                    source_path="data/raw/tables/교과과정.csv",
                    text="학수번호: 001234, 교과목명: 창의적공학설계입문",
                    score=0.91,
                    content_hash="b" * 64,
                ),
                DocumentSearchResult(
                    document_id="school-info",
                    chunk_id="txt-body-1",
                    file_name="학교정보.txt",
                    file_type="txt",
                    document_type="학교기본정보",
                    source_year="2026",
                    department="전체",
                    is_current=True,
                    title="학교정보",
                    source_path="data/raw/text/학교정보.txt",
                    text="학교 기본 정보 원문",
                    score=0.82,
                    content_hash="c" * 64,
                ),
            ]

    _render_search_page(
        MixedSearchService(),
        app_name="테스트 학사정보 검색 서비스",
    )


def _empty_result_app():
    from app import _render_search_page

    class EmptySearchService:
        indexed_chunk_count = 1

        def available_departments(self):
            return ["테스트학과"]

        def available_document_types(self):
            return ["장학금선정기준"]

        def search(self, question, **filters):
            return []

    _render_search_page(
        EmptySearchService(),
        app_name="테스트 학사정보 검색 서비스",
    )


def _empty_index_app():
    from app import _render_search_page

    class EmptyIndexService:
        indexed_chunk_count = 0

        def available_departments(self):
            return []

        def available_document_types(self):
            return []

        def search(self, question, **filters):
            raise AssertionError("빈 색인에서는 검색을 호출하면 안 됩니다.")

    _render_search_page(
        EmptyIndexService(),
        app_name="테스트 학사정보 검색 서비스",
    )


def _submit_filtered_search(app: AppTest, question: str) -> AppTest:
    app.text_input[0].set_value(question)
    app.selectbox[0].select("테스트학과B")
    app.selectbox[1].select("장학금선정기준")
    return app.button[0].click().run()


def test_search_screen_contains_requested_controls_and_disclaimer() -> None:
    app = AppTest.from_function(_result_search_app).run()

    assert app.exception == []
    assert app.title[0].value == "테스트 학사정보 검색 서비스"
    assert app.text_input[0].label == "질문"
    assert [selectbox.label for selectbox in app.selectbox] == [
        "학과 선택",
        "문서 유형 선택",
    ]
    assert app.button[0].label == "검색"
    assert any(
        warning.value
        == "본 서비스의 답변은 참고용이며, 공식 학사 행정 답변을 대신하지 않습니다."
        for warning in app.warning
    )


def test_search_result_shows_integrated_metadata_and_outdated_warning() -> None:
    app = AppTest.from_function(_result_search_app).run()
    app = _submit_filtered_search(app, "장학금 선발 기준")

    assert app.exception == []
    assert any(item.value == "검색 결과" for item in app.subheader)
    assert any("장학금선정기준" in item.value for item in app.markdown)
    assert any(
        metric.label == "페이지 번호" and metric.value == "7쪽"
        for metric in app.metric
    )
    assert any(
        metric.label == "Cosine 검색 점수" and metric.value == "0.877"
        for metric in app.metric
    )
    assert any(
        metric.label == "문서 유형" and metric.value == "장학금선정기준"
        for metric in app.metric
    )
    assert any(
        metric.label == "기준연도" and metric.value == "2024"
        for metric in app.metric
    )
    assert any(
        metric.label == "최신 자료 여부" and metric.value == "확인 필요"
        for metric in app.metric
    )
    assert any(
        warning.value == "최신 자료가 아닐 수 있습니다"
        for warning in app.warning
    )
    assert any(expander.label == "원문 펼쳐보기" for expander in app.expander)
    assert any(
        "장학금 선발은 등록된 성적 기준에 따릅니다." in code.value
        for code in app.code
    )
    visible_text = " ".join(
        str(element.value)
        for group in (app.markdown, app.caption, app.code)
        for element in group
    )
    assert "테스트학과B" in visible_text
    assert "2024_장학금선정기준.pdf" in visible_text
    assert "C:/internal/secret.pdf" not in visible_text


def test_csv_row_and_txt_whole_document_locations_are_rendered() -> None:
    app = AppTest.from_function(_mixed_source_search_app).run()
    app.text_input[0].set_value("교과목과 학교 정보")
    app = app.button[0].click().run()

    assert app.exception == []
    locations = {
        (metric.label, metric.value)
        for metric in app.metric
    }
    assert ("CSV 행 번호", "12행") in locations
    assert ("문서 위치", "문서 전체") in locations
    visible_text = " ".join(
        str(element.value)
        for group in (app.markdown, app.caption, app.code)
        for element in group
    )
    assert "교과과정.csv" in visible_text
    assert "학교정보.txt" in visible_text
    assert "None쪽" not in visible_text
    assert "None행" not in visible_text


def test_no_related_document_shows_standard_message() -> None:
    app = AppTest.from_function(_empty_result_app).run()
    app.text_input[0].set_value("관련 없는 질문")
    app = app.button[0].click().run()

    assert app.exception == []
    assert any(
        info.value
        == "등록된 학사 자료에서 확인할 수 없습니다. 학교 학사 담당 부서에 문의해 주세요."
        for info in app.info
    )


def test_empty_index_does_not_call_search_service() -> None:
    app = AppTest.from_function(_empty_index_app).run()
    app.text_input[0].set_value("장학금 기준")
    app = app.button[0].click().run()

    assert app.exception == []
    assert not app.error
    assert any(
        "등록된 학사 자료에서 확인할 수 없습니다" in info.value
        for info in app.info
    )
