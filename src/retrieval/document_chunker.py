"""documents.jsonl 레코드를 기존 문자 청커로 검색 청크화한다."""

from __future__ import annotations

import hashlib
import unicodedata
from uuid import NAMESPACE_URL, uuid5

from src.ingestion.chunker import split_text_into_chunks
from src.retrieval.document_models import CorpusChunk, CorpusRecord


CHUNK_ID_VERSION = "corpus-chunk-v1"


def _normalized_identifier(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip().casefold()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _locator(record: CorpusRecord) -> str:
    if record.file_type == "pdf":
        return f"p{record.page_number:05d}"
    if record.file_type == "csv":
        return f"r{record.row_number:06d}"
    return "body"


def _embedding_text(record: CorpusRecord, content: str) -> str:
    location = (
        f"PDF 페이지: {record.page_number}"
        if record.page_number is not None
        else (
            f"CSV 행: {record.row_number}"
            if record.row_number is not None
            else "문서 위치: 전체"
        )
    )
    current_status = (
        "최신"
        if record.is_current is True
        else "과거 자료"
        if record.is_current is False
        else "최신 여부 미확인"
    )
    return "\n".join(
        (
            f"문서명: {record.title}",
            f"자료 형식: {record.file_type}",
            f"문서 유형: {record.document_type or '미지정'}",
            f"학과: {record.department or '미지정'}",
            f"기준연도: {record.source_year or '미지정'}",
            f"최신 자료 여부: {current_status}",
            location,
            content,
        )
    )


def chunk_corpus_record(
    record: CorpusRecord,
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[CorpusChunk]:
    """검색 가능한 한 레코드를 페이지·행 경계 안에서 결정적으로 분할한다."""

    if not record.searchable or not record.text.strip():
        return []

    locator = _locator(record)
    record_namespace = uuid5(
        NAMESPACE_URL,
        ":".join(
            (
                "university-academic-ai",
                CHUNK_ID_VERSION,
                _normalized_identifier(record.document_id),
                record.file_type,
                _normalized_identifier(record.file_name),
                _normalized_identifier(record.source_path),
                locator,
            )
        ),
    )
    chunks: list[CorpusChunk] = []
    # A CSV row is one structured fact. Splitting it can detach its name/code
    # from the semester credits and required/elective flags.
    contents = ([record.text.strip()] if record.file_type == "csv" else
        split_text_into_chunks(
            record.text,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
    )
    for ordinal, content in enumerate(contents):
        content_hash = _sha256_text(content)
        chunk_id = str(
            uuid5(
                record_namespace,
                f"{CHUNK_ID_VERSION}:{ordinal:04d}:{content_hash}",
            )
        )
        chunks.append(
            CorpusChunk(
                document_id=record.document_id,
                chunk_id=chunk_id,
                file_name=record.file_name,
                file_type=record.file_type,
                document_type=record.document_type or "미지정",
                source_year=record.source_year,
                effective_from=record.effective_from,
                effective_to=record.effective_to,
                department=record.department or "미지정",
                admission_year_from=record.admission_year_from,
                admission_year_to=record.admission_year_to,
                track=record.track,
                authority=record.authority,
                is_current=record.is_current,
                source_url=record.source_url,
                page_number=record.page_number,
                row_number=record.row_number,
                title=record.title,
                source_path=record.source_path,
                source_file_hash=record.source_file_hash,
                content=content,
                content_hash=content_hash,
                embedding_text=_embedding_text(record, content),
            )
        )
    return chunks
