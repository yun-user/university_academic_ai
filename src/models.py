"""프레임워크와 저장소에 독립적인 핵심 데이터 계약.

이번 단계에서는 모델과 검증 규칙만 정의한다. PDF 추출, 검색, LLM 호출은
아직 구현하지 않는다.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
    model_validator,
)


NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
Sha256Hex = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True, pattern=r"^[0-9a-f]{64}$"),
]


class StrictModel(BaseModel):
    """알 수 없는 필드를 거부하는 불변 모델의 공통 기반."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DocumentType(str, Enum):
    PDF = "pdf"
    TXT = "txt"
    WEB_NOTICE = "web_notice"
    WEB_ATTACHMENT = "web_attachment"


class AnswerStatus(str, Enum):
    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    OUT_OF_SCOPE = "out_of_scope"
    PERSONAL_DATA_REQUIRED = "personal_data_required"
    RETRIEVAL_ONLY = "retrieval_only"
    ERROR = "error"


class ConfidenceLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNAVAILABLE = "unavailable"


class RuntimeMode(str, Enum):
    RETRIEVAL_ONLY = "retrieval-only"
    GENERATION_ENABLED = "generation-enabled"


class DocumentChunk(StrictModel):
    """검색과 인용에 사용될 문서 조각의 정본 메타데이터."""

    document_id: UUID
    chunk_id: NonEmptyText
    document_title: NonEmptyText
    document_type: DocumentType
    department: NonEmptyText
    category: NonEmptyText
    source_path: str | None = None
    source_url: HttpUrl | None = None
    page_number: int | None = Field(default=None, ge=1)
    section_title: NonEmptyText
    published_date: date | None = None
    collected_at: datetime
    content: NonEmptyText
    content_hash: Sha256Hex

    @field_validator("source_path")
    @classmethod
    def source_path_must_be_internal_relative_path(
        cls, value: str | None
    ) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        if not normalized:
            return None

        path = Path(normalized)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("source_path는 프로젝트 내부 상대 경로여야 합니다.")
        return path.as_posix()

    @field_validator("collected_at")
    @classmethod
    def collected_at_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("collected_at에는 시간대 정보가 필요합니다.")
        return value

    @model_validator(mode="after")
    def validate_source_contract(self) -> Self:
        if self.document_type in {DocumentType.PDF, DocumentType.TXT}:
            if self.source_path is None:
                raise ValueError("업로드 문서는 source_path가 필요합니다.")

        if self.document_type is DocumentType.PDF and self.page_number is None:
            raise ValueError("PDF 문서 조각에는 1부터 시작하는 page_number가 필요합니다.")

        if self.document_type in {
            DocumentType.WEB_NOTICE,
            DocumentType.WEB_ATTACHMENT,
        }:
            if self.source_url is None:
                raise ValueError("웹 문서에는 source_url이 필요합니다.")
            if self.published_date is None:
                raise ValueError("웹 문서에는 published_date가 필요합니다.")

        return self


class EvidenceReference(StrictModel):
    """검색 결과에서 답변에 사용하도록 승인된 근거."""

    evidence_id: NonEmptyText
    document_id: UUID
    chunk_id: NonEmptyText
    document_title: NonEmptyText
    document_type: DocumentType
    page_number: int | None = Field(default=None, ge=1)
    source_url: HttpUrl | None = None
    published_date: date | None = None
    quote: NonEmptyText
    content_hash: Sha256Hex

    @model_validator(mode="after")
    def validate_locator(self) -> Self:
        if self.page_number is None and self.source_url is None:
            raise ValueError("근거에는 page_number 또는 source_url이 필요합니다.")
        return self


class AnswerClaim(StrictModel):
    """답변 문장과 이를 뒷받침하는 근거 ID의 연결."""

    text: NonEmptyText
    evidence_ids: list[NonEmptyText] = Field(min_length=1)


class Confidence(StrictModel):
    """보정 여부와 이유를 포함하는 사용자 표시용 신뢰도."""

    level: ConfidenceLevel = ConfidenceLevel.UNAVAILABLE
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    calibrated: bool = False
    reasons: list[NonEmptyText] = Field(default_factory=list)


class AnswerBundle(StrictModel):
    """UI가 렌더링할 답변·거절 결과의 공통 계약."""

    status: AnswerStatus
    core_answer: str = ""
    details: list[NonEmptyText] = Field(default_factory=list)
    claims: list[AnswerClaim] = Field(default_factory=list)
    citations: list[EvidenceReference] = Field(default_factory=list)
    confidence: Confidence = Field(default_factory=Confidence)
    items_to_verify: list[NonEmptyText] = Field(default_factory=list)
    reason_codes: list[NonEmptyText] = Field(default_factory=list)
    trace_id: str | None = None
    index_revision_id: str | None = None

    @model_validator(mode="after")
    def answered_result_requires_evidence(self) -> Self:
        if self.status is AnswerStatus.ANSWERED:
            if not self.core_answer.strip():
                raise ValueError("답변 상태에는 core_answer가 필요합니다.")
            if not self.claims or not self.citations:
                raise ValueError("답변 상태에는 claims와 citations가 필요합니다.")
        return self


class RuntimeStatus(StrictModel):
    """기본 화면에서 노출할 비민감 런타임 상태."""

    app_name: NonEmptyText
    mode: RuntimeMode
    configuration_loaded: bool
    llm_configured: bool
