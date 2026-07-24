"""통합 문서 검색 CLI의 인자 전달과 JSON 출력을 검증한다."""

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
        error: Exception | None = None,
    ) -> None:
        self.project_root = project_root
        self.default_corpus_path = default_corpus_path
        self.search_results = search_results or []
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

    def search(
        self,
        question: str,
        *,
        top_k: int | None,
        min_score: float | None,
        department: str | None,
        document_type: str | None,
    ) -> list[dict[str, object]]:
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
        return self.search_results


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


def test_search_forwards_filters_and_serializes_pdf_and_csv_locations(
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
