"""실제 모델 다운로드 없는 SentenceTransformer 어댑터 테스트."""

from __future__ import annotations

from typing import Any

from src.retrieval.embeddings import SentenceTransformerEmbeddingProvider


class FakeSentenceTransformer:
    def __init__(self) -> None:
        self.max_seq_length = 0
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def encode(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        self.calls.append((texts, kwargs))
        return [[float(len(text)), 1.0] for text in texts]


def test_query_and_passage_prefixes_are_applied_without_model_download() -> None:
    fake_model = FakeSentenceTransformer()
    factory_calls: list[tuple[str, dict[str, Any]]] = []

    def factory(model_name: str, **kwargs: Any) -> FakeSentenceTransformer:
        factory_calls.append((model_name, kwargs))
        return fake_model

    provider = SentenceTransformerEmbeddingProvider(
        model_name="test/korean-model",
        revision="revision-1",
        device="cpu",
        normalize=True,
        query_prefix="query: ",
        passage_prefix="passage: ",
        max_length=256,
        model_factory=factory,
    )
    document_vectors = provider.embed_documents(["장학금 기준", "졸업 요건"])
    query_vector = provider.embed_query("장학금은 어떻게 받나요?")

    assert factory_calls == [
        ("test/korean-model", {"device": "cpu", "revision": "revision-1"})
    ]
    assert fake_model.max_seq_length == 256
    assert fake_model.calls[0][0] == [
        "passage: 장학금 기준",
        "passage: 졸업 요건",
    ]
    assert fake_model.calls[1][0] == ["query: 장학금은 어떻게 받나요?"]
    assert fake_model.calls[0][1]["normalize_embeddings"] is True
    assert len(document_vectors) == 2
    assert len(query_vector) == 2
    assert len(provider.fingerprint) == 64
