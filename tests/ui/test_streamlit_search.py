"""외부 모델 없이 Streamlit 검색 화면을 검증한다."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from src.models import DocumentType


def _result_search_app():
    from uuid import UUID

    from app import _render_search_page
    from src.models import DocumentType
    from src.retrieval.models import SearchResult

    class FakeSearchService:
        indexed_chunk_count = 2

        def available_departments(self):
            return ["테스트학과 A", "테스트학과 B"]

        def available_document_types(self):
            return [DocumentType.PDF]

        def search(self, question, **filters):
            if (
                question == "장학금 선발 기준"
                and filters.get("department") == "테스트학과 B"
                and filters.get("document_type") is DocumentType.PDF
            ):
                return [
                    SearchResult(
                        document_id=UUID(int=1),
                        chunk_id="test-chunk-1",
                        document_title="장학금 선정기준",
                        document_type=DocumentType.PDF,
                        department="테스트학과 B",
                        page_number=7,
                        content="장학금 선발은 등록된 성적 기준을 따릅니다.",
                        score=0.87654,
                        content_hash="a" * 64,
                        source_path="C:/internal/secret.pdf",
                    )
                ]
            return []

    _render_search_page(
        FakeSearchService(),
        app_name="테스트 학사정보 검색 서비스",
    )


def _empty_result_app():
    from app import _render_search_page
    from src.models import DocumentType

    class EmptySearchService:
        indexed_chunk_count = 1

        def available_departments(self):
            return ["테스트학과"]

        def available_document_types(self):
            return [DocumentType.PDF]

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
            raise AssertionError("빈 색인에서 검색을 호출하면 안 됩니다.")

    _render_search_page(
        EmptyIndexService(),
        app_name="테스트 학사정보 검색 서비스",
    )


def _submit_search(app: AppTest, question: str) -> AppTest:
    app.text_input[0].set_value(question)
    app.selectbox[0].select("테스트학과 B")
    app.selectbox[1].select(DocumentType.PDF)
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


def test_search_result_shows_source_metadata_score_and_expandable_original() -> None:
    app = AppTest.from_function(_result_search_app).run()
    app = _submit_search(app, "장학금 선발 기준")

    assert app.exception == []
    assert any(item.value == "검색 결과" for item in app.subheader)
    assert any("장학금 선정기준" in item.value for item in app.markdown)
    assert any(metric.label == "페이지 번호" and metric.value == "7쪽" for metric in app.metric)
    assert any(
        metric.label == "Cosine 검색 점수" and metric.value == "0.877"
        for metric in app.metric
    )
    assert any(expander.label == "원문 펼쳐보기" for expander in app.expander)
    assert any(
        "장학금 선발은 등록된 성적 기준을 따릅니다." in code.value
        for code in app.code
    )
    visible_text = " ".join(
        str(element.value)
        for group in (app.markdown, app.caption, app.code)
        for element in group
    )
    assert "C:/internal/secret.pdf" not in visible_text


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
    assert any("등록된 학사 자료에서 확인할 수 없습니다" in info.value for info in app.info)
