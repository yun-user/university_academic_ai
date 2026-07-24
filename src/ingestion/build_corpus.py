"""PDF, CSV, TXT 학사자료를 검색 전 단계의 JSONL corpus로 변환한다.

이 모듈은 원본 파일을 읽기만 한다. PDF는 기존 PyMuPDF 추출기를 재사용하고,
CSV 값은 숫자로 변환하지 않아 학수번호와 같은 선행 0을 보존한다.
"""

from __future__ import annotations

import codecs
import csv
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from src.config import PROJECT_ROOT
from src.ingestion.pdf_extractor import extract_pdf_file
from src.ingestion.pdf_models import PdfDocumentStatus, PdfPageStatus
from src.logging_config import configure_logging, get_logger


LOGGER = get_logger(__name__)

MANIFEST_RELATIVE_PATH = Path("data/metadata/documents_manifest.csv")
PDF_RELATIVE_DIRECTORY = Path("data/raw/pdfs")
CSV_RELATIVE_DIRECTORY = Path("data/raw/tables")
TXT_RELATIVE_DIRECTORY = Path("data/raw/text")
PROCESSED_RELATIVE_DIRECTORY = Path("data/processed")
DOCUMENTS_FILE_NAME = "documents.jsonl"
REPORT_FILE_NAME = "ingestion_report.json"

MANIFEST_FIELDS = (
    "document_id",
    "file_name",
    "file_type",
    "document_type",
    "source_year",
    "effective_from",
    "effective_to",
    "department",
    "admission_year_from",
    "admission_year_to",
    "track",
    "authority",
    "is_current",
    "source_url",
)

RECORD_FIELDS = (
    "document_id",
    "file_name",
    "file_type",
    "document_type",
    "source_year",
    "effective_from",
    "effective_to",
    "department",
    "admission_year_from",
    "admission_year_to",
    "track",
    "authority",
    "is_current",
    "source_url",
    "page_number",
    "row_number",
    "title",
    "text",
    "metadata",
    "image_only",
    "document_image_only",
    "page_status",
    "searchable",
)

REPORT_FIELDS = (
    "total_files",
    "success_files",
    "failed_files",
    "pdf_files",
    "text_pdf_files",
    "image_pdf_files",
    "pdf_pages",
    "csv_files",
    "csv_rows",
    "txt_files",
    "warnings",
    "errors",
)

_TRUE_VALUES = {"1", "true", "yes", "y", "on"}
_FALSE_VALUES = {"0", "false", "no", "n", "off"}
_HASH_READ_SIZE = 1024 * 1024


@dataclass(frozen=True, slots=True)
class CorpusBuildResult:
    """한 번의 corpus 빌드가 만든 데이터와 출력 경로."""

    documents: list[dict[str, Any]]
    report: dict[str, Any]
    documents_path: Path
    report_path: Path


@dataclass(slots=True)
class _ManifestCatalog:
    entries: list[dict[str, str]] = field(default_factory=list)
    indices_by_file_name: dict[str, list[int]] = field(default_factory=dict)
    matched_indices: set[int] = field(default_factory=set)
    encoding: str | None = None

    def match(self, file_name: str) -> dict[str, str] | None:
        indices = self.indices_by_file_name.get(_file_name_key(file_name), [])
        if not indices:
            return None
        self.matched_indices.update(indices)
        return self.entries[indices[0]]


def _new_report() -> dict[str, Any]:
    return {
        "total_files": 0,
        "success_files": 0,
        "failed_files": 0,
        "pdf_files": 0,
        "text_pdf_files": 0,
        "image_pdf_files": 0,
        "pdf_pages": 0,
        "csv_files": 0,
        "csv_rows": 0,
        "txt_files": 0,
        "warnings": [],
        "errors": [],
    }


def _add_issue(
    report: dict[str, Any],
    bucket: str,
    *,
    code: str,
    message: str,
    file_name: str | None = None,
    page_number: int | None = None,
    row_number: int | None = None,
) -> None:
    issue: dict[str, Any] = {"code": code, "message": message}
    if file_name is not None:
        issue["file_name"] = file_name
    if page_number is not None:
        issue["page_number"] = page_number
    if row_number is not None:
        issue["row_number"] = row_number
    report[bucket].append(issue)


def _file_name_key(file_name: str) -> str:
    return file_name.strip().casefold()


