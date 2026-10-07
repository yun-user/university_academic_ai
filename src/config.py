"""환경변수와 TOML 기본값을 검증된 설정 객체로 변환한다.

이 모듈은 설정을 읽기만 하며 디렉터리 생성, 모델 다운로드, DB 연결 같은
부작용을 일으키지 않는다.
"""

from __future__ import annotations

import os
import math
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULTS_PATH = PROJECT_ROOT / "config" / "defaults.toml"
DOTENV_PATH = PROJECT_ROOT / ".env"


class ConfigurationError(RuntimeError):
    """안전하게 실행할 수 없는 설정값이 발견됐을 때 발생한다."""


@dataclass(frozen=True, slots=True)
class Settings:
    """애플리케이션의 불변 런타임 설정."""

    project_root: Path = field(repr=False)
    app_name: str
    environment: str
    log_level: str
    display_timezone: str

    data_dir: Path = field(repr=False)
    raw_data_dir: Path = field(repr=False)
    processed_data_dir: Path = field(repr=False)
    snapshot_data_dir: Path = field(repr=False)
    catalog_dir: Path = field(repr=False)
    vector_db_dir: Path = field(repr=False)
    keyword_index_dir: Path = field(repr=False)
    quarantine_dir: Path = field(repr=False)

    embedding_model_name: str
    embedding_model_revision: str | None
    embedding_device: str
    embedding_normalize: bool
    embedding_query_prefix: str
    embedding_passage_prefix: str
    embedding_max_length: int

    reranker_enabled: bool
    reranker_model_name: str | None
    reranker_model_revision: str | None

    llm_enabled: bool
    llm_provider: str
    llm_model_name: str | None
    llm_base_url: str | None
    llm_api_key: str | None = field(repr=False)
    llm_timeout_seconds: int

    chunk_target_chars: int
    chunk_max_chars: int
    chunk_overlap_chars: int

    dense_top_k: int
    keyword_top_k: int
    rerank_top_k: int
    evidence_top_k: int
    rrf_k: int
    dense_weight: float
    keyword_weight: float
    min_retrieval_score: float
    retrieval_dedup_threshold: float

    crawl_delay_seconds: float
    crawl_max_pages: int
    upload_max_megabytes: int
    pdf_max_pages: int
    ocr_dpi: int
    ocr_languages: str

    @property
    def llm_configured(self) -> bool:
        """LLM 생성에 필요한 비밀값과 모델명이 있는지 반환한다."""

        return bool(self.llm_api_key and self.llm_model_name)

    @property
    def llm_available(self) -> bool:
        """명시적 활성화와 필수 설정이 모두 갖춰졌는지 반환한다."""

        provider_supported = self.llm_provider.strip().lower() in {
            "openai",
            "openai_compatible",
        }
        return self.llm_enabled and self.llm_configured and provider_supported

    @property
    def runtime_mode(self) -> str:
        """화면과 로그에서 사용할 안전한 실행 모드 이름."""

        return "generation-enabled" if self.llm_available else "retrieval-only"

    @property
    def vector_db_path(self) -> Path:
        """검색 구현에서 사용하는 ChromaDB 영속 경로."""

        return self.vector_db_dir

    @property
    def chunk_size(self) -> int:
        return self.chunk_target_chars

    @property
    def chunk_overlap(self) -> int:
        return self.chunk_overlap_chars

    @property
    def top_k(self) -> int:
        return self.evidence_top_k

    def safe_summary(self) -> dict[str, str | bool]:
        """비밀값과 내부 절대경로를 제외한 상태 정보만 반환한다."""

        return {
            "environment": self.environment,
            "log_level": self.log_level,
            "runtime_mode": self.runtime_mode,
            "llm_enabled": self.llm_enabled,
            "llm_configured": self.llm_configured,
            "llm_available": self.llm_available,
            "embedding_model": self.embedding_model_name,
            "reranker_enabled": self.reranker_enabled,
        }


