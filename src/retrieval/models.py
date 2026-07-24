"""PDF 검색 색인과 결과의 프레임워크 독립 데이터 계약."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from src.models import (
    DocumentChunk,
    DocumentType,
    NonEmptyText,
    Sha256Hex,
    StrictModel,
)


class SearchableChunk(StrictModel):
    """정본 청크와 임베딩 입력을 분리해 보관한다."""

    chunk: DocumentChunk
    embedding_text: NonEmptyText
    source_file_hash: Sha256Hex


class VectorCandidate(StrictModel):
    """벡터 저장소가 반환하는 내부 검색 후보."""

    document_id: UUID
    chunk_id: NonEmptyText
    document_title: NonEmptyText
    document_type: DocumentType
    department: NonEmptyText
    page_number: int = Field(ge=1)
    content: NonEmptyText
    content_hash: Sha256Hex
    source_path: str | None = None
    distance: float = Field(ge=0.0)
    score: float = Field(ge=-1.0, le=1.0)


class SearchResult(StrictModel):
    """검색 전용 API가 호출자에게 반환하는 출처 포함 결과."""

    document_id: UUID
    chunk_id: NonEmptyText
    document_title: NonEmptyText
    document_type: DocumentType
    department: NonEmptyText
    page_number: int = Field(ge=1)
    content: NonEmptyText
    score: float = Field(ge=-1.0, le=1.0)
    score_kind: Literal["cosine_similarity"] = "cosine_similarity"
    content_hash: Sha256Hex
    source_path: str | None = None


class VectorUpsertReport(StrictModel):
    attempted_count: int = Field(ge=0)
    inserted_count: int = Field(ge=0)
    updated_count: int = Field(ge=0)
    removed_stale_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> "VectorUpsertReport":
        if self.inserted_count + self.updated_count != self.attempted_count:
            raise ValueError("inserted_count와 updated_count 합이 attempted_count와 다릅니다.")
        return self


class PdfIndexReport(StrictModel):
    document_id: UUID
    document_title: NonEmptyText
    source_path: NonEmptyText
    source_file_hash: Sha256Hex
    chunk_count: int = Field(ge=0)
    inserted_count: int = Field(ge=0)
    updated_count: int = Field(ge=0)
    removed_stale_count: int = Field(default=0, ge=0)
    duplicate_registration_prevented: bool = False
    source_page_count: int = Field(default=0, ge=0)
    indexed_page_numbers: list[int] = Field(default_factory=list)
    empty_page_numbers: list[int] = Field(default_factory=list)
    failed_page_numbers: list[int] = Field(default_factory=list)
    issue_codes: list[str] = Field(default_factory=list)


class SkippedPdfIndex(StrictModel):
    source_path: NonEmptyText
    reason: NonEmptyText
    duplicate_of: str | None = None


class DirectoryIndexReport(StrictModel):
    indexed_documents: list[PdfIndexReport] = Field(default_factory=list)
    skipped_documents: list[SkippedPdfIndex] = Field(default_factory=list)


class DocumentIndexDeleteReport(StrictModel):
    document_id: UUID
    deleted_chunk_count: int = Field(ge=0)
