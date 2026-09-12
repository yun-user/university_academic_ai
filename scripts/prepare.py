"""Validate source processing and synchronize search; preserve the last index on extraction failure."""
from src.config import get_settings
from src.ingestion.build_corpus import build_corpus
from src.retrieval.document_search_service import DocumentSearchService
from src.operations import project_lock


def main():
    settings = get_settings()
    with project_lock(settings.project_root):
        corpus = build_corpus(settings.project_root)
        if corpus.report["errors"]:
            print("문서 처리 오류가 있습니다. data/processed/ingestion_report.json을 확인하세요.")
            return 1
        with DocumentSearchService.from_settings(settings) as service:
            report = service.index_corpus(corpus.documents_path)
        print(f"준비 완료: {report.indexed_document_count}개 문서, {report.indexed_chunk_count}개 검색 문단")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