def _read_defaults(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as file:
            return tomllib.load(file)
    except FileNotFoundError as exc:
        raise ConfigurationError(
            "기본 설정 파일(config/defaults.toml)을 찾을 수 없습니다."
        ) from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(
            "기본 설정 파일(config/defaults.toml)의 형식이 올바르지 않습니다."
        ) from exc


def _required(mapping: Mapping[str, Any], *keys: str) -> Any:
    value: Any = mapping
    for key in keys:
        if not isinstance(value, Mapping) or key not in value:
            dotted_key = ".".join(keys)
            raise ConfigurationError(f"필수 기본 설정이 없습니다: {dotted_key}")
        value = value[key]
    return value


def _env_text(name: str, default: Any) -> str:
    raw = os.getenv(name)
    return str(default).strip() if raw is None else raw.strip()


def _env_text_with_legacy(primary: str, legacy: str, default: Any) -> str:
    """우선 환경변수가 있으면 legacy 값을 읽거나 검증하지 않는다."""

    if os.getenv(primary) is not None:
        return _env_text(primary, default)
    return _env_text(legacy, default)


def _env_optional_text(name: str, default: Any = None) -> str | None:
    value = _env_text(name, "" if default is None else default)
    return value or None


def _env_bool(name: str, default: Any) -> bool:
    raw = os.getenv(name)
    if raw is None:
        if isinstance(default, bool):
            return default
        raw = str(default)

    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name}은 true 또는 false여야 합니다.")


def _env_int(name: str, default: Any) -> int:
    raw = os.getenv(name)
    try:
        return int(default if raw is None else raw)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{name}은 정수여야 합니다.") from exc


def _env_int_with_legacy(primary: str, legacy: str, default: Any) -> int:
    """우선 환경변수가 있으면 legacy 정수값을 파싱하지 않는다."""

    selected = primary if os.getenv(primary) is not None else legacy
    return _env_int(selected, default)


def _env_float(name: str, default: Any) -> float:
    raw = os.getenv(name)
    try:
        value = float(default if raw is None else raw)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{name}은 숫자여야 합니다.") from exc
    if not math.isfinite(value):
        raise ConfigurationError(f"{name}은 유한한 숫자여야 합니다.")
    return value


