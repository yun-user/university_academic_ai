"""PowerShell에서 PDF 색인·검색·삭제·재색인을 실행하는 CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import UUID

from src.config import get_settings
from src.retrieval.search_service import PdfSearchService


def _json(value: object) -> None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif isinstance(value, list):
        value = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in value
        ]
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PDF 문서 검색 전용 CLI")
    commands = parser.add_subparsers(dest="command", required=True)

    index = commands.add_parser("index", help="폴더의 PDF를 ChromaDB에 색인")
    index.add_argument(
        "--input-directory",
        type=Path,
        default=None,
        help="기본값: 설정된 RAW_DATA_DIR/pdfs",
    )

    search = commands.add_parser("search", help="한국어 질문으로 PDF 청크 검색")
    search.add_argument("question")
    search.add_argument("--top-k", type=int, default=None)
    search.add_argument("--min-score", type=float, default=None)

    delete = commands.add_parser(
        "delete-index",
        help="원본 PDF는 유지하고 특정 문서의 검색 색인만 삭제",
    )
    delete.add_argument("document_id", type=UUID)

    reindex = commands.add_parser("reindex", help="기존 document_id로 PDF 재색인")
    reindex.add_argument("pdf_path", type=Path)
    reindex.add_argument("document_id", type=UUID)
    return parser


def main() -> None:
    args = _parser().parse_args()
    settings = get_settings()
    with PdfSearchService.from_settings(settings) as service:
        if args.command == "index":
            directory = args.input_directory or settings.raw_data_dir / "pdfs"
            _json(service.index_pdf_directory(directory))
            return
        if args.command == "search":
            _json(
                service.search(
                    args.question,
                    top_k=args.top_k,
                    min_score=args.min_score,
                )
            )
            return
        if args.command == "delete-index":
            _json(service.delete_document_index(args.document_id))
            return
        if args.command == "reindex":
            _json(
                service.reindex_pdf(
                    args.pdf_path,
                    document_id=args.document_id,
                )
            )


if __name__ == "__main__":
    main()
