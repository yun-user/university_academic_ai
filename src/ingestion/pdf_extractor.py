"""PyMuPDF 기반 읽기 전용 PDF 목록 조회와 페이지별 텍스트 추출."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf

from src.config import PROJECT_ROOT
from src.ingestion.pdf_models import (
    DuplicatePdfGroup,
    PdfBatchExtraction,
    PdfDocumentExtraction,
    PdfDocumentStatus,
    PdfIssue,
    PdfIssueCode,
    PdfPageExtraction,
    PdfPageStatus,
)


DEFAULT_PDF_INPUT_DIRECTORY = PROJECT_ROOT / "data" / "raw" / "pdfs"
_HASH_READ_SIZE = 1024 * 1024


class PdfDirectoryError(RuntimeError):
    """PDF 입력 폴더를 읽을 수 없을 때 발생한다."""


def list_pdf_files(
    input_directory: str | Path = DEFAULT_PDF_INPUT_DIRECTORY,
) -> list[Path]:
    """입력 폴더 바로 아래의 PDF 파일을 이름순으로 반환한다."""

    directory = Path(input_directory)
    if not directory.exists():
        raise PdfDirectoryError(f"PDF 입력 폴더를 찾을 수 없습니다: {directory}")
    if not directory.is_dir():
        raise PdfDirectoryError(f"PDF 입력 경로가 폴더가 아닙니다: {directory}")

    return sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.casefold() == ".pdf"
        ),
        key=lambda path: (path.name.casefold(), path.name),
    )


def calculate_file_hash(pdf_path: str | Path) -> str:
    """파일 내용을 변경하지 않고 SHA-256 해시를 계산한다."""

    digest = hashlib.sha256()
    with Path(pdf_path).open("rb") as source:
        for block in iter(lambda: source.read(_HASH_READ_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_path(path: Path, project_root: Path) -> str:
    resolved_path = path.resolve()
    resolved_root = project_root.resolve()
    try:
        return resolved_path.relative_to(resolved_root).as_posix()
    except ValueError:
        return resolved_path.as_posix()


def _extract_page_text(page: pymupdf.Page) -> str:
    """테스트에서 실패를 주입할 수 있도록 분리한 페이지 추출 경계."""

    return page.get_text("text", sort=True).replace("\x00", "").strip()


def _inspect_page_images(page: pymupdf.Page) -> tuple[int, float]:
    """직접 텍스트가 없는 페이지의 표시 이미지 수와 최대 면적 비율."""

    page_rect = pymupdf.Rect(page.rect)
    page_area = max(page_rect.width * page_rect.height, 0.0)
    if page_area <= 0:
        return 0, 0.0

    visible_coverages: list[float] = []
    for image_info in page.get_image_info(hashes=False, xrefs=False):
        bbox = image_info.get("bbox")
        if bbox is None:
            continue
        visible_rect = pymupdf.Rect(bbox) & page_rect
        visible_area = max(visible_rect.width * visible_rect.height, 0.0)
        if visible_rect.is_empty or visible_area <= 0:
            continue
        visible_coverages.append(min(visible_area / page_area, 1.0))

    if not visible_coverages:
        return 0, 0.0
    return len(visible_coverages), max(visible_coverages)


def _error_result(
    *,
    path: Path,
    project_root: Path,
    content_hash: str,
    file_size: int,
    issue_code: PdfIssueCode,
    message: str,
) -> PdfDocumentExtraction:
    return PdfDocumentExtraction(
        document_title=path.stem,
        file_name=path.name,
        source_path=_source_path(path, project_root),
        content_hash=content_hash,
        file_size_bytes=file_size,
        page_count=0,
        text_page_count=0,
        image_page_count=0,
        empty_page_count=0,
        failed_page_count=0,
        pages=[],
        status=PdfDocumentStatus.ERROR,
        issues=[PdfIssue(code=issue_code, message=message)],
    )


def extract_pdf_file(
    pdf_path: str | Path,
    *,
    project_root: str | Path = PROJECT_ROOT,
    known_hash: str | None = None,
) -> PdfDocumentExtraction:
    """PDF 한 개를 읽기 전용으로 열어 모든 물리 페이지의 결과를 반환한다."""

    root = Path(project_root)
    path = Path(pdf_path)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()

    if not path.is_file():
        raise FileNotFoundError(f"PDF 파일을 찾을 수 없습니다: {path}")

    file_size = path.stat().st_size
    content_hash = known_hash or calculate_file_hash(path)
    if file_size == 0:
        return _error_result(
            path=path,
            project_root=root,
            content_hash=content_hash,
            file_size=file_size,
            issue_code=PdfIssueCode.EMPTY_FILE,
            message="PDF 파일이 비어 있습니다.",
        )

    try:
        document = pymupdf.open(str(path))
    except (pymupdf.FileDataError, RuntimeError, ValueError, OSError) as error:
        return _error_result(
            path=path,
            project_root=root,
            content_hash=content_hash,
            file_size=file_size,
            issue_code=PdfIssueCode.PDF_OPEN_FAILED,
            message=f"PDF를 열 수 없습니다: {error}",
        )

    with document:
        if document.needs_pass:
            return _error_result(
                path=path,
                project_root=root,
                content_hash=content_hash,
                file_size=file_size,
                issue_code=PdfIssueCode.PASSWORD_REQUIRED,
                message="암호화된 PDF는 비밀번호 없이 처리할 수 없습니다.",
            )

        metadata = document.metadata or {}
        metadata_title = str(metadata.get("title") or "").strip()
        document_title = metadata_title or path.stem
        page_count = document.page_count
        pages: list[PdfPageExtraction] = []
        issues: list[PdfIssue] = []

        for page_index in range(page_count):
            page_number = page_index + 1
            try:
                page = document.load_page(page_index)
                text = _extract_page_text(page)
            except Exception as error:
                message = f"{page_number}쪽 텍스트 추출에 실패했습니다: {error}"
                pages.append(
                    PdfPageExtraction(
                        page_index=page_index,
                        page_number=page_number,
                        status=PdfPageStatus.FAILED,
                        error_message=message,
                    )
                )
                issues.append(
                    PdfIssue(
                        code=PdfIssueCode.PAGE_EXTRACTION_FAILED,
                        page_number=page_number,
                        message=message,
                    )
                )
                continue

            if text:
                pages.append(
                    PdfPageExtraction(
                        page_index=page_index,
                        page_number=page_number,
                        text=text,
                        status=PdfPageStatus.TEXT,
                    )
                )
                continue

            try:
                image_count, max_image_coverage = _inspect_page_images(page)
            except Exception as error:
                message = f"{page_number}쪽 이미지 분류에 실패했습니다: {error}"
                pages.append(
                    PdfPageExtraction(
                        page_index=page_index,
                        page_number=page_number,
                        status=PdfPageStatus.FAILED,
                        error_message=message,
                    )
                )
                issues.append(
                    PdfIssue(
                        code=PdfIssueCode.PAGE_CLASSIFICATION_FAILED,
                        page_number=page_number,
                        message=message,
                    )
                )
                continue

            if image_count:
                message = (
                    f"{page_number}쪽은 직접 추출되는 텍스트 없이 "
                    "표시 이미지만 포함합니다."
                )
                pages.append(
                    PdfPageExtraction(
                        page_index=page_index,
                        page_number=page_number,
                        status=PdfPageStatus.IMAGE,
                        image_count=image_count,
                        max_image_coverage=max_image_coverage,
                    )
                )
                issues.append(
                    PdfIssue(
                        code=PdfIssueCode.IMAGE_PAGE,
                        page_number=page_number,
                        message=message,
                    )
                )
                continue

            message = f"{page_number}쪽에서 추출 가능한 내용을 찾지 못했습니다."
            pages.append(
                PdfPageExtraction(
                    page_index=page_index,
                    page_number=page_number,
                    status=PdfPageStatus.EMPTY,
                )
            )
            issues.append(
                PdfIssue(
                    code=PdfIssueCode.EMPTY_PAGE,
                    page_number=page_number,
                    message=message,
                )
            )

    text_page_count = sum(page.status is PdfPageStatus.TEXT for page in pages)
    image_page_count = sum(page.status is PdfPageStatus.IMAGE for page in pages)
    empty_page_count = sum(page.status is PdfPageStatus.EMPTY for page in pages)
    failed_page_count = sum(page.status is PdfPageStatus.FAILED for page in pages)

    if page_count == 0 or (text_page_count == 0 and failed_page_count == 0):
        status = PdfDocumentStatus.EMPTY_DOCUMENT
        issues.append(
            PdfIssue(
                code=PdfIssueCode.NO_EXTRACTABLE_TEXT,
                message="PDF에서 추출 가능한 텍스트가 없습니다.",
            )
        )
    elif text_page_count == 0:
        status = PdfDocumentStatus.ERROR
        issues.append(
            PdfIssue(
                code=PdfIssueCode.NO_EXTRACTABLE_TEXT,
                message="페이지 추출 실패로 사용할 수 있는 텍스트가 없습니다.",
            )
        )
    elif failed_page_count:
        status = PdfDocumentStatus.PARTIAL
    elif empty_page_count or image_page_count:
        status = PdfDocumentStatus.SUCCESS_WITH_WARNINGS
    else:
        status = PdfDocumentStatus.SUCCESS

    return PdfDocumentExtraction(
        document_title=document_title,
        file_name=path.name,
        source_path=_source_path(path, root),
        content_hash=content_hash,
        file_size_bytes=file_size,
        page_count=page_count,
        text_page_count=text_page_count,
        image_page_count=image_page_count,
        empty_page_count=empty_page_count,
        failed_page_count=failed_page_count,
        pages=pages,
        status=status,
        issues=issues,
    )


def process_pdf_directory(
    input_directory: str | Path = DEFAULT_PDF_INPUT_DIRECTORY,
    *,
    project_root: str | Path = PROJECT_ROOT,
) -> PdfBatchExtraction:
    """폴더의 PDF를 추출하고 같은 SHA-256을 가진 파일을 중복으로 표시한다."""

    root = Path(project_root)
    directory = Path(input_directory)
    if not directory.is_absolute():
        directory = root / directory
    directory = directory.resolve()

    documents: list[PdfDocumentExtraction] = []
    original_by_hash: dict[str, str] = {}
    paths_by_hash: dict[str, list[str]] = {}

    for pdf_path in list_pdf_files(directory):
        content_hash = calculate_file_hash(pdf_path)
        result = extract_pdf_file(
            pdf_path,
            project_root=root,
            known_hash=content_hash,
        )

        original_path = original_by_hash.get(content_hash)
        if original_path is None:
            original_by_hash[content_hash] = result.source_path
            paths_by_hash[content_hash] = [result.source_path]
        else:
            paths_by_hash[content_hash].append(result.source_path)
            result = result.model_copy(
                update={
                    "is_duplicate": True,
                    "duplicate_of": original_path,
                    "issues": [
                        *result.issues,
                        PdfIssue(
                            code=PdfIssueCode.DUPLICATE_FILE,
                            message=f"동일한 내용의 PDF가 이미 있습니다: {original_path}",
                        ),
                    ],
                }
            )

        documents.append(result)

    duplicate_groups = [
        DuplicatePdfGroup(
            content_hash=content_hash,
            original_source_path=source_paths[0],
            duplicate_source_paths=source_paths[1:],
        )
        for content_hash, source_paths in paths_by_hash.items()
        if len(source_paths) > 1
    ]

    return PdfBatchExtraction(
        input_directory=_source_path(directory, root),
        documents=documents,
        duplicate_groups=duplicate_groups,
    )
