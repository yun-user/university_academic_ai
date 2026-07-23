"""PDF 목록 조회와 페이지 추출 결과의 구조화된 데이터 계약."""

from __future__ import annotations

from enum import Enum
from typing import Self

from pydantic import Field, model_validator

from src.models import NonEmptyText, Sha256Hex, StrictModel


class PdfPageStatus(str, Enum):
    TEXT = "text"
    EMPTY = "empty"
    FAILED = "failed"


class PdfDocumentStatus(str, Enum):
    SUCCESS = "success"
    SUCCESS_WITH_WARNINGS = "success_with_warnings"
    PARTIAL = "partial"
    EMPTY_DOCUMENT = "empty_document"
    ERROR = "error"


class PdfIssueCode(str, Enum):
    EMPTY_FILE = "empty_file"
    PDF_OPEN_FAILED = "pdf_open_failed"
    PASSWORD_REQUIRED = "password_required"
    EMPTY_PAGE = "empty_page"
    PAGE_EXTRACTION_FAILED = "page_extraction_failed"
    NO_EXTRACTABLE_TEXT = "no_extractable_text"
    DUPLICATE_FILE = "duplicate_file"


class PdfIssue(StrictModel):
    code: PdfIssueCode
    message: NonEmptyText
    page_number: int | None = Field(default=None, ge=1)


class PdfPageExtraction(StrictModel):
    page_index: int = Field(ge=0)
    page_number: int = Field(ge=1)
    text: str = ""
    status: PdfPageStatus
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_page_state(self) -> Self:
        if self.page_number != self.page_index + 1:
            raise ValueError("page_number는 page_index + 1이어야 합니다.")
        if self.status is PdfPageStatus.TEXT and not self.text.strip():
            raise ValueError("TEXT 상태에는 추출된 텍스트가 필요합니다.")
        if self.status is not PdfPageStatus.TEXT and self.text:
            raise ValueError("EMPTY 또는 FAILED 상태의 text는 비어 있어야 합니다.")
        if self.status is PdfPageStatus.FAILED and not self.error_message:
            raise ValueError("FAILED 상태에는 error_message가 필요합니다.")
        return self


class PdfDocumentExtraction(StrictModel):
    document_title: NonEmptyText
    file_name: NonEmptyText
    source_path: NonEmptyText
    content_hash: Sha256Hex
    file_size_bytes: int = Field(ge=0)
    page_count: int = Field(ge=0)
    text_page_count: int = Field(ge=0)
    empty_page_count: int = Field(ge=0)
    failed_page_count: int = Field(ge=0)
    pages: list[PdfPageExtraction] = Field(default_factory=list)
    status: PdfDocumentStatus
    is_duplicate: bool = False
    duplicate_of: str | None = None
    issues: list[PdfIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_page_sequence(self) -> Self:
        if len(self.pages) != self.page_count:
            raise ValueError("pages 길이는 PDF page_count와 같아야 합니다.")

        actual_indices = [page.page_index for page in self.pages]
        actual_numbers = [page.page_number for page in self.pages]
        if actual_indices != list(range(self.page_count)):
            raise ValueError("page_index는 0부터 순서대로 있어야 합니다.")
        if actual_numbers != list(range(1, self.page_count + 1)):
            raise ValueError("page_number는 1부터 순서대로 있어야 합니다.")

        count_sum = (
            self.text_page_count
            + self.empty_page_count
            + self.failed_page_count
        )
        if count_sum != self.page_count:
            raise ValueError("페이지 상태별 개수 합은 page_count와 같아야 합니다.")

        if self.is_duplicate != bool(self.duplicate_of):
            raise ValueError("중복 문서는 duplicate_of를 함께 가져야 합니다.")
        return self


class DuplicatePdfGroup(StrictModel):
    content_hash: Sha256Hex
    original_source_path: NonEmptyText
    duplicate_source_paths: list[NonEmptyText] = Field(min_length=1)


class PdfBatchExtraction(StrictModel):
    input_directory: NonEmptyText
    documents: list[PdfDocumentExtraction] = Field(default_factory=list)
    duplicate_groups: list[DuplicatePdfGroup] = Field(default_factory=list)
