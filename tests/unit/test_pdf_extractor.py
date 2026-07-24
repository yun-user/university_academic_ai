"""PDF 페이지 추출과 중복 감지 회귀 테스트."""

from __future__ import annotations

import base64
import shutil
from pathlib import Path

import pymupdf

import src.ingestion.pdf_extractor as pdf_extractor
from src.ingestion.pdf_extractor import (
    calculate_file_hash,
    extract_pdf_file,
    list_pdf_files,
    process_pdf_directory,
)
from src.ingestion.pdf_models import (
    PdfDocumentStatus,
    PdfIssueCode,
    PdfPageStatus,
)


_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _create_pdf(
    path: Path,
    page_texts: list[str],
    *,
    title: str | None = None,
) -> None:
    document = pymupdf.open()
    try:
        if title:
            document.set_metadata({"title": title})
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


def test_list_pdf_files_reads_only_pdf_files_in_name_order(tmp_path: Path) -> None:
    _create_pdf(tmp_path / "b.pdf", ["second"])
    _create_pdf(tmp_path / "A.PDF", ["first"])
    (tmp_path / "note.txt").write_text("not a pdf", encoding="utf-8")

    files = list_pdf_files(tmp_path)

    assert [file.name for file in files] == ["A.PDF", "b.pdf"]


def test_page_count_text_and_one_based_page_numbers_are_preserved(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "three-pages.pdf"
    _create_pdf(
        pdf_path,
        ["first page", "second page", "third page"],
        title="Metadata title",
    )

    result = extract_pdf_file(pdf_path, project_root=tmp_path)

    assert result.document_title == "Metadata title"
    assert result.source_path == "three-pages.pdf"
    assert result.page_count == 3
    assert len(result.pages) == 3
    assert [page.page_index for page in result.pages] == [0, 1, 2]
    assert [page.page_number for page in result.pages] == [1, 2, 3]
    assert [page.text for page in result.pages] == [
        "first page",
        "second page",
        "third page",
    ]
    assert result.status is PdfDocumentStatus.SUCCESS


def test_image_page_is_distinguished_from_blank_page(tmp_path: Path) -> None:
    pdf_path = tmp_path / "image.pdf"
    _create_image_pdf(pdf_path)

    result = extract_pdf_file(pdf_path, project_root=tmp_path)

    assert result.page_count == 1
    assert result.text_page_count == 0
    assert result.image_page_count == 1
    assert result.empty_page_count == 0
    assert result.pages[0].status is PdfPageStatus.IMAGE
    assert result.pages[0].image_count == 1
    assert result.pages[0].max_image_coverage > 0
    assert any(
        issue.code is PdfIssueCode.IMAGE_PAGE for issue in result.issues
    )


def test_blank_page_keeps_its_page_number_and_reports_warning(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "mixed.pdf"
    _create_pdf(pdf_path, ["first page", "", "third page"])

    result = extract_pdf_file(pdf_path, project_root=tmp_path)

    assert result.page_count == 3
    assert [page.page_number for page in result.pages] == [1, 2, 3]
    assert result.pages[1].status is PdfPageStatus.EMPTY
    assert result.pages[1].text == ""
    assert result.empty_page_count == 1
    assert result.status is PdfDocumentStatus.SUCCESS_WITH_WARNINGS


def test_duplicate_pdf_is_detected_without_modifying_originals(
    tmp_path: Path,
) -> None:
    original = tmp_path / "a-original.pdf"
    duplicate = tmp_path / "b-duplicate.pdf"
    _create_pdf(original, ["same content"])
    shutil.copyfile(original, duplicate)
    original_bytes = original.read_bytes()
    duplicate_bytes = duplicate.read_bytes()
    original_mtime = original.stat().st_mtime_ns
    duplicate_mtime = duplicate.stat().st_mtime_ns

    result = process_pdf_directory(tmp_path, project_root=tmp_path)

    assert len(result.documents) == 2
    assert result.documents[0].is_duplicate is False
    assert result.documents[1].is_duplicate is True
    assert result.documents[1].duplicate_of == "a-original.pdf"
    assert result.documents[0].content_hash == result.documents[1].content_hash
    assert len(result.duplicate_groups) == 1
    assert result.duplicate_groups[0].duplicate_source_paths == [
        "b-duplicate.pdf"
    ]
    assert original.read_bytes() == original_bytes
    assert duplicate.read_bytes() == duplicate_bytes
    assert original.stat().st_mtime_ns == original_mtime
    assert duplicate.stat().st_mtime_ns == duplicate_mtime


def test_blank_pdf_returns_visible_error_message(tmp_path: Path) -> None:
    pdf_path = tmp_path / "blank.pdf"
    _create_pdf(pdf_path, [""])

    result = extract_pdf_file(pdf_path, project_root=tmp_path)

    assert result.page_count == 1
    assert result.pages[0].page_number == 1
    assert result.pages[0].status is PdfPageStatus.EMPTY
    assert result.status is PdfDocumentStatus.EMPTY_DOCUMENT
    assert any(
        issue.code is PdfIssueCode.NO_EXTRACTABLE_TEXT
        and "추출 가능한 텍스트가 없습니다" in issue.message
        for issue in result.issues
    )


def test_zero_byte_pdf_returns_empty_file_error(tmp_path: Path) -> None:
    pdf_path = tmp_path / "zero-byte.pdf"
    pdf_path.write_bytes(b"")

    result = extract_pdf_file(pdf_path, project_root=tmp_path)

    assert result.status is PdfDocumentStatus.ERROR
    assert result.page_count == 0
    assert result.issues[0].code is PdfIssueCode.EMPTY_FILE
    assert "비어 있습니다" in result.issues[0].message


def test_page_extraction_failure_does_not_shift_following_page_numbers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pdf_path = tmp_path / "partial.pdf"
    _create_pdf(pdf_path, ["first page", "second page", "third page"])
    original_extract = pdf_extractor._extract_page_text

    def fail_on_second_page(page: pymupdf.Page) -> str:
        if page.number == 1:
            raise RuntimeError("forced extraction failure")
        return original_extract(page)

    monkeypatch.setattr(pdf_extractor, "_extract_page_text", fail_on_second_page)

    result = extract_pdf_file(pdf_path, project_root=tmp_path)

    assert result.page_count == 3
    assert [page.page_number for page in result.pages] == [1, 2, 3]
    assert result.pages[1].status is PdfPageStatus.FAILED
    assert result.pages[1].error_message
    assert result.pages[2].text == "third page"
    assert result.status is PdfDocumentStatus.PARTIAL
    assert result.failed_page_count == 1


def test_calculate_file_hash_is_stable_and_read_only(tmp_path: Path) -> None:
    pdf_path = tmp_path / "stable.pdf"
    _create_pdf(pdf_path, ["content"])
    before = pdf_path.read_bytes()
    before_mtime = pdf_path.stat().st_mtime_ns

    first_hash = calculate_file_hash(pdf_path)
    second_hash = calculate_file_hash(pdf_path)

    assert first_hash == second_hash
    assert len(first_hash) == 64
    assert pdf_path.read_bytes() == before
    assert pdf_path.stat().st_mtime_ns == before_mtime
