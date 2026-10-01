"""One shared search service per Streamlit process."""
import atexit
import streamlit as st
from src.config import get_settings
from src.retrieval.document_search_service import DocumentSearchService


@st.cache_resource(show_spinner=False)
def get_search_service():
    service = DocumentSearchService.from_settings(get_settings())
    atexit.register(service.close)
    return service


def synchronize():
    from src.ingestion.build_corpus import build_corpus
    from src.operations import preserve_corpus_on_failure
    settings = get_settings()
    with preserve_corpus_on_failure(settings.project_root):
        corpus = build_corpus(settings.project_root)
        if corpus.report["errors"]:
            raise ValueError("전처리 오류가 있습니다. 처리 보고서를 확인하세요. 기존 색인은 유지됩니다.")
        # Embeddings are fully prepared before modifying the active index.
        report = get_search_service().index_corpus(corpus.documents_path)
        return report
