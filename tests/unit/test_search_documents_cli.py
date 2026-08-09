"""통합 문서 검색 CLI의 간결 출력, 개수 제한과 JSON 출력을 검증한다."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts import search_documents


class FakeDocumentSearchService:
    """모델·ChromaDB 없이 CLI 경계만 검증하는 가짜 서비스."""

    def __init__(
        self,
        *,
        project_root: Path,
        default_corpus_path: Path,
        search_results: list[dict[str, object]] | None = None,
        structured_query: bool = False,
        exact_match_count: int = 0,
        semantic_fallback_used: bool = False,
        error: Exception | None = None,
    ) -> None:
        self.project_root = project_root
        self.default_corpus_path = default_corpus_path
        self.search_results = search_results or []
        self.structured_query = structured_query
        self.exact_match_count = exact_match_count
        self.semantic_fallback_used = semantic_fallback_used
        self.error = error
        self.rebuild_calls: list[Path | None] = []
        self.search_calls: list[dict[str, object]] = []
        self.closed = False

    def __enter__(self) -> "FakeDocumentSearchService":
        return self

    def __exit__(self, *_args: object) -> None:
        self.closed = True

    def rebuild_corpus(self, corpus_path: Path | None) -> dict[str, object]:
        self.rebuild_calls.append(corpus_path)
        if self.error is not None:
            raise self.error

        effective_path = corpus_path or self.default_corpus_path
        return {
            "corpus_path": effective_path.relative_to(self.project_root).as_posix(),
            "total_record_count": 2,
            "indexed_document_count": 1,
            "indexed_record_count": 2,
            "indexed_chunk_count": 3,
        }

    def search_with_context(
        self,
        question: str,
        *,
        top_k: int | None,
        min_score: float | None,
        department: str | None,
        document_type: str | None,
    ) -> SimpleNamespace:
        self.search_calls.append(
            {
                "question": question,
                "top_k": top_k,
                "min_score": min_score,
                "department": department,
                "document_type": document_type,
            }
        )
        if self.error is not None:
            raise self.error
        results = self.search_results
        if self.exact_match_count == 0 and top_k is not None:
            results = results[:top_k]
        return SimpleNamespace(
            results=results,
            structured_query=self.structured_query,
            exact_match_count=self.exact_match_count,
            semantic_fallback_used=self.semantic_fallback_used,
        )


def _patch_service_factory(
    monkeypatch,
    *,
    service: FakeDocumentSearchService,
    settings: object,
) -> list[object]:
    factory_calls: list[object] = []

    class FakeFactory:
        @classmethod
        def from_settings(cls, received_settings: object) -> FakeDocumentSearchService:
            factory_calls.append(received_settings)
            return service

    monkeypatch.setattr(search_documents, "DocumentSearchService", FakeFactory)
    monkeypatch.setattr(search_documents, "get_settings", lambda: settings)
    return factory_calls


def _course_result(name: str, *, row_number: int) -> dict[str, object]:
    return {
        "document_id": "COURSE-TABLE-2026",
        "chunk_id": f"COURSE-TABLE-2026:row:{row_number}:0",
        "file_name": "소프트웨어융합학과_학년별교과과정_2026.csv",
        "file_type": "csv",
        "document_type": "학년별교과과정",
        "source_year": "2026",
        "department": "소프트웨어융합학과",
        "page_number": None,
        "row_number": row_number,
        "title": "교과과정",
        "text": (
            "학년: 2\n이수구분: 전공필수\n"
            f"교과목명: {name}\n"
            f"1학기_학수번호: 7048{row_number}\n"
            "1학기_학점: 3\n1학기_시수: 3\n"
            "2학기_학수번호: \n2학기_학점: \n2학기_시수: \n"
            "전공필수여부: Y\n전공선택여부: N"
        ),
        "score": 0.91,
    }


def test_rebuild_uses_default_corpus_and_prints_json(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    default_corpus_path = tmp_path / "data" / "processed" / "documents.jsonl"
    settings = SimpleNamespace(processed_data_dir=default_corpus_path.parent)
    service = FakeDocumentSearchService(
        project_root=tmp_path,
        default_corpus_path=default_corpus_path,
    )
    factory_calls = _patch_service_factory(
        monkeypatch,
        service=service,
        settings=settings,
    )

    exit_code = search_documents.main(["rebuild"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert captured.err == ""
    assert service.rebuild_calls == [None]
    assert payload["corpus_path"] == "data/processed/documents.jsonl"
    assert payload["indexed_chunk_count"] == 3
    assert factory_calls == [settings]
    assert service.closed is True


def test_json_option_forwards_filters_and_serializes_full_results(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    results = [
        {
            "document_id": "GRAD-REQ-2026",
            "chunk_id": "GRAD-REQ-2026:page:7:0",
            "file_name": "졸업요건.pdf",
            "file_type": "pdf",
            "document_type": "졸업요건",
            "department": "소프트웨어융합학과",
            "page_number": 7,
            "row_number": None,
            "title": "졸업요건",
            "text": "졸업에 필요한 전공학점 안내",
            "score": 0.91,
            "currentness_warning": None,
        },
        {
            "document_id": "COURSE-TABLE-2026",
            "chunk_id": "COURSE-TABLE-2026:row:3:0",
            "file_name": "교과과정.csv",
            "file_type": "csv",
            "document_type": "교과과정",
            "department": "소프트웨어융합학과",
            "page_number": None,
            "row_number": 3,
            "title": "전공 교과목",
            "text": "전공필수 교과목 목록",
            "score": 0.78,
            "currentness_warning": None,
        },
    ]
    settings = SimpleNamespace(processed_data_dir=tmp_path / "data" / "processed")
    service = FakeDocumentSearchService(
        project_root=tmp_path,
        default_corpus_path=settings.processed_data_dir / "documents.jsonl",
        search_results=results,
    )
    _patch_service_factory(monkeypatch, service=service, settings=settings)

    exit_code = search_documents.main(
        [
            "search",
            "졸업 전공학점",
            "--top-k",
            "4",
            "--min-score",
            "0.42",
            "--department",
            "소프트웨어융합학과",
            "--document-type",
            "졸업요건",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert captured.err == ""
    assert service.search_calls == [
        {
            "question": "졸업 전공학점",
            "top_k": 4,
            "min_score": 0.42,
            "department": "소프트웨어융합학과",
            "document_type": "졸업요건",
        }
    ]
    assert payload[0]["file_type"] == "pdf"
    assert payload[0]["page_number"] == 7
    assert payload[0]["row_number"] is None
    assert payload[1]["file_type"] == "csv"
    assert payload[1]["page_number"] is None
    assert payload[1]["row_number"] == 3
    assert service.closed is True


def test_structured_course_search_prints_exact_match_count_and_single_csv_result(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    settings = SimpleNamespace(processed_data_dir=tmp_path / "data/processed")
    service = FakeDocumentSearchService(
        project_root=tmp_path,
        default_corpus_path=settings.processed_data_dir / "documents.jsonl",
        search_results=[_course_result("자료구조및프로그래밍", row_number=21)],
        structured_query=True,
        exact_match_count=1,
    )
    _patch_service_factory(monkeypatch, service=service, settings=settings)

    exit_code = search_documents.main(
        [
            "search",
            "소프트웨어융합학과 2학년 1학기 전공필수 과목을 알려줘",
            "--top-k",
            "5",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.splitlines()[0] == "조건에 맞는 과목 1개를 찾았습니다"
    assert "[1] 자료구조및프로그래밍" in captured.out
    assert "[2]" not in captured.out
    assert ".pdf" not in captured.out
    assert "- 일치 방식: 구조화 조건 정확 일치" in captured.out
    assert "- 유사도:" not in captured.out


def test_structured_course_search_prints_all_exact_results_even_when_top_k_is_one(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    settings = SimpleNamespace(processed_data_dir=tmp_path / "data/processed")
    service = FakeDocumentSearchService(
        project_root=tmp_path,
        default_corpus_path=settings.processed_data_dir / "documents.jsonl",
        search_results=[
            _course_result("자료구조및프로그래밍", row_number=21),
            _course_result("알고리즘", row_number=22),
        ],
        structured_query=True,
        exact_match_count=2,
    )
    _patch_service_factory(monkeypatch, service=service, settings=settings)

    exit_code = search_documents.main(
        [
            "search",
            "소프트웨어융합학과 2학년 1학기 전공필수 과목을 알려줘",
            "--top-k",
            "1",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert service.search_calls[0]["top_k"] == 1
    assert captured.out.splitlines()[0] == "조건에 맞는 과목 2개를 찾았습니다"
    assert "[1] 자료구조및프로그래밍" in captured.out
    assert "[2] 알고리즘" in captured.out


def test_structured_course_search_prints_semantic_fallback_notice(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    fallback_result = {
        "document_id": "PROGRAM-RULES",
        "chunk_id": "PROGRAM-RULES:page:4:0",
        "file_name": "소프트웨어융합학과_프로그램내규.pdf",
        "file_type": "pdf",
        "document_type": "프로그램내규",
        "source_year": "2026",
        "department": "소프트웨어융합학과",
        "page_number": 4,
        "row_number": None,
        "title": "프로그램내규",
        "text": "소프트웨어융합학과 전공필수 관련 자료",
        "score": 0.82,
    }
    settings = SimpleNamespace(processed_data_dir=tmp_path / "data/processed")
    service = FakeDocumentSearchService(
        project_root=tmp_path,
        default_corpus_path=settings.processed_data_dir / "documents.jsonl",
        search_results=[fallback_result],
        structured_query=True,
        exact_match_count=0,
        semantic_fallback_used=True,
    )
    _patch_service_factory(monkeypatch, service=service, settings=settings)

    exit_code = search_documents.main(
        [
            "search",
            "소프트웨어융합학과 2학년 1학기 전공필수 과목을 알려줘",
            "--top-k",
            "1",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert service.search_calls[0]["top_k"] == 1
    assert captured.out.splitlines()[0] == (
        "정확한 교과과정 항목을 찾지 못해 관련 자료를 표시합니다"
    )
    assert "[1] 프로그램내규" in captured.out
    assert "조건에 맞는 과목" not in captured.out


def test_search_defaults_to_three_compact_text_results(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    results = [
        {
            "document_id": f"DOC-{index}",
            "chunk_id": f"chunk-{index}",
            "file_name": f"자료-{index}.pdf",
            "file_type": "pdf",
            "document_type": "학사자료",
            "source_year": "2026",
            "department": "소프트웨어융합학과",
            "page_number": index,
            "row_number": None,
            "title": f"자료 {index}",
            "text": f"학생이 읽을 수 있는 내용 {index}",
            "score": 0.9 - index / 100,
        }
        for index in range(1, 5)
    ]
    settings = SimpleNamespace(processed_data_dir=tmp_path / "data/processed")
    service = FakeDocumentSearchService(
        project_root=tmp_path,
        default_corpus_path=settings.processed_data_dir / "documents.jsonl",
        search_results=results,
    )
    _patch_service_factory(monkeypatch, service=service, settings=settings)

    exit_code = search_documents.main(["search", "학사자료 질문"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert service.search_calls[0]["top_k"] == 3
    assert "[1] 자료 1" in captured.out
    assert "[3] 자료 3" in captured.out
    assert "[4] 자료 4" not in captured.out
    assert "- 페이지 또는 CSV 행: 1쪽" in captured.out
    assert "- 내용 요약:" in captured.out
    assert captured.out.splitlines()[0] == "[1] 자료 1"
    assert '"document_id"' not in captured.out


def test_top_k_option_changes_compact_result_count(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    results = [
        {
            "file_name": f"과목-{index}.csv",
            "file_type": "csv",
            "document_type": "학년별교과과정",
            "source_year": "2026",
            "department": "소프트웨어융합학과",
            "page_number": None,
            "row_number": index,
            "title": "교과과정",
            "text": (
                f"학년: 1\n이수구분: 전공선택\n교과목명: 과목{index}\n"
                f"1학기_학수번호: 0010{index}\n1학기_학점: 3\n"
                "1학기_시수: 3\n전공선택여부: Y"
            ),
            "score": 0.8,
        }
        for index in range(1, 7)
    ]
    settings = SimpleNamespace(processed_data_dir=tmp_path / "data/processed")
    service = FakeDocumentSearchService(
        project_root=tmp_path,
        default_corpus_path=settings.processed_data_dir / "documents.jsonl",
        search_results=results,
    )
    _patch_service_factory(monkeypatch, service=service, settings=settings)

    exit_code = search_documents.main(
        ["search", "1학년 전공과목", "--top-k", "5"]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert service.search_calls[0]["top_k"] == 5
    assert "[5] 과목5" in captured.out
    assert "[6] 과목6" not in captured.out
    assert "- 페이지 또는 CSV 행: CSV 5행" in captured.out


def test_cli_returns_nonzero_and_reports_service_error(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    settings = SimpleNamespace(processed_data_dir=tmp_path / "data" / "processed")
    service = FakeDocumentSearchService(
        project_root=tmp_path,
        default_corpus_path=settings.processed_data_dir / "documents.jsonl",
        error=ValueError("forced failure"),
    )
    _patch_service_factory(monkeypatch, service=service, settings=settings)

    exit_code = search_documents.main(["rebuild"])

    captured = capsys.readouterr()
    assert exit_code != 0
    assert captured.out == ""
    assert "forced failure" in captured.err
    assert service.closed is True
