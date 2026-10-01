"""결정적 답변과 그 근거를 전달하는 프레임워크 독립 모델."""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum

from pydantic import Field, model_validator

from src.models import NonEmptyText, StrictModel
from src.retrieval.document_models import (
    DocumentFileType,
    DocumentSearchResponse,
)


class AnswerStatus(str, Enum):
    """답변 계층이 근거 있는 답변을 만들었는지 나타낸다."""

    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class AnswerFormat(str, Enum):
    """답변을 만드는 데 사용한 최상위 근거 형식."""

    CSV = "csv"
    PDF = "pdf"
    TXT = "txt"
    MIXED = "mixed"
    NONE = "none"


class AnswerMode(str, Enum):
    """최종 답변을 만든 계층."""

    DETERMINISTIC = "deterministic"
    LLM = "llm"


class AnswerSource(StrictModel):
    """답변 본문에 실제로 사용된 검색 결과의 출처."""

    chunk_id: NonEmptyText
    document_id: str | None = None
    file_name: NonEmptyText
    file_type: DocumentFileType
    source_year: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    row_number: int | None = Field(default=None, ge=1)
    is_current: bool | None = None
    excerpt: NonEmptyText
    source_url: str | None = None

    @model_validator(mode="after")
    def validate_locator(self) -> "AnswerSource":
        if self.file_type == "pdf":
            if self.page_number is None or self.row_number is not None:
                raise ValueError("PDF 답변 출처에는 페이지 번호만 필요합니다.")
        elif self.file_type == "csv":
            if self.row_number is None or self.page_number is not None:
                raise ValueError("CSV 답변 출처에는 행 번호만 필요합니다.")
        elif self.page_number is not None or self.row_number is not None:
            raise ValueError("TXT 답변 출처에는 페이지나 행 번호가 없어야 합니다.")
        return self


def answer_source_key(source: AnswerSource) -> tuple[str, ...]:
    """사용자에게 표시할 물리 출처 위치를 안정적인 키로 만든다."""

    identity = (source.document_id or "", source.file_name, source.source_year or "", source.source_url or "")
    if source.file_type == "pdf":
        return ("pdf", *identity, str(source.page_number))
    if source.file_type == "csv":
        return ("csv", *identity, str(source.row_number))
    return ("txt", *identity)


def deduplicate_answer_sources(
    sources: Sequence[AnswerSource],
) -> list[AnswerSource]:
    """동일 파일·페이지/행 출처는 첫 번째 근거만 남긴다."""

    unique: list[AnswerSource] = []
    seen: set[tuple[str, ...]] = set()
    for source in sources:
        key = answer_source_key(source)
        if key in seen:
            continue
        seen.add(key)
        unique.append(source)
    return unique


class AnswerResponse(StrictModel):
    """사람이 읽을 답변과 재검색 없이 표시할 검색 근거를 함께 보관한다."""

    question: NonEmptyText
    status: AnswerStatus
    answer_format: AnswerFormat
    text: NonEmptyText
    sources: list[AnswerSource] = Field(default_factory=list)
    search_response: DocumentSearchResponse
    answer_mode: AnswerMode = AnswerMode.DETERMINISTIC

    @model_validator(mode="after")
    def validate_answer_evidence(self) -> "AnswerResponse":
        if self.status is AnswerStatus.ANSWERED:
            if self.answer_format is AnswerFormat.NONE or not self.sources:
                raise ValueError("근거 있는 답변에는 답변 형식과 출처가 필요합니다.")
            source_types = {source.file_type for source in self.sources}
            if self.answer_format is AnswerFormat.MIXED:
                if len(source_types) < 2:
                    raise ValueError("혼합 답변에는 서로 다른 형식의 출처가 필요합니다.")
            elif any(
                source.file_type != self.answer_format.value
                for source in self.sources
            ):
                raise ValueError("답변 형식과 사용된 출처 형식이 일치해야 합니다.")

            results_by_chunk = {
                result.chunk_id: result for result in self.search_response.results
            }
            for source in self.sources:
                result = results_by_chunk.get(source.chunk_id)
                if result is None:
                    raise ValueError("답변 출처는 검색 결과에 포함되어야 합니다.")
                if source.document_id is not None and source.document_id != result.document_id:
                    raise ValueError("답변 출처의 문서 ID가 검색 결과와 다릅니다.")
                source_locator = (
                    source.file_name,
                    source.file_type,
                    source.source_year,
                    source.page_number,
                    source.row_number,
                    source.is_current,
                    source.source_url,
                )
                result_locator = (
                    result.file_name,
                    result.file_type,
                    result.source_year,
                    result.page_number,
                    result.row_number,
                    result.is_current,
                    result.source_url,
                )
                if source_locator != result_locator:
                    raise ValueError("답변 출처 메타데이터가 검색 결과와 다릅니다.")

                normalized_excerpt = " ".join(
                    source.excerpt.removesuffix("…").split()
                )
                normalized_source = " ".join(result.text.split())
                if normalized_excerpt not in normalized_source:
                    raise ValueError("답변 발췌문은 검색 원문에 포함되어야 합니다.")
        elif self.answer_format is not AnswerFormat.NONE or self.sources:
            raise ValueError("근거 부족 답변에는 사용된 출처가 없어야 합니다.")
        return self