def _resolve_project_path(value: str) -> Path:
    path = Path(os.path.expandvars(value)).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _validate(settings: Settings) -> Settings:
    if not settings.app_name:
        raise ConfigurationError("APP_NAME은 비워 둘 수 없습니다.")

    allowed_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if settings.log_level not in allowed_levels:
        raise ConfigurationError(
            "LOG_LEVEL은 DEBUG, INFO, WARNING, ERROR, CRITICAL 중 하나여야 합니다."
        )

    try:
        ZoneInfo(settings.display_timezone)
    except ZoneInfoNotFoundError as exc:
        raise ConfigurationError(
            "DISPLAY_TIMEZONE에 유효한 IANA 시간대를 입력하세요."
        ) from exc

    if not settings.embedding_model_name:
        raise ConfigurationError("EMBEDDING_MODEL_NAME은 비워 둘 수 없습니다.")
    if settings.embedding_max_length <= 0:
        raise ConfigurationError("EMBEDDING_MAX_LENGTH는 1 이상이어야 합니다.")
    if settings.reranker_enabled and not settings.reranker_model_name:
        raise ConfigurationError(
            "RERANKER_ENABLED=true이면 RERANKER_MODEL_NAME이 필요합니다."
        )
    positive_values = {
        "LLM_TIMEOUT_SECONDS": settings.llm_timeout_seconds,
        "CHUNK_TARGET_CHARS": settings.chunk_target_chars,
        "CHUNK_MAX_CHARS": settings.chunk_max_chars,
        "DENSE_TOP_K": settings.dense_top_k,
        "KEYWORD_TOP_K": settings.keyword_top_k,
        "RERANK_TOP_K": settings.rerank_top_k,
        "EVIDENCE_TOP_K": settings.evidence_top_k,
        "RRF_K": settings.rrf_k,
        "CRAWL_MAX_PAGES": settings.crawl_max_pages,
        "UPLOAD_MAX_MB": settings.upload_max_megabytes,
        "PDF_MAX_PAGES": settings.pdf_max_pages,
        "OCR_DPI": settings.ocr_dpi,
    }
    invalid = [name for name, value in positive_values.items() if value <= 0]
    if invalid:
        raise ConfigurationError(
            f"다음 설정은 1 이상이어야 합니다: {', '.join(invalid)}"
        )

    if settings.chunk_overlap_chars < 0:
        raise ConfigurationError("CHUNK_OVERLAP_CHARS는 0 이상이어야 합니다.")
    if settings.chunk_target_chars > settings.chunk_max_chars:
        raise ConfigurationError(
            "CHUNK_TARGET_CHARS는 CHUNK_MAX_CHARS 이하여야 합니다."
        )
    if settings.chunk_overlap_chars >= settings.chunk_target_chars:
        raise ConfigurationError(
            "CHUNK_OVERLAP_CHARS는 CHUNK_TARGET_CHARS보다 작아야 합니다."
        )
    if settings.crawl_delay_seconds < 0:
        raise ConfigurationError("CRAWL_DELAY_SECONDS는 0 이상이어야 합니다.")
    if settings.dense_weight < 0 or settings.keyword_weight < 0:
        raise ConfigurationError("검색 결합 가중치는 0 이상이어야 합니다.")
    if settings.dense_weight + settings.keyword_weight <= 0:
        raise ConfigurationError("검색 결합 가중치 합은 0보다 커야 합니다.")

    if not 0.0 <= settings.min_retrieval_score <= 1.0:
        raise ConfigurationError(
            "MIN_RETRIEVAL_SCORE는 0 이상 1 이하여야 합니다."
        )
    if not 0.0 <= settings.retrieval_dedup_threshold <= 1.0:
        raise ConfigurationError(
            "RETRIEVAL_DEDUP_THRESHOLD는 0 이상 1 이하여야 합니다."
        )

    vector_db_uses_raw_area = (
        settings.vector_db_dir == settings.raw_data_dir
        or settings.vector_db_dir.is_relative_to(settings.raw_data_dir)
    )
    if vector_db_uses_raw_area:
        raise ConfigurationError(
            "VECTOR_DB_PATH는 원본 보존 영역인 RAW_DATA_DIR 밖에 있어야 합니다."
        )

    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """`.env`와 TOML을 읽어 검증된 설정을 반환한다."""

    load_dotenv(dotenv_path=DOTENV_PATH, override=False)
    defaults = _read_defaults(DEFAULTS_PATH)

    app = _required(defaults, "app")
    paths = _required(defaults, "paths")
    embedding = _required(defaults, "models", "embedding")
    reranker = _required(defaults, "models", "reranker")
    llm = _required(defaults, "models", "llm")
    chunk = _required(defaults, "chunk")
    retrieval = _required(defaults, "retrieval")
    crawl = _required(defaults, "crawl")
    upload = _required(defaults, "upload")
    ocr = _required(defaults, "ocr")

    settings = Settings(
        project_root=PROJECT_ROOT,
        app_name=_env_text("APP_NAME", _required(app, "name")),
        environment=_env_text("APP_ENV", _required(app, "environment")),
        log_level=_env_text("LOG_LEVEL", _required(app, "log_level")).upper(),
        display_timezone=_env_text(
            "DISPLAY_TIMEZONE", _required(app, "display_timezone")
        ),
        data_dir=_resolve_project_path(
            _env_text("DATA_DIR", _required(paths, "data"))
        ),
        raw_data_dir=_resolve_project_path(
            _env_text("RAW_DATA_DIR", _required(paths, "raw"))
        ),
        processed_data_dir=_resolve_project_path(
            _env_text("PROCESSED_DATA_DIR", _required(paths, "processed"))
        ),
        snapshot_data_dir=_resolve_project_path(
            _env_text("SNAPSHOT_DATA_DIR", _required(paths, "snapshots"))
        ),
        catalog_dir=_resolve_project_path(
            _env_text("CATALOG_DIR", _required(paths, "catalog"))
        ),
        vector_db_dir=_resolve_project_path(
            _env_text_with_legacy(
                "VECTOR_DB_PATH", "VECTOR_DB_DIR", _required(paths, "vector_db")
            )
        ),
        keyword_index_dir=_resolve_project_path(
            _env_text("KEYWORD_INDEX_DIR", _required(paths, "keyword_index"))
        ),
        quarantine_dir=_resolve_project_path(
            _env_text("QUARANTINE_DIR", _required(paths, "quarantine"))
        ),
        embedding_model_name=_env_text(
            "EMBEDDING_MODEL_NAME", _required(embedding, "name")
        ),
        embedding_model_revision=_env_optional_text(
            "EMBEDDING_MODEL_REVISION", _required(embedding, "revision")
        ),
        embedding_device=_env_text(
            "EMBEDDING_DEVICE", _required(embedding, "device")
        ),
        embedding_normalize=_env_bool(
            "EMBEDDING_NORMALIZE", _required(embedding, "normalize")
        ),
        embedding_query_prefix=_env_text(
            "EMBEDDING_QUERY_PREFIX", _required(embedding, "query_prefix")
        ),
        embedding_passage_prefix=_env_text(
            "EMBEDDING_PASSAGE_PREFIX", _required(embedding, "passage_prefix")
        ),
        embedding_max_length=_env_int(
            "EMBEDDING_MAX_LENGTH", _required(embedding, "max_length")
        ),
        reranker_enabled=_env_bool(
            "RERANKER_ENABLED", _required(reranker, "enabled")
        ),
        reranker_model_name=_env_optional_text(
            "RERANKER_MODEL_NAME", _required(reranker, "name")
        ),
        reranker_model_revision=_env_optional_text(
            "RERANKER_MODEL_REVISION", _required(reranker, "revision")
        ),
        llm_enabled=_env_bool("LLM_ENABLED", _required(llm, "enabled")),
        llm_provider=_env_text("LLM_PROVIDER", _required(llm, "provider")),
        llm_model_name=_env_optional_text(
            "LLM_MODEL_NAME", _required(llm, "name")
        ),
        llm_base_url=_env_optional_text(
            "LLM_BASE_URL", _required(llm, "base_url")
        ),
        llm_api_key=_env_optional_text("LLM_API_KEY"),
        llm_timeout_seconds=_env_int(
            "LLM_TIMEOUT_SECONDS", _required(llm, "timeout_seconds")
        ),
        chunk_target_chars=_env_int_with_legacy(
            "CHUNK_SIZE",
            "CHUNK_TARGET_CHARS", _required(chunk, "target_chars"),
        ),
        chunk_max_chars=_env_int(
            "CHUNK_MAX_CHARS", _required(chunk, "max_chars")
        ),
        chunk_overlap_chars=_env_int_with_legacy(
            "CHUNK_OVERLAP",
            "CHUNK_OVERLAP_CHARS", _required(chunk, "overlap_chars"),
        ),
        dense_top_k=_env_int(
            "DENSE_TOP_K", _required(retrieval, "dense_top_k")
        ),
        keyword_top_k=_env_int(
            "KEYWORD_TOP_K", _required(retrieval, "keyword_top_k")
        ),
        rerank_top_k=_env_int(
            "RERANK_TOP_K", _required(retrieval, "rerank_top_k")
        ),
        evidence_top_k=_env_int_with_legacy(
            "TOP_K",
            "EVIDENCE_TOP_K", _required(retrieval, "evidence_top_k"),
        ),
        rrf_k=_env_int("RRF_K", _required(retrieval, "rrf_k")),
        dense_weight=_env_float(
            "DENSE_WEIGHT", _required(retrieval, "dense_weight")
        ),
        keyword_weight=_env_float(
            "KEYWORD_WEIGHT", _required(retrieval, "keyword_weight")
        ),
        min_retrieval_score=_env_float(
            "MIN_RETRIEVAL_SCORE", _required(retrieval, "min_score")
        ),
        retrieval_dedup_threshold=_env_float(
            "RETRIEVAL_DEDUP_THRESHOLD",
            _required(retrieval, "dedup_similarity_threshold"),
        ),
        crawl_delay_seconds=_env_float(
            "CRAWL_DELAY_SECONDS", _required(crawl, "delay_seconds")
        ),
        crawl_max_pages=_env_int(
            "CRAWL_MAX_PAGES", _required(crawl, "max_pages")
        ),
        upload_max_megabytes=_env_int(
            "UPLOAD_MAX_MB", _required(upload, "max_megabytes")
        ),
        pdf_max_pages=_env_int(
            "PDF_MAX_PAGES", _required(upload, "pdf_max_pages")
        ),
        ocr_dpi=_env_int("OCR_DPI", _required(ocr, "dpi")),
        ocr_languages=_env_text(
            "OCR_LANGUAGES", _required(ocr, "languages")
        ),
    )
    return _validate(settings)


def clear_settings_cache() -> None:
    """테스트나 명시적 설정 재로딩을 위해 캐시를 비운다."""

    get_settings.cache_clear()
