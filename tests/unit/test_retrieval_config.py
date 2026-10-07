"""검색 설정 환경변수 우선순위 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import ConfigurationError, clear_settings_cache, get_settings


@pytest.mark.parametrize("name", ["DENSE_WEIGHT", "KEYWORD_WEIGHT", "CRAWL_DELAY_SECONDS"])
@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_nonfinite_configuration_is_rejected(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    clear_settings_cache()
    try:
        with pytest.raises(ConfigurationError):
            get_settings()
    finally:
        clear_settings_cache()


def test_requested_retrieval_environment_variables_are_loaded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("EMBEDDING_MODEL_NAME", "test/korean-embedding")
    monkeypatch.setenv("CHUNK_SIZE", "240")
    monkeypatch.setenv("CHUNK_OVERLAP", "30")
    monkeypatch.setenv("TOP_K", "4")
    monkeypatch.setenv("MIN_RETRIEVAL_SCORE", "0.42")
    monkeypatch.setenv("VECTOR_DB_PATH", str(tmp_path / "vectors"))
    clear_settings_cache()

    try:
        settings = get_settings()
        assert settings.embedding_model_name == "test/korean-embedding"
        assert settings.chunk_size == 240
        assert settings.chunk_overlap == 30
        assert settings.top_k == 4
        assert settings.min_retrieval_score == 0.42
        assert settings.vector_db_path == (tmp_path / "vectors").resolve()
    finally:
        clear_settings_cache()


def test_primary_retrieval_variables_ignore_invalid_legacy_values(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CHUNK_SIZE", "240")
    monkeypatch.setenv("CHUNK_TARGET_CHARS", "invalid")
    monkeypatch.setenv("CHUNK_OVERLAP", "30")
    monkeypatch.setenv("CHUNK_OVERLAP_CHARS", "invalid")
    monkeypatch.setenv("TOP_K", "4")
    monkeypatch.setenv("EVIDENCE_TOP_K", "invalid")
    monkeypatch.setenv("VECTOR_DB_PATH", str(tmp_path / "vectors"))
    monkeypatch.setenv("VECTOR_DB_DIR", "ignored-legacy-path")
    clear_settings_cache()

    try:
        settings = get_settings()
        assert settings.chunk_size == 240
        assert settings.chunk_overlap == 30
        assert settings.top_k == 4
        assert settings.vector_db_path == (tmp_path / "vectors").resolve()
    finally:
        clear_settings_cache()


def test_vector_db_path_cannot_be_inside_raw_data_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    raw_dir = tmp_path / "raw"
    monkeypatch.setenv("RAW_DATA_DIR", str(raw_dir))
    monkeypatch.setenv("VECTOR_DB_PATH", str(raw_dir / "pdfs" / "chroma"))
    clear_settings_cache()

    try:
        with pytest.raises(ConfigurationError, match="RAW_DATA_DIR 밖"):
            get_settings()
    finally:
        clear_settings_cache()
