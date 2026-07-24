"""PDF 청킹, Chroma 색인과 질문 검색을 연결하는 검색 전용 서비스."""

from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from uuid import UUID

from src.config import PROJECT_ROOT, Settings, get_settings
from src.ingestion.chunker import chunk_pdf_document
from src.ingestion.pdf_extractor import extract_pdf_file, process_pdf_directory
from src.models import DocumentType
from src.ingestion.pdf_models import (
    PdfDocumentExtraction,
    PdfDocumentStatus,
    PdfPageStatus,
)
from src.retrieval.embeddings import (
    EmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
)
from src.retrieval.models import (
    DirectoryIndexReport,
    DocumentIndexDeleteReport,
    PdfIndexReport,
    SearchResult,
    SkippedPdfIndex,
    VectorCandidate,
)
from src.retrieval.vector_store import ChromaVectorStore


DEFAULT_COLLECTION_NAME = "pdf_chunks_v1"


class NoSearchablePdfContentError(RuntimeError):
    pass


class PdfSearchService:
    """LLM, API 키, Streamlit 없이 동작하는 PDF 검색 유스케이스."""

    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider,
        vector_store: ChromaVectorStore,
        chunk_size: int,
        chunk_overlap: int,
        top_k: int,
        min_retrieval_score: float,
        dedup_similarity_threshold: float,
        project_root: str | Path = PROJECT_ROOT,
    ) -> None:
        if chunk_size <= 0 or not 0 <= chunk_overlap < chunk_size:
            raise ValueError("청크 크기와 겹침 설정이 올바르지 않습니다.")
        if top_k <= 0:
            raise ValueError("top_k는 1 이상이어야 합니다.")
        if not 0 <= min_retrieval_score <= 1:
            raise ValueError("min_retrieval_score는 0 이상 1 이하여야 합니다.")
        if not 0 <= dedup_similarity_threshold <= 1:
            raise ValueError("dedup_similarity_threshold는 0 이상 1 이하여야 합니다.")
        self._embeddings = embedding_provider
        self._store = vector_store
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._top_k = top_k
        self._min_score = min_retrieval_score
        self._dedup_threshold = dedup_similarity_threshold
        self._project_root = Path(project_root).resolve()

    @classmethod
    def from_settings(
        cls,
        settings: Settings | None = None,
        *,
        collection_name: str = DEFAULT_COLLECTION_NAME,
    ) -> "PdfSearchService":
        settings = settings or get_settings()
        provider = SentenceTransformerEmbeddingProvider(
            model_name=settings.embedding_model_name,
            revision=settings.embedding_model_revision,
            device=settings.embedding_device,
            normalize=settings.embedding_normalize,
            query_prefix=settings.embedding_query_prefix,
            passage_prefix=settings.embedding_passage_prefix,
            max_length=settings.embedding_max_length,
        )
        store = ChromaVectorStore(
            persist_directory=settings.vector_db_path,
            collection_name=collection_name,
            embedding_fingerprint=provider.fingerprint,
        )
        return cls(
            embedding_provider=provider,
            vector_store=store,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            top_k=settings.top_k,
            min_retrieval_score=settings.min_retrieval_score,
            dedup_similarity_threshold=settings.retrieval_dedup_threshold,
            project_root=settings.project_root,
        )

    @property
    def indexed_chunk_count(self) -> int:
        return self._store.count()

    def available_departments(self) -> list[str]:
        """색인에 실제로 존재하는 학과 선택지를 반환한다."""

        return self._store.list_metadata_values("department")

    def available_document_types(self) -> list[DocumentType]:
        """색인에 실제로 존재하는 문서 유형 선택지를 반환한다."""

        return [
            DocumentType(value)
            for value in self._store.list_metadata_values("document_type")
        ]

    @staticmethod
    def _build_search_filter(
        *,
        department: str | None,
        document_type: DocumentType | str | None,
    ) -> dict[str, Any] | None:
        conditions: list[dict[str, Any]] = []
        if department is not None:
            normalized_department = department.strip()
            if not normalized_department:
                raise ValueError("department 필터는 비워 둘 수 없습니다.")
            conditions.append(
                {"department": {"$eq": normalized_department}}
            )

        if document_type is not None:
            try:
                normalized_document_type = DocumentType(document_type)
            except ValueError as error:
                raise ValueError("지원하지 않는 문서 유형입니다.") from error
            conditions.append(
                {"document_type": {"$eq": normalized_document_type.value}}
            )

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    def close(self) -> None:
        self._store.close()

    def __enter__(self) -> "PdfSearchService":
        return self

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        self.close()

    @staticmethod
    def _page_report(extraction: PdfDocumentExtraction) -> dict[str, object]:
        return {
            "source_page_count": extraction.page_count,
            "indexed_page_numbers": [
                page.page_number
                for page in extraction.pages
                if page.status is PdfPageStatus.TEXT
            ],
            "empty_page_numbers": [
                page.page_number
                for page in extraction.pages
                if page.status is PdfPageStatus.EMPTY
            ],
            "failed_page_numbers": [
                page.page_number
                for page in extraction.pages
                if page.status is PdfPageStatus.FAILED
            ],
            "issue_codes": [issue.code.value for issue in extraction.issues],
        }

    def _project_input_path(self, value: str | Path) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = self._project_root / path
        resolved = path.resolve()
        if not resolved.is_relative_to(self._project_root):
            raise ValueError(
                "PDF 입력 경로는 프로젝트 루트 내부에 있어야 합니다. "
                "파일을 data/raw/pdfs에 복사한 뒤 색인하세요."
            )
        return resolved

    def _index(
        self,
        extraction: PdfDocumentExtraction,
        *,
        document_id: UUID | None,
        department: str,
        category: str,
        section_title: str,
        replace: bool,
    ) -> PdfIndexReport:
        if extraction.status in {
            PdfDocumentStatus.ERROR,
            PdfDocumentStatus.EMPTY_DOCUMENT,
        }:
            raise NoSearchablePdfContentError(
                "PDF에서 검색 색인에 사용할 직접 추출 텍스트를 찾지 못했습니다."
            )

        page_report = self._page_report(extraction)
        effective_document_id = document_id
        effective_replace = replace
        if not replace:
            duplicate_id = self._store.find_document_by_source_file_hash(
                extraction.content_hash
            )
            if duplicate_id is not None:
                return PdfIndexReport(
                    document_id=duplicate_id,
                    document_title=extraction.document_title,
                    source_path=extraction.source_path,
                    source_file_hash=extraction.content_hash,
                    chunk_count=len(
                        self._store.get_document_chunk_ids(duplicate_id)
                    ),
                    inserted_count=0,
                    updated_count=0,
                    duplicate_registration_prevented=True,
                    **page_report,
                )

            indexed_path_id = self._store.find_document_by_source_path(
                extraction.source_path
            )
            if indexed_path_id is not None:
                effective_document_id = indexed_path_id
                effective_replace = True

        chunks = chunk_pdf_document(
            extraction,
            chunk_size=self._chunk_size,
            chunk_overlap=self._chunk_overlap,
            document_id=effective_document_id,
            department=department,
            category=category,
            section_title=section_title,
        )
        if not chunks:
            raise NoSearchablePdfContentError(
                "PDF에서 검색 색인에 사용할 직접 추출 텍스트를 찾지 못했습니다."
            )
        vectors = self._embeddings.embed_documents(
            [item.embedding_text for item in chunks]
        )
        canonical_id = chunks[0].chunk.document_id
        report = (
            self._store.replace_document(
                document_id=canonical_id, chunks=chunks, embeddings=vectors
            )
            if effective_replace
            else self._store.upsert_chunks(chunks, vectors)
        )
        return PdfIndexReport(
            document_id=canonical_id,
            document_title=extraction.document_title,
            source_path=extraction.source_path,
            source_file_hash=extraction.content_hash,
            chunk_count=len(chunks),
            inserted_count=report.inserted_count,
            updated_count=report.updated_count,
            removed_stale_count=report.removed_stale_count,
            duplicate_registration_prevented=False,
            **page_report,
        )

    def index_pdf_extraction(
        self,
        extraction: PdfDocumentExtraction,
        *,
        document_id: UUID | None = None,
        department: str = "미지정",
        category: str = "미지정",
        section_title: str = "본문",
    ) -> PdfIndexReport:
        return self._index(
            extraction,
            document_id=document_id,
            department=department,
            category=category,
            section_title=section_title,
            replace=False,
        )

    def index_pdf(self, pdf_path: str | Path) -> PdfIndexReport:
        extraction = extract_pdf_file(
            self._project_input_path(pdf_path),
            project_root=self._project_root,
        )
        return self.index_pdf_extraction(extraction)

    def index_pdf_directory(self, input_directory: str | Path) -> DirectoryIndexReport:
        batch = process_pdf_directory(
            self._project_input_path(input_directory),
            project_root=self._project_root,
        )
        indexed: list[PdfIndexReport] = []
        skipped: list[SkippedPdfIndex] = []
        for extraction in batch.documents:
            if extraction.is_duplicate:
                skipped.append(
                    SkippedPdfIndex(
                        source_path=extraction.source_path,
                        reason="같은 SHA-256 원본이 이미 이 배치에 있습니다.",
                        duplicate_of=extraction.duplicate_of,
                    )
                )
                continue
            try:
                indexed.append(self.index_pdf_extraction(extraction))
            except NoSearchablePdfContentError as error:
                skipped.append(
                    SkippedPdfIndex(source_path=extraction.source_path, reason=str(error))
                )
        return DirectoryIndexReport(
            indexed_documents=indexed, skipped_documents=skipped
        )

    @staticmethod
    def _normalized(content: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", content).casefold().split())

    def _deduplicate(self, candidates: list[VectorCandidate]) -> list[VectorCandidate]:
        kept: list[VectorCandidate] = []
        ids: set[str] = set()
        hashes: set[str] = set()
        normalized_texts: set[str] = set()
        source_texts: list[tuple[UUID, int, str]] = []
        for candidate in candidates:
            normalized = self._normalized(candidate.content)
            similar_in_same_page = any(
                candidate.document_id == document_id
                and candidate.page_number == page_number
                and SequenceMatcher(None, normalized, text).ratio()
                >= self._dedup_threshold
                for document_id, page_number, text in source_texts
            )
            if (
                candidate.chunk_id in ids
                or candidate.content_hash in hashes
                or normalized in normalized_texts
                or similar_in_same_page
            ):
                continue
            kept.append(candidate)
            ids.add(candidate.chunk_id)
            hashes.add(candidate.content_hash)
            normalized_texts.add(normalized)
            source_texts.append(
                (candidate.document_id, candidate.page_number, normalized)
            )
        return kept

    def search(
        self,
        question: str,
        *,
        top_k: int | None = None,
        min_score: float | None = None,
        department: str | None = None,
        document_type: DocumentType | str | None = None,
    ) -> list[SearchResult]:
        question = question.strip()
        limit = self._top_k if top_k is None else top_k
        threshold = self._min_score if min_score is None else min_score
        if not question:
            raise ValueError("검색 질문은 비워 둘 수 없습니다.")
        if limit <= 0 or not 0 <= threshold <= 1:
            raise ValueError("top_k 또는 min_score가 올바르지 않습니다.")
        where = self._build_search_filter(
            department=department,
            document_type=document_type,
        )
        record_count = self.indexed_chunk_count
        if record_count == 0:
            return []

        candidates = self._store.query(
            self._embeddings.embed_query(question),
            fetch_k=max(record_count, limit),
            where=where,
        )
        selected = self._deduplicate(
            [item for item in candidates if item.score >= threshold]
        )[:limit]
        return [
            SearchResult(
                document_id=item.document_id,
                chunk_id=item.chunk_id,
                document_title=item.document_title,
                document_type=item.document_type,
                department=item.department,
                page_number=item.page_number,
                content=item.content,
                score=item.score,
                content_hash=item.content_hash,
                source_path=item.source_path,
            )
            for item in selected
        ]

    def delete_document_index(self, document_id: UUID | str) -> DocumentIndexDeleteReport:
        parsed = document_id if isinstance(document_id, UUID) else UUID(document_id)
        return DocumentIndexDeleteReport(
            document_id=parsed,
            deleted_chunk_count=self._store.delete_document_index(parsed),
        )

    def reindex_pdf_extraction(
        self,
        extraction: PdfDocumentExtraction,
        *,
        document_id: UUID,
        department: str = "미지정",
        category: str = "미지정",
        section_title: str = "본문",
    ) -> PdfIndexReport:
        return self._index(
            extraction,
            document_id=document_id,
            department=department,
            category=category,
            section_title=section_title,
            replace=True,
        )

    def reindex_pdf(
        self,
        pdf_path: str | Path,
        *,
        document_id: UUID,
        department: str = "미지정",
        category: str = "미지정",
        section_title: str = "본문",
    ) -> PdfIndexReport:
        extraction = extract_pdf_file(
            self._project_input_path(pdf_path),
            project_root=self._project_root,
        )
        return self.reindex_pdf_extraction(
            extraction,
            document_id=document_id,
            department=department,
            category=category,
            section_title=section_title,
        )
