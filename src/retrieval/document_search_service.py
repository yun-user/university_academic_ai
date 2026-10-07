"""documents.jsonl 기반 PDF·CSV·TXT 통합 색인과 검색 서비스."""

from __future__ import annotations

import json
import hashlib
import os
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError
from src.operations import locked_service
from src.retrieval.keyword_search import KeywordIndex, fuse
from src.retrieval.reviewed_rules import reviewed_rule_search
from src.retrieval.university_guide import GUIDE_DOCUMENT_TYPE, university_guide_search

from src.config import PROJECT_ROOT, Settings, get_settings
from src.retrieval.document_chunker import chunk_corpus_record
from src.retrieval.course_search import (
    COURSE_DOCUMENT_TYPE,
    CourseQueryIntent,
    lexical_overlap,
    normalize_text,
    parse_course_info,
    parse_course_query,
    requested_course_code,
    has_course_code,
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
from src.retrieval.query_intent import (
    QuestionIntent,
    academic_rule_relevance,
    academic_rule_signatures,
    classify_question_intent,
    is_graduation_question,
)


DEFAULT_DOCUMENT_COLLECTION_NAME = "academic_corpus_chunks_v1"
DEFAULT_CORPUS_RELATIVE_PATH = Path("data/processed/documents.jsonl")


def _one_character_typo(left: str, right: str) -> bool:
    """Accept one insertion, deletion, or substitution, not broad similarity."""
    if min(len(left), len(right)) < 6 or abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) == 1
    short, long = sorted((left, right), key=len)
    return any(long[:i] + long[i + 1:] == short for i in range(len(long)))


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
        search_mode: str = "dense",
        dense_top_k: int = 40,
        keyword_top_k: int = 40,
        rrf_k: int = 60,
        dense_weight: float = .55,
        keyword_weight: float = .45,
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
        if search_mode not in {"dense", "hybrid"}:
            raise ValueError("SEARCH_MODE는 dense 또는 hybrid여야 합니다.")
        self._search_mode = search_mode
        self._dense_top_k, self._keyword_top_k = dense_top_k, keyword_top_k
        self._rrf_k, self._dense_weight, self._keyword_weight = rrf_k, dense_weight, keyword_weight

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
            search_mode=os.getenv("SEARCH_MODE", "hybrid"),
            dense_top_k=settings.dense_top_k,
            keyword_top_k=settings.keyword_top_k,
            rrf_k=settings.rrf_k,
            dense_weight=settings.dense_weight,
            keyword_weight=settings.keyword_weight,
        )

    @property
    def indexed_chunk_count(self) -> int:
        return self._store.count()

    @property
    def corpus_path(self) -> Path:
        return self._corpus_path

    def available_departments(self) -> list[str]:
        departments = self._store.list_metadata_values("department")
        # 검토 규정 번들은 색인 없이도 답하므로 그 학과도 선택지에 포함한다.
        try:
            reviewed = json.loads((self._project_root / "config/reviewed_rules/hongik.json")
                                  .read_text(encoding="utf-8"))["department"]
        except (OSError, ValueError, KeyError, TypeError):
            return departments
        return departments if reviewed in departments else sorted({*departments, reviewed})

    def available_document_types(self) -> list[str]:
        types = set(self._store.list_metadata_values("document_type"))
        if (self._project_root / "config/reviewed_rules/hongik.json").is_file():
            types.add("검토된 학사규정")
        if (self._project_root / "config/reviewed_rules/hongik_academic_guide.json").is_file():
            types.add(GUIDE_DOCUMENT_TYPE)
        return sorted(types)

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

    @locked_service
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
        sync_report = self._store.sync_chunks(chunks, vectors, reset_collection=reset_collection)
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
        include_global_department: bool = False,
    ) -> dict[str, Any] | None:
        conditions: list[dict[str, Any]] = []
        if department is not None:
            normalized = department.strip()
            if not normalized:
                raise ValueError("department 필터는 비워 둘 수 없습니다.")
            if include_global_department and normalize_text(normalized) != normalize_text(
                "전체"
            ):
                conditions.append(
                    {"department": {"$in": [normalized, "전체"]}}
                )
            else:
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
        seen_contents: set[tuple] = set()
        seen_courses: set[tuple] = set()
        for candidate in candidates:
            normalized = self._normalized(candidate.content)
            course = (
                parse_course_info(candidate.content)
                if candidate.file_type == "csv"
                else None
            )
            scope = (candidate.department, candidate.document_type, candidate.source_year,
                     candidate.track, candidate.admission_year_from, candidate.admission_year_to)
            content_key = (*scope, normalized)
            # A shared name is not a duplicate: credits/codes can differ by
            # curriculum version. Preserve each distinct value and scope.
            course_key = (*scope, normalize_text(course.course_name).replace(" ", ""),
                          course.grade, course.completion_type, course.semesters) if course is not None else None
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
                or content_key in seen_contents
                or (course_key is not None and course_key in seen_courses)
                or (course is None and same_locator_similar)
            ):
                continue
            kept.append(candidate)
            seen_ids.add(candidate.chunk_id)
            seen_contents.add(content_key)
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
        normalized_question = re.sub(r"\s+", "", normalize_text(question))
        departments = sorted(
            self.available_departments(),
            key=lambda value: len(normalize_text(value)),
            reverse=True,
        )
        for department in departments:
            normalized_department = re.sub(r"\s+", "", normalize_text(department))
            if (
                normalized_department
                and normalized_department != normalize_text("전체")
                and normalized_department in normalized_question
            ):
                return department
        # An unindexed department must not silently widen the search to all
        # departments. Keep its name as an exact filter, yielding no evidence.
        unknown = re.search(r"([가-힣A-Za-z][가-힣A-Za-z0-9·]*(?:학과|학부))", question)
        if unknown:
            name = unknown.group(1)
            normalized_name = normalize_text(name)
            matches = [d for d in departments if d.endswith(name[-2:])
                       and _one_character_typo(normalized_name,
                           re.sub(r"\s+", "", normalize_text(d)))]
            # Never pick arbitrarily between similarly named departments.
            return matches[0] if len(matches) == 1 else name
        return explicit_department if explicit_department != "전체" else None

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

    def _hybrid_order(self, question, candidates, threshold):
        dense = [c for c in candidates if c.score >= threshold]
        if self._search_mode == "dense":
            return dense
        index = KeywordIndex(self._store.list_candidates(),
                             self._project_root / "data/keyword_index/tokens.json")
        by_id = {c.chunk_id: c for c in candidates}
        lexical = index.search(question, set(by_id), self._keyword_top_k)
        if not any(coverage >= .5 for _, _, coverage in lexical):
            return []
        # Exact identifier/term retrieval can recover low-cosine results; weak
        # single-token matches in long questions cannot bypass the evidence gate.
        lexical_ids = [key for key, score, coverage in lexical
                       if coverage >= .5 or by_id[key].score >= threshold]
        ranking = fuse([c.chunk_id for c in dense[:self._dense_top_k]], lexical_ids,
                       k=self._rrf_k, dense_weight=self._dense_weight,
                       keyword_weight=self._keyword_weight)
        return [by_id[key] for key in ranking]

    @locked_service
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

        question_intent = classify_question_intent(question)
        guide = university_guide_search(question, self._project_root, document_type)
        if guide is not None:
            return guide
        course_intent = parse_course_query(question)
        effective_department = self._question_department(question, department)
        if is_graduation_question(question) and effective_department is None:
            scoped_departments = [d for d in self.available_departments() if d != "전체"]
            if len(scoped_departments) == 1:
                effective_department = scoped_departments[0]
            else:
                return DocumentSearchResponse(question_intent=question_intent,
                    clarification_message="졸업요건은 학과마다 다릅니다. 학과를 선택하거나 질문에 학과명을 적어 주세요.")
        reviewed = reviewed_rule_search(question, effective_department, self._project_root, document_type)
        if reviewed is not None:
            return reviewed
        structured_query = (
            question_intent is QuestionIntent.COURSE_LIST
            and course_intent.has_structured_conditions
            and effective_department is not None
            and document_type in {None, COURSE_DOCUMENT_TYPE}
        )
        record_count = self.indexed_chunk_count
        if record_count == 0:
            return DocumentSearchResponse(
                question_intent=question_intent,
                structured_query=structured_query,
            )

        # Private records are not part of the public academic corpus.
        if re.search(r"(개인|다른\s*학생).*(비밀번호|성적표|계좌|잔액)", question):
            return DocumentSearchResponse(question_intent=question_intent)

        # Course identifiers and complete course names are exact lookups, never
        # truncated dense results. Keep metadata filters before this lookup.
        if question_intent is not QuestionIntent.ACADEMIC_RULE and document_type in {None, COURSE_DOCUMENT_TYPE}:
            code = requested_course_code(question)
            normalized_question = normalize_text(question)
            exact_named = []
            short_named = []
            short_match = re.search(r"([가-힣A-Za-z0-9·]{3,})\s*(?:교과목|과목)(?:은|는|이|가)?\s*(?:몇|학점)", question)
            for candidate in self._store.list_candidates(where=self._build_search_filter(
                    department=effective_department, document_type=COURSE_DOCUMENT_TYPE, file_type="csv")):
                course = parse_course_info(candidate.content)
                if course is None:
                    continue
                if short_match and not code:
                    short_name = normalize_text(short_match.group(1))
                    full_name = normalize_text(course.course_name)
                    if full_name.startswith(short_name + " "):
                        short_named.append(candidate)
                if code:
                    matches = any(has_course_code(item, code) for item in course.semesters)
                else:
                    name = normalize_text(course.course_name)
                    matches = bool(name and name in normalized_question and (
                        normalized_question == name or re.search("교과목|과목|학점|학기", question)))
                if matches:
                    exact_named.append(candidate)
            if not exact_named and short_named:
                names = {normalize_text(parse_course_info(c.content).course_name) for c in short_named}
                if len(names) == 1:
                    exact_named = short_named
                else:
                    return DocumentSearchResponse(question_intent=QuestionIntent.COURSE_LIST,
                        clarification_message="해당 이름으로 시작하는 과목이 여러 개입니다. 정식 과목명이나 학수번호를 알려 주세요.")
            if exact_named:
                exact_named = self._course_candidates(exact_named, question=question,
                    intent=course_intent, department=effective_department)
                if code and course_intent.semester is not None:
                    exact_named = [candidate for candidate in exact_named if any(
                        item.semester == course_intent.semester and has_course_code(item, code)
                        for item in parse_course_info(candidate.content).semesters)]
                if not exact_named:
                    return DocumentSearchResponse(question_intent=QuestionIntent.COURSE_LIST,
                        structured_query=True, clarification_message=
                        "해당 과목은 등록되어 있지만 질문의 학년·학기·이수구분과 일치하지 않습니다. 적용 조건을 확인해 주세요.")
                exact_named = self._deduplicate(exact_named)
                return DocumentSearchResponse(results=self._to_results(exact_named, score_kind="structured_exact"),
                    question_intent=QuestionIntent.COURSE_LIST, structured_query=True,
                    exact_match_count=len(exact_named))
            if code:
                return DocumentSearchResponse(question_intent=QuestionIntent.COURSE_LIST,
                                              structured_query=True)

        if question_intent is QuestionIntent.ACADEMIC_RULE:
            rule_filter = self._build_search_filter(
                department=effective_department,
                document_type=document_type,
                # '전체' can contain rules for another department, rather than
                # universally applicable rules. Never widen a scoped query.
                include_global_department=False,
            )
            page_context_candidates = self._store.list_candidates(
                where=rule_filter,
            )
            # Graduation tables are page-level evidence. Keep the table body
            # with its heading instead of ranking isolated heading chunks.
            if is_graduation_question(question):
                try:
                    records = self._load_records(self._corpus_path)
                except CorpusLoadError:
                    records = []
                tables = {(r.document_id, r.page_number): r for r in records
                    if r.searchable and r.file_type == "pdf"
                    and re.search(r"<표\s*\d+>[^\n]*졸업\s*요건", r.text)
                    and re.search(r"총\s*\d+\s*학점", r.text)}
                expanded, seen_pages = [], set()
                for candidate in page_context_candidates:
                    key = (candidate.document_id, candidate.page_number)
                    if key in tables:
                        if key in seen_pages:
                            continue
                        seen_pages.add(key)
                        full_text = tables[key].text
                        candidate = candidate.model_copy(update={"content": full_text,
                            "content_hash": hashlib.sha256(full_text.encode()).hexdigest()})
                    expanded.append(candidate)
                page_context_candidates = expanded
            semantic_candidates = self._store.query(
                self._embeddings.embed_query(question),
                fetch_k=record_count,
                where=rule_filter,
            )
            semantic_by_id = {
                candidate.chunk_id: candidate
                for candidate in semantic_candidates
            }
            # 학사 규정은 강한 lexical 조건을 모두 만족해야 하므로 semantic
            # top-k 누락 때문에 직접 규정이 사라지지 않게 PDF 후보 전체를
            # 판정한다. cosine 점수는 동률 정렬과 화면 표시 용도로만 보존한다.
            rule_candidates = [
                candidate.model_copy(
                    update={
                        "distance": (
                            semantic_by_id[candidate.chunk_id].distance
                            if candidate.chunk_id in semantic_by_id
                            else 1.0
                        ),
                        "score": (
                            semantic_by_id[candidate.chunk_id].score
                            if candidate.chunk_id in semantic_by_id
                            else 0.0
                        ),
                    }
                )
                for candidate in page_context_candidates
            ]
            directly_relevant = [
                (candidate, academic_rule_relevance(question, candidate.content))
                for candidate in rule_candidates
                if candidate.file_type == "pdf" or (
                    candidate.file_type == "txt" and candidate.document_type == "공개공지"
                    and (candidate.source_url or "").startswith("https://"))
            ]
            directly_relevant = [
                (candidate, relevance)
                for candidate, relevance in directly_relevant
                if relevance >= 0
            ]
            directly_relevant.sort(
                key=lambda item: (
                    bool(is_graduation_question(question)
                         and re.search(r"<표\s*\d+>[^\n]*졸업\s*요건", item[0].content)
                         and re.search(r"총\s*\d+\s*학점", item[0].content)),
                    item[1],
                    item[0].is_current is True,
                    item[0].source_year or "",
                    item[0].score,
                ),
                reverse=True,
            )
            rule_pool = self._deduplicate(
                [candidate for candidate, _relevance in directly_relevant]
            )
            selected_rules: list[DocumentVectorCandidate] = []
            seen_rule_blocks: set[
                tuple[str, int | None, frozenset[str]]
            ] = set()
            for candidate in rule_pool:
                signatures = academic_rule_signatures(candidate.content)
                block_key = (
                    candidate.document_id,
                    candidate.page_number,
                    signatures,
                )
                if signatures and block_key in seen_rule_blocks:
                    continue
                seen_rule_blocks.add(block_key)
                selected_rules.append(candidate)
                if len(selected_rules) == limit:
                    break
            page_contexts: dict[
                tuple[str, str, int | None],
                list[str],
            ] = {}
            for candidate in page_context_candidates:
                page_key = (
                    candidate.document_id,
                    candidate.file_name,
                    candidate.page_number,
                )
                page_contexts.setdefault(page_key, [])
                if candidate.content not in page_contexts[page_key]:
                    page_contexts[page_key].append(candidate.content)
            # 원본 corpus가 있으면 청크 순서가 보존된 동일 페이지 원문을 쓴다.
            # 색인만 배포된 환경에서는 위의 후보 청크 문맥으로 안전하게
            # fallback한다.
            try:
                corpus_records = self._load_records(self._corpus_path)
            except CorpusLoadError:
                corpus_records = []
            selected_page_keys = {
                (
                    candidate.document_id,
                    candidate.file_name,
                    candidate.page_number,
                )
                for candidate in selected_rules
            }
            for record in corpus_records:
                page_key = (
                    record.document_id,
                    record.file_name,
                    record.page_number,
                )
                if (
                    record.file_type == "pdf"
                    and page_key in selected_page_keys
                    and record.text.strip()
                ):
                    page_contexts[page_key] = [record.text]
            results = self._to_results(selected_rules)
            results = [
                result.model_copy(
                    update={
                        "context_text": "\n\n".join(
                            page_contexts.get(
                                (
                                    result.document_id,
                                    result.file_name,
                                    result.page_number,
                                ),
                                [result.text],
                            )
                        )
                    }
                )
                for result in results
            ]
            return DocumentSearchResponse(
                results=results,
                question_intent=question_intent,
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
                    intent=course_intent,
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
                    question_intent=question_intent,
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
        eligible = self._hybrid_order(question, candidates, threshold)

        if structured_query:
            selected = self._deduplicate(eligible)[:limit]
            return DocumentSearchResponse(
                results=self._to_results(selected),
                question_intent=question_intent,
                structured_query=True,
                semantic_fallback_used=True,
            )

        if (
            question_intent is QuestionIntent.COURSE_LIST
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
                    intent=course_intent,
                    department=effective_department,
                )
            )
            course_target = min(3, limit)
            if len(course_candidates) >= course_target:
                results = self._to_results(course_candidates[:limit])
                return DocumentSearchResponse(
                    results=results,
                    question_intent=question_intent,
                )

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
                results=self._to_results(selected[:limit]),
                question_intent=question_intent,
            )

        selected = self._deduplicate(eligible)[:limit]
        return DocumentSearchResponse(
            results=self._to_results(selected),
            question_intent=question_intent,
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
