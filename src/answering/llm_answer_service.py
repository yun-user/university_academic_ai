"""선택적 LLM 생성과 결정적 답변 fallback을 조정한다."""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Protocol
from src.answering.graduation import reviewed_graduation

from src.answering.answer_service import (
    NO_ACADEMIC_RULE_MESSAGE,
    NO_EVIDENCE_MESSAGE,
    OUTDATED_ANSWER_WARNING,
    AnswerService,
    SearchService,
)
from src.answering.models import (
    AnswerFormat,
    AnswerMode,
    AnswerResponse,
    AnswerSource,
    AnswerStatus,
    deduplicate_answer_sources,
)
from src.answering.prompts import (
    CONFLICT_NOTICE,
    SYSTEM_PROMPT,
    build_user_prompt,
)
from src.retrieval.course_search import parse_course_info
from src.retrieval.document_models import DocumentSearchResult
from src.retrieval.query_intent import (
    QuestionIntent,
    academic_rule_signatures,
    classify_question_intent,
    is_retake_completion_rule_question,
)

if TYPE_CHECKING:
    from src.config import Settings


_JSON_FENCE = re.compile(
    r"^```(?:json)?\s*(?P<body>.*)\s*```$",
    flags=re.IGNORECASE | re.DOTALL,
)
_NUMBER_TOKEN = re.compile(r"(?<!\d)\d+(?:[.,]\d+)*(?!\d)")
_ALPHANUMERIC_CODE = re.compile(
    r"\b(?=[A-Za-z0-9_-]*[A-Za-z])(?=[A-Za-z0-9_-]*\d)"
    r"[A-Za-z0-9_-]{2,}\b"
)
_FIELD_LINE = re.compile(r"^\s*[-*]?\s*([^:\n]{1,60})\s*:\s*(.*?)\s*$")


class LLMProvider(Protocol):
    """검색 기능을 갖지 않는 텍스트 생성 provider의 최소 계약."""

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        timeout_seconds: float,
    ) -> str: ...


class OpenAICompatibleProvider:
    """OpenAI 호환 chat-completions endpoint를 지연 로딩해 호출한다."""

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        base_url: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._model_name = model_name
        self._base_url = base_url

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        timeout_seconds: float,
    ) -> str:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - 설치 환경에 따라 달라짐
            raise RuntimeError("LLM provider dependency is unavailable") from exc

        client_options: dict[str, Any] = {
            "api_key": self._api_key,
            "timeout": timeout_seconds,
            "max_retries": 0,
        }
        if self._base_url:
            client_options["base_url"] = self._base_url
        client = OpenAI(**client_options)
        completion = client.chat.completions.create(
            model=self._model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
        )
        content = completion.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise ValueError("LLM provider returned an empty response")
        return content


