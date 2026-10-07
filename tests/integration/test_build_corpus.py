"""PDF, CSV, TXT 통합 corpus 빌드의 파일 I/O 회귀 테스트."""

from __future__ import annotations

import base64
import csv
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest

from src.ingestion.build_corpus import (
    MANIFEST_FIELDS,
    RECORD_FIELDS,
    REPORT_FIELDS,
    build_corpus,
)
from src.ingestion.pdf_models import PdfDocumentStatus, PdfPageStatus


MANIFEST_COLUMNS = (*MANIFEST_FIELDS, "notes")
_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


@pytest.mark.parametrize("headers", [["학점", "학점", "학점_2"], ["학점_2", "학점", "학점"], ["", "column_1"]])
def test_csv_header_collisions_preserve_every_value(corpus_root, headers):
    path = corpus_root / "data/raw/tables/collision.csv"
    values = [f"value-{i}" for i in range(len(headers))]
    _write_table(path, headers, [values])
    result = build_corpus(corpus_root)
    row = result.documents[0]["metadata"]["row"]
    assert len(row) == len(headers)
    assert list(row.values()) == values
    assert not result.report["errors"]


@pytest.mark.parametrize("failure", ["text", "load"])
def test_partial_pdf_failure_preserves_published_corpus(corpus_root, monkeypatch, failure):
    from src.ingestion import pdf_extractor
    path = corpus_root / "data/raw/pdfs/partial.pdf"
    _create_text_pdf(path, ["Original first page", "Original second page"])
    good = build_corpus(corpus_root)
    previous = good.documents_path.read_bytes()
    if failure == "text":
        original = pdf_extractor._extract_page_text
        def fail(page):
            if page.number == 1:
                raise RuntimeError("injected text failure")
            return original(page)
        monkeypatch.setattr(pdf_extractor, "_extract_page_text", fail)
    else:
        original = pymupdf.Document.load_page
        def fail(doc, number):
            if number == 1:
                raise RuntimeError("injected page load failure")
            return original(doc, number)
        monkeypatch.setattr(pymupdf.Document, "load_page", fail)
    failed = build_corpus(corpus_root)
    assert failed.report["errors"]
    assert good.documents_path.read_bytes() == previous
    assert failed.documents_path.name == "documents.failed.jsonl"
    assert any(issue.get("page_number") == 2 for issue in failed.report["errors"])


@pytest.fixture
def corpus_root(tmp_path: Path) -> Path:
    for relative_path in (
        "data/raw/pdfs",
        "data/raw/tables",
        "data/raw/text",
        "data/metadata",
    ):
        (tmp_path / relative_path).mkdir(parents=True)
    return tmp_path


def _manifest_row(
    file_name: str,
    file_type: str,
    **overrides: str,
) -> dict[str, str]:
    row = {column: "" for column in MANIFEST_COLUMNS}
    row.update(
        {
            "document_id": f"DOC-{Path(file_name).stem}",
            "file_name": file_name,
            "file_type": file_type,
            "document_type": "테스트자료",
            "department": "테스트학과",
            "authority": "테스트기관",
            "is_current": "Y",
        }
    )
    row.update(overrides)
    return row