def _clean_manifest_row(row: dict[str | None, str | None]) -> dict[str, str]:
    return {
        str(key).strip(): "" if value is None else str(value).strip()
        for key, value in row.items()
        if key is not None
    }


def _detect_utf8_encoding(path: Path) -> str:
    """BOM만 검사해 UTF-8-SIG와 BOM 없는 UTF-8을 구분한다."""

    with path.open("rb") as source:
        prefix = source.read(len(codecs.BOM_UTF8))
    return "utf-8-sig" if prefix == codecs.BOM_UTF8 else "utf-8"


def _load_manifest(path: Path, report: dict[str, Any]) -> _ManifestCatalog:
    catalog = _ManifestCatalog()
    if not path.is_file():
        _add_issue(
            report,
            "warnings",
            code="MANIFEST_NOT_FOUND",
            message="메타데이터 manifest를 찾지 못해 기본 메타데이터로 처리합니다.",
            file_name=path.name,
        )
        return catalog

    try:
        catalog.encoding = _detect_utf8_encoding(path)
        with path.open(
            "r",
            encoding=catalog.encoding,
            errors="strict",
            newline="",
        ) as source:
            reader = csv.DictReader(source)
            headers = [str(header).strip() for header in (reader.fieldnames or [])]
            if not headers:
                raise ValueError("manifest에 헤더가 없습니다.")

            missing_columns = [field for field in MANIFEST_FIELDS if field not in headers]
            if missing_columns:
                _add_issue(
                    report,
                    "warnings",
                    code="MANIFEST_COLUMNS_MISSING",
                    message=(
                        "manifest에 일부 권장 열이 없습니다: "
                        + ", ".join(missing_columns)
                    ),
                    file_name=path.name,
                )

            for row_number, raw_row in enumerate(reader, start=2):
                row = _clean_manifest_row(raw_row)
                entry_index = len(catalog.entries)
                catalog.entries.append(row)
                file_name = row.get("file_name", "")
                if not file_name:
                    _add_issue(
                        report,
                        "warnings",
                        code="MANIFEST_FILE_NAME_MISSING",
                        message="manifest 행에 file_name이 없습니다.",
                        file_name=path.name,
                        row_number=row_number,
                    )
                    continue

                normalized_name = file_name.replace("\\", "/")
                if "/" in normalized_name or normalized_name in {".", ".."}:
                    _add_issue(
                        report,
                        "warnings",
                        code="MANIFEST_FILE_NAME_INVALID",
                        message="manifest file_name은 하위 경로 없이 파일명만 허용합니다.",
                        file_name=file_name,
                        row_number=row_number,
                    )
                    continue

                key = _file_name_key(file_name)
                existing = catalog.indices_by_file_name.setdefault(key, [])
                if existing:
                    _add_issue(
                        report,
                        "warnings",
                        code="DUPLICATE_MANIFEST_FILE",
                        message="같은 file_name의 manifest 행이 중복되어 첫 행을 사용합니다.",
                        file_name=file_name,
                        row_number=row_number,
                    )
                existing.append(entry_index)
    except (OSError, UnicodeError, csv.Error, ValueError) as error:
        _add_issue(
            report,
            "errors",
            code="MANIFEST_READ_FAILED",
            message=f"manifest를 읽을 수 없습니다: {error}",
            file_name=path.name,
        )

    return catalog


