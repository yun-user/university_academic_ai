"""documents.jsonl 기반 PDF·CSV·TXT 통합 색인과 검색 서비스."""

from __future__ import annotations

import json
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from src.config import PROJECT_ROOT, Settings, get_settings
from src.retrieval.document_chunker import chunk_corpus_record
from src.retrieval.course_search import (
    COURSE_DOCUMENT_TYPE,
    CourseQueryIntent,
    lexical_overlap,
    normalize_text,
    parse_course_info,
    parse_course_query,
)
from src.retrieval.document_models import (
    CorpusChunk,
    CorpusIndexReport,
    CorpusRecord,
    DocumentSearchResponse,
    DocumentSearchResult,
    DocumentVectorCandidate,
    OUTDATED_DOCUMENT_WARNING,
)
from src.retrieval.document_vector_store import ChromaDocumentVectorStore
from src.retrieval.embeddings import (
    EmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
)


DEFAULT_DOCUMENT_COLLECTION_NAME = "academic_corpus_chunks_v1"
DEFAULT_CORPUS_RELATIVE_PATH = Path("data/processed/documents.jsonl")


class CorpusLoadError(RuntimeError):
    """통합 corpus 파일을 안전하게 읽거나 검증할 수 없을 때 발생한다."""


class DocumentSearchService:
    """LLM 없이 통합 corpus 원문을 색인하고 검색하는 서비스."""

    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider,
        vector_store: ChromaDocumentVectorStore,
        chunk_size: int,
        chunk_overlap: int,
        top_k: int,
        min_retrieval_score: float,
        dedup_similarity_threshold: float,
        project_root: str | Path = PROJECT_ROOT,
        corpus_path: str | Path | None = None,
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
        default_corpus = self._project_root / DEFAULT_CORPUS_RELATIVE_PATH
        self._corpus_path = Path(corpus_path or default_corpus).resolve()

    @classmethod
    def from_settings(
        cls,
        settings: Settings | None = None,
        *,
        collection_name: str = DEFAULT_DOCUMENT_COLLECTION_NAME,
    ) -> "DocumentSearchService":
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
        store = ChromaDocumentVectorStore(
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
            corpus_path=settings.processed_data_dir / "documents.jsonl",
        )

    @property
    def indexed_chunk_count(self) -> int:
        return self._store.count()

    @property
    def corpus_path(self) -> Path:
        return self._corpus_path

    def available_departments(self) -> list[str]:
        return self._store.list_metadata_values("department")

    def available_document_types(self) -> list[str]:
        return self._store.list_metadata_values("document_type")

    def available_file_types(self) -> list[str]:
        return self._store.list_metadata_values("file_type")

    def indexed_chunk_counts_by_file_type(self) -> dict[str, int]:
        return self._store.indexed_chunk_counts_by_file_type()

    def close(self) -> None:
        self._store.close()

    def __enter__(self) -> "DocumentSearchService":
        return self

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        self.close()

    def _resolve_corpus_path(self, corpus_path: str | Path | None) -> Path:
        path = Path(corpus_path or self._corpus_path)
        if not path.is_absolute():
            path = self._project_root / path
        return path.resolve()

    @staticmethod
    def _load_records(path: Path) -> list[CorpusRecord]:
        if not path.is_file():
            raise CorpusLoadError(f"통합 corpus 파일을 찾을 수 없습니다: {path}")

        records: list[CorpusRecord] = []
        try:
            with path.open(
                "r",
                encoding="utf-8-sig",
                errors="strict",
                newline="",
            ) as source:
                for line_number, line in enumerate(source, start=1):
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                        records.append(CorpusRecord.model_validate(payload))
                    except (json.JSONDecodeError, ValidationError) as error:
                        raise CorpusLoadError(
                            f"documents.jsonl {line_number}번째 줄이 올바르지 않습니다: "
                            f"{error}"
                        ) from error
        except (OSError, UnicodeError) as error:
            raise CorpusLoadError(f"통합 corpus를 읽을 수 없습니다: {error}") from error
        return records

    @staticmethod
    def _display_path(path: Path, project_root: Path) -> str:
        try:
            return path.relative_to(project_root).as_posix()
        except ValueError:
            return path.as_posix()

    def index_corpus(
        self,
        corpus_path: str | Path | None = None,
        *,
        reset_collection: bool = False,
    ) -> CorpusIndexReport:
        """완성된 corpus snapshot과 통합 컬렉션을 일치시킨다."""

        path = self._resolve_corpus_path(corpus_path)
        records = self._load_records(path)
        chunks: list[CorpusChunk] = []
        indexed_records: list[CorpusRecord] = []
        skipped_unsearchable = 0
        skipped_empty = 0
        record_counts: Counter[str] = Counter()
        chunk_counts: Counter[str] = Counter()

        for record in records:
            if not record.searchable:
                skipped_unsearchable += 1
                continue
            if not record.text.strip():
                skipped_empty += 1
                continue
            record_chunks = chunk_corpus_record(
                record,
                chunk_size=self._chunk_size,
                chunk_overlap=self._chunk_overlap,
            )
            if not record_chunks:
                skipped_empty += 1
                continue
            indexed_records.append(record)
            record_counts[record.file_type] += 1
            chunk_counts[record.file_type] += len(record_chunks)
            chunks.extend(record_chunks)

        vectors = self._embeddings.embed_documents(
            [chunk.embedding_text for chunk in chunks]
        )
        if reset_collection:
            self._store.reset_collection()
        sync_report = self._store.sync_chunks(chunks, vectors)
        logical_documents = {
            (record.document_id, record.file_name, record.file_type)
            for record in indexed_records
        }
        return CorpusIndexReport(
            corpus_path=self._display_path(path, self._project_root),
            total_record_count=len(records),
            indexed_document_count=len(logical_documents),
            indexed_record_count=len(indexed_records),
            indexed_chunk_count=len(chunks),
            skipped_unsearchable_count=skipped_unsearchable,
            skipped_empty_text_count=skipped_empty,
            inserted_count=sync_report.inserted_count,
            updated_count=sync_report.updated_count,
            removed_stale_count=sync_report.removed_stale_count,
            indexed_records_by_file_type=dict(sorted(record_counts.items())),
            indexed_chunks_by_file_type=dict(sorted(chunk_counts.items())),
        )

    def rebuild_corpus(
        self,
        corpus_path: str | Path | None = None,
    ) -> CorpusIndexReport:
        return self.index_corpus(corpus_path, reset_collection=True)

    @staticmethod
    def _build_search_filter(
        *,
        department: str | None,
        document_type: str | None,
        file_type: str | None = None,
    ) -> dict[str, Any] | None:
        conditions: list[dict[str, Any]] = []
        if department is not None:
            normalized = department.strip()
            if not normalized:
                raise ValueError("department 필터는 비워 둘 수 없습니다.")
            conditions.append({"department": {"$eq": normalized}})
        if document_type is not None:
            normalized = document_type.strip()
            if not normalized:
                raise ValueError("document_type 필터는 비워 둘 수 없습니다.")
            conditions.append({"document_type": {"$eq": normalized}})
        if file_type is not None:
            normalized = file_type.strip()
            if not normalized:
                raise ValueError("file_type 필터는 비워 둘 수 없습니다.")
            conditions.append({"file_type": {"$eq": normalized}})
        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    @staticmethod
    def _normalized(value: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", value).casefold().split())

    def _deduplicate(
        self,
        candidates: list[DocumentVectorCandidate],
    ) -> list[DocumentVectorCandidate]:
        kept: list[DocumentVectorCandidate] = []
        source_texts: list[
            tuple[str, str, int | None, int | None, str]
        ] = []
        seen_ids: set[str] = set()
        seen_contents: set[str] = set()
        seen_courses: set[tuple[str, str]] = set()
        for candidate in candidates:
            normalized = self._normalized(candidate.content)
            course = (
                parse_course_info(candidate.content)
                if candidate.file_type == "csv"
                else None
            )
            course_key = (
                normalize_text(candidate.department),
                normalize_text(course.course_name).replace(" ", ""),
            ) if course is not None else None
            same_locator_similar = any(
                candidate.document_id == document_id
                and candidate.file_name == file_name
                and candidate.page_number == page_number
                and candidate.row_number == row_number
                and SequenceMatcher(None, normalized, previous).ratio()
                >= self._dedup_threshold
                for (
                    document_id,
                    file_name,
                    page_number,
                    row_number,
                    previous,
                ) in source_texts
            )
            if (
                candidate.chunk_id in seen_ids
                or normalized in seen_contents
                or (course_key is not None and course_key in seen_courses)
                or same_locator_similar
            ):
                continue
            kept.append(candidate)
            seen_ids.add(candidate.chunk_id)
            seen_contents.add(normalized)
            if course_key is not None:
                seen_courses.add(course_key)
            source_texts.append(
                (
                    candidate.document_id,
                    candidate.file_name,
                    candidate.page_number,
                    candidate.row_number,
                    normalized,
                )
            )
        return kept

    def _question_department(
        self,
        question: str,
        explicit_department: str | None,
    ) -> str | None:
        if explicit_department is not None:
            return explicit_department
        normalized_question = normalize_text(question)
        departments = sorted(
            self.available_departments(),
            key=lambda value: len(normalize_text(value)),
            reverse=True,
        )
        for department in departments:
            normalized_department = normalize_text(department)
            if (
                normalized_department
                and normalized_department != normalize_text("전체")
                and normalized_department in normalized_question
            ):
                return department
        return None

    @staticmethod
    def _course_candidates(
        candidates: list[DocumentVectorCandidate],
        *,
        question: str,
        intent: CourseQueryIntent,
        department: str | None = None,
    ) -> list[DocumentVectorCandidate]:
        parsed = [
            (candidate, parse_course_info(candidate.content))
            for candidate in candidates
            if candidate.file_type == "csv"
            and candidate.document_type == COURSE_DOCUMENT_TYPE
        ]
        parsed = [
            (candidate, course)
            for candidate, course in parsed
            if course is not None
        ]
        if department is not None:
            normalized_department = normalize_text(department)
            parsed = [
                (candidate, course)
                for candidate, course in parsed
                if normalize_text(candidate.department) == normalized_department
            ]
        if intent.grade is not None:
            parsed = [
                (candidate, course)
                for candidate, course in parsed
                if normalize_text(course.grade).removesuffix("학년")
                == str(intent.grade)
            ]
        if intent.semester is not None:
            parsed = [
                (candidate, course)
                for candidate, course in parsed
                if course.has_semester(intent.semester)
            ]
        if intent.completion_types:
            normalized_types = {
                normalize_text(value) for value in intent.completion_types
            }
            parsed = [
                (candidate, course)
                for candidate, course in parsed
                if normalize_text(course.completion_type) in normalized_types
            ]
        parsed.sort(
            key=lambda item: (
                lexical_overlap(question, item[0].content),
                item[0].is_current is True,
                item[0].source_year or "",
                item[0].score,
                -(item[0].row_number or 0),
            ),
            reverse=True,
        )
        return [candidate for candidate, _course in parsed]

    @staticmethod
    def _to_results(
        candidates: list[DocumentVectorCandidate],
        *,
        score_kind: Literal[
            "cosine_similarity", "structured_exact"
        ] = "cosine_similarity",
    ) -> list[DocumentSearchResult]:
        return [
            DocumentSearchResult(
                document_id=item.document_id,
                chunk_id=item.chunk_id,
                file_name=item.file_name,
                file_type=item.file_type,
                document_type=item.document_type,
                source_year=item.source_year,
                effective_from=item.effective_from,
                effective_to=item.effective_to,
                department=item.department,
                admission_year_from=item.admission_year_from,
                admission_year_to=item.admission_year_to,
                track=item.track,
                authority=item.authority,
                is_current=item.is_current,
                source_url=item.source_url,
                page_number=item.page_number,
                row_number=item.row_number,
                title=item.title,
                source_path=item.source_path,
                text=item.content,
                score=item.score,
                score_kind=score_kind,
                content_hash=item.content_hash,
                currentness_warning=(
                    OUTDATED_DOCUMENT_WARNING
                    if item.is_current is False
                    else None
                ),
            )
            for item in candidates
        ]

    def search_with_context(
        self,
        question: str,
        *,
        top_k: int | None = None,
        min_score: float | None = None,
        department: str | None = None,
        document_type: str | None = None,
    ) -> DocumentSearchResponse:
        question = question.strip()
        limit = self._top_k if top_k is None else top_k
        threshold = self._min_score if min_score is None else min_score
        if not question:
            raise ValueError("검색 질문은 비워 둘 수 없습니다.")
        if limit <= 0 or not 0 <= threshold <= 1:
            raise ValueError("top_k 또는 min_score가 올바르지 않습니다.")

        intent = parse_course_query(question)
        effective_department = (
            self._question_department(question, department)
            if intent.is_course_query
            else department
        )
        structured_query = (
            intent.has_structured_conditions
            and effective_department is not None
        )
        record_count = self.indexed_chunk_count
        if record_count == 0:
            return DocumentSearchResponse(
                structured_query=structured_query,
            )

        if structured_query:
            exact_candidates = self._store.list_candidates(
                where=self._build_search_filter(
                    department=effective_department,
                    document_type=COURSE_DOCUMENT_TYPE,
                    file_type="csv",
                )
            )
            exact_courses = self._deduplicate(
                self._course_candidates(
                    exact_candidates,
                    question=question,
                    intent=intent,
                    department=effective_department,
                )
            )
            if exact_courses:
                results = self._to_results(
                    exact_courses,
                    score_kind="structured_exact",
                )
                return DocumentSearchResponse(
                    results=results,
                    structured_query=True,
                    exact_match_count=len(results),
                    semantic_fallback_used=False,
                )

        candidates = self._store.query(
            self._embeddings.embed_query(question),
            fetch_k=record_count,
            where=self._build_search_filter(
                department=effective_department,
                document_type=document_type,
            ),
        )
        eligible = [
            candidate for candidate in candidates if candidate.score >= threshold
        ]

        if structured_query:
            selected = self._deduplicate(eligible)[:limit]
            return DocumentSearchResponse(
                results=self._to_results(selected),
                structured_query=True,
                semantic_fallback_used=True,
            )

        if (
            intent.is_course_query
            and not structured_query
            and document_type in {
                None,
                COURSE_DOCUMENT_TYPE,
            }
        ):
            course_candidates = self._deduplicate(
                self._course_candidates(
                    eligible,
                    question=question,
                    intent=intent,
                    department=effective_department,
                )
            )
            course_target = min(3, limit)
            if len(course_candidates) >= course_target:
                results = self._to_results(course_candidates[:limit])
                return DocumentSearchResponse(results=results)

            selected = list(course_candidates)
            selected_ids = {item.chunk_id for item in selected}
            supplemental = self._deduplicate(
                [
                    candidate
                    for candidate in eligible
                    if candidate.file_type in {"pdf", "txt"}
                    and candidate.chunk_id not in selected_ids
                ]
            )
            selected.extend(supplemental[: max(0, limit - len(selected))])
            selected = self._deduplicate(selected)
            return DocumentSearchResponse(
                results=self._to_results(selected[:limit])
            )

        selected = self._deduplicate(eligible)[:limit]
        return DocumentSearchResponse(
            results=self._to_results(selected),
        )

    def search(
        self,
        question: str,
        *,
        top_k: int | None = None,
        min_score: float | None = None,
        department: str | None = None,
        document_type: str | None = None,
    ) -> list[DocumentSearchResult]:
        """기존 호출자를 위해 검색 결과 목록만 반환한다."""

        return self.search_with_context(
            question,
            top_k=top_k,
            min_score=min_score,
            department=department,
            document_type=document_type,
        ).results
