"""PowerShell에서 통합 corpus 색인과 검색을 실행하는 CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from src.config import ConfigurationError, get_settings
from src.retrieval.document_search_service import (
    CorpusLoadError,
    DocumentSearchService,
)
from src.retrieval.course_search import (
    course_summary,
    parse_course_info,
    truncate_text,
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


def _field(item: object, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _location(item: object) -> str:
    page_number = _field(item, "page_number")
    row_number = _field(item, "row_number")
    if page_number is not None:
        return f"{page_number}쪽"
    if row_number is not None:
        return f"CSV {row_number}행"
    return "문서 전체"


def _print_search_results(
    results: Sequence[object],
    *,
    exact_match_count: int = 0,
    semantic_fallback_used: bool = False,
) -> None:
    if exact_match_count > 0:
        print(f"조건에 맞는 과목 {exact_match_count}개를 찾았습니다")
    elif semantic_fallback_used:
        print("정확한 교과과정 항목을 찾지 못해 관련 자료를 표시합니다")

    if not results:
        print(
            "등록된 학사 자료에서 확인할 수 없습니다. "
            "학교 학사 담당 부서에 문의해 주세요."
        )
        return

    for index, result in enumerate(results, start=1):
        text = str(_field(result, "text", ""))
        course = (
            parse_course_info(text)
            if _field(result, "file_type") == "csv"
            else None
        )
        title = course.course_name if course is not None else _field(
            result,
            "title",
            "제목 미지정",
        )
        summary = (
            course_summary(course)
            if course is not None
            else truncate_text(text, limit=200)
        )
        print(f"[{index}] {title}")
        print(f"- 문서 유형: {_field(result, 'document_type', '미지정')}")
        print(f"- 학과: {_field(result, 'department', '미지정')}")
        print(f"- 기준연도: {_field(result, 'source_year') or '미지정'}")
        print(f"- 페이지 또는 CSV 행: {_location(result)}")
        print(f"- 출처: {_field(result, 'file_name', '미지정')}")
        if exact_match_count > 0:
            print("- 일치 방식: 구조화 조건 정확 일치")
        else:
            print(f"- 유사도: {float(_field(result, 'score', 0.0)):.3f}")
        print(f"- 내용 요약: {summary or '요약할 내용 없음'}")
        if index < len(results):
            print()


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
    search.add_argument("--top-k", type=int, default=3)
    search.add_argument("--min-score", type=float, default=None)
    search.add_argument("--department", default=None)
    search.add_argument("--document-type", default=None)
    search.add_argument(
        "--json",
        action="store_true",
        help="전체 검색 결과를 기존 JSON 형식으로 출력",
    )
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
                response = service.search_with_context(
                    args.question,
                    top_k=args.top_k,
                    min_score=args.min_score,
                    department=args.department,
                    document_type=args.document_type,
                )
                if args.json:
                    _json(response.results)
                else:
                    _print_search_results(
                        response.results,
                        exact_match_count=response.exact_match_count,
                        semantic_fallback_used=response.semantic_fallback_used,
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
