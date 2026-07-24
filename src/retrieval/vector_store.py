"""외부 임베딩을 사용하는 ChromaDB 영속 벡터 저장소."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import chromadb
from chromadb.config import Settings as ChromaSettings

from src.models import DocumentType
from src.retrieval.models import SearchableChunk, VectorCandidate, VectorUpsertReport


COLLECTION_SCHEMA_VERSION = 1
DISTANCE_METRIC = "cosine"
FILTERABLE_METADATA_FIELDS = frozenset({"department", "document_type"})
MetadataFilterField = Literal["department", "document_type"]


class VectorStoreError(RuntimeError):
    """벡터 저장소 계약 또는 영속 색인 상태가 올바르지 않을 때 발생한다."""


class ChromaVectorStore:
    """Chroma 세부 형식을 공통 검색 모델로 변환하는 어댑터."""

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
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            embedding_function=None,
            configuration={"hnsw": {"space": "cosine"}},
            metadata={
                "embedding_fingerprint": self._embedding_fingerprint,
                "schema_version": COLLECTION_SCHEMA_VERSION,
                "distance_metric": DISTANCE_METRIC,
            },
        )

        collection_metadata = self._collection.metadata or {}
        stored_fingerprint = collection_metadata.get("embedding_fingerprint")
        if stored_fingerprint != self._embedding_fingerprint:
            self.close()
            raise VectorStoreError(
                "기존 컬렉션의 임베딩 설정이 현재 설정과 다릅니다. "
                "새 컬렉션 이름 또는 벡터 DB 경로를 사용하세요."
            )
        if collection_metadata.get("schema_version") != COLLECTION_SCHEMA_VERSION:
            self.close()
            raise VectorStoreError("기존 ChromaDB 컬렉션의 스키마 버전이 다릅니다.")
        if collection_metadata.get("distance_metric") != DISTANCE_METRIC:
            self.close()
            raise VectorStoreError(
                "기존 ChromaDB 컬렉션이 cosine 거리 방식을 사용하지 않습니다."
            )

    def close(self) -> None:
        """영속 저장을 완료하고 Windows 파일 잠금을 해제한다."""

        if self._closed:
            return
        self._client.close()
        self._closed = True

    def __enter__(self) -> "ChromaVectorStore":
        return self

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        self.close()

    @property
    def persist_directory(self) -> Path:
        return self._persist_directory

    @property
    def collection_name(self) -> str:
        return self._collection_name

    def count(self) -> int:
        return self._collection.count()

    def list_metadata_values(self, field: MetadataFilterField) -> list[str]:
        """UI 필터에 허용된 메타데이터 값만 중복 없이 반환한다."""

        if field not in FILTERABLE_METADATA_FIELDS:
            raise ValueError(f"지원하지 않는 메타데이터 필터입니다: {field}")
        try:
            result = self._collection.get(include=["metadatas"])
        except Exception as error:
            raise VectorStoreError(
                "ChromaDB 필터 선택지 조회에 실패했습니다."
            ) from error

        values = {
            str(metadata.get(field, "")).strip()
            for metadata in (result.get("metadatas") or [])
            if metadata is not None
        }
        values.discard("")
        return sorted(values, key=str.casefold)

    @staticmethod
    def _metadata(searchable: SearchableChunk) -> dict[str, str | int | float | bool]:
        chunk = searchable.chunk
        if chunk.page_number is None:
            raise VectorStoreError("PDF 청크에 page_number가 없습니다.")
        return {
            "document_id": str(chunk.document_id),
            "chunk_id": chunk.chunk_id,
            "document_title": chunk.document_title,
            "document_type": chunk.document_type.value,
            "department": chunk.department,
            "category": chunk.category,
            "source_path": chunk.source_path or "",
            "page_number": chunk.page_number,
            "section_title": chunk.section_title,
            "published_date": (
                chunk.published_date.isoformat() if chunk.published_date else ""
            ),
            "collected_at": chunk.collected_at.isoformat(),
            "content_hash": chunk.content_hash,
            "source_file_hash": searchable.source_file_hash,
        }

    @staticmethod
    def _validate_vectors(
        chunks: Sequence[SearchableChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> list[list[float]]:
        if len(chunks) != len(embeddings):
            raise VectorStoreError("청크 수와 임베딩 수가 다릅니다.")
        if not chunks:
            return []
        if len({chunk.chunk.chunk_id for chunk in chunks}) != len(chunks):
            raise VectorStoreError("한 번의 upsert 요청에 중복 chunk_id가 있습니다.")

        vectors = [[float(value) for value in vector] for vector in embeddings]
        dimensions = {len(vector) for vector in vectors}
        if dimensions == {0} or len(dimensions) != 1:
            raise VectorStoreError("임베딩 벡터 차원이 비어 있거나 서로 다릅니다.")
        return vectors

    def _existing_ids(self, ids: Sequence[str]) -> set[str]:
        if not ids:
            return set()
        result = self._collection.get(ids=list(ids), include=[])
        return set(result.get("ids") or [])

    def upsert_chunks(
        self,
        chunks: Sequence[SearchableChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> VectorUpsertReport:
        vectors = self._validate_vectors(chunks, embeddings)
        if not chunks:
            return VectorUpsertReport(
                attempted_count=0,
                inserted_count=0,
                updated_count=0,
            )

        ids = [item.chunk.chunk_id for item in chunks]
        existing_ids = self._existing_ids(ids)
        try:
            self._collection.upsert(
                ids=ids,
                embeddings=vectors,
                documents=[item.chunk.content for item in chunks],
                metadatas=[self._metadata(item) for item in chunks],
            )
        except Exception as error:
            raise VectorStoreError("ChromaDB 청크 저장에 실패했습니다.") from error

        return VectorUpsertReport(
            attempted_count=len(ids),
            inserted_count=len(set(ids) - existing_ids),
            updated_count=len(existing_ids),
        )

    def _find_document_id(self, where: dict[str, str]) -> UUID | None:
        try:
            result = self._collection.get(
                where=where,
                limit=1,
                include=["metadatas"],
            )
            metadatas = result.get("metadatas") or []
            if not metadatas:
                return None
            return UUID(str(metadatas[0]["document_id"]))
        except (KeyError, TypeError, ValueError) as error:
            raise VectorStoreError(
                "ChromaDB 문서 메타데이터가 올바르지 않습니다."
            ) from error
        except Exception as error:
            raise VectorStoreError("ChromaDB 문서 조회에 실패했습니다.") from error

    def find_document_by_source_file_hash(self, source_file_hash: str) -> UUID | None:
        return self._find_document_id({"source_file_hash": source_file_hash})

    def find_document_by_source_path(self, source_path: str) -> UUID | None:
        return self._find_document_id({"source_path": source_path})

    def get_document_chunk_ids(self, document_id: UUID | str) -> list[str]:
        try:
            result = self._collection.get(
                where={"document_id": str(document_id)},
                include=[],
            )
        except Exception as error:
            raise VectorStoreError("ChromaDB 문서 청크 조회에 실패했습니다.") from error
        return sorted(result.get("ids") or [])

    def replace_document(
        self,
        *,
        document_id: UUID,
        chunks: Sequence[SearchableChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> VectorUpsertReport:
        if not chunks:
            raise VectorStoreError("빈 청크 목록으로 문서를 재색인할 수 없습니다.")
        if any(item.chunk.document_id != document_id for item in chunks):
            raise VectorStoreError("재색인 청크의 document_id가 대상 문서와 다릅니다.")

        previous_ids = set(self.get_document_chunk_ids(document_id))
        report = self.upsert_chunks(chunks, embeddings)
        current_ids = {item.chunk.chunk_id for item in chunks}
        stale_ids = sorted(previous_ids - current_ids)
        if stale_ids:
            self._collection.delete(ids=stale_ids)
        return VectorUpsertReport(
            attempted_count=report.attempted_count,
            inserted_count=report.inserted_count,
            updated_count=report.updated_count,
            removed_stale_count=len(stale_ids),
        )

    def delete_document_index(self, document_id: UUID | str) -> int:
        ids = self.get_document_chunk_ids(document_id)
        if ids:
            try:
                self._collection.delete(ids=ids)
            except Exception as error:
                raise VectorStoreError("ChromaDB 문서 색인 삭제에 실패했습니다.") from error
        return len(ids)

    def query(
        self,
        query_embedding: Sequence[float],
        *,
        fetch_k: int,
        where: dict[str, Any] | None = None,
    ) -> list[VectorCandidate]:
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
            raise VectorStoreError("ChromaDB 검색에 실패했습니다.") from error

        ids = (raw.get("ids") or [[]])[0]
        documents = (raw.get("documents") or [[]])[0]
        metadatas = (raw.get("metadatas") or [[]])[0]
        distances = (raw.get("distances") or [[]])[0]
        candidates: list[VectorCandidate] = []
        try:
            for chunk_id, content, metadata, distance_value in zip(
                ids, documents, metadatas, distances, strict=True
            ):
                distance = max(0.0, float(distance_value))
                score = max(-1.0, min(1.0, 1.0 - distance))
                source_path = str(metadata.get("source_path") or "").strip() or None
                candidates.append(
                    VectorCandidate(
                        document_id=UUID(str(metadata["document_id"])),
                        chunk_id=str(chunk_id),
                        document_title=str(metadata["document_title"]),
                        document_type=DocumentType(str(metadata["document_type"])),
                        department=str(metadata["department"]),
                        page_number=int(metadata["page_number"]),
                        content=str(content),
                        content_hash=str(metadata["content_hash"]),
                        source_path=source_path,
                        distance=distance,
                        score=score,
                    )
                )
        except (KeyError, TypeError, ValueError) as error:
            raise VectorStoreError(
                "ChromaDB 검색 결과 메타데이터가 올바르지 않습니다."
            ) from error

        return sorted(
            candidates,
            key=lambda item: (
                -item.score,
                item.document_title.casefold(),
                item.page_number,
                item.chunk_id,
            ),
        )
