"""통합 검색 결과를 LLM 없이 한국어 답변으로 변환한다."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol
from src.answering.graduation import reviewed_graduation

from src.answering.models import (
    AnswerFormat,
    AnswerResponse,
    AnswerSource,
    AnswerStatus,
    deduplicate_answer_sources,
)
from src.retrieval.course_search import (
    CourseInfo,
    SemesterCourseInfo,
    lexical_overlap,
    normalize_text,
    parse_course_info,
    parse_course_query,
    parse_key_value_text,
    truncate_text,
)
from src.retrieval.document_models import (
    DocumentSearchResponse,
    DocumentSearchResult,
)
from src.retrieval.query_intent import (
    QuestionIntent,
    academic_rule_relevance,
    academic_rule_signatures,
    classify_question_intent,
    is_retake_completion_rule_question,
)


NO_EVIDENCE_MESSAGE = (
    "현재 등록된 자료에서는 질문에 대한 정확한 근거를 찾지 못했습니다."
)
NO_ACADEMIC_RULE_MESSAGE = "현재 등록된 자료에서 정확한 규정을 찾지 못했습니다."
OUTDATED_ANSWER_WARNING = (
    "※ 이 자료는 최신 자료가 아닐 수 있으므로 최신 공지를 함께 확인하세요."
)
UNKNOWN_RULE_SCOPE_MESSAGE = (
    "해당 규정의 적용 대상은 원문 기준을 추가로 확인해야 합니다."
)
ACADEMIC_RULE_CONFLICT_NOTICE = "자료별 적용 기준이 다릅니다."
_EXCERPT_LIMIT = 360
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?。])\s+|\n+")
_QUESTION_TOKEN = re.compile(r"[0-9A-Za-z가-힣]{2,}")


def _word_stem(word: str) -> str:
    """조사·어미·'하다/되다' 접미사 앞까지만 남긴다. 예: 선발해 → 선발."""

    from src.retrieval.keyword_search import _kiwi

    for token in _kiwi().tokenize(word):
        if token.tag.startswith(("J", "E")) or token.tag in {"XSV", "XSA", "VCP"}:
            return word[: token.start]
    return word


def _has_lexical_support(question: str, text: str) -> bool:
    """질문 어절이나 그 어간 중 하나라도 근거 원문에 있는지 확인한다."""

    content = normalize_text(text).replace(" ", "")
    for word in _QUESTION_TOKEN.findall(normalize_text(question)):
        if word in content:
            return True
        stem = _word_stem(word)
        if len(stem) >= 2 and stem in content:
            return True
    return False


class SearchService(Protocol):
    """AnswerService가 재사용하는 기존 검색 서비스의 최소 계약."""

    def search_with_context(
        self,
        question: str,
        *,
        top_k: int | None = None,
        min_score: float | None = None,
        department: str | None = None,
        document_type: str | None = None,
    ) -> DocumentSearchResponse: ...


class AnswerService:
    """기존 검색을 한 번 호출하고 검색 근거만으로 답변을 조립한다."""

    def __init__(self, search_service: SearchService) -> None:
        self._search_service = search_service

    def answer_question(
        self,
        question: str,
        *,
        top_k: int | None = None,
        min_score: float | None = None,
        department: str | None = None,
        document_type: str | None = None,
    ) -> AnswerResponse:
        response = self._search_service.search_with_context(
            question,
            top_k=top_k,
            min_score=min_score,
            department=department,
            document_type=document_type,
        )
        normalized_response = self._normalize_response(response)
        return self.compose_answer(question, normalized_response)

    @staticmethod
    def _normalize_response(response: object) -> DocumentSearchResponse:
        """테스트 대역 등 동일 필드를 가진 응답도 정식 모델로 고정한다."""

        if isinstance(response, DocumentSearchResponse):
            return response
        return DocumentSearchResponse(
            results=list(getattr(response, "results")),
            question_intent=getattr(
                response,
                "question_intent",
                QuestionIntent.GENERAL_SEARCH,
            ),
            structured_query=bool(getattr(response, "structured_query", False)),
            exact_match_count=int(getattr(response, "exact_match_count", 0)),
            semantic_fallback_used=bool(
                getattr(response, "semantic_fallback_used", False)
            ),
        )

    @classmethod
    def compose_answer(
        cls,
        question: str,
        response: DocumentSearchResponse,
    ) -> AnswerResponse:
        """이미 검색된 결과를 재검색 없이 결정적으로 답변으로 바꾼다."""

        answer = cls._compose(question, response)
        if response.scope_notice and answer.status is AnswerStatus.ANSWERED:
            answer = answer.model_copy(
                update={"text": f"{response.scope_notice}\n\n{answer.text}"}
            )
        return answer

    @classmethod
    def _compose(
        cls,
        question: str,
        response: DocumentSearchResponse,
    ) -> AnswerResponse:
        normalized_question = question.strip()
        if not normalized_question:
            raise ValueError("답변할 질문은 비워 둘 수 없습니다.")
        question_intent = classify_question_intent(normalized_question)
        if not response.results:
            return AnswerResponse(
                question=normalized_question,
                status=AnswerStatus.INSUFFICIENT_EVIDENCE,
                answer_format=AnswerFormat.NONE,
                text=(
                    response.clarification_message or (NO_ACADEMIC_RULE_MESSAGE
                    if question_intent is QuestionIntent.ACADEMIC_RULE
                    else NO_EVIDENCE_MESSAGE)
                ),
                search_response=response,
            )

        if response.reviewed_answer:
            return AnswerResponse(question=normalized_question, status=AnswerStatus.ANSWERED,
                answer_format=AnswerFormat.TXT, text=response.reviewed_answer,
                sources=[cls._source(result, result.text) for result in response.results],
                search_response=response)

        if question_intent is QuestionIntent.ACADEMIC_RULE:
            reviewed = reviewed_graduation(normalized_question, response.results)
            if reviewed:
                summary, result = reviewed
                scoped_response = response.model_copy(update={"results": [result]})
                return AnswerResponse(question=normalized_question, status=AnswerStatus.ANSWERED,
                    answer_format=AnswerFormat.PDF, text=summary,
                    sources=[cls._source(result, result.text)], search_response=scoped_response)
            if any(result.file_type == "txt" and result.document_type == "공개공지"
                   and (result.source_url or "").startswith("https://") for result in response.results):
                return cls._official_web_rule_answer(normalized_question, response)
            return cls._academic_rule_answer(
                normalized_question,
                response,
            )

        if response.exact_match_count > 0:
            exact_results = [
                result
                for result in response.results
                if result.file_type == "csv"
            ]
            exact_courses = cls._parsed_courses(exact_results)
            if exact_courses and len(exact_courses) == len(exact_results):
                return cls._course_answer(
                    normalized_question,
                    response,
                    exact_courses,
                    exact=True,
                )
            return AnswerResponse(
                question=normalized_question,
                status=AnswerStatus.INSUFFICIENT_EVIDENCE,
                answer_format=AnswerFormat.NONE,
                text=NO_EVIDENCE_MESSAGE,
                search_response=response,
            )

        primary = response.results[0]
        if (
            response.structured_query
            and response.semantic_fallback_used
            and primary.file_type == "csv"
        ):
            return AnswerResponse(
                question=normalized_question,
                status=AnswerStatus.INSUFFICIENT_EVIDENCE,
                answer_format=AnswerFormat.NONE,
                text=NO_EVIDENCE_MESSAGE,
                search_response=response,
            )
        if primary.file_type == "csv":
            csv_results = [
                result for result in response.results if result.file_type == "csv"
            ]
            parsed_courses = cls._parsed_courses(csv_results)
            if parsed_courses:
                return cls._course_answer(
                    normalized_question,
                    response,
                    parsed_courses,
                    exact=False,
                )
            return cls._generic_csv_answer(
                normalized_question,
                response,
                primary,
            )
        if not _has_lexical_support(normalized_question, primary.text):
            # 의미 검색 점수만 넘고 질문 단어가 하나도 없는 문단을 답으로
            # 내보내지 않는다. 예: "졸업식 언제야?" → 내규의 "제5조 (강의 배정)".
            return AnswerResponse(
                question=normalized_question,
                status=AnswerStatus.INSUFFICIENT_EVIDENCE,
                answer_format=AnswerFormat.NONE,
                text=NO_EVIDENCE_MESSAGE,
                search_response=response,
            )
        if primary.file_type == "pdf":
            return cls._document_answer(
                normalized_question,
                response,
                primary,
                answer_format=AnswerFormat.PDF,
            )
        return cls._document_answer(
            normalized_question,
            response,
            primary,
            answer_format=AnswerFormat.TXT,
        )

    @staticmethod
    def _parsed_courses(
        results: Sequence[DocumentSearchResult],
    ) -> list[tuple[DocumentSearchResult, CourseInfo]]:
        parsed: list[tuple[DocumentSearchResult, CourseInfo]] = []
        for result in results:
            course = parse_course_info(result.text)
            if course is not None:
                parsed.append((result, course))
        return parsed

    @classmethod
    def _course_answer(
        cls,
        question: str,
        response: DocumentSearchResponse,
        courses: Sequence[tuple[DocumentSearchResult, CourseInfo]],
        *,
        exact: bool,
    ) -> AnswerResponse:
        intent = parse_course_query(question)
        first_result = courses[0][0]
        if exact and intent.has_structured_conditions:
            completion = "·".join(intent.completion_types)
            heading = (
                f"{first_result.department} {intent.grade}학년 "
                f"{intent.semester}학기 {completion + ' ' if completion else ''}"
                f"과목은 총 {len(courses)}개입니다."
            )
        else:
            heading = (
                f"{first_result.department} 교과과정 검색 결과에서 질문과 관련된 "
                f"과목을 총 {len(courses)}개 확인했습니다."
            )

        lines = [heading, ""]
        sources: list[AnswerSource] = []
        for index, (result, course) in enumerate(courses, start=1):
            semester = cls._answer_semester(course, intent.semester)
            lines.extend(
                (
                    f"{index}. {course.course_name}",
                    f"   - 학수번호: {'미지정(원문: 부학기)' if semester.course_code == '부학기' else semester.course_code or '미지정'}",
                    f"   - 학점: {semester.credits or '미지정'}",
                    f"   - 시수: {semester.hours or '미지정'}",
                )
            )
            if index < len(courses):
                lines.append("")
            sources.append(cls._source(result, result.text))

        lines.extend(("", "출처:"))
        lines.extend(
            f"- {file_name}"
            for file_name in dict.fromkeys(
                result.file_name for result, _course in courses
            )
        )
        if any(result.is_current is False for result, _course in courses):
            lines.extend(("", OUTDATED_ANSWER_WARNING))

        return AnswerResponse(
            question=question,
            status=AnswerStatus.ANSWERED,
            answer_format=AnswerFormat.CSV,
            text="\n".join(lines),
            sources=deduplicate_answer_sources(sources),
            search_response=response,
        )

    @staticmethod
    def _answer_semester(
        course: CourseInfo,
        requested_semester: int | None,
    ) -> SemesterCourseInfo:
        available = [item for item in course.semesters if item.is_available]
        if requested_semester is not None:
            requested = next(
                (
                    item
                    for item in available
                    if item.semester == requested_semester
                ),
                None,
            )
            if requested is not None:
                return requested
            return SemesterCourseInfo(semester=requested_semester)
        if available:
            with_real_code = [item for item in available if item.course_code and item.course_code != '부학기']
            if with_real_code:
                return with_real_code[0]
            return available[0]
        return SemesterCourseInfo(semester=requested_semester or 1)

    @classmethod
    def _document_answer(
        cls,
        question: str,
        response: DocumentSearchResponse,
        result: DocumentSearchResult,
        *,
        answer_format: AnswerFormat,
    ) -> AnswerResponse:
        excerpt = cls._extractive_excerpt(question, result.text)
        fallback_notice = (
            "정확히 일치하는 교과과정 항목은 찾지 못했습니다.\n\n"
            if response.structured_query and response.semantic_fallback_used
            else ""
        )
        if answer_format is AnswerFormat.PDF:
            introduction = (
                "가장 관련성이 높은 PDF 자료에서 다음 내용을 확인했습니다."
            )
            location_lines = (
                f"- 출처 파일명: {result.file_name}",
                f"- 페이지 번호: {result.page_number or '미지정'}",
                f"- 기준연도: {result.source_year or '미지정'}",
                f"- 최신 자료 여부: {cls._currentness_label(result.is_current)}",
            )
        else:
            introduction = (
                "가장 관련성이 높은 TXT 자료에서 다음 내용을 확인했습니다."
            )
            location_lines = (
                f"- 출처 파일명: {result.file_name}",
                f"- 기준연도: {result.source_year or '미지정'}",
                f"- 최신 자료 여부: {cls._currentness_label(result.is_current)}",
            )

        text = (
            f"{fallback_notice}{introduction}\n\n"
            f"> {excerpt}\n\n"
            "출처:\n"
            + "\n".join(location_lines)
        )
        if result.is_current is False:
            text += f"\n\n{OUTDATED_ANSWER_WARNING}"

        return AnswerResponse(
            question=question,
            status=AnswerStatus.ANSWERED,
            answer_format=answer_format,
            text=text,
            sources=[cls._source(result, excerpt)],
            search_response=response,
        )

    @classmethod
    def _official_web_rule_answer(cls, question, response):
        results = [r for r in response.results if academic_rule_relevance(question, r.text) >= 0
                   and (r.file_type == "pdf" or (r.document_type == "공개공지" and r.source_url))]
        if not results:
            return AnswerResponse(question=question, status=AnswerStatus.INSUFFICIENT_EVIDENCE,
                answer_format=AnswerFormat.NONE, text=NO_ACADEMIC_RULE_MESSAGE,
                search_response=response)
        sources = deduplicate_answer_sources([cls._source(r, r.text) for r in results])
        kinds = {s.file_type for s in sources}
        text = "등록된 공식 자료에서 다음 내용을 확인했습니다. 적용 대상과 게시일을 함께 확인하세요.\n\n"
        text += "\n\n".join(r.text for r in results)
        if any(r.is_current is not True for r in results):
            text += "\n\n" + OUTDATED_ANSWER_WARNING
        return AnswerResponse(question=question, status=AnswerStatus.ANSWERED,
            answer_format=AnswerFormat.MIXED if len(kinds) > 1 else AnswerFormat(next(iter(kinds))),
            text=text, sources=sources, search_response=response)

    @classmethod
    def _academic_rule_answer(
        cls,
        question: str,
        response: DocumentSearchResponse,
    ) -> AnswerResponse:
        rule_results = [
            result
            for result in response.results
            if result.file_type == "pdf"
            and academic_rule_relevance(question, result.text) >= 0
        ]
        rule_response = response.model_copy(
            update={
                "results": rule_results,
                "question_intent": QuestionIntent.ACADEMIC_RULE,
                "structured_query": False,
                "exact_match_count": 0,
                "semantic_fallback_used": False,
            }
        )
        if not rule_results:
            return AnswerResponse(
                question=question,
                status=AnswerStatus.INSUFFICIENT_EVIDENCE,
                answer_format=AnswerFormat.NONE,
                text=NO_ACADEMIC_RULE_MESSAGE,
                search_response=rule_response,
            )

        retake_completion_question = is_retake_completion_rule_question(question)
        if retake_completion_question:
            return cls._retake_completion_answer(
                question,
                rule_response,
                rule_results,
            )

        facts: list[tuple[str, DocumentSearchResult]] = []
        for result in rule_results:
            facts.extend(
                (excerpt, result)
                for excerpt in cls._academic_rule_excerpts(question, result.text)
            )

        deduplicated_facts: list[tuple[str, DocumentSearchResult]] = []
        seen_facts: set[str] = set()
        for fact, result in facts:
            normalized_fact = normalize_text(fact)
            if normalized_fact in seen_facts:
                continue
            seen_facts.add(normalized_fact)
            deduplicated_facts.append((fact, result))

        lines = [
            "검색된 학사 규정은 적용 대상과 조건에 따라 다음과 같이 "
            "안내합니다.",
            "",
        ]
        used_results: list[DocumentSearchResult] = []
        scope_unknown = False
        for fact, result in deduplicated_facts:
            lines.append(f"- {fact} {cls._page_citation(result)}")
            scope_details = cls._academic_rule_scope_details(result)
            if scope_details:
                lines.append(
                    "  - 확인된 적용 조건: " + " · ".join(scope_details)
                )
            else:
                scope_unknown = True
            used_results.append(result)

        if scope_unknown:
            lines.extend(("", UNKNOWN_RULE_SCOPE_MESSAGE))
        lines.extend(("", "출처:"))
        for source in deduplicate_answer_sources(
            [cls._source(result, result.text) for result in used_results]
        ):
            lines.extend(
                (
                    f"- 파일명: {source.file_name}",
                    f"  - PDF 페이지: {source.page_number}",
                    f"  - 기준연도: {source.source_year or '미지정'}",
                    "  - 최신 자료 여부: "
                    f"{cls._currentness_label(source.is_current)}",
                )
            )
        if any(result.is_current is False for result in used_results):
            lines.extend(("", OUTDATED_ANSWER_WARNING))

        sources = deduplicate_answer_sources(
            [cls._source(result, result.text) for result in used_results]
        )
        return AnswerResponse(
            question=question,
            status=AnswerStatus.ANSWERED,
            answer_format=AnswerFormat.PDF,
            text="\n".join(lines),
            sources=sources,
            search_response=rule_response,
        )

    @classmethod
    def _retake_completion_answer(
        cls,
        question: str,
        response: DocumentSearchResponse,
        results: Sequence[DocumentSearchResult],
    ) -> AnswerResponse:
        """재수강 이수구분 규정을 결과·적용 범위별로 조립한다."""

        change_labels = {
            "retake_changed_to_required": (
                "선택과목이 필수과목으로 변경된 뒤 동일과목을 재수강하여 "
                "취득 → 필수 이수구분으로 인정"
            ),
            "retake_changed_to_elective": (
                "필수과목이 선택과목으로 변경된 뒤 동일과목을 재수강하여 "
                "취득 → 선택 이수구분으로 인정"
            ),
        }
        conditional_labels = {
            "retake_core_to_general_elective": (
                "핵심교양 재수강 → 교양선택으로 인정"
            ),
            "retake_core_to_free_elective": (
                "핵심교양 재수강 → 일반선택으로 인정"
            ),
            "retake_msc_to_general_elective": (
                "MSC 과목 재수강 → 일반선택으로 인정"
            ),
            "retake_msc_to_culture_elective": (
                "MSC 과목 재수강 → 교양선택으로 인정"
            ),
        }

        change_facts: list[tuple[str, str, DocumentSearchResult]] = []
        conditional_facts: list[tuple[str, str, DocumentSearchResult]] = []
        for result in results:
            signatures = academic_rule_signatures(result.text)
            for signature, label in change_labels.items():
                if signature in signatures:
                    change_facts.append((signature, label, result))
            for signature, label in conditional_labels.items():
                if signature in signatures:
                    conditional_facts.append((signature, label, result))

        change_facts = cls._deduplicate_scoped_facts(change_facts)
        conditional_facts = cls._deduplicate_scoped_facts(conditional_facts)
        used_results = [
            result
            for _signature, _label, result in [*change_facts, *conditional_facts]
        ]
        if not used_results:
            return AnswerResponse(
                question=question,
                status=AnswerStatus.INSUFFICIENT_EVIDENCE,
                answer_format=AnswerFormat.NONE,
                text=NO_ACADEMIC_RULE_MESSAGE,
                search_response=response.model_copy(update={"results": []}),
            )

        lines = [
            "재수강 시 이수구분은 과목 유형과 교과과정 변경 여부에 "
            "따라 달라집니다.",
        ]
        if cls._conditional_rules_conflict(conditional_facts):
            lines.extend(("", ACADEMIC_RULE_CONFLICT_NOTICE))
        if change_facts:
            lines.extend(("", "[교과과정 변경에 따른 처리]"))
            for _signature, label, result in change_facts:
                lines.append(f"- {label} {cls._page_citation(result)}")
            transition_result = next(
                (
                    result
                    for _signature, _label, result in change_facts
                    if cls._has_transition_priority(result)
                ),
                None,
            )
            if transition_result is not None:
                lines.append(
                    "- 별도 경과조치가 규정되어 있으면 그 조치가 우선합니다. "
                    f"{cls._page_citation(transition_result)}"
                )

        grouped_conditional: list[
            tuple[
                tuple[str, int | None],
                DocumentSearchResult,
                list[str],
                list[str],
            ]
        ] = []
        grouped_by_location: dict[
            tuple[str, int | None],
            tuple[DocumentSearchResult, list[str], list[str]],
        ] = {}
        for _signature, label, result in conditional_facts:
            key = (result.file_name, result.page_number)
            if key not in grouped_by_location:
                grouped_by_location[key] = (
                    result,
                    [],
                    cls._academic_rule_scope_details(result),
                )
            grouped_by_location[key][1].append(label)
        grouped_conditional = [
            (key, result, labels, scope)
            for key, (result, labels, scope) in grouped_by_location.items()
        ]

        scoped_groups = [group for group in grouped_conditional if group[3]]
        unknown_groups = [group for group in grouped_conditional if not group[3]]
        if scoped_groups:
            lines.extend(("", "[적용 대상이 제한된 규정]"))
            for _key, result, labels, scope_details in scoped_groups:
                lines.append("- 확인된 적용 대상: " + " · ".join(scope_details))
                for label in labels:
                    lines.append(
                        "  - 해당 적용 대상의 공학교육인증 관련 기준: "
                        f"{label} {cls._page_citation(result)}"
                    )

        if unknown_groups:
            lines.extend(("", "[적용 대상 확인이 필요한 규정]"))
            for _key, result, labels, _scope_details in unknown_groups:
                for label in labels:
                    lines.append(
                        "- 일부 공학교육인증 관련 기준에서는 "
                        f"{label} {cls._page_citation(result)}"
                    )
            lines.extend(("", UNKNOWN_RULE_SCOPE_MESSAGE))

        if scoped_groups:
            lines.extend(
                (
                    "",
                    "※ 학생별 입학연도와 공학교육인증 과정 적용 여부는 "
                    "해당 학생의 교과과정을 확인해야 합니다.",
                )
            )
        if any(result.is_current is False for result in used_results):
            lines.extend(("", OUTDATED_ANSWER_WARNING))

        sources = deduplicate_answer_sources(
            [cls._source(result, result.text) for result in used_results]
        )
        return AnswerResponse(
            question=question,
            status=AnswerStatus.ANSWERED,
            answer_format=AnswerFormat.PDF,
            text="\n".join(lines),
            sources=sources,
            search_response=response,
        )

    @staticmethod
    def _conditional_rules_conflict(
        facts: Sequence[tuple[str, str, DocumentSearchResult]],
    ) -> bool:
        """동일 과목 유형에 서로 다른 인정 결과가 있으면 충돌로 본다."""

        outcomes_by_subject: dict[str, set[str]] = {}
        for signature, _label, _result in facts:
            if signature.startswith("retake_core_to_"):
                subject = "core"
            elif signature.startswith("retake_msc_to_"):
                subject = "msc"
            else:
                continue
            outcomes_by_subject.setdefault(subject, set()).add(signature)
        return any(len(outcomes) > 1 for outcomes in outcomes_by_subject.values())

    @staticmethod
    def _deduplicate_scoped_facts(
        facts: Sequence[tuple[str, str, DocumentSearchResult]],
    ) -> list[tuple[str, str, DocumentSearchResult]]:
        unique: list[tuple[str, str, DocumentSearchResult]] = []
        seen: set[tuple[str, str, int | None]] = set()
        for signature, label, result in facts:
            key = (signature, result.file_name, result.page_number)
            if key in seen:
                continue
            seen.add(key)
            unique.append((signature, label, result))
        return unique

    @classmethod
    def _academic_rule_scope_details(
        cls,
        result: DocumentSearchResult,
    ) -> list[str]:
        """규정 원문에 명시된 적용 범위만 반환한다.

        manifest의 입학연도/트랙은 파일 전체 메타데이터이므로 규정 문장과
        충돌할 수 있다. 이 함수는 검색된 본문과 동일 페이지 문맥만 쓴다.
        """

        local = re.sub(r"\s+", "", result.text)
        page_context = re.sub(
            r"\s+",
            "",
            result.context_text or result.text,
        )
        scope_context = local
        rule_anchor = page_context.find("재수강시핵심교양")
        if rule_anchor < 0:
            rule_anchor = page_context.find("핵심교양은교양선택")
        if rule_anchor >= 0:
            scope_context = page_context[
                max(0, rule_anchor - 650) : rule_anchor + 350
            ]
        details: list[str] = []

        admission = cls._explicit_admission_scope(local)
        if admission is None:
            admission = cls._explicit_admission_scope(scope_context)
        if admission:
            details.append(admission)

        department_match = re.search(
            r"입학생중(?P<department>[가-힣A-Za-z0-9·()]+?학과)"
            r"공학교육인증트랙에적용",
            local,
        )
        if department_match is not None:
            details.append(department_match.group("department"))

        if "공학교육인증트랙에적용" in local:
            details.append("공학교육인증 트랙")
        elif "비인증과정대상" in page_context:
            details.append("비인증과정 대상")

        if "공학교육인증과정운영대상학년과동일하지않은경우" in scope_context:
            details.append("공학교육인증과정 운영대상 학년과 동일하지 않은 경우")
        if (
            "공학교육인증신청불가" in scope_context
            or (
                "공학교육인증" in scope_context
                and "신청불가" in scope_context
            )
        ):
            details.append("공학교육인증 신청 불가")

        if all(
            term in page_context
            for term in ("공과대학", "게임소프트웨어전공", "AID융합과학기술대학")
        ):
            details.append(
                "공과대학·게임소프트웨어전공·AID융합과학기술대학"
            )
        if (
            "AID융합과학기술대학" in page_context
            and "건축학전공" in page_context
            and ("5년제" in page_context or "5년제제외" in page_context)
            and "제외" in page_context
        ):
            details.append("AID융합과학기술대학 건축학전공(5년제) 제외")

        return list(dict.fromkeys(details))

    @staticmethod
    def _explicit_admission_scope(compact_text: str) -> str | None:
        direct = re.search(
            r"(?P<year>(?:19|20)\d{2})학년도"
            r"(?P<modifier>이후|이전|부터)?입학생"
            r"(?P<ending>까지|부터)?",
            compact_text,
        )
        if direct is not None:
            modifier = direct.group("modifier")
            return (
                f"{direct.group('year')}학년도"
                f"{' ' + modifier if modifier else ''} 입학생"
                f"{direct.group('ending') or ''}"
            )

        candidates: list[tuple[int, str]] = []
        for match in re.finditer(r"(?P<year>(?:19|20)\d{2})학년도", compact_text):
            tail = compact_text[match.end() : match.end() + 180]
            distance = tail.find("입학생까지")
            if distance >= 0:
                candidates.append((distance, match.group("year")))
        if candidates:
            _distance, year = min(candidates)
            return f"{year}학년도 입학생까지"
        return None

    @staticmethod
    def _has_transition_priority(result: DocumentSearchResult) -> bool:
        context = re.sub(r"\s+", "", result.context_text or result.text)
        return "경과조치우선" in context or (
            "경과조치" in context and "이에따른다" in context
        )

    @staticmethod
    def _page_citation(result: DocumentSearchResult) -> str:
        return f"[{result.page_number}쪽]"

    @staticmethod
    def _canonical_rule_facts(text: str) -> list[str]:
        signatures = academic_rule_signatures(text)
        facts: list[str] = []
        if "retake_core_to_general_elective" in signatures:
            facts.append("핵심교양 재수강 → 교양선택으로 인정")
        if "retake_msc_to_general_elective" in signatures:
            facts.append("MSC 과목 재수강 → 일반선택으로 인정")
        if "retake_changed_to_required" in signatures:
            facts.append(
                "선택과목이 필수과목으로 변경된 뒤 동일과목을 재수강하여 "
                "취득 → 필수 이수구분으로 인정"
            )
        if "retake_changed_to_elective" in signatures:
            facts.append(
                "필수과목이 선택과목으로 변경된 뒤 동일과목을 재수강하여 "
                "취득 → 선택 이수구분으로 인정"
            )
        return facts

    @classmethod
    def _academic_rule_excerpts(cls, question: str, text: str) -> list[str]:
        segments = [
            " ".join(segment.split())
            for segment in re.split(r"\n+", text)
            if segment.strip()
        ]
        windows: list[tuple[int, str]] = []
        for index, segment in enumerate(segments):
            window = segment
            if index + 1 < len(segments):
                following = segments[index + 1]
                if any(
                    term in normalize_text(following).replace(" ", "")
                    for term in ("인정", "이수구분", "변경")
                ):
                    window = f"{segment} {following}"
            relevance = academic_rule_relevance(question, window)
            if relevance >= 0:
                windows.append((relevance, window))

        if not windows:
            return [cls._extractive_excerpt(question, text)]
        windows.sort(key=lambda item: item[0], reverse=True)
        excerpts: list[str] = []
        for _score, window in windows:
            excerpt = truncate_text(window, limit=_EXCERPT_LIMIT)
            if excerpt not in excerpts:
                excerpts.append(excerpt)
            if len(excerpts) == 2:
                break
        return excerpts

    @classmethod
    def _generic_csv_answer(
        cls,
        question: str,
        response: DocumentSearchResponse,
        result: DocumentSearchResult,
    ) -> AnswerResponse:
        values = parse_key_value_text(result.text)
        if values:
            detail_lines = [
                f"- {key}: {value}"
                for key, value in list(values.items())[:8]
                if value
            ]
            excerpt = "\n".join(detail_lines) or truncate_text(
                result.text,
                limit=_EXCERPT_LIMIT,
            )
        else:
            excerpt = cls._extractive_excerpt(question, result.text)

        text = (
            "가장 관련성이 높은 CSV 행에서 다음 내용을 확인했습니다.\n\n"
            f"{excerpt}\n\n"
            "출처:\n"
            f"- 출처 파일명: {result.file_name}\n"
            f"- CSV 행 번호: {result.row_number or '미지정'}\n"
            f"- 기준연도: {result.source_year or '미지정'}\n"
            f"- 최신 자료 여부: {cls._currentness_label(result.is_current)}"
        )
        if result.is_current is False:
            text += f"\n\n{OUTDATED_ANSWER_WARNING}"

        return AnswerResponse(
            question=question,
            status=AnswerStatus.ANSWERED,
            answer_format=AnswerFormat.CSV,
            text=text,
            sources=[cls._source(result, result.text)],
            search_response=response,
        )

    @staticmethod
    def _currentness_label(is_current: bool | None) -> str:
        if is_current is True:
            return "최신 자료"
        if is_current is False:
            return "최신 자료가 아님"
        return "확인되지 않음"

    @staticmethod
    def _source(result: DocumentSearchResult, excerpt: str) -> AnswerSource:
        return AnswerSource(
            chunk_id=result.chunk_id,
            file_name=result.file_name,
            file_type=result.file_type,
            source_year=result.source_year,
            page_number=result.page_number,
            row_number=result.row_number,
            is_current=result.is_current,
            excerpt=excerpt,
            source_url=result.source_url,
        )

    @staticmethod
    def _extractive_excerpt(question: str, text: str) -> str:
        """원문 조각을 바꾸지 않고 관련 문장 최대 두 개만 짧게 고른다."""

        segments = [
            " ".join(segment.split())
            for segment in _SENTENCE_BOUNDARY.split(text)
            if segment.strip()
        ]
        if not segments:
            return truncate_text(text, limit=_EXCERPT_LIMIT)

        scores = [lexical_overlap(question, segment) for segment in segments]
        relevant_indices = [
            index for index, score in enumerate(scores) if score > 0
        ]
        candidate_indices = relevant_indices or list(range(len(segments)))
        ranked_indices = sorted(
            candidate_indices,
            key=lambda index: (-scores[index], index),
        )
        selected = segments[ranked_indices[0]]
        return truncate_text(selected, limit=_EXCERPT_LIMIT)
