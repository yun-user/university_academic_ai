"""통합 PDF·CSV·TXT corpus용 ChromaDB 저장소."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

import chromadb
from chromadb.config import Settings as ChromaSettings

from src.retrieval.document_models import (
    CorpusChunk,
    CorpusStoreSyncReport,
    DocumentVectorCandidate,
)


DOCUMENT_COLLECTION_SCHEMA_VERSION = 1
DOCUMENT_DISTANCE_METRIC = "cosine"
DocumentMetadataFilter = Literal["department", "document_type", "file_type"]


class DocumentVectorStoreError(RuntimeError):
    """통합 Chroma 컬렉션의 계약이나 상태가 올바르지 않을 때 발생한다."""


class ChromaDocumentVectorStore:
    """PDF 전용 컬렉션과 분리된 통합 corpus Chroma 어댑터."""

    def __init__(
        self,
        *,
        persist_directory: str | Path,
        collection_name: str,
        embedding_fingerprint: str,
    ) -> None:
        if not collection_name.strip():
            raise ValueError("collection_name은 비워 둘 수 없습니다.")
        if not embedding_fingerprint.strip():
            raise ValueError("embedding_fingerprint는 비워 둘 수 없습니다.")

        self._persist_directory = Path(persist_directory).resolve()
        self._persist_directory.mkdir(parents=True, exist_ok=True)
        self._collection_name = collection_name.strip()
        self._embedding_fingerprint = embedding_fingerprint.strip()
        self._closed = False
        self._client = chromadb.PersistentClient(
            path=str(self._persist_directory),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection = self._get_or_create_collection()
        self._validate_collection()

    def _collection_metadata(self) -> dict[str, str | int]:
        return {
            "embedding_fingerprint": self._embedding_fingerprint,
            "schema_version": DOCUMENT_COLLECTION_SCHEMA_VERSION,
            "distance_metric": DOCUMENT_DISTANCE_METRIC,
            "source": "data/processed/documents.jsonl",
        }

    def _get_or_create_collection(self):
        return self._client.get_or_create_collection(
            name=self._collection_name,
            embedding_function=None,
            configuration={"hnsw": {"space": DOCUMENT_DISTANCE_METRIC}},
            metadata=self._collection_metadata(),
        )

    def _validate_collection(self) -> None:
        metadata = self._collection.metadata or {}
        if metadata.get("embedding_fingerprint") != self._embedding_fingerprint:
            self.close()
            raise DocumentVectorStoreError(
                "기존 통합 컬렉션의 임베딩 설정이 현재 설정과 다릅니다. "
                "rebuild 전에 모델 설정을 확인하세요."
            )
        if metadata.get("schema_version") != DOCUMENT_COLLECTION_SCHEMA_VERSION:
            self.close()
            raise DocumentVectorStoreError(
                "기존 통합 Chroma 컬렉션의 스키마 버전이 다릅니다."
            )
        if metadata.get("distance_metric") != DOCUMENT_DISTANCE_METRIC:
            self.close()
            raise DocumentVectorStoreError(
                "통합 Chroma 컬렉션이 cosine 거리를 사용하지 않습니다."
            )

    def close(self) -> None:
        if self._closed:
            return
        self._client.close()
        self._closed = True

    def __enter__(self) -> "ChromaDocumentVectorStore":
        return self

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        self.close()

    @property
    def collection_name(self) -> str:
        return self._collection_name

    def count(self) -> int:
        return self._collection.count()

    def reset_collection(self) -> None:
        """통합 컬렉션만 초기화하고 PDF 전용 컬렉션과 DB 폴더는 보존한다."""

        try:
            collection_names = {
                getattr(collection, "name", str(collection))
                for collection in self._client.list_collections()
            }
            if self._collection_name in collection_names:
                self._client.delete_collection(name=self._collection_name)
            self._collection = self._get_or_create_collection()
            self._validate_collection()
        except Exception as error:
            raise DocumentVectorStoreError(
                "통합 Chroma 컬렉션 초기화에 실패했습니다."
            ) from error

    def list_metadata_values(self, field: DocumentMetadataFilter) -> list[str]:
        if field not in {"department", "document_type", "file_type"}:
            raise ValueError(f"지원하지 않는 메타데이터 필터입니다: {field}")
        try:
            result = self._collection.get(include=["metadatas"])
        except Exception as error:
            raise DocumentVectorStoreError(
                "통합 색인 필터 값 조회에 실패했습니다."
            ) from error
        values = {
            str(metadata.get(field) or "").strip()
            for metadata in (result.get("metadatas") or [])
            if metadata is not None
        }
        values.discard("")
        return sorted(values, key=str.casefold)

    @staticmethod
    def _metadata(chunk: CorpusChunk) -> dict[str, str | int | float | bool]:
        metadata: dict[str, str | int | float | bool] = {
            "document_id": chunk.document_id,
            "chunk_id": chunk.chunk_id,
            "file_name": chunk.file_name,
            "file_type": chunk.file_type,
            "document_type": chunk.document_type,
            "department": chunk.department,
            "title": chunk.title,
            "source_path": chunk.source_path,
            "content_hash": chunk.content_hash,
        }
        optional_text = {
            "source_year": chunk.source_year,
            "effective_from": chunk.effective_from,
            "effective_to": chunk.effective_to,
            "admission_year_from": chunk.admission_year_from,
            "admission_year_to": chunk.admission_year_to,
            "track": chunk.track,
            "authority": chunk.authority,
            "source_url": chunk.source_url,
            "source_file_hash": chunk.source_file_hash,
        }
        for key, value in optional_text.items():
            normalized = str(value or "").strip()
            if normalized:
                metadata[key] = normalized
        if chunk.is_current is not None:
            metadata["is_current"] = chunk.is_current
        if chunk.page_number is not None:
            metadata["page_number"] = chunk.page_number
        if chunk.row_number is not None:
            metadata["row_number"] = chunk.row_number
        return metadata

    @staticmethod
    def _validate_vectors(
        chunks: Sequence[CorpusChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> list[list[float]]:
        if len(chunks) != len(embeddings):
            raise DocumentVectorStoreError("청크 수와 임베딩 수가 다릅니다.")
        if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
            raise DocumentVectorStoreError("색인 요청에 중복 chunk_id가 있습니다.")
        if not chunks:
            return []
        vectors = [[float(value) for value in vector] for vector in embeddings]
        dimensions = {len(vector) for vector in vectors}
        if dimensions == {0} or len(dimensions) != 1:
            raise DocumentVectorStoreError(
                "임베딩 벡터 차원이 비어 있거나 서로 다릅니다."
            )
        return vectors

    def _all_ids(self) -> set[str]:
        result = self._collection.get(include=[])
        return set(result.get("ids") or [])

    def sync_chunks(
        self,
        chunks: Sequence[CorpusChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> CorpusStoreSyncReport:
        """현재 corpus snapshot과 일치하도록 upsert 후 stale 청크를 제거한다."""

        vectors = self._validate_vectors(chunks, embeddings)
        previous_ids = self._all_ids()
        current_ids = {chunk.chunk_id for chunk in chunks}
        if chunks:
            try:
                self._collection.upsert(
                    ids=[chunk.chunk_id for chunk in chunks],
                    embeddings=vectors,
                    documents=[chunk.content for chunk in chunks],
                    metadatas=[self._metadata(chunk) for chunk in chunks],
                )
            except Exception as error:
                raise DocumentVectorStoreError(
                    "통합 문서 청크 저장에 실패했습니다."
                ) from error

        stale_ids = sorted(previous_ids - current_ids)
        if stale_ids:
            try:
                self._collection.delete(ids=stale_ids)
            except Exception as error:
                raise DocumentVectorStoreError(
                    "통합 색인의 stale 청크 삭제에 실패했습니다."
                ) from error
        return CorpusStoreSyncReport(
            attempted_count=len(chunks),
            inserted_count=len(current_ids - previous_ids),
            updated_count=len(current_ids & previous_ids),
            removed_stale_count=len(stale_ids),
        )

    def query(
        self,
        query_embedding: Sequence[float],
        *,
        fetch_k: int,
        where: dict[str, Any] | None = None,
    ) -> list[DocumentVectorCandidate]:
        if fetch_k <= 0:
            raise ValueError("fetch_k는 1 이상이어야 합니다.")
        if not query_embedding:
            raise ValueError("query_embedding은 비워 둘 수 없습니다.")
        record_count = self.count()
        if record_count == 0:
            return []
        try:
            raw: dict[str, Any] = self._collection.query(
                query_embeddings=[[float(value) for value in query_embedding]],
                n_results=min(fetch_k, record_count),
                include=["documents", "metadatas", "distances"],
                where=where,
            )
        except Exception as error:
            raise DocumentVectorStoreError("통합 문서 검색에 실패했습니다.") from error

        ids = (raw.get("ids") or [[]])[0]
        documents = (raw.get("documents") or [[]])[0]
        metadatas = (raw.get("metadatas") or [[]])[0]
        distances = (raw.get("distances") or [[]])[0]
        candidates: list[DocumentVectorCandidate] = []
        try:
            for chunk_id, content, metadata, distance_value in zip(
                ids,
                documents,
                metadatas,
                distances,
                strict=True,
            ):
                distance = max(0.0, float(distance_value))
                score = max(-1.0, min(1.0, 1.0 - distance))
                candidates.append(
                    DocumentVectorCandidate(
                        document_id=str(metadata["document_id"]),
                        chunk_id=str(chunk_id),
                        file_name=str(metadata["file_name"]),
                        file_type=str(metadata["file_type"]),
                        document_type=str(metadata["document_type"]),
                        source_year=_optional_text(metadata, "source_year"),
                        effective_from=_optional_text(metadata, "effective_from"),
                        effective_to=_optional_text(metadata, "effective_to"),
                        department=str(metadata["department"]),
                        admission_year_from=_optional_text(
                            metadata, "admission_year_from"
                        ),
                        admission_year_to=_optional_text(
                            metadata, "admission_year_to"
                        ),
                        track=_optional_text(metadata, "track"),
                        authority=_optional_text(metadata, "authority"),
                        is_current=_optional_bool(metadata, "is_current"),
                        source_url=_optional_text(metadata, "source_url"),
                        page_number=_optional_int(metadata, "page_number"),
                        row_number=_optional_int(metadata, "row_number"),
                        title=str(metadata["title"]),
                        source_path=str(metadata["source_path"]),
                        content=str(content),
                        content_hash=str(metadata["content_hash"]),
                        distance=distance,
                        score=score,
                    )
                )
        except (KeyError, TypeError, ValueError) as error:
            raise DocumentVectorStoreError(
                "통합 Chroma 검색 결과 메타데이터가 올바르지 않습니다."
            ) from error
        return sorted(
            candidates,
            key=lambda item: (
                -item.score,
                item.title.casefold(),
                item.page_number or 0,
                item.row_number or 0,
                item.chunk_id,
            ),
        )

    def indexed_chunk_counts_by_file_type(self) -> dict[str, int]:
        try:
            result = self._collection.get(include=["metadatas"])
        except Exception as error:
            raise DocumentVectorStoreError(
                "형식별 통합 색인 수 조회에 실패했습니다."
            ) from error
        counts = Counter(
            str(metadata.get("file_type") or "")
            for metadata in (result.get("metadatas") or [])
            if metadata
        )
        counts.pop("", None)
        return dict(sorted(counts.items()))


def _optional_text(metadata: dict[str, Any], key: str) -> str | None:
    value = str(metadata.get(key) or "").strip()
    return value or None


def _optional_int(metadata: dict[str, Any], key: str) -> int | None:
    value = metadata.get(key)
    return None if value is None else int(value)


def _optional_bool(metadata: dict[str, Any], key: str) -> bool | None:
    value = metadata.get(key)
    return value if isinstance(value, bool) else None