def _relative_source_path(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.name


def _discover_files(
    directory: Path,
    suffix: str,
    report: dict[str, Any],
) -> list[Path]:
    if not directory.exists():
        _add_issue(
            report,
            "warnings",
            code="INPUT_DIRECTORY_MISSING",
            message="입력 폴더가 없어 해당 형식을 건너뜁니다.",
            file_name=directory.as_posix(),
        )
        return []
    if not directory.is_dir():
        _add_issue(
            report,
            "errors",
            code="INPUT_PATH_NOT_DIRECTORY",
            message="입력 경로가 폴더가 아닙니다.",
            file_name=directory.as_posix(),
        )
        return []

    discovered: list[Path] = []
    try:
        entries = list(directory.iterdir())
    except OSError as error:
        _add_issue(
            report,
            "errors",
            code="INPUT_DIRECTORY_READ_FAILED",
            message=f"입력 폴더를 읽을 수 없습니다: {error}",
            file_name=directory.as_posix(),
        )
        return []

    all_files: list[Path] = []
    resolved_directory = directory.resolve()
    for path in entries:
        if path.is_dir():
            _add_issue(
                report,
                "warnings",
                code="INPUT_SUBDIRECTORY_IGNORED",
                message="입력 폴더 바로 아래의 파일만 처리합니다.",
                file_name=path.name,
            )
            continue
        if not path.is_file():
            continue
        try:
            resolved_path = path.resolve(strict=True)
        except OSError as error:
            _add_issue(
                report,
                "warnings",
                code="INPUT_FILE_RESOLVE_FAILED",
                message=f"입력 파일 경로를 확인할 수 없어 건너뜁니다: {error}",
                file_name=path.name,
            )
            continue
        if not resolved_path.is_relative_to(resolved_directory):
            _add_issue(
                report,
                "warnings",
                code="INPUT_FILE_OUTSIDE_DIRECTORY",
                message="입력 폴더 밖을 가리키는 파일 링크를 처리하지 않습니다.",
                file_name=path.name,
            )
            continue
        all_files.append(path)

    for path in sorted(
        all_files,
        key=lambda item: (item.name.casefold(), item.name),
    ):
        if path.suffix.casefold() == suffix:
            discovered.append(path)
        else:
            _add_issue(
                report,
                "warnings",
                code="UNSUPPORTED_FILE_IGNORED",
                message=(
                    f"{directory.name} 입력 폴더에서 지원하지 않는 형식이라 "
                    "처리하지 않았습니다."
                ),
                file_name=path.name,
            )
    return discovered


def _match_manifest(
    path: Path,
    file_type: str,
    catalog: _ManifestCatalog,
    report: dict[str, Any],
) -> dict[str, str] | None:
    manifest = catalog.match(path.name)
    if manifest is None:
        _add_issue(
            report,
            "warnings",
            code="MANIFEST_ENTRY_MISSING",
            message="manifest에 없는 파일을 기본 메타데이터로 처리합니다.",
            file_name=path.name,
        )
        return None

    manifest_file_type = manifest.get("file_type", "").casefold()
    if manifest_file_type and manifest_file_type != file_type:
        _add_issue(
            report,
            "warnings",
            code="MANIFEST_FILE_TYPE_MISMATCH",
            message=(
                f"manifest file_type({manifest_file_type})과 실제 형식"
                f"({file_type})이 달라 실제 형식을 사용합니다."
            ),
            file_name=path.name,
        )

    current_value = manifest.get("is_current", "").strip().casefold()
    if current_value and current_value not in _TRUE_VALUES | _FALSE_VALUES:
        _add_issue(
            report,
            "warnings",
            code="INVALID_IS_CURRENT",
            message="is_current 값을 boolean으로 해석할 수 없어 null로 저장합니다.",
            file_name=path.name,
        )
    return manifest


def _add_unmatched_manifest_warnings(
    catalog: _ManifestCatalog,
    report: dict[str, Any],
) -> None:
    for index, entry in enumerate(catalog.entries):
        file_name = entry.get("file_name", "")
        if not file_name or index in catalog.matched_indices:
            continue
        _add_issue(
            report,
            "warnings",
            code="MANIFEST_FILE_NOT_FOUND",
            message="manifest에 등록되어 있지만 실제 입력 파일을 찾지 못했습니다.",
            file_name=file_name,
        )


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(_HASH_READ_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def _nullable_manifest_value(
    manifest: dict[str, str] | None,
    key: str,
) -> str | None:
    if manifest is None:
        return None
    value = manifest.get(key, "").strip()
    return value or None


def _parse_is_current(manifest: dict[str, str] | None) -> bool | None:
    value = _nullable_manifest_value(manifest, "is_current")
    if value is None:
        return None
    normalized = value.casefold()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return None


def _fallback_document_id(source_path: str) -> str:
    stable_id = uuid5(NAMESPACE_URL, source_path.casefold())
    return f"UNMANIFESTED-{stable_id.hex[:16].upper()}"


def _base_record(
    *,
    path: Path,
    project_root: Path,
    file_type: str,
    content_hash: str,
    manifest: dict[str, str] | None,
    title: str | None = None,
) -> dict[str, Any]:
    source_path = _relative_source_path(path, project_root)
    manifest_id = _nullable_manifest_value(manifest, "document_id")
    metadata: dict[str, Any] = {
        "source_path": source_path,
        "source_file_hash": content_hash,
        "manifest_registered": manifest is not None,
        "manifest": dict(manifest) if manifest is not None else {},
    }
    return {
        "document_id": manifest_id or _fallback_document_id(source_path),
        "file_name": path.name,
        "file_type": file_type,
        "document_type": _nullable_manifest_value(manifest, "document_type"),
        "source_year": _nullable_manifest_value(manifest, "source_year"),
        "effective_from": _nullable_manifest_value(manifest, "effective_from"),
        "effective_to": _nullable_manifest_value(manifest, "effective_to"),
        "department": _nullable_manifest_value(manifest, "department"),
        "admission_year_from": _nullable_manifest_value(
            manifest, "admission_year_from"
        ),
        "admission_year_to": _nullable_manifest_value(
            manifest, "admission_year_to"
        ),
        "track": _nullable_manifest_value(manifest, "track"),
        "authority": _nullable_manifest_value(manifest, "authority"),
        "is_current": _parse_is_current(manifest),
        "source_url": _nullable_manifest_value(manifest, "source_url"),
        "page_number": None,
        "row_number": None,
        "title": title or path.stem,
        "text": "",
        "metadata": metadata,
        "image_only": False,
        "document_image_only": False,
        "page_status": None,
        "searchable": False,
    }


def _process_pdf(
    path: Path,
    *,
    project_root: Path,
    manifest: dict[str, str] | None,
    report: dict[str, Any],
) -> list[dict[str, Any]]:
    try:
        extraction = extract_pdf_file(path, project_root=project_root)
    except (OSError, RuntimeError, ValueError) as error:
        report["failed_files"] += 1
        _add_issue(
            report,
            "errors",
            code="PDF_PROCESSING_FAILED",
            message=f"PDF 처리 중 예외가 발생했습니다: {error}",
            file_name=path.name,
        )
        return []

    report["pdf_pages"] += extraction.page_count
    if extraction.status is PdfDocumentStatus.ERROR:
        report["failed_files"] += 1
        for issue in extraction.issues:
            _add_issue(
                report,
                "errors",
                code=f"PDF_{issue.code.value.upper()}",
                message=issue.message,
                file_name=path.name,
                page_number=issue.page_number,
            )
        if not extraction.issues:
            _add_issue(
                report,
                "errors",
                code="PDF_EXTRACTION_FAILED",
                message="PDF에서 사용할 수 있는 페이지를 추출하지 못했습니다.",
                file_name=path.name,
            )
        return []

    report["success_files"] += 1
    document_image_only = (
        extraction.text_page_count == 0
        and extraction.image_page_count > 0
    )
    canonical_title = (
        _nullable_manifest_value(manifest, "title") or path.stem
    )
    if document_image_only:
        report["image_pdf_files"] += 1
    elif extraction.text_page_count:
        report["text_pdf_files"] += 1

    for issue in extraction.issues:
        _add_issue(
            report,
            "warnings",
            code=f"PDF_{issue.code.value.upper()}",
            message=issue.message,
            file_name=path.name,
            page_number=issue.page_number,
        )

    records: list[dict[str, Any]] = []
    for page in extraction.pages:
        record = _base_record(
            path=path,
            project_root=project_root,
            file_type="pdf",
            content_hash=extraction.content_hash,
            manifest=manifest,
            title=canonical_title,
        )
        record["page_number"] = page.page_number
        record["text"] = page.text
        record["image_only"] = document_image_only
        record["document_image_only"] = document_image_only
        record["page_status"] = page.status.value
        record["searchable"] = (
            page.status is PdfPageStatus.TEXT and bool(page.text.strip())
        )
        record["metadata"].update(
            {
                "pdf_status": extraction.status.value,
                "extraction_page_status": page.status.value,
                "page_error": page.error_message,
                "pdf_page_count": extraction.page_count,
                "extracted_pdf_title": extraction.document_title,
                "image_count": page.image_count,
                "max_image_coverage": page.max_image_coverage,
            }
        )
        records.append(record)

    if not extraction.pages:
        record = _base_record(
            path=path,
            project_root=project_root,
            file_type="pdf",
            content_hash=extraction.content_hash,
            manifest=manifest,
            title=canonical_title,
        )
        record["image_only"] = document_image_only
        record["document_image_only"] = document_image_only
        record["metadata"].update(
            {
                "pdf_status": extraction.status.value,
                "extraction_page_status": None,
                "page_error": None,
                "pdf_page_count": 0,
                "extracted_pdf_title": extraction.document_title,
                "image_count": 0,
                "max_image_coverage": 0.0,
            }
        )
        records.append(record)
    return records


def _unique_headers(
    raw_headers: list[str],
    *,
    path: Path,
    report: dict[str, Any],
) -> list[str]:
    headers: list[str] = []
    occurrences: dict[str, int] = {}
    for column_index, raw_header in enumerate(raw_headers, start=1):
        header = raw_header.strip() or f"column_{column_index}"
        count = occurrences.get(header, 0) + 1
        occurrences[header] = count
        if count > 1:
            unique_header = f"{header}_{count}"
            _add_issue(
                report,
                "warnings",
                code="CSV_DUPLICATE_HEADER",
                message=f"중복 열 이름을 {unique_header}(으)로 저장합니다.",
                file_name=path.name,
            )
            header = unique_header
        headers.append(header)
    return headers


def _process_csv(
    path: Path,
    *,
    project_root: Path,
    manifest: dict[str, str] | None,
    report: dict[str, Any],
) -> list[dict[str, Any]]:
    try:
        content_hash = _file_hash(path)
        encoding = _detect_utf8_encoding(path)
        with path.open(
            "r",
            encoding=encoding,
            errors="strict",
            newline="",
        ) as source:
            reader = csv.reader(source)
            try:
                raw_headers = next(reader)
            except StopIteration:
                raw_headers = []

            if not raw_headers:
                raise ValueError("CSV 헤더가 없습니다.")
            headers = _unique_headers(raw_headers, path=path, report=report)

            records: list[dict[str, Any]] = []
            for row_number, raw_values in enumerate(reader, start=1):
                values = list(raw_values)
                row_headers = list(headers)
                if len(values) != len(headers):
                    _add_issue(
                        report,
                        "warnings",
                        code="CSV_COLUMN_COUNT_MISMATCH",
                        message=(
                            f"데이터 열 수({len(values)})가 헤더 열 수"
                            f"({len(headers)})와 다릅니다."
                        ),
                        file_name=path.name,
                        row_number=row_number,
                    )
                if len(values) < len(headers):
                    values.extend([""] * (len(headers) - len(values)))
                elif len(values) > len(headers):
                    for extra_index in range(len(headers), len(values)):
                        base_name = f"extra_column_{extra_index + 1}"
                        unique_name = base_name
                        suffix = 2
                        while unique_name in row_headers:
                            unique_name = f"{base_name}_{suffix}"
                            suffix += 1
                        row_headers.append(unique_name)

                row = {
                    header: "" if value is None else str(value)
                    for header, value in zip(row_headers, values, strict=True)
                }
                record = _base_record(
                    path=path,
                    project_root=project_root,
                    file_type="csv",
                    content_hash=content_hash,
                    manifest=manifest,
                )
                record["row_number"] = row_number
                record["text"] = "\n".join(
                    f"{column}: {value}" for column, value in row.items()
                )
                record["searchable"] = any(
                    value.strip() for value in row.values()
                )
                record["metadata"].update(
                    {
                        "row": row,
                        "column_order": row_headers,
                        "encoding": encoding,
                    }
                )
                source_page = row.get("출처페이지", "").strip()
                if source_page:
                    record["metadata"]["source_page_number"] = source_page
                records.append(record)
    except (OSError, UnicodeError, csv.Error, ValueError) as error:
        report["failed_files"] += 1
        _add_issue(
            report,
            "errors",
            code="CSV_READ_FAILED",
            message=f"CSV를 읽을 수 없습니다: {error}",
            file_name=path.name,
        )
        return []

    report["success_files"] += 1
    report["csv_rows"] += len(records)
    if not records:
        _add_issue(
            report,
            "warnings",
            code="CSV_NO_DATA_ROWS",
            message="CSV에 데이터 행이 없습니다.",
            file_name=path.name,
        )
    return records


def _process_txt(
    path: Path,
    *,
    project_root: Path,
    manifest: dict[str, str] | None,
    report: dict[str, Any],
) -> list[dict[str, Any]]:
    try:
        content_hash = _file_hash(path)
        encoding = _detect_utf8_encoding(path)
        with path.open(
            "r",
            encoding=encoding,
            errors="strict",
            newline=None,
        ) as source:
            text = source.read()
    except (OSError, UnicodeError) as error:
        report["failed_files"] += 1
        _add_issue(
            report,
            "errors",
            code="TXT_READ_FAILED",
            message=f"TXT를 읽을 수 없습니다: {error}",
            file_name=path.name,
        )
        return []

    record = _base_record(
        path=path,
        project_root=project_root,
        file_type="txt",
        content_hash=content_hash,
        manifest=manifest,
    )
    record["text"] = text
    record["searchable"] = bool(text.strip())
    record["metadata"]["encoding"] = encoding
    report["success_files"] += 1
    if not text.strip():
        _add_issue(
            report,
            "warnings",
            code="TXT_EMPTY",
            message="TXT 파일에 검색할 텍스트가 없습니다.",
            file_name=path.name,
        )
    return [record]


def _write_outputs(
    documents: list[dict[str, Any]],
    report: dict[str, Any],
    processed_directory: Path,
) -> tuple[Path, Path]:
    processed_directory.mkdir(parents=True, exist_ok=True)
    documents_path = processed_directory / DOCUMENTS_FILE_NAME
    report_path = processed_directory / REPORT_FILE_NAME
    documents_temp_path = processed_directory / f".{DOCUMENTS_FILE_NAME}.tmp"
    report_temp_path = processed_directory / f".{REPORT_FILE_NAME}.tmp"

    with documents_temp_path.open(
        "w",
        encoding="utf-8",
        errors="strict",
        newline="\n",
    ) as output:
        for record in documents:
            output.write(
                json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
            )

    with report_temp_path.open(
        "w",
        encoding="utf-8",
        errors="strict",
        newline="\n",
    ) as output:
        json.dump(
            report,
            output,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
        )
        output.write("\n")

    documents_temp_path.replace(documents_path)
    report_temp_path.replace(report_path)
    return documents_path, report_path


def build_corpus(
    project_root: str | Path = PROJECT_ROOT,
) -> CorpusBuildResult:
    """프로젝트의 raw 자료 전체를 읽고 JSONL corpus와 report를 만든다."""

    root = Path(project_root).resolve()
    report = _new_report()
    catalog = _load_manifest(root / MANIFEST_RELATIVE_PATH, report)

    pdf_files = _discover_files(root / PDF_RELATIVE_DIRECTORY, ".pdf", report)
    csv_files = _discover_files(root / CSV_RELATIVE_DIRECTORY, ".csv", report)
    txt_files = _discover_files(root / TXT_RELATIVE_DIRECTORY, ".txt", report)

    report["pdf_files"] = len(pdf_files)
    report["csv_files"] = len(csv_files)
    report["txt_files"] = len(txt_files)
    report["total_files"] = len(pdf_files) + len(csv_files) + len(txt_files)

    documents: list[dict[str, Any]] = []
    for path in pdf_files:
        manifest = _match_manifest(path, "pdf", catalog, report)
        documents.extend(
            _process_pdf(
                path,
                project_root=root,
                manifest=manifest,
                report=report,
            )
        )

    for path in csv_files:
        manifest = _match_manifest(path, "csv", catalog, report)
        documents.extend(
            _process_csv(
                path,
                project_root=root,
                manifest=manifest,
                report=report,
            )
        )

    for path in txt_files:
        manifest = _match_manifest(path, "txt", catalog, report)
        documents.extend(
            _process_txt(
                path,
                project_root=root,
                manifest=manifest,
                report=report,
            )
        )

    _add_unmatched_manifest_warnings(catalog, report)
    report["document_records"] = len(documents)
    documents_path, report_path = _write_outputs(
        documents,
        report,
        root / PROCESSED_RELATIVE_DIRECTORY,
    )
    return CorpusBuildResult(
        documents=documents,
        report=report,
        documents_path=documents_path,
        report_path=report_path,
    )


def main() -> int:
    """`python -m src.ingestion.build_corpus` 명령 진입점."""

    try:
        configure_logging(os.getenv("LOG_LEVEL", "INFO"))
        result = build_corpus()
    except Exception as error:  # CLI 최상위 안전망
        LOGGER.exception("통합 corpus 빌드에 실패했습니다.")
        print(f"통합 corpus 빌드에 실패했습니다: {error}", file=sys.stderr)
        return 1

    summary = {
        field: result.report[field]
        for field in REPORT_FIELDS
        if field not in {"warnings", "errors"}
    }
    summary["warning_count"] = len(result.report["warnings"])
    summary["error_count"] = len(result.report["errors"])
    summary["documents_path"] = result.documents_path.relative_to(
        PROJECT_ROOT
    ).as_posix()
    summary["report_path"] = result.report_path.relative_to(PROJECT_ROOT).as_posix()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if result.report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