class LLMAnswerService:
    """기존 검색/답변 경로 위에서만 동작하는 실패 격리 LLM 계층."""

    def __init__(
        self,
        search_service: SearchService,
        *,
        provider: LLMProvider | None,
        enabled: bool = False,
        timeout_seconds: float = 60,
        logger: logging.Logger | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds는 0보다 커야 합니다.")
        self._deterministic = AnswerService(search_service)
        self._provider = provider
        self._enabled = enabled
        self._timeout_seconds = timeout_seconds
        self._logger = logger or logging.getLogger(__name__)

    @property
    def available(self) -> bool:
        return self._enabled and self._provider is not None

    def answer_question(
        self,
        question: str,
        *,
        top_k: int | None = None,
        min_score: float | None = None,
        department: str | None = None,
        document_type: str | None = None,
    ) -> AnswerResponse:
        """검색은 한 번만 실행하고 모든 LLM 오류를 기존 답변으로 격리한다."""

        deterministic = self._deterministic.answer_question(
            question,
            top_k=top_k,
            min_score=min_score,
            department=department,
            document_type=document_type,
        )
        response = deterministic.search_response
        if response.reviewed_answer or reviewed_graduation(question, response.results):
            return deterministic
        if (
            not self.available
            or deterministic.status is AnswerStatus.INSUFFICIENT_EVIDENCE
            or not response.results
        ):
            return deterministic

        # 구조화 교과과정 값은 생성 모델을 거치지 않는 것이 가장 강한 보존 규칙이다.
        contains_course_rows = any(
            result.file_type == "csv" and parse_course_info(result.text) is not None
            for result in response.results
        )
        if contains_course_rows:
            conflict_ids = _conflicting_evidence_ids(response.results)
            if conflict_ids:
                return _structured_conflict_answer(
                    deterministic,
                    response.results,
                    conflict_ids,
                )
            return deterministic

        # 조건별 이수구분 규정은 일부 조건 누락을 막기 위해 결정적 조립을 유지한다.
        if is_retake_completion_rule_question(question) and any(
            academic_rule_signatures(result.text) for result in response.results
        ):
            return deterministic

        evidence = list(response.results)
        try:
            raw_completion = self._provider.generate(  # type: ignore[union-attr]
                system_prompt=SYSTEM_PROMPT,
                user_prompt=build_user_prompt(question, evidence),
                timeout_seconds=self._timeout_seconds,
            )
            answer_text, cited_ids = _parse_grounded_completion(raw_completion, evidence)
            if answer_text in {
                NO_ACADEMIC_RULE_MESSAGE,
                NO_EVIDENCE_MESSAGE,
            }:
                fallback_text = (
                    NO_ACADEMIC_RULE_MESSAGE
                    if classify_question_intent(question)
                    is QuestionIntent.ACADEMIC_RULE
                    else NO_EVIDENCE_MESSAGE
                )
                return AnswerResponse(
                    question=deterministic.question,
                    status=AnswerStatus.INSUFFICIENT_EVIDENCE,
                    answer_format=AnswerFormat.NONE,
                    text=fallback_text,
                    search_response=response,
                    answer_mode=AnswerMode.LLM,
                )

            results_by_id = {result.chunk_id: result for result in evidence}
            if not cited_ids or any(
                chunk_id not in results_by_id for chunk_id in cited_ids
            ):
                raise ValueError("LLM cited an unavailable evidence id")

            conflict_ids = _conflicting_evidence_ids(evidence)
            if conflict_ids:
                cited_ids = _ordered_union(cited_ids, conflict_ids, evidence)
                if CONFLICT_NOTICE not in answer_text:
                    answer_text = f"{CONFLICT_NOTICE}.\n\n{answer_text}"

            cited_results = [results_by_id[chunk_id] for chunk_id in cited_ids]
            _validate_generated_values(answer_text, cited_results)
            sources = deduplicate_answer_sources(
                [_answer_source(result) for result in cited_results]
            )
            answer_format = _answer_format(sources)
            final_text = _append_trusted_sources(answer_text, cited_results)
            if response.scope_notice:
                final_text = f"{response.scope_notice}\n\n{final_text}"
            return AnswerResponse(
                question=deterministic.question,
                status=AnswerStatus.ANSWERED,
                answer_format=answer_format,
                text=final_text,
                sources=sources,
                search_response=response,
                answer_mode=AnswerMode.LLM,
            )
        except Exception as error:
            # 사용자 화면에는 예외 문자열을 전달하지 않는다. 키도 로그에 넣지 않는다.
            self._logger.warning(
                "llm_answer_failed fallback=deterministic failure_type=%s",
                type(error).__name__,
            )
            return deterministic


def create_llm_provider(settings: "Settings") -> LLMProvider | None:
    """지원 설정이 완성된 경우에만 실제 provider를 만든다."""

    if not settings.llm_available:
        return None
    if settings.llm_provider.strip().lower() not in {
        "openai",
        "openai_compatible",
    }:
        return None
    if not settings.llm_api_key or not settings.llm_model_name:
        return None
    return OpenAICompatibleProvider(
        api_key=settings.llm_api_key,
        model_name=settings.llm_model_name,
        base_url=settings.llm_base_url,
    )


def build_answer_service(
    search_service: SearchService,
    settings: "Settings",
    *,
    provider: LLMProvider | None = None,
    logger: logging.Logger | None = None,
) -> LLMAnswerService:
    """Streamlit/CLI가 사용할 선택적 LLM facade를 구성한다."""

    selected_provider = provider
    if selected_provider is None:
        selected_provider = create_llm_provider(settings)
    return LLMAnswerService(
        search_service,
        provider=selected_provider,
        enabled=settings.llm_enabled,
        timeout_seconds=settings.llm_timeout_seconds,
        logger=logger,
    )


def _parse_completion(raw_completion: str) -> tuple[str, list[str]]:
    raw = raw_completion.strip()
    fenced = _JSON_FENCE.fullmatch(raw)
    if fenced is not None:
        raw = fenced.group("body").strip()
    payload = json.loads(raw)
    if not isinstance(payload, Mapping):
        raise ValueError("LLM response must be a JSON object")

    answer = payload.get("answer")
    evidence_ids = payload.get("evidence_ids")
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("LLM response has no answer")
    if not isinstance(evidence_ids, list) or any(
        not isinstance(value, str) or not value.strip()
        for value in evidence_ids
    ):
        raise ValueError("LLM response has invalid evidence ids")
    return answer.strip(), list(dict.fromkeys(value.strip() for value in evidence_ids))


def _parse_grounded_completion(raw, evidence):
    """The LLM selects exact supporting sentences. Unverifiable paraphrases fall back.

    This deliberately avoids claiming that mere citation IDs prove entailment.
    """
    fenced = _JSON_FENCE.fullmatch(raw.strip())
    payload = json.loads(fenced.group("body") if fenced else raw)
    if not isinstance(payload, dict):
        raise ValueError("LLM output must be an object")
    if payload.get("answer") in {NO_ACADEMIC_RULE_MESSAGE, NO_EVIDENCE_MESSAGE} and not payload.get("claims"):
        return payload["answer"], []
    claims = payload.get("claims")
    if not isinstance(claims, list) or not 1 <= len(claims) <= 12:
        raise ValueError("LLM output has no verifiable claims")
    by_id = {result.chunk_id: result for result in evidence}
    lines, ids = [], []
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValueError("Invalid claim")
        key, quote = claim.get("evidence_id"), claim.get("quote")
        if key not in by_id or not isinstance(quote, str) or len(quote.strip()) < 8:
            raise ValueError("Missing evidence or quotation")
        normalized = " ".join(quote.split())
        if normalized not in " ".join(by_id[key].text.split()):
            raise ValueError("Quote is not contained in cited evidence")
        if claim.get("text", quote) != quote:
            raise ValueError("Unverified paraphrases are not allowed")
        source = by_id[key]
        location = f"PDF {source.page_number}쪽" if source.page_number else "공식 웹 원문" if source.source_url else "TXT 원문"
        lines.append(quote.strip() + f"\n({source.file_name} · {location})")
        ids.append(key)
    return "\n\n".join(lines), list(dict.fromkeys(ids))


def _answer_source(result: DocumentSearchResult) -> AnswerSource:
    return AnswerSource(
        chunk_id=result.chunk_id,
        file_name=result.file_name,
        file_type=result.file_type,
        source_year=result.source_year,
        page_number=result.page_number,
        row_number=result.row_number,
        is_current=result.is_current,
        excerpt=result.text,
        source_url=result.source_url,
    )


def _structured_conflict_answer(
    deterministic: AnswerResponse,
    evidence: Sequence[DocumentSearchResult],
    conflict_ids: set[str],
) -> AnswerResponse:
    """충돌한 교과 값은 생성하지 않고 각 CSV 원문을 그대로 나란히 둔다."""

    conflicting_results = [
        result for result in evidence if result.chunk_id in conflict_ids
    ]
    sources = deduplicate_answer_sources(
        [_answer_source(result) for result in conflicting_results]
    )
    lines = [CONFLICT_NOTICE + ".", "", "검색 근거별 값:"]
    for result in conflicting_results:
        lines.extend(
            (
                f"- {result.file_name} (CSV {result.row_number}행)",
                "```text",
                result.text,
                "```",
            )
        )
    text = _append_trusted_sources("\n".join(lines), conflicting_results)
    return AnswerResponse(
        question=deterministic.question,
        status=AnswerStatus.ANSWERED,
        answer_format=_answer_format(sources),
        text=text,
        sources=sources,
        search_response=deterministic.search_response,
        answer_mode=AnswerMode.DETERMINISTIC,
    )


def _answer_format(sources: Sequence[AnswerSource]) -> AnswerFormat:
    source_types = {source.file_type for source in sources}
    if len(source_types) > 1:
        return AnswerFormat.MIXED
    return AnswerFormat(next(iter(source_types)))


def _trusted_result_text(result: DocumentSearchResult) -> str:
    values = (
        result.chunk_id,
        result.file_name,
        result.file_type,
        result.document_type,
        result.source_year,
        result.department,
        result.page_number,
        result.row_number,
        result.title,
        result.text,
        result.context_text,
    )
    return "\n".join(str(value) for value in values if value is not None)


def _validate_generated_values(
    answer_text: str,
    cited_results: Sequence[DocumentSearchResult],
) -> None:
    """생성된 숫자와 영숫자 코드는 인용 근거에 그대로 있어야 한다."""

    trusted_text = "\n".join(_trusted_result_text(result) for result in cited_results)
    allowed_numbers = set(_NUMBER_TOKEN.findall(trusted_text))
    generated_numbers = set(_NUMBER_TOKEN.findall(answer_text))
    if not generated_numbers.issubset(allowed_numbers):
        raise ValueError("LLM generated a number outside cited evidence")

    allowed_codes = set(_ALPHANUMERIC_CODE.findall(trusted_text))
    generated_codes = set(_ALPHANUMERIC_CODE.findall(answer_text))
    if not generated_codes.issubset(allowed_codes):
        raise ValueError("LLM generated a code outside cited evidence")


def _parse_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        match = _FIELD_LINE.fullmatch(line)
        if match is None:
            continue
        key = "".join(match.group(1).split()).lower()
        value = " ".join(match.group(2).split())
        if key and value:
            fields[key] = value
    return fields


def _conflicting_evidence_ids(
    evidence: Sequence[DocumentSearchResult],
) -> set[str]:
    """동일 문맥의 key-value 근거가 서로 다른 값을 가질 때 출처를 찾는다."""

    values_by_field: dict[
        tuple[str, str, str, str, str, str],
        dict[str, set[str]],
    ] = defaultdict(lambda: defaultdict(set))
    identity_keys = {"교과목명", "과목명", "학년", "이수구분"}
    for result in evidence:
        fields = _parse_fields(result.text)
        course_name = fields.get("교과목명") or fields.get("과목명") or ""
        grade = fields.get("학년", "")
        completion = fields.get("이수구분", "")
        identity = (
            result.document_type,
            result.department,
            course_name,
            grade,
            completion,
        )
        for key, value in fields.items():
            if key in identity_keys:
                continue
            values_by_field[(*identity, key)][value].add(result.chunk_id)

    conflict_ids: set[str] = set()
    for ids_by_value in values_by_field.values():
        if len(ids_by_value) > 1:
            for ids in ids_by_value.values():
                conflict_ids.update(ids)
    return conflict_ids


def _ordered_union(
    cited_ids: Sequence[str],
    extra_ids: set[str],
    evidence: Sequence[DocumentSearchResult],
) -> list[str]:
    included = set(cited_ids) | extra_ids
    return [result.chunk_id for result in evidence if result.chunk_id in included]


def _source_location(result: DocumentSearchResult) -> str:
    if result.file_type == "pdf":
        return f"PDF 페이지: {result.page_number}"
    if result.file_type == "csv":
        return f"CSV 행: {result.row_number}"
    return "문서 위치: 문서 전체"


def _currentness_label(is_current: bool | None) -> str:
    if is_current is True:
        return "최신 자료"
    if is_current is False:
        return "최신 자료가 아님"
    return "확인되지 않음"


def _append_trusted_sources(
    answer_text: str,
    results: Sequence[DocumentSearchResult],
) -> str:
    unique_results: list[DocumentSearchResult] = []
    seen_locations: set[tuple[str, str, int | None]] = set()
    for result in results:
        locator = (
            result.file_type,
            result.file_name,
            result.page_number if result.file_type == "pdf" else result.row_number,
        )
        if locator in seen_locations:
            continue
        seen_locations.add(locator)
        unique_results.append(result)

    lines = [answer_text, "", "답변에 사용된 출처:"]
    for result in unique_results:
        lines.append(
            f"- [근거:{result.chunk_id}] 파일명: {result.file_name} | "
            f"{_source_location(result)} | "
            f"기준연도: {result.source_year or '미지정'} | "
            f"최신 자료 여부: {_currentness_label(result.is_current)}"
        )
    if (
        any(result.is_current is False for result in unique_results)
        and OUTDATED_ANSWER_WARNING not in answer_text
    ):
        lines.extend(("", OUTDATED_ANSWER_WARNING))
    return "\n".join(lines)


__all__ = [
    "LLMAnswerService",
    "LLMProvider",
    "OpenAICompatibleProvider",
    "build_answer_service",
    "create_llm_provider",
]
