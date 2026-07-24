"""한국어 지원 Sentence Transformers 임베딩 어댑터와 포트."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from typing import Any, Protocol, runtime_checkable


class EmbeddingError(RuntimeError):
    """임베딩 모델을 로드하거나 실행할 수 없을 때 발생한다."""


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def fingerprint(self) -> str:
        ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...


class SentenceTransformerEmbeddingProvider:
    """모델을 최초 사용 시 로드하는 sentence-transformers 구현."""

    def __init__(
        self,
        *,
        model_name: str,
        revision: str | None,
        device: str,
        normalize: bool,
        query_prefix: str,
        passage_prefix: str,
        max_length: int,
        model_factory: Callable[..., Any] | None = None,
    ) -> None:
        if not model_name.strip():
            raise ValueError("model_name은 비워 둘 수 없습니다.")
        if max_length <= 0:
            raise ValueError("max_length는 1 이상이어야 합니다.")

        self._model_name = model_name.strip()
        self._revision = revision
        self._device = device.strip() or "cpu"
        self._normalize = normalize
        self._query_prefix = query_prefix
        self._passage_prefix = passage_prefix
        self._max_length = max_length
        self._model_factory = model_factory
        self._model: Any | None = None

        payload = {
            "model_name": self._model_name,
            "revision": self._revision or "",
            "normalize": self._normalize,
            "query_prefix": self._query_prefix,
            "passage_prefix": self._passage_prefix,
            "max_length": self._max_length,
        }
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self._fingerprint = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model

        factory = self._model_factory
        if factory is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as error:
                raise EmbeddingError(
                    "sentence-transformers 패키지를 불러올 수 없습니다."
                ) from error
            factory = SentenceTransformer

        kwargs: dict[str, Any] = {"device": self._device}
        if self._revision:
            kwargs["revision"] = self._revision
        try:
            model = factory(self._model_name, **kwargs)
            model.max_seq_length = self._max_length
        except Exception as error:
            raise EmbeddingError(
                "임베딩 모델을 로드할 수 없습니다. 모델 설정과 로컬 캐시를 확인하세요."
            ) from error

        self._model = model
        return model

    def _encode(self, texts: Sequence[str], *, prefix: str) -> list[list[float]]:
        if not texts:
            return []
        prepared: list[str] = []
        for text in texts:
            stripped = text.strip()
            if not stripped:
                raise ValueError("임베딩 입력 텍스트는 비워 둘 수 없습니다.")
            prepared.append(f"{prefix}{stripped}")

        model = self._load_model()
        try:
            encoded = model.encode(
                prepared,
                convert_to_numpy=True,
                normalize_embeddings=self._normalize,
                show_progress_bar=False,
            )
        except Exception as error:
            raise EmbeddingError("텍스트 임베딩 생성에 실패했습니다.") from error

        converted = encoded.tolist() if hasattr(encoded, "tolist") else encoded
        if converted and isinstance(converted[0], (int, float)):
            converted = [converted]
        try:
            vectors = [
                [float(value) for value in vector]
                for vector in converted
            ]
        except (TypeError, ValueError) as error:
            raise EmbeddingError("임베딩 모델이 올바른 벡터를 반환하지 않았습니다.") from error

        if len(vectors) != len(prepared) or any(not vector for vector in vectors):
            raise EmbeddingError("임베딩 결과 개수 또는 차원이 올바르지 않습니다.")
        return vectors

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode(texts, prefix=self._passage_prefix)

    def embed_query(self, text: str) -> list[float]:
        return self._encode([text], prefix=self._query_prefix)[0]