def _write_manifest(
    root: Path,
    rows: list[dict[str, str]],
    *,
    encoding: str = "utf-8",
) -> None:
    path = root / "data/metadata/documents_manifest.csv"
    with path.open("w", encoding=encoding, newline="") as output:
        writer = csv.DictWriter(output, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _create_text_pdf(
    path: Path,
    page_texts: list[str],
    *,
    metadata_title: str | None = None,
) -> None:
    document = pymupdf.open()
    try:
        if metadata_title:
            document.set_metadata({"title": metadata_title})
        for text in page_texts:
            page = document.new_page()
            if text:
                page.insert_text((72, 72), text)
        document.save(path)
    finally:
        document.close()


def _create_image_pdf(path: Path) -> None:
    document = pymupdf.open()
    try:
        page = document.new_page()
        page.insert_image(page.rect, stream=_ONE_PIXEL_PNG)
        document.save(path)
    finally:
        document.close()


def _create_mixed_pdf(path: Path) -> None:
    document = pymupdf.open()
    try:
        text_page = document.new_page()
        text_page.insert_text((72, 72), "searchable text")
        image_page = document.new_page()
        image_page.insert_image(image_page.rect, stream=_ONE_PIXEL_PNG)
        document.new_page()
        document.save(path)
    finally:
        document.close()


def _write_table(
    path: Path,
    headers: list[str],
    rows: list[list[str]],
    *,
    encoding: str = "utf-8",
) -> None:
    with path.open("w", encoding=encoding, newline="") as output:
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows(rows)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _warning_codes(report: dict[str, object]) -> set[str]:
    warnings = report["warnings"]
    assert isinstance(warnings, list)
    return {str(item["code"]) for item in warnings}


def test_build_corpus_creates_jsonl_and_report(corpus_root: Path) -> None:
    txt_path = corpus_root / "data/raw/text/info.txt"
    txt_path.write_text("sample text", encoding="utf-8")
    _write_manifest(corpus_root, [_manifest_row("info.txt", "txt")])

    result = build_corpus(project_root=corpus_root)

    assert result.documents_path.is_file()
    assert result.report_path.is_file()
    documents = _read_jsonl(result.documents_path)
    saved_report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert len(documents) == 1
    assert set(RECORD_FIELDS).issubset(documents[0])
    assert set(REPORT_FIELDS).issubset(saved_report)
    assert isinstance(documents[0]["metadata"], dict)
    assert isinstance(documents[0]["image_only"], bool)
    assert isinstance(documents[0]["document_image_only"], bool)
    assert isinstance(documents[0]["searchable"], bool)
    assert documents[0]["page_status"] is None
    assert str(corpus_root) not in result.documents_path.read_text(encoding="utf-8")


def test_pdf_preserves_all_physical_page_numbers(corpus_root: Path) -> None:
    pdf_path = corpus_root / "data/raw/pdfs/pages.pdf"
    _create_text_pdf(
        pdf_path,
        ["first", "", "third"],
        metadata_title="Internal source title",
    )
    _write_manifest(corpus_root, [_manifest_row("pages.pdf", "pdf")])

    result = build_corpus(project_root=corpus_root)
    records = [item for item in result.documents if item["file_type"] == "pdf"]

    assert [item["page_number"] for item in records] == [1, 2, 3]
    assert [item["row_number"] for item in records] == [None, None, None]
    assert records[1]["text"] == ""
    assert records[1]["metadata"]["extraction_page_status"] == "empty"
    assert [item["page_status"] for item in records] == [
        "text",
        "empty",
        "text",
    ]
    assert [item["searchable"] for item in records] == [True, False, True]
    assert records[0]["title"] == "pages"
    assert (
        records[0]["metadata"]["extracted_pdf_title"]
        == "Internal source title"
    )
    assert all(item["image_only"] is False for item in records)
    assert all(item["document_image_only"] is False for item in records)
    assert result.report["pdf_pages"] == 3


def test_all_curriculum_pdf_assigns_department_from_each_page_text(
    corpus_root: Path,
    monkeypatch,
) -> None:
    pdf_path = (
        corpus_root
        / "data/raw/pdfs/2026_홍익대학교_전체교과과정.pdf"
    )
    pdf_path.write_bytes(b"synthetic pdf")
    _write_manifest(
        corpus_root,
        [
            _manifest_row(
                pdf_path.name,
                "pdf",
                document_id="CURR-2026",
                document_type="전체교과과정",
                department="소프트웨어융합학과",
            )
        ],
    )
    pages = [
        SimpleNamespace(
            page_number=1,
            text="조소과 1학년 교과과정",
            status=PdfPageStatus.TEXT,
            error_message=None,
            image_count=0,
            max_image_coverage=0.0,
        ),
        SimpleNamespace(
            page_number=2,
            text="소프트웨어융합학과 1학년 교과과정",
            status=PdfPageStatus.TEXT,
            error_message=None,
            image_count=0,
            max_image_coverage=0.0,
        ),
    ]
    extraction = SimpleNamespace(
        document_title="2026 전체교과과정",
        content_hash="a" * 64,
        page_count=2,
        text_page_count=2,
        image_page_count=0,
        failed_page_count=0,
        status=PdfDocumentStatus.SUCCESS,
        issues=[],
        pages=pages,
    )
    build_module = importlib.import_module("src.ingestion.build_corpus")
    monkeypatch.setattr(
        build_module,
        "extract_pdf_file",
        lambda *_args, **_kwargs: extraction,
    )

    result = build_corpus(project_root=corpus_root)
    pdf_records = [
        item for item in result.documents if item["file_type"] == "pdf"
    ]

    assert [item["department"] for item in pdf_records] == [
        "전체",
        "소프트웨어융합학과",
    ]
    assert [item["page_number"] for item in pdf_records] == [1, 2]
    assert all(item["searchable"] is True for item in pdf_records)


def test_image_pdf_is_kept_and_flagged(corpus_root: Path) -> None:
    pdf_path = corpus_root / "data/raw/pdfs/image.pdf"
    _create_image_pdf(pdf_path)
    _write_manifest(corpus_root, [_manifest_row("image.pdf", "pdf")])

    result = build_corpus(project_root=corpus_root)
    record = result.documents[0]

    assert record["page_number"] == 1
    assert record["text"] == ""
    assert record["image_only"] is True
    assert record["document_image_only"] is True
    assert record["page_status"] == "image"
    assert record["searchable"] is False
    assert record["metadata"]["image_count"] == 1
    assert result.report["image_pdf_files"] == 1
    assert result.report["text_pdf_files"] == 0


def test_blank_pdf_is_not_misclassified_as_image(corpus_root: Path) -> None:
    pdf_path = corpus_root / "data/raw/pdfs/blank.pdf"
    _create_text_pdf(pdf_path, [""])
    _write_manifest(corpus_root, [_manifest_row("blank.pdf", "pdf")])

    result = build_corpus(project_root=corpus_root)
    record = result.documents[0]

    assert record["page_status"] == "empty"
    assert record["document_image_only"] is False
    assert record["image_only"] is False
    assert record["searchable"] is False
    assert result.report["image_pdf_files"] == 0


def test_mixed_pdf_separates_document_and_page_image_state(
    corpus_root: Path,
) -> None:
    pdf_path = corpus_root / "data/raw/pdfs/mixed.pdf"
    _create_mixed_pdf(pdf_path)
    _write_manifest(corpus_root, [_manifest_row("mixed.pdf", "pdf")])

    result = build_corpus(project_root=corpus_root)
    records = result.documents

    assert [item["page_status"] for item in records] == [
        "text",
        "image",
        "empty",
    ]
    assert [item["searchable"] for item in records] == [True, False, False]
    assert all(item["document_image_only"] is False for item in records)
    assert result.report["text_pdf_files"] == 1
    assert result.report["image_pdf_files"] == 0


def test_csv_preserves_leading_zero_values(corpus_root: Path) -> None:
    csv_path = corpus_root / "data/raw/tables/courses.csv"
    _write_table(
        csv_path,
        ["학수번호", "교과목명", "빈값"],
        [["001012", "자료구조", ""]],
        encoding="utf-8-sig",
    )
    _write_manifest(corpus_root, [_manifest_row("courses.csv", "csv")])

    result = build_corpus(project_root=corpus_root)
    record = result.documents[0]

    assert record["metadata"]["row"]["학수번호"] == "001012"
    assert "학수번호: 001012" in record["text"]
    assert record["searchable"] is True
    assert record["metadata"]["encoding"] == "utf-8-sig"
    serialized = json.dumps(record, ensure_ascii=False)
    assert "NaN" not in serialized
    assert "nan" not in serialized.casefold()


def test_csv_emits_one_document_for_each_data_row(corpus_root: Path) -> None:
    csv_path = corpus_root / "data/raw/tables/two-rows.csv"
    _write_table(
        csv_path,
        ["학수번호", "교과목명"],
        [["000001", "첫 과목"], ["000002", "둘째 과목"]],
    )
    _write_manifest(corpus_root, [_manifest_row("two-rows.csv", "csv")])

    result = build_corpus(project_root=corpus_root)
    records = [item for item in result.documents if item["file_type"] == "csv"]

    assert len(records) == 2
    assert [item["row_number"] for item in records] == [1, 2]
    assert all(item["page_number"] is None for item in records)
    assert result.report["csv_rows"] == 2


def test_txt_is_processed_as_one_utf8_document(corpus_root: Path) -> None:
    txt_path = corpus_root / "data/raw/text/korean.txt"
    txt_path.write_bytes("\ufeff학교 정보\r\n두 번째 줄".encode("utf-8"))
    _write_manifest(
        corpus_root,
        [_manifest_row("korean.txt", "txt")],
        encoding="utf-8-sig",
    )

    result = build_corpus(project_root=corpus_root)
    record = result.documents[0]

    assert record["text"] == "학교 정보\n두 번째 줄"
    assert record["page_number"] is None
    assert record["row_number"] is None
    assert record["image_only"] is False
    assert record["document_image_only"] is False
    assert record["searchable"] is True
    assert record["metadata"]["encoding"] == "utf-8-sig"
    assert result.report["txt_files"] == 1


@pytest.mark.parametrize(
    ("manifest_encoding", "data_encoding"),
    [
        ("utf-8", "utf-8"),
        ("utf-8", "utf-8-sig"),
        ("utf-8-sig", "utf-8"),
        ("utf-8-sig", "utf-8-sig"),
    ],
)
def test_utf8_inputs_and_korean_values_round_trip_without_mojibake(
    corpus_root: Path,
    manifest_encoding: str,
    data_encoding: str,
) -> None:
    csv_path = corpus_root / "data/raw/tables/학년별교과과정.csv"
    txt_path = corpus_root / "data/raw/text/학교정보.txt"
    _write_table(
        csv_path,
        ["학교명", "학과", "교과목명"],
        [
            ["홍익대학교", "소프트웨어융합학과", "창의적공학설계입문"],
            ["홍익대학교", "소프트웨어융합학과", "종합설계(1)"],
        ],
        encoding=data_encoding,
    )
    txt_path.write_text(
        "홍익대학교 소프트웨어융합학과 장학금선정기준",
        encoding=data_encoding,
    )
    (corpus_root / "data/raw/tables/참고용.xlsx").write_bytes(b"not supported")
    _write_manifest(
        corpus_root,
        [
            _manifest_row(
                csv_path.name,
                "csv",
                document_id="KOREAN-TABLE",
                document_type="장학금선정기준",
                department="소프트웨어융합학과",
                authority="홍익대학교",
            ),
            _manifest_row(
                txt_path.name,
                "txt",
                document_id="KOREAN-TEXT",
                document_type="장학금선정기준",
                department="소프트웨어융합학과",
                authority="홍익대학교",
            ),
        ],
        encoding=manifest_encoding,
    )

    result = build_corpus(project_root=corpus_root)
    records = result.documents
    csv_records = [item for item in records if item["file_type"] == "csv"]
    txt_record = next(item for item in records if item["file_type"] == "txt")

    assert [item["document_id"] for item in csv_records] == [
        "KOREAN-TABLE",
        "KOREAN-TABLE",
    ]
    assert all(
        item["document_type"] == "장학금선정기준"
        and item["department"] == "소프트웨어융합학과"
        and item["authority"] == "홍익대학교"
        for item in records
    )
    assert csv_records[0]["metadata"]["row"]["교과목명"] == "창의적공학설계입문"
    assert csv_records[1]["metadata"]["row"]["교과목명"] == "종합설계(1)"
    assert txt_record["text"] == (
        "홍익대학교 소프트웨어융합학과 장학금선정기준"
    )
    assert all(
        item["metadata"]["encoding"] == data_encoding for item in records
    )

    documents_bytes = result.documents_path.read_bytes()
    report_bytes = result.report_path.read_bytes()
    assert not documents_bytes.startswith(b"\xef\xbb\xbf")
    assert not report_bytes.startswith(b"\xef\xbb\xbf")
    documents_text = documents_bytes.decode("utf-8", errors="strict")
    report_text = report_bytes.decode("utf-8", errors="strict")
    for expected in (
        "홍익대학교",
        "소프트웨어융합학과",
        "장학금선정기준",
        "창의적공학설계입문",
        "종합설계(1)",
    ):
        assert expected in documents_text
    assert "참고용.xlsx" in report_text
    assert "?뚰봽" not in documents_text
    assert "\\ud64d\\uc775\\ub300\\ud559\\uad50" not in documents_text


def test_manifest_metadata_is_joined_without_type_coercion(
    corpus_root: Path,
) -> None:
    pdf_path = corpus_root / "data/raw/pdfs/rules.pdf"
    _create_text_pdf(pdf_path, ["rules"])
    row = _manifest_row(
        "rules.pdf",
        "pdf",
        document_id="RULE-2024",
        document_type="졸업요건",
        source_year="2024",
        effective_from="2024-2",
        effective_to="2025-1",
        department="소프트웨어융합학과",
        admission_year_from="0019",
        admission_year_to="2024",
        track="공학인증",
        authority="학과",
        is_current="N",
        source_url="https://example.edu/rules",
        notes="원문 메모",
    )
    _write_manifest(corpus_root, [row])

    result = build_corpus(project_root=corpus_root)
    record = result.documents[0]

    assert record["document_id"] == "RULE-2024"
    assert record["file_type"] == "pdf"
    assert record["document_type"] == "졸업요건"
    assert record["effective_from"] == "2024-2"
    assert record["admission_year_from"] == "0019"
    assert record["department"] == "소프트웨어융합학과"
    assert record["is_current"] is False
    assert record["source_url"] == "https://example.edu/rules"
    assert record["metadata"]["manifest"]["notes"] == "원문 메모"


def test_unregistered_supported_file_is_processed_and_warned(
    corpus_root: Path,
) -> None:
    txt_path = corpus_root / "data/raw/text/unregistered.txt"
    txt_path.write_text("등록되지 않은 자료", encoding="utf-8")
    _write_manifest(corpus_root, [])

    result = build_corpus(project_root=corpus_root)

    assert len(result.documents) == 1
    assert result.documents[0]["file_name"] == "unregistered.txt"
    assert result.documents[0]["document_id"].startswith("UNMANIFESTED-")
    assert "MANIFEST_ENTRY_MISSING" in _warning_codes(result.report)
    assert result.report["failed_files"] == 0


def test_manifest_entry_without_actual_file_blocks_publication(
    corpus_root: Path,
) -> None:
    _write_manifest(corpus_root, [_manifest_row("missing.txt", "txt")])

    result = build_corpus(project_root=corpus_root)

    assert result.documents == []
    assert any(item["code"] == "MANIFEST_FILE_NOT_FOUND" for item in result.report["errors"])
    assert not (corpus_root / "data/processed/documents.jsonl").exists()
    assert result.report["total_files"] == 0
    assert result.report["failed_files"] == 0


def test_report_counts_mixed_corpus(corpus_root: Path) -> None:
    text_pdf = corpus_root / "data/raw/pdfs/text.pdf"
    image_pdf = corpus_root / "data/raw/pdfs/image.pdf"
    csv_path = corpus_root / "data/raw/tables/table.csv"
    txt_path = corpus_root / "data/raw/text/info.txt"
    _create_text_pdf(text_pdf, ["text"])
    _create_image_pdf(image_pdf)
    _write_table(csv_path, ["코드"], [["001"], ["002"]])
    txt_path.write_text("text", encoding="utf-8")
    _write_manifest(
        corpus_root,
        [
            _manifest_row("text.pdf", "pdf"),
            _manifest_row("image.pdf", "pdf"),
            _manifest_row("table.csv", "csv"),
            _manifest_row("info.txt", "txt"),
        ],
    )

    result = build_corpus(project_root=corpus_root)
    report = result.report

    assert report["total_files"] == 4
    assert report["success_files"] == 4
    assert report["failed_files"] == 0
    assert report["pdf_files"] == 2
    assert report["text_pdf_files"] == 1
    assert report["image_pdf_files"] == 1
    assert report["pdf_pages"] == 2
    assert report["csv_files"] == 1
    assert report["csv_rows"] == 2
    assert report["txt_files"] == 1
    assert report["document_records"] == 5
    assert report["errors"] == []


def test_build_keeps_pdf_csv_and_txt_originals_unchanged(
    corpus_root: Path,
) -> None:
    pdf_path = corpus_root / "data/raw/pdfs/original.pdf"
    csv_path = corpus_root / "data/raw/tables/original.csv"
    txt_path = corpus_root / "data/raw/text/original.txt"
    _create_text_pdf(pdf_path, ["original text"])
    _write_table(csv_path, ["학수번호"], [["001012"]], encoding="utf-8-sig")
    txt_path.write_text("원본 텍스트", encoding="utf-8")
    _write_manifest(
        corpus_root,
        [
            _manifest_row(pdf_path.name, "pdf"),
            _manifest_row(csv_path.name, "csv"),
            _manifest_row(txt_path.name, "txt"),
        ],
    )
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in (pdf_path, csv_path, txt_path)
    }

    build_corpus(project_root=corpus_root)

    for path, (expected_bytes, expected_mtime) in before.items():
        assert path.read_bytes() == expected_bytes
        assert path.stat().st_mtime_ns == expected_mtime


def test_broken_pdf_does_not_stop_other_files(corpus_root: Path) -> None:
    pdf_path = corpus_root / "data/raw/pdfs/broken.pdf"
    txt_path = corpus_root / "data/raw/text/valid.txt"
    pdf_path.write_bytes(b"")
    txt_path.write_text("valid", encoding="utf-8")
    _write_manifest(
        corpus_root,
        [
            _manifest_row("broken.pdf", "pdf"),
            _manifest_row("valid.txt", "txt"),
        ],
    )

    result = build_corpus(project_root=corpus_root)

    assert [item["file_name"] for item in result.documents] == ["valid.txt"]
    assert result.report["failed_files"] == 1
    assert result.report["success_files"] == 1
    assert any(
        issue["code"] == "PDF_EMPTY_FILE" for issue in result.report["errors"]
    )
