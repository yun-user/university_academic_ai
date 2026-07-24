"""PowerShell에서 통합 corpus 색인과 검색을 실행하는 CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from src.config import ConfigurationError, get_settings
from src.retrieval.document_search_service import (
    CorpusLoadError,
    DocumentSearchService,
)
from src.retrieval.document_vector_store import DocumentVectorStoreError
from src.retrieval.embeddings import EmbeddingError


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
    parser = argparse.ArgumentParser(description="PDF·CSV·TXT 통합 검색 CLI")
    commands = parser.add_subparsers(dest="command", required=True)

    rebuild = commands.add_parser(
        "rebuild",
        help="documents.jsonl에서 통합 Chroma 컬렉션을 안전하게 다시 생성",
    )
    rebuild.add_argument(
        "--corpus",
        type=Path,
        default=None,
        help="기본값: data/processed/documents.jsonl",
    )

    search = commands.add_parser("search", help="한국어 질문으로 통합 문서 검색")
    search.add_argument("question")
    search.add_argument("--top-k", type=int, default=None)
    search.add_argument("--min-score", type=float, default=None)
    search.add_argument("--department", default=None)
    search.add_argument("--document-type", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = get_settings()
        with DocumentSearchService.from_settings(settings) as service:
            if args.command == "rebuild":
                _json(service.rebuild_corpus(args.corpus))
                return 0
            if args.command == "search":
                _json(
                    service.search(
                        args.question,
                        top_k=args.top_k,
                        min_score=args.min_score,
                        department=args.department,
                        document_type=args.document_type,
                    )
                )
                return 0
    except (
        ConfigurationError,
        CorpusLoadError,
        DocumentVectorStoreError,
        EmbeddingError,
        ValueError,
    ) as error:
        print(f"통합 검색 명령을 실행할 수 없습니다: {error}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
