"""애플리케이션 공통 로깅 설정과 비밀값 마스킹."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable


LOGGER_NAME = "university_academic_ai"
_KEY_VALUE_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|authorization|token|secret|password)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/]+=*")


def _redact(message: str, secrets: tuple[str, ...]) -> str:
    redacted = _KEY_VALUE_SECRET_PATTERN.sub(r"\1\2***", message)
    redacted = _BEARER_PATTERN.sub("Bearer ***", redacted)
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "***")
    return redacted


class RedactingFormatter(logging.Formatter):
    """완전히 포맷된 로그와 예외 문자열에서 비밀값을 제거한다."""

    def __init__(self, format_string: str, secrets: Iterable[str] = ()) -> None:
        super().__init__(format_string)
        self._secrets = tuple(secret for secret in secrets if secret)

    def format(self, record: logging.LogRecord) -> str:
        return _redact(super().format(record), self._secrets)


def configure_logging(
    level: str = "INFO",
    *,
    secrets: Iterable[str] = (),
) -> logging.Logger:
    """프로젝트 로거를 중복 핸들러 없이 설정한다."""

    normalized_level = level.upper()
    numeric_level = logging.getLevelNamesMapping().get(normalized_level)
    if numeric_level is None:
        raise ValueError(f"지원하지 않는 로그 레벨입니다: {level}")

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(numeric_level)
    logger.propagate = False

    handler = logging.StreamHandler()
    handler.setLevel(numeric_level)
    handler.setFormatter(
        RedactingFormatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            secrets,
        )
    )

    logger.handlers.clear()
    logger.addHandler(handler)
    return logger


def get_logger(name: str) -> logging.Logger:
    """프로젝트 로거의 자식 로거를 반환한다."""

    return logging.getLogger(f"{LOGGER_NAME}.{name}")
