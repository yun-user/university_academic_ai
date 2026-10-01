"""통합 corpus 색인과 검색 결과의 프레임워크 독립 데이터 계약."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.models import NonEmptyText, Sha256Hex, StrictModel
from src.retrieval.query_intent import QuestionIntent


DocumentFileType = Literal["pdf", "csv", "txt"]
OUTDATED_DOCUMENT_WARNING = "최신 자료가 아닐 수 있습니다"


class CorpusRecord(BaseModel):
    """documents.jsonl 한 줄의 입력 계약."""

    model_config = ConfigDict(extra="allow", frozen=True)

    document_id: NonEmptyText
    file_name: NonEmptyText
    file_type: DocumentFileType
    document_type: str | None = None
    source_year: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    department: str | None = None
    admission_year_from: str | None = None
    admission_year_to: str | None = None
    track: str | None = None
    authority: str | None = None
    is_current: bool | None = None
    source_url: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    row_number: int | None = Field(default=None, ge=1)
    title: NonEmptyText
    text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    searchable: bool = False

    @model_validator(mode="after")
    def validate_searchable_locator(self) -> Self:
        if not self.searchable:
            return self
        if self.file_type == "pdf" and self.page_number is None:
            raise ValueError("검색 가능한 PDF 레코드에는 page_number가 필요합니다.")
        if self.file_type == "csv" and self.row_number is None:
            raise ValueError("검색 가능한 CSV 레코드에는 row_number가 필요합니다.")
        return self

    @property
    def source_path(self) -> str:
        value = str(self.metadata.get("source_path") or "").strip()
        return value or f"data/processed/{self.file_name}"

    @property
    def source_file_hash(self) -> str:
        return str(self.metadata.get("source_file_hash") or "").strip()


class CorpusChunk(StrictModel):
    """통합 문서 레코드에서 생성된 결정적 검색 청크."""

    document_id: NonEmptyText
    chunk_id: NonEmptyText
    file_name: NonEmptyText
    file_type: DocumentFileType
    document_type: NonEmptyText
    source_year: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    department: NonEmptyText
    admission_year_from: str | None = None
    admission_year_to: str | None = None
    track: str | None = None
    authority: str | None = None
    is_current: bool | None = None
    source_url: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    row_number: int | None = Field(default=None, ge=1)
    title: NonEmptyText
    source_path: NonEmptyText
    source_file_hash: str = ""
    content: NonEmptyText
    content_hash: Sha256Hex
    embedding_text: NonEmptyText

    @model_validator(mode="after")
    def validate_locator(self) -> Self:
        if self.file_type == "pdf":
            if self.page_number is None or self.row_number is not None:
                raise ValueError("PDF 청크에는 page_number만 필요합니다.")
        elif self.file_type == "csv":
            if self.row_number is None or self.page_number is not None:
                raise ValueError("CSV 청크에는 row_number만 필요합니다.")
        elif self.page_number is not None or self.row_number is not None:
            raise ValueError("TXT 청크에는 페이지나 행 번호를 저장하지 않습니다.")
        return self


class DocumentVectorCandidate(StrictModel):
    """통합 ChromaDB가 반환하는 내부 검색 후보."""

    document_id: NonEmptyText
    chunk_id: NonEmptyText
    file_name: NonEmptyText
    file_type: DocumentFileType
    document_type: NonEmptyText
    source_year: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    department: NonEmptyText
    admission_year_from: str | None = None
    admission_year_to: str | None = None
    track: str | None = None
    authority: str | None = None
    is_current: bool | None = None
    source_url: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    row_number: int | None = Field(default=None, ge=1)
    title: NonEmptyText
    source_path: NonEmptyText
    content: NonEmptyText
    content_hash: Sha256Hex
    distance: float = Field(ge=0.0)
    score: float = Field(ge=-1.0, le=1.0)


class DocumentSearchResult(StrictModel):
    """Streamlit과 CLI가 표시하는 통합 검색 결과."""

    document_id: NonEmptyText
    chunk_id: NonEmptyText
    file_name: NonEmptyText
    file_type: DocumentFileType
    document_type: NonEmptyText
    source_year: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    department: NonEmptyText
    admission_year_from: str | None = None
    admission_year_to: str | None = None
    track: str | None = None
    authority: str | None = None
    is_current: bool | None = None
    source_url: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    row_number: int | None = Field(default=None, ge=1)
    title: NonEmptyText
    source_path: NonEmptyText
    text: NonEmptyText
    # 규정 답변에서 동일 PDF 페이지의 제목·표 머리말 등 인접 청크를
    # 적용 범위 확인에만 사용한다. 실제 인용 원문은 ``text``로 유지한다.
    context_text: str | None = None
    score: float = Field(ge=-1.0, le=1.0)
    score_kind: Literal["cosine_similarity", "structured_exact"] = (
        "cosine_similarity"
    )
    content_hash: Sha256Hex
    currentness_warning: str | None = None


class DocumentSearchResponse(StrictModel):
    """검색 결과와 구조화 교과과정 검색 분기 정보를 함께 전달한다."""

    results: list[DocumentSearchResult] = Field(default_factory=list)
    clarification_message: str | None = None
    reviewed_answer: str | None = None
    # 학과 범위 밖 자료로 넓혀 찾았을 때 답변 맨 앞에 붙일 안내.
    scope_notice: str | None = None
    question_intent: QuestionIntent = QuestionIntent.GENERAL_SEARCH
    structured_query: bool = False
    exact_match_count: int = Field(default=0, ge=0)
    semantic_fallback_used: bool = False


class CorpusStoreSyncReport(StrictModel):
    attempted_count: int = Field(ge=0)
    inserted_count: int = Field(ge=0)
    updated_count: int = Field(ge=0)
    removed_stale_count: int = Field(ge=0)


class CorpusIndexReport(StrictModel):
    corpus_path: NonEmptyText
    total_record_count: int = Field(ge=0)
    indexed_document_count: int = Field(ge=0)
    indexed_record_count: int = Field(ge=0)
    indexed_chunk_count: int = Field(ge=0)
    skipped_unsearchable_count: int = Field(ge=0)
    skipped_empty_text_count: int = Field(ge=0)
    inserted_count: int = Field(ge=0)
    updated_count: int = Field(ge=0)
    removed_stale_count: int = Field(ge=0)
    indexed_records_by_file_type: dict[str, int] = Field(default_factory=dict)
    indexed_chunks_by_file_type: dict[str, int] = Field(default_factory=dict)
