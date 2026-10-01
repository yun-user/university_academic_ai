"""documents.jsonl부터 실제 ChromaDB 검색까지의 통합 회귀 테스트."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from pathlib import Path

import pytest

from src.retrieval.document_models import OUTDATED_DOCUMENT_WARNING
from src.retrieval.document_search_service import DocumentSearchService
from src.retrieval.document_vector_store import ChromaDocumentVectorStore


_OPEN_SERVICES: list[DocumentSearchService] = []


@pytest.fixture(autouse=True)
def _close_services():
    yield
    for service in reversed(_OPEN_SERVICES):
        service.close()
    _OPEN_SERVICES.clear()


class CorpusKeywordEmbeddingProvider:
    fingerprint = hashlib.sha256(b"corpus-keyword-embedding-v1").hexdigest()
    _groups = (
        ("장학금", "장학"),
        ("졸업", "전공학점"),
        ("교과목", "학수번호", "과목", "학년", "학기", "전공"),
        ("학교", "홍익대학교"),
        ("휴학",),
    )

    @classmethod
    def _vector(cls, text: str) -> list[float]:
        values = [
            float(any(token in text for token in group))
            for group in cls._groups
        ]
        values.append(0.0)
        if not any(values):
            values[-1] = 1.0
        norm = math.sqrt(sum(value * value for value in values))
        return [value / norm for value in values]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


def _record(
    *,
    document_id: str,
    file_name: str,
    file_type: str,
    document_type: str,
    text: str,
    page_number: int | None = None,
    row_number: int | None = None,
    department: str = "소프트웨어융합학과",
    source_year: str = "2026",
    is_current: bool | None = True,
    searchable: bool = True,
) -> dict[str, object]:
    source_path = f"data/raw/{file_type}/{file_name}"
    return {
        "document_id": document_id,
        "file_name": file_name,
        "file_type": file_type,
        "document_type": document_type,
        "source_year": source_year,
        "effective_from": source_year,
        "effective_to": None,
        "department": department,
        "admission_year_from": None,
        "admission_year_to": None,
        "track": "전체",
        "authority": "홍익대학교",
        "is_current": is_current,
        "source_url": None,
        "page_number": page_number,
        "row_number": row_number,
        "title": Path(file_name).stem,
        "text": text,
        "metadata": {
            "source_path": source_path,
            "source_file_hash": hashlib.sha256(
                file_name.encode("utf-8")
            ).hexdigest(),
        },
        "image_only": False,
        "document_image_only": False,
        "page_status": "text" if file_type == "pdf" else None,
        "searchable": searchable,
    }


def _write_corpus(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")


def _course_text(
    name: str,
    *,
    grade: int,
    completion_type: str,
    first_code: str = "",
    second_code: str = "",
    credits: str = "3",
    hours: str = "3",
) -> str:
    required = "Y" if completion_type == "전공필수" else "N"
    elective = "Y" if completion_type == "전공선택" else "N"
    return "\n".join(
        (
            f"학년: {grade}",
            f"이수구분: {completion_type}",
            f"교과목명: {name}",
            f"1학기_학수번호: {first_code}",
            f"1학기_학점: {credits if first_code else ''}",
            f"1학기_시수: {hours if first_code else ''}",
            f"2학기_학수번호: {second_code}",
            f"2학기_학점: {credits if second_code else ''}",
            f"2학기_시수: {hours if second_code else ''}",
            f"전공필수여부: {required}",
            f"전공선택여부: {elective}",
        )
    )


def _service(
    tmp_path: Path,
    *,
    collection_name: str = "document_search_test",
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> DocumentSearchService:
    provider = CorpusKeywordEmbeddingProvider()
    store = ChromaDocumentVectorStore(
        persist_directory=tmp_path / "data/vector_db",
        collection_name=collection_name,
        embedding_fingerprint=provider.fingerprint,
    )
    service = DocumentSearchService(
        embedding_provider=provider,
        vector_store=store,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        top_k=5,
        min_retrieval_score=0.1,
        dedup_similarity_threshold=0.95,
        project_root=tmp_path,
        corpus_path=tmp_path / "data/processed/documents.jsonl",
    )
    _OPEN_SERVICES.append(service)
    return service


def test_release_exact_identifier_ignores_dense_rank_and_respects_department(tmp_path):
    service = _service(tmp_path)
    records = [_record(document_id=f"course-{i}", file_name=f"{i}.csv", file_type="csv",
        document_type="학년별교과과정", department=department, row_number=1,
        text=_course_text("자료구조", grade=2, completion_type="전공필수", first_code="001234"))
        for i, department in enumerate(["학과A", "학과B"])]
    _write_corpus(service.corpus_path, records)
    service.index_corpus()
    response = service.search_with_context("학수번호 001234 교과목 정보", department="학과A", top_k=1)
    assert response.exact_match_count == 1
    assert response.results[0].department == "학과A"
    assert response.results[0].score_kind == "structured_exact"
    assert not service.search("학수번호 009999 교과목 정보")


def test_structured_course_query_respects_document_type(tmp_path):
    service = _service(tmp_path)
    _write_corpus(service.corpus_path, [_record(document_id="course", file_name="courses.csv",
        file_type="csv", document_type="학년별교과과정", row_number=1,
        text=_course_text("자료구조", grade=2, completion_type="전공필수", first_code="001234"))])
    service.index_corpus()
    response = service.search_with_context("소프트웨어융합학과 2학년 1학기 전공필수 과목",
                                           document_type="장학안내")
    assert response.results == []


@pytest.mark.parametrize("same_filename", [False, True])
def test_conflicting_course_versions_are_not_silently_deduplicated(tmp_path, same_filename):
    from src.answering.answer_service import AnswerService
    service = _service(tmp_path)
    _write_corpus(service.corpus_path, [_record(document_id=f"course-{i}", file_name="courses.csv" if same_filename else f"courses-{i}.csv",
        file_type="csv", document_type="학년별교과과정", row_number=1, source_year=str(2025 + i),
        text=_course_text("자료구조", grade=2, completion_type="전공필수", first_code="001234", credits=str(3+i)))
        for i in range(2)])
    service.index_corpus()
    answer = AnswerService(service).answer_question("자료구조 과목 학점")
    assert len(answer.sources) == 2
    assert "자료별 교과목 정보가 다릅니다" in answer.text
    assert "2025" in answer.text and "2026" in answer.text


def test_vector_sync_batches_upsert_and_stale_delete(tmp_path, monkeypatch):
    service = _service(tmp_path)
    client, collection = service._store._client, service._store._collection
    monkeypatch.setattr(type(client), "get_max_batch_size", lambda self: 2)
    original_upsert, original_delete = type(collection).upsert, type(collection).delete
    def bounded_upsert(self, **kwargs):
        assert len(kwargs["ids"]) <= 2, "backend batch limit exceeded"
        return original_upsert(self, **kwargs)
    def bounded_delete(self, **kwargs):
        assert len(kwargs["ids"]) <= 2, "backend batch limit exceeded"
        return original_delete(self, **kwargs)
    monkeypatch.setattr(type(collection), "upsert", bounded_upsert)
    monkeypatch.setattr(type(collection), "delete", bounded_delete)
    records = [_record(document_id=f"d{i}", file_name=f"{i}.txt", file_type="txt",
                       document_type="안내", text=f"등록 안내 자료 {i}") for i in range(5)]
    _write_corpus(service.corpus_path, records)
    assert service.index_corpus().indexed_chunk_count == 5
    _write_corpus(service.corpus_path, records[:1])
    assert service.index_corpus().removed_stale_count == 4
    assert service.indexed_chunk_count == 1


def test_short_course_name_requires_unique_registered_prefix(tmp_path):
    from src.answering.answer_service import AnswerService
    service = _service(tmp_path)
    def course(i, name):
        return _record(document_id=f"course-{i}", file_name=f"{i}.csv", file_type="csv",
            document_type="학년별교과과정", row_number=1,
            text=_course_text(name, grade=2, completion_type="전공필수", first_code=str(704818 + i)))
    records = [course(0, "자료구조 및 프로그래밍 실습")]
    _write_corpus(service.corpus_path, records)
    service.index_corpus()
    response = service.search_with_context("자료구조 과목은 몇 학점이야?")
    assert response.exact_match_count == 1
    assert response.results[0].file_type == "csv"
    assert "자료구조 및 프로그래밍 실습" in AnswerService.compose_answer("자료구조 과목은 몇 학점이야?", response).text
    records.append(course(1, "자료구조 심화 실습"))
    _write_corpus(service.corpus_path, records)
    service.index_corpus()
    response = service.search_with_context("자료구조 과목은 몇 학점이야?")
    assert not response.results
    assert "여러 개" in AnswerService.compose_answer("자료구조 과목은 몇 학점이야?", response).text


def test_release_hybrid_retrieves_keyword_then_removes_disabled_chunk(tmp_path):
    service = _service(tmp_path)
    service._search_mode = "hybrid"
    records = [_record(document_id="special", file_name="notice.txt", file_type="txt",
                       document_type="안내", text="특별한 우주항공연구 신청 안내")]
    _write_corpus(service.corpus_path, records)
    service.index_corpus()
    assert service.search("우주항공연구")
    _write_corpus(service.corpus_path, [])
    service.index_corpus()
    assert not service.search("우주항공연구")


def test_release_official_web_rule_keeps_url_and_excludes_unofficial_seed(tmp_path):
    from src.answering.answer_service import AnswerService
    service = _service(tmp_path)
    rows = [_record(document_id="web", file_name="notice.txt", file_type="txt",
                    document_type="공개공지", text="장학금 선발 기준은 직전 학기 성적을 기준으로 선정합니다.")]
    rows[0]["source_url"] = "https://school.example/scholarship"
    _write_corpus(service.corpus_path, rows)
    service.index_corpus()
    answer = AnswerService(service).answer_question("장학금 선발 기준")
    assert answer.sources[0].source_url == rows[0]["source_url"]
    assert answer.sources[0].page_number is None


def test_indexes_and_searches_pdf_csv_and_txt_with_source_metadata(
    tmp_path: Path,
) -> None:
    corpus_path = tmp_path / "data/processed/documents.jsonl"
    _write_corpus(
        corpus_path,
        [
            _record(
                document_id="GRAD-REQ",
                file_name="졸업요건.pdf",
                file_type="pdf",
                document_type="졸업요건",
                text="졸업을 위해 전공학점을 이수해야 합니다.",
                page_number=7,
            ),
            _record(
                document_id="COURSE-TABLE",
                file_name="교과과정.csv",
                file_type="csv",
                document_type="학년별교과과정",
                text="학수번호: 001012\n교과목명: 창의적공학설계입문",
                row_number=3,
            ),
            _record(
                document_id="SCHOOL-INFO",
                file_name="학교정보.txt",
                file_type="txt",
                document_type="학교기본정보",
                text="학교명: 홍익대학교",
            ),
            _record(
                document_id="SKIP-FLAG",
                file_name="제외.pdf",
                file_type="pdf",
                document_type="휴학안내",
                text="휴학 신청 기준",
                page_number=1,
                searchable=False,
            ),
            _record(
                document_id="SKIP-EMPTY",
                file_name="빈문서.txt",
                file_type="txt",
                document_type="빈문서",
                text="   ",
                searchable=True,
            ),
        ],
    )
    service = _service(tmp_path)

    report = service.index_corpus()
    pdf_result = service.search("졸업 전공학점", top_k=1)[0]
    csv_result = service.search("교과목 학수번호", top_k=1)[0]
    txt_result = service.search("홍익대학교 학교", top_k=1)[0]

    assert report.total_record_count == 5
    assert report.indexed_document_count == 3
    assert report.indexed_record_count == 3
    assert report.indexed_chunk_count == 3
    assert report.skipped_unsearchable_count == 1
    assert report.skipped_empty_text_count == 1
    assert report.indexed_records_by_file_type == {
        "csv": 1,
        "pdf": 1,
        "txt": 1,
    }
    assert service.indexed_chunk_count == 3

    assert pdf_result.document_id == "GRAD-REQ"
    assert pdf_result.file_type == "pdf"
    assert pdf_result.document_type == "졸업요건"
    assert pdf_result.department == "소프트웨어융합학과"
    assert pdf_result.page_number == 7
    assert pdf_result.row_number is None

    assert csv_result.document_id == "COURSE-TABLE"
    assert csv_result.file_type == "csv"
    assert csv_result.document_type == "학년별교과과정"
    assert csv_result.page_number is None
    assert csv_result.row_number == 3
    assert "001012" in csv_result.text

    assert txt_result.file_type == "txt"
    assert txt_result.file_name == "학교정보.txt"
    assert txt_result.document_type == "학교기본정보"
    assert txt_result.page_number is None
    assert txt_result.row_number is None
    assert service.search("휴학 신청") == []


def test_same_corpus_reindex_is_idempotent(tmp_path: Path) -> None:
    corpus_path = tmp_path / "data/processed/documents.jsonl"
    records = [
        _record(
            document_id="PDF",
            file_name="pages.pdf",
            file_type="pdf",
            document_type="학사규정",
            text="장학금 첫 페이지",
            page_number=1,
        ),
        _record(
            document_id="PDF",
            file_name="pages.pdf",
            file_type="pdf",
            document_type="학사규정",
            text="장학금 둘째 페이지",
            page_number=2,
        ),
        _record(
            document_id="CSV",
            file_name="rows.csv",
            file_type="csv",
            document_type="교과과정",
            text="교과목 첫 행",
            row_number=1,
        ),
        _record(
            document_id="CSV",
            file_name="rows.csv",
            file_type="csv",
            document_type="교과과정",
            text="교과목 둘째 행",
            row_number=2,
        ),
    ]
    _write_corpus(corpus_path, records)
    service = _service(tmp_path)

    first = service.index_corpus()
    first_count = service.indexed_chunk_count
    second = service.index_corpus()

    assert first.inserted_count == 4
    assert second.inserted_count == 0
    assert second.updated_count == 4
    assert service.indexed_chunk_count == first_count == 4


def test_reindex_removes_record_that_became_unsearchable(
    tmp_path: Path,
) -> None:
    corpus_path = tmp_path / "data/processed/documents.jsonl"
    record = _record(
        document_id="LEAVE",
        file_name="휴학.pdf",
        file_type="pdf",
        document_type="휴학안내",
        text="휴학 신청 기간",
        page_number=1,
    )
    _write_corpus(corpus_path, [record])
    service = _service(tmp_path)
    service.index_corpus()

    record["searchable"] = False
    _write_corpus(corpus_path, [record])
    report = service.index_corpus()

    assert report.removed_stale_count == 1
    assert service.indexed_chunk_count == 0
    assert service.search("휴학 신청") == []


def test_department_and_business_document_type_filters_are_preserved(
    tmp_path: Path,
) -> None:
    corpus_path = tmp_path / "data/processed/documents.jsonl"
    _write_corpus(
        corpus_path,
        [
            _record(
                document_id="A",
                file_name="a.pdf",
                file_type="pdf",
                document_type="장학금선정기준",
                text="장학금 선발 기준",
                page_number=1,
                department="학과 A",
            ),
            _record(
                document_id="B",
                file_name="b.csv",
                file_type="csv",
                document_type="학년별교과과정",
                text="장학금 관련 교과목",
                row_number=2,
                department="학과 B",
            ),
        ],
    )
    service = _service(tmp_path)
    service.index_corpus()

    results = service.search(
        "장학금",
        department="학과 B",
        document_type="학년별교과과정",
    )

    assert len(results) == 1
    assert results[0].department == "학과 B"
    assert results[0].document_type == "학년별교과과정"
    assert service.available_departments() == ["학과 A", "학과 B"]
    assert service.available_document_types() == [
        "장학금선정기준",
        "학년별교과과정",
    ]


def test_non_current_document_has_standard_warning(tmp_path: Path) -> None:
    corpus_path = tmp_path / "data/processed/documents.jsonl"
    _write_corpus(
        corpus_path,
        [
            _record(
                document_id="OLD",
                file_name="2024_장학금.pdf",
                file_type="pdf",
                document_type="장학금선정기준",
                text="장학금 선발 기준",
                page_number=2,
                source_year="2024",
                is_current=False,
            )
        ],
    )
    service = _service(tmp_path)
    service.index_corpus()

    result = service.search("장학금 선발", top_k=1)[0]

    assert result.is_current is False
    assert result.source_year == "2024"
    assert result.currentness_warning == OUTDATED_DOCUMENT_WARNING


def test_long_record_uses_existing_chunker_and_stays_idempotent(
    tmp_path: Path,
) -> None:
    corpus_path = tmp_path / "data/processed/documents.jsonl"
    _write_corpus(
        corpus_path,
        [
            _record(
                document_id="LONG-TXT",
                file_name="긴문서.txt",
                file_type="txt",
                document_type="학교기본정보",
                text=("학교 안내 문장입니다. " * 20),
            )
        ],
    )
    service = _service(tmp_path, chunk_size=40, chunk_overlap=5)

    first = service.index_corpus()
    second = service.index_corpus()

    assert first.indexed_chunk_count > 1
    assert second.indexed_chunk_count == first.indexed_chunk_count
    assert service.indexed_chunk_count == first.indexed_chunk_count


def test_persistent_integrated_index_can_be_reopened(tmp_path: Path) -> None:
    corpus_path = tmp_path / "data/processed/documents.jsonl"
    _write_corpus(
        corpus_path,
        [
            _record(
                document_id="PERSIST",
                file_name="교과과정.csv",
                file_type="csv",
                document_type="학년별교과과정",
                text="교과목명: 종합설계(1)",
                row_number=48,
            )
        ],
    )
    first = _service(tmp_path, collection_name="persistent_corpus")
    first.index_corpus()
    first.close()

    reopened = _service(tmp_path, collection_name="persistent_corpus")
    result = reopened.search("교과목 종합설계", top_k=1)[0]

    assert reopened.indexed_chunk_count == 1
    assert result.row_number == 48
    assert result.file_type == "csv"


def test_rebuild_resets_only_integrated_collection(tmp_path: Path) -> None:
    corpus_path = tmp_path / "data/processed/documents.jsonl"
    _write_corpus(
        corpus_path,
        [
            _record(
                document_id="RESET",
                file_name="학교정보.txt",
                file_type="txt",
                document_type="학교기본정보",
                text="학교명: 홍익대학교",
            )
        ],
    )
    service = _service(tmp_path)
    first = service.index_corpus()
    rebuilt = service.rebuild_corpus()

    assert first.inserted_count == 1
    assert rebuilt.inserted_count == 1
    assert rebuilt.updated_count == 0
    assert service.indexed_chunk_count == 1


def test_first_year_question_prioritizes_first_year_csv_rows(
    tmp_path: Path,
) -> None:
    corpus_path = tmp_path / "data/processed/documents.jsonl"
    records = [
        _record(
            document_id="COURSES",
            file_name="courses.csv",
            file_type="csv",
            document_type="학년별교과과정",
            text=_course_text(
                f"1학년과목{index}",
                grade=1,
                completion_type="전공선택",
                first_code=f"00100{index}",
            ),
            row_number=index,
        )
        for index in range(1, 4)
    ]
    records.append(
        _record(
            document_id="COURSES",
            file_name="courses.csv",
            file_type="csv",
            document_type="학년별교과과정",
            text=_course_text(
                "2학년과목",
                grade=2,
                completion_type="전공필수",
                first_code="002001",
            ),
            row_number=4,
        )
    )
    _write_corpus(corpus_path, records)
    service = _service(tmp_path)
    service.index_corpus()

    results = service.search("소프트웨어융합학과 1학년 과목", top_k=3)

    assert len(results) == 3
    assert all(result.file_type == "csv" for result in results)
    assert all("학년: 1" in result.text for result in results)


def test_second_semester_question_prioritizes_second_semester_row(
    tmp_path: Path,
) -> None:
    corpus_path = tmp_path / "data/processed/documents.jsonl"
    _write_corpus(
        corpus_path,
        [
            _record(
                document_id="COURSES",
                file_name="courses.csv",
                file_type="csv",
                document_type="학년별교과과정",
                text=_course_text(
                    "1학기과목",
                    grade=1,
                    completion_type="전공선택",
                    first_code="001001",
                ),
                row_number=1,
            ),
            _record(
                document_id="COURSES",
                file_name="courses.csv",
                file_type="csv",
                document_type="학년별교과과정",
                text=_course_text(
                    "2학기과목",
                    grade=1,
                    completion_type="전공선택",
                    second_code="001002",
                ),
                row_number=2,
            ),
        ],
    )
    service = _service(tmp_path)
    service.index_corpus()

    result = service.search("1학년 2학기 과목", top_k=1)[0]

    assert "교과목명: 2학기과목" in result.text
    assert "2학기_학수번호: 001002" in result.text


def test_major_course_question_keeps_required_and_elective_rows_first(
    tmp_path: Path,
) -> None:
    corpus_path = tmp_path / "data/processed/documents.jsonl"
    _write_corpus(
        corpus_path,
        [
            _record(
                document_id="COURSES",
                file_name="courses.csv",
                file_type="csv",
                document_type="학년별교과과정",
                text=_course_text(
                    "전공필수과목",
                    grade=1,
                    completion_type="전공필수",
                    first_code="001001",
                ),
                row_number=1,
            ),
            _record(
                document_id="COURSES",
                file_name="courses.csv",
                file_type="csv",
                document_type="학년별교과과정",
                text=_course_text(
                    "전공선택과목",
                    grade=1,
                    completion_type="전공선택",
                    second_code="001002",
                ),
                row_number=2,
            ),
            _record(
                document_id="COURSES",
                file_name="courses.csv",
                file_type="csv",
                document_type="학년별교과과정",
                text=_course_text(
                    "기초교양과목",
                    grade=1,
                    completion_type="기본소양",
                    first_code="001003",
                ),
                row_number=3,
            ),
        ],
    )
    service = _service(tmp_path)
    service.index_corpus()

    results = service.search("1학년 전공과목", top_k=2)

    assert len(results) == 2
    assert {"이수구분: 전공필수", "이수구분: 전공선택"} == {
        next(
            line for line in result.text.splitlines()
            if line.startswith("이수구분:")
        )
        for result in results
    }


def test_structured_course_search_honors_selected_pdf_type(
    tmp_path: Path,
    monkeypatch,
) -> None:
    corpus_path = tmp_path / "data/processed/documents.jsonl"
    _write_corpus(
        corpus_path,
        [
            _record(
                document_id="COURSES",
                file_name="courses.csv",
                file_type="csv",
                document_type="학년별교과과정",
                text=_course_text(
                    "자료구조및프로그래밍",
                    grade=2,
                    completion_type="전공필수",
                    first_code="704818",
                ),
                row_number=21,
            ),
            _record(
                document_id="COURSES",
                file_name="courses.csv",
                file_type="csv",
                document_type="학년별교과과정",
                text=_course_text(
                    "회로이론",
                    grade=2,
                    completion_type="전공필수",
                    second_code="704305",
                ),
                row_number=22,
            ),
            _record(
                document_id="COURSES",
                file_name="courses.csv",
                file_type="csv",
                document_type="학년별교과과정",
                text=_course_text(
                    "자료구조 및 프로그래밍",
                    grade=2,
                    completion_type="전공필수",
                    first_code="704999",
                ),
                row_number=23,
            ),
            _record(
                document_id="PROGRAM",
                file_name="소프트웨어융합학과_프로그램내규.pdf",
                file_type="pdf",
                document_type="프로그램내규",
                text="소프트웨어융합학과 2학년 1학기 전공필수 과목 안내",
                page_number=4,
            ),
        ],
    )
    service = _service(tmp_path)
    service.index_corpus()
    response = service.search_with_context(
        "소프트웨어융합학과 2학년 1학기 전공필수 과목을 알려줘",
        top_k=5,
        document_type="프로그램내규",
    )

    assert response.structured_query is False
    assert response.exact_match_count == 0
    assert response.semantic_fallback_used is False
    assert len(response.results) == 1
    assert response.results[0].file_type == "pdf"
    assert response.results[0].document_type == "프로그램내규"
    assert response.results[0].page_number == 4


def test_structured_course_search_returns_all_exact_csv_matches_ignoring_top_k(
    tmp_path: Path,
) -> None:
    corpus_path = tmp_path / "data/processed/documents.jsonl"
    _write_corpus(
        corpus_path,
        [
            _record(
                document_id="COURSES",
                file_name="courses.csv",
                file_type="csv",
                document_type="학년별교과과정",
                text=_course_text(
                    "자료구조및프로그래밍",
                    grade=2,
                    completion_type="전공필수",
                    first_code="704818",
                ),
                row_number=21,
            ),
            _record(
                document_id="COURSES",
                file_name="courses.csv",
                file_type="csv",
                document_type="학년별교과과정",
                text=_course_text(
                    "알고리즘",
                    grade=2,
                    completion_type="전공필수",
                    first_code="704819",
                ),
                row_number=22,
            ),
            _record(
                document_id="PROGRAM",
                file_name="소프트웨어융합학과_프로그램내규.pdf",
                file_type="pdf",
                document_type="프로그램내규",
                text="소프트웨어융합학과 2학년 1학기 전공필수 과목 안내",
                page_number=4,
            ),
        ],
    )
    service = _service(tmp_path)
    service.index_corpus()

    response = service.search_with_context(
        "소프트웨어융합학과 2학년 1학기 전공필수 과목을 알려줘",
        top_k=1,
    )

    assert response.structured_query is True
    assert response.exact_match_count == 2
    assert response.semantic_fallback_used is False
    assert len(response.results) == 2
    assert {result.row_number for result in response.results} == {21, 22}
    assert all(result.file_type == "csv" for result in response.results)


def test_structured_course_search_uses_general_search_only_when_csv_match_is_zero(
    tmp_path: Path,
    monkeypatch,
) -> None:
    corpus_path = tmp_path / "data/processed/documents.jsonl"
    _write_corpus(
        corpus_path,
        [
            _record(
                document_id="COURSES",
                file_name="courses.csv",
                file_type="csv",
                document_type="학년별교과과정",
                text=_course_text(
                    "회로이론",
                    grade=2,
                    completion_type="전공필수",
                    second_code="704305",
                ),
                row_number=22,
            ),
            _record(
                document_id="PROGRAM",
                file_name="소프트웨어융합학과_프로그램내규.pdf",
                file_type="pdf",
                document_type="프로그램내규",
                text="소프트웨어융합학과 2학년 1학기 전공필수 과목 안내",
                page_number=4,
            ),
            _record(
                document_id="PROGRAM-TXT",
                file_name="소프트웨어융합학과_프로그램내규.txt",
                file_type="txt",
                document_type="프로그램내규",
                text="소프트웨어융합학과 2학년 전공필수 관련 자료",
            ),
        ],
    )
    service = _service(tmp_path)
    service.index_corpus()
    semantic_queries: list[str] = []
    embed_query = service._embeddings.embed_query

    def tracked_embed_query(question: str) -> list[float]:
        semantic_queries.append(question)
        return embed_query(question)

    monkeypatch.setattr(service._embeddings, "embed_query", tracked_embed_query)

    response = service.search_with_context(
        "소프트웨어융합학과 2학년 1학기 전공필수 과목을 알려줘",
        top_k=1,
    )

    assert response.structured_query is True
    assert response.exact_match_count == 0
    assert response.semantic_fallback_used is True
    assert semantic_queries == [
        "소프트웨어융합학과 2학년 1학기 전공필수 과목을 알려줘"
    ]
    assert len(response.results) == 1


def test_empty_index_does_not_claim_semantic_fallback_was_run(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)

    response = service.search_with_context(
        "소프트웨어융합학과 2학년 1학기 전공필수 과목을 알려줘",
        department="소프트웨어융합학과",
    )

    assert response.structured_query is True
    assert response.exact_match_count == 0
    assert response.semantic_fallback_used is False
    assert response.results == []


def test_structured_course_search_supports_general_elective_completion_type(
    tmp_path: Path,
    monkeypatch,
) -> None:
    corpus_path = tmp_path / "data/processed/documents.jsonl"
    _write_corpus(
        corpus_path,
        [
            _record(
                document_id="COURSES",
                file_name="courses.csv",
                file_type="csv",
                document_type="학년별교과과정",
                text=_course_text(
                    "졸업논문",
                    grade=4,
                    completion_type="일반선택",
                    first_code="704999",
                ),
                row_number=42,
            ),
            _record(
                document_id="PROGRAM",
                file_name="소프트웨어융합학과_프로그램내규.pdf",
                file_type="pdf",
                document_type="프로그램내규",
                text="소프트웨어융합학과 4학년 졸업논문 안내",
                page_number=8,
            ),
        ],
    )
    service = _service(tmp_path)
    service.index_corpus()
    monkeypatch.setattr(
        service._embeddings,
        "embed_query",
        lambda _question: pytest.fail(
            "일반선택도 정확 CSV 구조화 검색으로 처리해야 합니다."
        ),
    )

    response = service.search_with_context(
        "소프트웨어융합학과 4학년 1학기 일반선택 과목을 알려줘",
        top_k=3,
    )

    assert response.structured_query is True
    assert response.exact_match_count == 1
    assert response.semantic_fallback_used is False
    assert len(response.results) == 1
    assert response.results[0].file_type == "csv"
    assert "교과목명: 졸업논문" in response.results[0].text


@pytest.mark.parametrize("second_code,expected_count", [("704818", 1), ("704819", 2)])
def test_only_identical_course_values_are_removed(tmp_path: Path, second_code, expected_count) -> None:
    corpus_path = tmp_path / "data/processed/documents.jsonl"
    duplicate = _course_text(
        "자료구조및프로그래밍",
        grade=2,
        completion_type="전공필수",
        first_code="704818",
    )
    _write_corpus(
        corpus_path,
        [
            _record(
                document_id="COURSES",
                file_name="courses.csv",
                file_type="csv",
                document_type="학년별교과과정",
                text=duplicate,
                row_number=1,
            ),
            _record(
                document_id="COURSES",
                file_name="courses.csv",
                file_type="csv",
                document_type="학년별교과과정",
                text=(
                    duplicate
                    .replace(
                        "자료구조및프로그래밍",
                        "자료구조 및 프로그래밍",
                    )
                    .replace("704818", second_code)
                ),
                row_number=2,
            ),
        ],
    )
    service = _service(tmp_path)
    service.index_corpus()

    results = service.search("2학년 전공필수 과목", top_k=3)

    assert len(results) == expected_count
    assert "교과목명: 자료구조및프로그래밍" in results[0].text


def test_administrative_semester_question_uses_general_search(
    tmp_path: Path,
) -> None:
    corpus_path = tmp_path / "data/processed/documents.jsonl"
    _write_corpus(
        corpus_path,
        [
            _record(
                document_id="COURSES",
                file_name="courses.csv",
                file_type="csv",
                document_type="학년별교과과정",
                text=_course_text(
                    "일반 교과목",
                    grade=1,
                    completion_type="전공선택",
                    first_code="001001",
                ),
                row_number=1,
            ),
            _record(
                document_id="SCHOLARSHIP",
                file_name="scholarship.pdf",
                file_type="pdf",
                document_type="장학금안내",
                text="이번 학기 장학금 신청 기간 안내",
                page_number=2,
            ),
        ],
    )
    service = _service(tmp_path)
    service.index_corpus()

    result = service.search("이번 학기 장학금 신청 기간", top_k=1)[0]

    assert result.file_type == "pdf"
    assert result.document_type == "장학금안내"


@pytest.mark.parametrize("query,dropdown", [
    ("소프트웨어융합학과 졸업요건", None),
    ("소프트웨어 융합 학과 졸업요건", None),
    ("소프트웨어융합학과 졸업요건", "디자인엔지니어링학과"),
    ("졸업요건", "소프트웨어융합학과"),
])
def test_department_scoped_rules_never_include_global_or_other_departments(tmp_path, query, dropdown):
    from src.answering.answer_service import AnswerService
    service = _service(tmp_path)
    rows = [_record(document_id=name, file_name=name+".pdf", file_type="pdf",
        document_type="학사규정", page_number=1, department=dept, text=text)
        for name, dept, text in [
            ("software", "소프트웨어융합학과", "소프트웨어융합학과 졸업요건은 전공 60학점 이상 이수입니다."),
            ("design", "디자인엔지니어링학과", "디자인엔지니어링학과 졸업요건은 디자인실습 40학점 이수입니다."),
            ("global", "전체", "디자인엔지니어링 전공 졸업요건은 스케칭과시각적사고 이수입니다."),
        ]]
    _write_corpus(service.corpus_path, rows)
    service.index_corpus()
    response = service.search_with_context(query, department=dropdown)
    assert response.results
    assert {r.document_id for r in response.results} == {"software"}
    answer = AnswerService(service).answer_question(query, department=dropdown)
    assert "디자인" not in answer.text
    assert "스케칭" not in answer.text
    assert not service.search("존재하지않는학과 졸업요건")
    _write_corpus(service.corpus_path, rows[1:])
    service.index_corpus()
    assert not service.search(query, department="소프트웨어융합학과")


def test_graduation_table_keeps_body_and_outranks_guidance(tmp_path):
    service = _service(tmp_path, chunk_size=100, chunk_overlap=10)
    table = "<표 5> 공학교육인증(심화 프로그램) 졸업요건\n" + "영역별 이수 조건을 확인합니다. " * 12 + "총 132학점 이상 이수하여야 합니다."
    rows = [_record(document_id="rules", file_name="규정.pdf", file_type="pdf", document_type="학사규정",
        page_number=16, text=table), _record(document_id="guidance", file_name="지도.pdf", file_type="pdf",
        document_type="학사규정", page_number=10, text="학생 지도 시 졸업요건을 고려하여 과목을 선택하고 학습계획서를 작성합니다.")]
    _write_corpus(service.corpus_path, rows)
    service.index_corpus()
    response = service.search_with_context("소프트웨어융합학과 졸업요건", top_k=1)
    assert len(response.results) == 1
    assert response.results[0].page_number == 16
    assert response.results[0].text == table
    assert "132학점" in response.results[0].text



def test_unscoped_graduation_uses_single_department_or_requests_scope(tmp_path):
    from src.answering.answer_service import AnswerService
    service = _service(tmp_path)
    rows = [_record(document_id="software", file_name="내규.pdf", file_type="pdf", document_type="학사규정",
        page_number=16, text="<표 5> 심화과정 졸업요건\n 전공 54학점을 포함하여 총 132학점 이수하여야 함."),
        _record(document_id="global", file_name="전체.pdf", file_type="pdf", document_type="학사규정",
        department="전체", page_number=26, text="디자인엔지니어링 졸업요건은 전공 60학점 이수입니다.")]
    _write_corpus(service.corpus_path, rows)
    service.index_corpus()
    question = "졸업할려면 전공학점을 몇 학점 들어야 해?"
    results = service.search(question)
    assert results and {r.document_id for r in results} == {"software"}
    rows.append(_record(document_id="design", file_name="디자인.pdf", file_type="pdf", document_type="학사규정",
        department="디자인학과", page_number=1, text="디자인학과 졸업요건은 전공 60학점 이수입니다."))
    _write_corpus(service.corpus_path, rows)
    service.index_corpus()
    answer = AnswerService(service).answer_question(question)
    assert not answer.search_response.results
    assert "학과를 선택" in answer.text
    assert "60학점" not in answer.text
    assert service.search(question, department="소프트웨어융합학과")
