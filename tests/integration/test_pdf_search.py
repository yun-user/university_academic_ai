"""실제 ChromaDB와 fake 한국어 임베딩을 연결한 검색 통합 테스트."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from pathlib import Path

import pytest

from src.ingestion.pdf_models import (
    PdfDocumentExtraction,
    PdfDocumentStatus,
    PdfPageExtraction,
    PdfPageStatus,
)
from src.models import DocumentType
from src.retrieval.search_service import PdfSearchService
from src.retrieval.vector_store import ChromaVectorStore


_OPEN_SERVICES: list[PdfSearchService] = []


@pytest.fixture(autouse=True)
def _close_test_services():
    yield
    for service in reversed(_OPEN_SERVICES):
        service.close()
    _OPEN_SERVICES.clear()


class KoreanKeywordEmbeddingProvider:
    fingerprint = hashlib.sha256(b"fake-korean-embedding-v1").hexdigest()
    _groups = (
        ("장학금", "장학"),
        ("졸업", "전공학점"),
        ("휴학",),
        ("수강", "교과목"),
    )

    @classmethod
    def _vector(cls, text: str) -> list[float]:
        values = [float(any(token in text for token in group)) for group in cls._groups]
        values.append(0.0)
        if not any(values):
            values[-1] = 1.0
        norm = math.sqrt(sum(value * value for value in values))
        return [value / norm for value in values]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


def _extraction(
    title: str,
    source_path: str,
    page_texts: list[str],
    source_file_hash: str | None = None,
) -> PdfDocumentExtraction:
    pages = [
        PdfPageExtraction(
            page_index=index,
            page_number=index + 1,
            text=text,
            status=PdfPageStatus.TEXT if text else PdfPageStatus.EMPTY,
        )
        for index, text in enumerate(page_texts)
    ]
    text_count = sum(page.status is PdfPageStatus.TEXT for page in pages)
    empty_count = len(pages) - text_count
    return PdfDocumentExtraction(
        document_title=title,
        file_name=Path(source_path).name,
        source_path=source_path,
        content_hash=(
            source_file_hash
            or hashlib.sha256(source_path.encode("utf-8")).hexdigest()
        ),
        file_size_bytes=200,
        page_count=len(pages),
        text_page_count=text_count,
        empty_page_count=empty_count,
        failed_page_count=0,
        pages=pages,
        status=(
            PdfDocumentStatus.SUCCESS_WITH_WARNINGS
            if empty_count
            else PdfDocumentStatus.SUCCESS
        ),
    )


def _service(
    tmp_path: Path,
    *,
    top_k: int = 5,
    min_score: float = 0.1,
    dedup_threshold: float = 1.0,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> PdfSearchService:
    provider = KoreanKeywordEmbeddingProvider()
    store = ChromaVectorStore(
        persist_directory=tmp_path / "chroma",
        collection_name="pdf_search_test",
        embedding_fingerprint=provider.fingerprint,
    )
    service = PdfSearchService(
        embedding_provider=provider,
        vector_store=store,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        top_k=top_k,
        min_retrieval_score=min_score,
        dedup_similarity_threshold=dedup_threshold,
        project_root=tmp_path,
    )
    _OPEN_SERVICES.append(service)
    return service


def test_chromadb_stores_and_searches_pdf_chunks_with_source_metadata(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    report = service.index_pdf_extraction(
        _extraction(
            "학사 안내",
            "data/raw/pdfs/academic.pdf",
            ["졸업 전공학점 안내", "장학금 선발 기준과 제출 서류 안내"],
        )
    )

    results = service.search("장학금 선발 기준")

    assert report.chunk_count == 2
    assert service.indexed_chunk_count == 2
    assert results[0].document_title == "학사 안내"
    assert results[0].page_number == 2
    assert results[0].content == "장학금 선발 기준과 제출 서류 안내"
    assert results[0].score == 1.0


def test_same_document_registration_is_idempotent(tmp_path: Path) -> None:
    service = _service(tmp_path)
    extraction = _extraction(
        "장학 문서", "data/raw/pdfs/scholarship.pdf", ["장학금 선발 기준"]
    )
    first = service.index_pdf_extraction(extraction)
    count_after_first = service.indexed_chunk_count
    second = service.index_pdf_extraction(extraction)

    assert first.inserted_count == 1
    assert second.inserted_count == 0
    assert second.updated_count == 0
    assert second.duplicate_registration_prevented is True
    assert service.indexed_chunk_count == count_after_first


def test_document_delete_removes_its_search_results(tmp_path: Path) -> None:
    service = _service(tmp_path)
    deleted_target = service.index_pdf_extraction(
        _extraction("휴학 안내", "data/raw/pdfs/leave.pdf", ["휴학 신청 기준"])
    )
    preserved = service.index_pdf_extraction(
        _extraction(
            "장학 안내",
            "data/raw/pdfs/scholarship.pdf",
            ["장학금 신청 기준"],
        )
    )
    deleted = service.delete_document_index(deleted_target.document_id)

    assert deleted.deleted_chunk_count == 1
    assert service.indexed_chunk_count == 1
    assert service.search("휴학 신청") == []
    assert service.search("장학금 신청", top_k=1)[0].document_id == preserved.document_id


def test_top_k_limits_result_count(tmp_path: Path) -> None:
    service = _service(tmp_path, top_k=3)
    contents = [
        "장학금 성적 기준 안내",
        "장학금 제출 서류 설명",
        "장학금 봉사 시간 조건",
        "장학금 동점자 우선순위",
        "장학금 신청 자격 항목",
    ]
    for index, content in enumerate(contents):
        service.index_pdf_extraction(
            _extraction(
                f"장학 문서 {index}",
                f"data/raw/pdfs/scholarship-{index}.pdf",
                [content],
            )
        )

    assert len(service.search("장학금", top_k=3)) == 3


def test_minimum_score_excludes_below_threshold_results(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.index_pdf_extraction(
        _extraction("장학", "data/raw/pdfs/a.pdf", ["장학금 선발 기준"])
    )
    service.index_pdf_extraction(
        _extraction("졸업", "data/raw/pdfs/b.pdf", ["졸업 전공학점 기준"])
    )

    assert service.search("장학금과 졸업", min_score=0.8) == []
    assert len(service.search("장학금과 졸업", min_score=0.7)) == 2


def test_unrelated_question_returns_no_results(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.index_pdf_extraction(
        _extraction("장학", "data/raw/pdfs/a.pdf", ["장학금 선발 기준"])
    )

    assert service.search("오늘 날씨와 축구 경기", min_score=0.1) == []


def test_korean_question_finds_relevant_document(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.index_pdf_extraction(
        _extraction("휴학", "data/raw/pdfs/leave.pdf", ["휴학 신청 절차"])
    )
    service.index_pdf_extraction(
        _extraction("장학", "data/raw/pdfs/award.pdf", ["장학금 성적 기준"])
    )

    result = service.search("한국어로 장학금 선발 기준을 알려줘", top_k=1)

    assert len(result) == 1
    assert result[0].document_title == "장학"


def test_persistent_store_can_be_reopened_and_searched(tmp_path: Path) -> None:
    first_service = _service(tmp_path)
    first_service.index_pdf_extraction(
        _extraction("졸업", "data/raw/pdfs/grad.pdf", ["졸업 전공학점 기준"])
    )
    first_service.close()

    reopened_service = _service(tmp_path)
    result = reopened_service.search("졸업 전공학점", top_k=1)

    assert reopened_service.indexed_chunk_count == 1
    assert result[0].document_title == "졸업"
    assert result[0].page_number == 1


def test_similar_chunks_are_collapsed(tmp_path: Path) -> None:
    service = _service(tmp_path, dedup_threshold=0.9)
    service.index_pdf_extraction(
        _extraction("장학 A", "data/raw/pdfs/a.pdf", ["장학금 선발 성적 기준 안내입니다."])
    )
    service.index_pdf_extraction(
        _extraction("장학 B", "data/raw/pdfs/b.pdf", ["장학금 선발 성적 기준 안내입니다."])
    )

    assert len(service.search("장학금 선발", top_k=5)) == 1


def test_duplicate_file_hash_does_not_overwrite_original_metadata(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    shared_hash = hashlib.sha256(b"same-pdf-bytes").hexdigest()
    original = service.index_pdf_extraction(
        _extraction(
            "원본 장학 문서",
            "data/raw/pdfs/original.pdf",
            ["장학금 선발 기준"],
            source_file_hash=shared_hash,
        )
    )
    duplicate = service.index_pdf_extraction(
        _extraction(
            "복사본 장학 문서",
            "data/raw/pdfs/copy.pdf",
            ["장학금 선발 기준"],
            source_file_hash=shared_hash,
        )
    )

    result = service.search("장학금 선발", top_k=1)[0]
    assert duplicate.document_id == original.document_id
    assert duplicate.duplicate_registration_prevented is True
    assert result.document_title == "원본 장학 문서"
    assert result.source_path == "data/raw/pdfs/original.pdf"


def test_reindex_removes_stale_chunks_and_keeps_document_id(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = service.index_pdf_extraction(
        _extraction(
            "학사 문서",
            "data/raw/pdfs/academic.pdf",
            ["휴학 신청 기준", "휴학 제출 서류"],
        )
    )
    changed = _extraction(
        "학사 문서",
        "data/raw/pdfs/academic.pdf",
        ["장학금 선발 기준"],
        source_file_hash=hashlib.sha256(b"changed-pdf").hexdigest(),
    )

    report = service.reindex_pdf_extraction(changed, document_id=first.document_id)

    assert report.document_id == first.document_id
    assert report.removed_stale_count == 2
    assert service.indexed_chunk_count == 1
    assert service.search("휴학 신청") == []
    assert service.search("장학금 선발", top_k=1)[0].page_number == 1


def test_similar_rules_from_different_sources_are_preserved(tmp_path: Path) -> None:
    service = _service(tmp_path, dedup_threshold=0.9)
    service.index_pdf_extraction(
        _extraction(
            "2025 졸업 규정",
            "data/raw/pdfs/grad-2025.pdf",
            ["소프트웨어 전공 졸업에는 전공 60학점 이상 이수가 필요합니다."],
        )
    )
    service.index_pdf_extraction(
        _extraction(
            "2026 졸업 규정",
            "data/raw/pdfs/grad-2026.pdf",
            ["소프트웨어 전공 졸업에는 전공 66학점 이상 이수가 필요합니다."],
        )
    )

    results = service.search("졸업 전공학점", top_k=5)
    assert {result.document_title for result in results} == {
        "2025 졸업 규정",
        "2026 졸업 규정",
    }


def test_similar_overlap_chunks_in_same_page_are_collapsed(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        dedup_threshold=0.9,
        chunk_size=22,
        chunk_overlap=0,
    )
    service.index_pdf_extraction(
        _extraction(
            "장학 문서",
            "data/raw/pdfs/overlap.pdf",
            ["장학금 선발 성적 기준 안내입니다. 장학금 선발 성적 기준 안내입니다!"],
        )
    )

    assert service.indexed_chunk_count == 2
    assert len(service.search("장학금 선발", top_k=5)) == 1


def test_top_k_is_filled_after_duplicate_collapse(tmp_path: Path) -> None:
    service = _service(tmp_path, top_k=2)
    for index in range(11):
        service.index_pdf_extraction(
            _extraction(
                f"{index:02d} 중복 문서",
                f"data/raw/pdfs/duplicate-{index}.pdf",
                ["장학금 공통 안내"],
            )
        )
    service.index_pdf_extraction(
        _extraction("고유 문서", "data/raw/pdfs/unique.pdf", ["장학금 성적 기준"])
    )

    assert len(service.search("장학금", top_k=2)) == 2


def test_department_filter_is_applied_before_top_k_and_metadata_is_returned(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path, top_k=1)
    service.index_pdf_extraction(
        _extraction(
            "A학과 장학 문서",
            "data/raw/pdfs/department-a.pdf",
            ["장학금 공통 선발 기준"],
        ),
        department="테스트학과 A",
    )
    service.index_pdf_extraction(
        _extraction(
            "B학과 장학 문서",
            "data/raw/pdfs/department-b.pdf",
            ["장학금 공통 선발 기준과 제출 서류"],
        ),
        department="테스트학과 B",
    )

    results = service.search(
        "장학금 선발 기준",
        top_k=1,
        department="테스트학과 B",
    )

    assert len(results) == 1
    assert results[0].document_title == "B학과 장학 문서"
    assert results[0].department == "테스트학과 B"
    assert results[0].document_type is DocumentType.PDF


def test_department_and_document_type_filters_work_together(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.index_pdf_extraction(
        _extraction(
            "학사 문서",
            "data/raw/pdfs/combined-filter.pdf",
            ["졸업 전공학점 기준"],
        ),
        department="테스트학과",
    )

    results = service.search(
        "졸업 전공학점",
        department="테스트학과",
        document_type=DocumentType.PDF,
    )

    assert len(results) == 1
    assert results[0].department == "테스트학과"
    assert results[0].document_type is DocumentType.PDF
    assert PdfSearchService._build_search_filter(
        department="테스트학과",
        document_type=DocumentType.PDF,
    ) == {
        "$and": [
            {"department": {"$eq": "테스트학과"}},
            {"document_type": {"$eq": "pdf"}},
        ]
    }


def test_filter_options_are_distinct_and_sorted_from_index_metadata(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    for index, department in enumerate(
        ["테스트학과 B", "테스트학과 A", "테스트학과 B"]
    ):
        service.index_pdf_extraction(
            _extraction(
                f"필터 문서 {index}",
                f"data/raw/pdfs/filter-{index}.pdf",
                [f"장학금 안내 {index}"],
            ),
            department=department,
        )

    assert service.available_departments() == ["테스트학과 A", "테스트학과 B"]
    assert service.available_document_types() == [DocumentType.PDF]


def test_empty_index_returns_without_loading_query_embedding(tmp_path: Path) -> None:
    class FailOnQueryEmbedding(KoreanKeywordEmbeddingProvider):
        fingerprint = hashlib.sha256(b"fail-on-query-embedding").hexdigest()

        def embed_query(self, text: str) -> list[float]:
            raise AssertionError("빈 색인에서는 임베딩을 호출하면 안 됩니다.")

    provider = FailOnQueryEmbedding()
    store = ChromaVectorStore(
        persist_directory=tmp_path / "empty-chroma",
        collection_name="empty_search_test",
        embedding_fingerprint=provider.fingerprint,
    )
    service = PdfSearchService(
        embedding_provider=provider,
        vector_store=store,
        chunk_size=500,
        chunk_overlap=50,
        top_k=5,
        min_retrieval_score=0.1,
        dedup_similarity_threshold=1.0,
        project_root=tmp_path,
    )
    _OPEN_SERVICES.append(service)

    assert service.search("장학금", department="테스트학과") == []
