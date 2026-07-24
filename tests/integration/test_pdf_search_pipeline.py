"""실제 PyMuPDF 추출부터 Chroma 검색까지의 원본 불변 통합 테스트."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from pathlib import Path

import pymupdf

from src.retrieval.search_service import PdfSearchService
from src.retrieval.vector_store import ChromaVectorStore


class PipelineEmbeddingProvider:
    fingerprint = hashlib.sha256(b"pipeline-fake-embedding-v1").hexdigest()

    @staticmethod
    def _vector(text: str) -> list[float]:
        normalized = text.casefold()
        values = [
            float("장학금" in normalized or "scholarship" in normalized),
            float("졸업" in normalized or "graduation" in normalized),
            0.0,
        ]
        if not any(values):
            values[-1] = 1.0
        norm = math.sqrt(sum(value * value for value in values))
        return [value / norm for value in values]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_three_page_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True)
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Graduation requirements")
    document.new_page()
    document.new_page().insert_text((72, 72), "Scholarship selection criteria")
    document.save(path)
    document.close()


def test_real_pdf_pipeline_preserves_page_number_and_original_file(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "data" / "raw" / "pdfs" / "academic.pdf"
    _write_three_page_pdf(pdf_path)
    original_hash = _sha256(pdf_path)
    original_stat = pdf_path.stat()

    provider = PipelineEmbeddingProvider()
    store = ChromaVectorStore(
        persist_directory=tmp_path / "data" / "vector_db",
        collection_name="pipeline_test",
        embedding_fingerprint=provider.fingerprint,
    )
    with PdfSearchService(
        embedding_provider=provider,
        vector_store=store,
        chunk_size=500,
        chunk_overlap=50,
        top_k=5,
        min_retrieval_score=0.1,
        dedup_similarity_threshold=0.95,
        project_root=tmp_path,
    ) as service:
        report = service.index_pdf(pdf_path)
        results = service.search("장학금 선발 기준", top_k=1)

        assert report.source_page_count == 3
        assert report.indexed_page_numbers == [1, 3]
        assert report.empty_page_numbers == [2]
        assert results[0].document_title == "academic"
        assert results[0].page_number == 3
        assert results[0].content == "Scholarship selection criteria"

        deleted = service.delete_document_index(report.document_id)
        assert deleted.deleted_chunk_count == 2

    current_stat = pdf_path.stat()
    assert pdf_path.exists()
    assert _sha256(pdf_path) == original_hash
    assert current_stat.st_size == original_stat.st_size
    assert current_stat.st_mtime_ns == original_stat.st_mtime_ns
