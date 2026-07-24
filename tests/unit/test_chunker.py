"""PDF 페이지 보존 청커 단위 테스트."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from src.ingestion.chunker import chunk_pdf_document
from src.ingestion.pdf_models import (
    PdfDocumentExtraction,
    PdfDocumentStatus,
    PdfPageExtraction,
    PdfPageStatus,
)


def _extraction(page_texts: list[str]) -> PdfDocumentExtraction:
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
        document_title="테스트 학사 문서",
        file_name="academic.pdf",
        source_path="data/raw/pdfs/academic.pdf",
        content_hash=hashlib.sha256(b"source-pdf").hexdigest(),
        file_size_bytes=100,
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


def test_chunks_keep_document_title_source_and_page_number() -> None:
    extraction = _extraction(
        [
            "졸업을 위해 전공학점을 이수해야 합니다. 세부 기준을 확인합니다.",
            "장학금 선발 기준과 제출 서류를 안내합니다.",
        ]
    )
    chunks = chunk_pdf_document(
        extraction,
        chunk_size=24,
        chunk_overlap=5,
        department="미지정",
        category="학사",
        collected_at=datetime(2026, 7, 23, tzinfo=timezone.utc),
    )

    assert len(chunks) >= 3
    assert {item.chunk.page_number for item in chunks} == {1, 2}
    assert all(item.chunk.document_title == "테스트 학사 문서" for item in chunks)
    assert all(
        item.chunk.source_path == "data/raw/pdfs/academic.pdf" for item in chunks
    )
    assert all(item.chunk.content for item in chunks)
    assert all(len(item.chunk.content_hash) == 64 for item in chunks)


def test_empty_page_creates_no_chunk_and_later_page_number_is_not_shifted() -> None:
    extraction = _extraction(["첫 페이지 본문", "", "세 번째 페이지 본문"])
    chunks = chunk_pdf_document(
        extraction,
        chunk_size=100,
        chunk_overlap=10,
    )

    assert [item.chunk.page_number for item in chunks] == [1, 3]
    assert all(item.chunk.page_number != 2 for item in chunks)


def test_chunk_ids_are_deterministic_for_same_pdf_and_settings() -> None:
    extraction = _extraction(["동일한 PDF를 다시 색인해도 같은 청크가 생성됩니다."])
    fixed_time = datetime(2026, 7, 23, tzinfo=timezone.utc)
    first = chunk_pdf_document(
        extraction,
        chunk_size=18,
        chunk_overlap=4,
        collected_at=fixed_time,
    )
    second = chunk_pdf_document(
        extraction,
        chunk_size=18,
        chunk_overlap=4,
        collected_at=fixed_time,
    )

    assert [item.chunk.chunk_id for item in first] == [
        item.chunk.chunk_id for item in second
    ]


def test_failed_page_creates_no_chunk_and_later_page_number_is_preserved() -> None:
    extraction = PdfDocumentExtraction(
        document_title="부분 추출 문서",
        file_name="partial.pdf",
        source_path="data/raw/pdfs/partial.pdf",
        content_hash=hashlib.sha256(b"partial-pdf").hexdigest(),
        file_size_bytes=100,
        page_count=3,
        text_page_count=2,
        empty_page_count=0,
        failed_page_count=1,
        pages=[
            PdfPageExtraction(
                page_index=0,
                page_number=1,
                text="첫 페이지 본문",
                status=PdfPageStatus.TEXT,
            ),
            PdfPageExtraction(
                page_index=1,
                page_number=2,
                status=PdfPageStatus.FAILED,
                error_message="테스트 추출 실패",
            ),
            PdfPageExtraction(
                page_index=2,
                page_number=3,
                text="세 번째 페이지 본문",
                status=PdfPageStatus.TEXT,
            ),
        ],
        status=PdfDocumentStatus.PARTIAL,
    )

    chunks = chunk_pdf_document(
        extraction,
        chunk_size=100,
        chunk_overlap=10,
    )

    assert [item.chunk.page_number for item in chunks] == [1, 3]
