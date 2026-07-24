"""PDF 페이지 경계를 넘지 않는 결정적 검색 청크 생성."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

from src.ingestion.pdf_models import PdfDocumentExtraction, PdfPageStatus
from src.models import DocumentChunk, DocumentType
from src.retrieval.models import SearchableChunk


_BOUNDARY_PATTERN = re.compile(r"(?:\r?\n+|[.!?。！？](?:\s+|$))")


def stable_pdf_document_id(extraction: PdfDocumentExtraction) -> UUID:
    """동일한 원본 PDF 해시에 항상 같은 문서 ID를 만든다."""

    return uuid5(
        NAMESPACE_URL,
        f"university-academic-ai:pdf:{extraction.content_hash}",
    )


def split_text_into_chunks(
    text: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    """원문 순서를 유지하며 문장 경계를 우선하는 문자 기반 청킹."""

    if chunk_size <= 0:
        raise ValueError("chunk_size는 1 이상이어야 합니다.")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap은 0 이상 chunk_size 미만이어야 합니다.")

    normalized = text.strip()
    if not normalized:
        return []
    if len(normalized) <= chunk_size:
        return [normalized]

    chunks: list[str] = []
    start = 0
    text_length = len(normalized)

    while start < text_length:
        hard_end = min(start + chunk_size, text_length)
        end = hard_end
        if hard_end < text_length:
            window = normalized[start:hard_end]
            minimum_boundary = max(1, int(len(window) * 0.6))
            boundary_ends = [
                match.end()
                for match in _BOUNDARY_PATTERN.finditer(window)
                if match.end() >= minimum_boundary
            ]
            if boundary_ends:
                end = start + boundary_ends[-1]
            else:
                whitespace_end = window.rfind(" ", minimum_boundary)
                if whitespace_end > 0:
                    end = start + whitespace_end + 1

        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= text_length:
            break

        next_start = max(start + 1, end - chunk_overlap)
        while next_start < end and normalized[next_start].isspace():
            next_start += 1
        start = next_start

    return chunks


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _embedding_text(
    *,
    document_title: str,
    department: str,
    category: str,
    section_title: str,
    page_number: int,
    content: str,
) -> str:
    return "\n".join(
        (
            f"문서명: {document_title}",
            f"학과: {department}",
            f"분류: {category}",
            f"절: {section_title}",
            f"PDF 페이지: {page_number}",
            content,
        )
    )


def chunk_pdf_document(
    extraction: PdfDocumentExtraction,
    *,
    chunk_size: int,
    chunk_overlap: int,
    document_id: UUID | None = None,
    department: str = "미지정",
    category: str = "미지정",
    section_title: str = "본문",
    published_date: date | None = None,
    collected_at: datetime | None = None,
) -> list[SearchableChunk]:
    """TEXT 상태 페이지만 청킹하고 기존 1-based 페이지를 그대로 유지한다."""

    canonical_document_id = document_id or stable_pdf_document_id(extraction)
    collected = collected_at or datetime.now(timezone.utc)
    if collected.tzinfo is None or collected.utcoffset() is None:
        raise ValueError("collected_at에는 시간대 정보가 필요합니다.")

    searchable_chunks: list[SearchableChunk] = []
    for page in extraction.pages:
        if page.status is not PdfPageStatus.TEXT:
            continue

        page_chunks = split_text_into_chunks(
            page.text,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        for ordinal, content in enumerate(page_chunks):
            content_hash = _sha256_text(content)
            chunk_id = (
                f"{canonical_document_id}:p{page.page_number:05d}:"
                f"c{ordinal:04d}:{content_hash[:16]}"
            )
            canonical_chunk = DocumentChunk(
                document_id=canonical_document_id,
                chunk_id=chunk_id,
                document_title=extraction.document_title,
                document_type=DocumentType.PDF,
                department=department,
                category=category,
                source_path=extraction.source_path,
                page_number=page.page_number,
                section_title=section_title,
                published_date=published_date,
                collected_at=collected,
                content=content,
                content_hash=content_hash,
            )
            searchable_chunks.append(
                SearchableChunk(
                    chunk=canonical_chunk,
                    embedding_text=_embedding_text(
                        document_title=extraction.document_title,
                        department=department,
                        category=category,
                        section_title=section_title,
                        page_number=page.page_number,
                        content=content,
                    ),
                    source_file_hash=extraction.content_hash,
                )
            )

    return searchable_chunks
