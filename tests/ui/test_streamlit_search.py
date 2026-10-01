"""외부 모델 없이 학생용 통합 Streamlit 검색 카드를 검증한다."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest


def _result_search_app():
    from types import SimpleNamespace

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

        def search_with_context(self, question, **filters):
            if (
                question == "장학금 선발 기준"
                and filters.get("top_k") == 3
                and filters.get("department") == "테스트학과B"
                and filters.get("document_type") == "장학금선정기준"
            ):
                return SimpleNamespace(
                    results=[DocumentSearchResult(
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
                        text=("장학금 선발은 등록된 성적 기준에 따릅니다. " * 30),
                        score=0.87654,
                        content_hash="a" * 64,
                        currentness_warning=OUTDATED_DOCUMENT_WARNING,
                    )],
                    structured_query=False,
                    exact_match_count=0,
                    semantic_fallback_used=False,
                )
            return SimpleNamespace(
                results=[],
                structured_query=False,
                exact_match_count=0,
                semantic_fallback_used=False,
            )

    _render_search_page(
        FakeSearchService(),
        app_name="테스트 학사정보 검색 서비스",
    )


def _mixed_source_search_app():
    from types import SimpleNamespace

    from app import _render_search_page
    from src.retrieval.document_models import DocumentSearchResult

    class MixedSearchService:
        indexed_chunk_count = 4

        def available_departments(self):
            return ["소프트웨어융합학과"]

        def available_document_types(self):
            return ["학년별교과과정", "학교기본정보"]

        def search_with_context(self, question, **filters):
            if question != "교과목과 학교 정보" or filters.get("top_k") != 3:
                return SimpleNamespace(
                    results=[],
                    structured_query=False,
                    exact_match_count=0,
                    semantic_fallback_used=False,
                )
            results = [
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
                    text=(
                        "학년: 1\n"
                        "이수구분: 전공필수\n"
                        "교과목명: 자료구조및프로그래밍\n"
                        "1학기_학수번호: \n"
                        "1학기_학점: \n"
                        "1학기_시수: \n"
                        "2학기_학수번호: 001234\n"
                        "2학기_학점: 3\n"
                        "2학기_시수: 3\n"
                        "전공필수여부: Y\n"
                        "전공선택여부: N"
                    ),
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
                DocumentSearchResult(
                    document_id="rules",
                    chunk_id="pdf-page-9",
                    file_name="학사규정.pdf",
                    file_type="pdf",
                    document_type="학사규정",
                    source_year="2026",
                    department="전체",
                    is_current=True,
                    page_number=9,
                    title="학사규정",
                    source_path="data/raw/pdfs/학사규정.pdf",
                    text="학사규정 관련 원문",
                    score=0.79,
                    content_hash="d" * 64,
                ),
                DocumentSearchResult(
                    document_id="hidden-fourth",
                    chunk_id="hidden-fourth",
                    file_name="숨김.txt",
                    file_type="txt",
                    document_type="기타",
                    source_year="2026",
                    department="전체",
                    is_current=True,
                    title="네 번째 결과는 표시되면 안 됨",
                    source_path="data/raw/text/숨김.txt",
                    text="화면에 표시되면 안 되는 원문",
                    score=0.70,
                    content_hash="e" * 64,
                ),
            ]
            return SimpleNamespace(
                results=results[: filters["top_k"]],
                structured_query=False,
                exact_match_count=0,
                semantic_fallback_used=False,
            )

    _render_search_page(
        MixedSearchService(),
        app_name="테스트 학사정보 검색 서비스",
    )


def _structured_course_search_app():
    from types import SimpleNamespace

    from app import _render_search_page
    from src.retrieval.document_models import DocumentSearchResult

    class StructuredCourseSearchService:
        indexed_chunk_count = 5

        def available_departments(self):
            return ["소프트웨어융합학과"]

        def available_document_types(self):
            return ["학년별교과과정", "프로그램내규"]

        def search_with_context(self, question, **filters):
            if (
                question
                != "소프트웨어융합학과 2학년 1학기 전공필수 과목을 알려줘"
                or filters.get("top_k") != 3
            ):
                return SimpleNamespace(
                    results=[],
                    structured_query=False,
                    exact_match_count=0,
                    semantic_fallback_used=False,
                )
            names = (
                "자료구조및프로그래밍",
                "알고리즘",
                "운영체제",
                "데이터베이스",
            )
            results = [
                DocumentSearchResult(
                    document_id="curriculum-2026",
                    chunk_id=f"csv-row-{row_number}",
                    file_name="소프트웨어융합학과_학년별교과과정_2026.csv",
                    file_type="csv",
                    document_type="학년별교과과정",
                    source_year="2026",
                    department="소프트웨어융합학과",
                    is_current=True,
                    row_number=row_number,
                    title="교과과정",
                    source_path="data/raw/tables/교과과정.csv",
                    text=(
                        "학년: 2\n"
                        "이수구분: 전공필수\n"
                        f"교과목명: {name}\n"
                        f"1학기_학수번호: 7048{row_number}\n"
                        "1학기_학점: 3\n"
                        "1학기_시수: 3\n"
                        "2학기_학수번호: \n"
                        "2학기_학점: \n"
                        "2학기_시수: \n"
                        "전공필수여부: Y\n"
                        "전공선택여부: N"
                    ),
                    score=0.91,
                    content_hash=(str(row_number) * 64)[:64],
                )
                for row_number, name in enumerate(names, start=21)
            ]
            return SimpleNamespace(
                results=results,
                structured_query=True,
                exact_match_count=len(results),
                semantic_fallback_used=False,
            )

    _render_search_page(
        StructuredCourseSearchService(),
        app_name="테스트 학사정보 검색 서비스",
    )


def _structured_course_fallback_app():
    from types import SimpleNamespace

    from app import _render_search_page
    from src.retrieval.document_models import DocumentSearchResult

    class StructuredCourseFallbackService:
        indexed_chunk_count = 1

        def available_departments(self):
            return ["소프트웨어융합학과"]

        def available_document_types(self):
            return ["학년별교과과정", "프로그램내규"]

        def search_with_context(self, question, **filters):
            return SimpleNamespace(
                results=[
                    DocumentSearchResult(
                        document_id="program-rules",
                        chunk_id="program-rules-page-4",
                        file_name="소프트웨어융합학과_프로그램내규.pdf",
                        file_type="pdf",
                        document_type="프로그램내규",
                        source_year="2026",
                        department="소프트웨어융합학과",
                        is_current=True,
                        page_number=4,
                        title="프로그램내규",
                        source_path="data/raw/pdfs/프로그램내규.pdf",
                        text="소프트웨어융합학과 전공필수 관련 자료",
                        score=0.82,
                        content_hash="f" * 64,
                    )
                ],
                structured_query=True,
                exact_match_count=0,
                semantic_fallback_used=True,
            )

    _render_search_page(
        StructuredCourseFallbackService(),
        app_name="테스트 학사정보 검색 서비스",
    )


def _empty_result_app():
    from types import SimpleNamespace

    from app import _render_search_page

    class EmptySearchService:
        indexed_chunk_count = 1

        def available_departments(self):
            return ["테스트학과"]

        def available_document_types(self):
            return ["장학금선정기준"]

        def search_with_context(self, question, **filters):
            return SimpleNamespace(
                results=[],
                structured_query=False,
                exact_match_count=0,
                semantic_fallback_used=False,
            )

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

        def search_with_context(self, question, **filters):
            # 실제 서비스처럼 검토 규정만 확인하고, 색인이 비면 빈 결과를 돌려준다.
            from pathlib import Path
            from src.retrieval.document_models import DocumentSearchResponse
            from src.retrieval.reviewed_rules import reviewed_rule_search
            import src
            root = Path(src.__file__).resolve().parents[1]
            return (reviewed_rule_search(question, "소프트웨어융합학과", root)
                    or DocumentSearchResponse())

    _render_search_page(
        EmptyIndexService(),
        app_name="테스트 학사정보 검색 서비스",
    )


def _submit_filtered_search(app: AppTest, question: str) -> AppTest:
    app.text_input[0].set_value(question)
    app.selectbox[0].select("테스트학과B")
    app.selectbox[1].select("장학금선정기준")
    return app.button[0].click().run()


def _visible_text(app: AppTest) -> str:
    return " ".join(
        str(element.value)
        for group in (app.markdown, app.caption, app.info, app.code)
        for element in group
    )


def test_search_screen_contains_requested_controls_and_disclaimer() -> None:
    app = AppTest.from_function(_result_search_app).run()

    assert app.exception == []
    assert app.title[0].value == "테스트 학사정보 검색 서비스"
    assert app.text_input[0].label == "질문"
    assert [selectbox.label for selectbox in app.selectbox] == [
        "학과 선택",
        "문서 유형 선택",
        "입학연도 (선택)",
        "졸업 과정 (선택)",
    ]
    assert app.button[0].label == "검색"
    assert any(
        warning.value
        == "본 서비스의 답변은 참고용이며, 공식 학사 행정 답변을 대신하지 않습니다."
        for warning in app.warning
    )


def test_pdf_card_shows_source_preview_and_outdated_warning() -> None:
    app = AppTest.from_function(_result_search_app).run()
    app = _submit_filtered_search(app, "장학금 선발 기준")

    assert app.exception == []
    visible_text = _visible_text(app)
    for expected in (
        "장학금선정기준",
        "테스트학과B",
        "2024",
        "7쪽",
        "2024_장학금선정기준.pdf",
        "0.877",
        "미리보기",
    ):
        assert expected in visible_text
    assert any(
        warning.value == "최신 자료가 아닐 수 있습니다"
        for warning in app.warning
    )
    assert any(expander.label == "검색 근거 보기" for expander in app.expander)
    preview = next(
        markdown.value
        for markdown in app.markdown
        if markdown.value.startswith("장학금 선발은")
    )
    assert len(preview) <= 300
    assert preview.endswith("…")
    assert any(len(code.value) > 300 for code in app.code)
    assert "C:/internal/secret.pdf" not in visible_text


def test_general_search_renders_only_the_top_three_results() -> None:
    app = AppTest.from_function(_mixed_source_search_app).run()
    app.text_input[0].set_value("교과목과 학교 정보")
    app = app.button[0].click().run()

    assert app.exception == []
    visible_text = _visible_text(app)
    for expected in (
        "자료구조및프로그래밍",
        "학년별교과과정",
        "소프트웨어융합학과",
        "1학년 · 2학기",
        "전공필수",
        "001234",
        "3/3",
        "12행",
        "교과과정.csv",
        "학교정보.txt",
        "9쪽",
    ):
        assert expected in visible_text
    assert "네 번째 결과는 표시되면 안 됨" not in visible_text
    assert "화면에 표시되면 안 되는 원문" not in visible_text


def test_streamlit_structured_search_shows_count_and_every_exact_course() -> None:
    app = AppTest.from_function(_structured_course_search_app).run()
    app.text_input[0].set_value(
        "소프트웨어융합학과 2학년 1학기 전공필수 과목을 알려줘"
    )
    app = app.button[0].click().run()

    assert app.exception == []
    visible_text = _visible_text(app)
    assert "조건에 맞는 과목 4개를 찾았습니다" in visible_text
    for course_name in (
        "자료구조및프로그래밍",
        "알고리즘",
        "운영체제",
        "데이터베이스",
    ):
        assert course_name in visible_text
    assert "구조화 조건 정확 일치" in visible_text
    assert "유사도 점수" not in visible_text
    assert "프로그램내규.pdf" not in visible_text


def test_streamlit_structured_search_shows_semantic_fallback_notice() -> None:
    app = AppTest.from_function(_structured_course_fallback_app).run()
    app.text_input[0].set_value(
        "소프트웨어융합학과 2학년 1학기 전공필수 과목을 알려줘"
    )
    app = app.button[0].click().run()

    assert app.exception == []
    visible_text = _visible_text(app)
    assert (
        "정확한 교과과정 항목을 찾지 못해 관련 자료를 표시합니다"
        in visible_text
    )
    assert "소프트웨어융합학과_프로그램내규.pdf" in visible_text
    assert "조건에 맞는 과목" not in visible_text


def test_no_related_document_shows_standard_message() -> None:
    app = AppTest.from_function(_empty_result_app).run()
    app.text_input[0].set_value("관련 없는 질문")
    app = app.button[0].click().run()

    assert app.exception == []
    assert app.subheader[0].value == "답변"
    assert (
        "현재 등록된 자료에서는 질문에 대한 정확한 근거를 찾지 못했습니다."
        in _visible_text(app)
    )
    assert app.expander == []


def test_empty_index_explains_setup_and_returns_no_evidence() -> None:
    app = AppTest.from_function(_empty_index_app).run()
    assert any("setup.cmd" in info.value for info in app.info)
    app.text_input[0].set_value("장학금 기준")
    app = app.button[0].click().run()

    assert app.exception == []
    assert not app.error
    assert app.subheader[0].value == "답변"
    assert (
        "현재 등록된 자료에서 정확한 규정을 찾지 못했습니다."
        in _visible_text(app)
    )
    assert app.expander == []


def test_empty_index_still_answers_reviewed_graduation_rules() -> None:
    # 새로 받은 저장소에서 색인을 만들기 전에도 검토된 졸업요건은 답한다.
    app = AppTest.from_function(_empty_index_app).run()
    app.text_input[0].set_value("소프트웨어융합학과 졸업요건이 뭐야?")
    app = app.button[0].click().run()

    assert app.exception == []
    assert "54학점 이상" in _visible_text(app)
