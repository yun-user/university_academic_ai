"""검색 전에 질문의 최상위 의도를 결정하는 공용 분류기."""

from __future__ import annotations

import re
import unicodedata
from enum import Enum


class QuestionIntent(str, Enum):
    """검색 대상과 fallback 정책을 결정하는 질문 의도."""

    COURSE_LIST = "course_list"
    ACADEMIC_RULE = "academic_rule"
    GENERAL_SEARCH = "general_search"


_ACADEMIC_RULE_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"재수강",
        r"성적.{0,12}(처리|반영|산정|평가)",
        r"이수구분.{0,12}(처리|인정|변경|어떻)",
        r"(학사|성적)경고",
        r"졸업.{0,8}(요건|조건|기준|학점)",
        r"학점.{0,8}(인정|대체|전환)",
        r"(필수|선택)과목.{0,12}(변경|바뀌|전환|폐지)",
        r"복학",
        r"재입학",
        r"(장학금|장학생).{0,12}(조건|요건|기준|자격|선발)",
    )
)
_COURSE_TARGET_PATTERN = re.compile(r"(교과목|과목)")
_COURSE_REQUEST_PATTERN = re.compile(
    r"(알려|목록|뭐|무엇|어떤|보여|찾아|검색|조회|개설|있(?:어|나요|는지))"
)
_COURSE_FILTER_PATTERN = re.compile(
    r"([1-4]학년|[12]학기|msc|전공필수|전공선택|전공과목|일반선택|"
    r"기본소양|학수번호)"
)
_COURSE_CODE_PATTERN = re.compile(
    r"학수번호[:#]?([0-9a-z][0-9a-z-]{3,})"
)


def _normalize(value: str) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", value).casefold().split()
    )


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", _normalize(value))


def graduation_topic(question: str) -> str | None:
    """Interpret conversational degree-requirement questions without rewriting
    the user's text or inferring their year, academic record, or program.
    """
    compact = _compact(question)
    # These concern events, employment, or a particular course, not degree
    # requirements. Never answer them with the reviewed graduation table.
    if re.search(r"졸업식|졸업사진|졸업앨범|졸업여행|졸업후|졸업생취업", compact):
        return None
    if re.search(r"졸업(논문|프로젝트|작품)", compact):
        return None
    if ("설계학점" in compact or "설계인정학점" in compact or "설계교과목" in compact) and re.search(r"얼마|몇|필요|최소|이수|과목|포함|어떤|뭐|알려|채우|채워|인정", compact):
        return "design"
    if re.search(r"영어|어학|토익|toeic|opic|토플|teps|텝스|교양중국어|교양일본어", compact) and re.search(r"대체|인정|졸업|최저|기준|몇점", compact):
        return "english"
    if re.search(r"msc", compact) and re.search(r"학점|졸업|필요|얼마|몇", compact) and not re.search(r"과목.*(목록|보여|알려)|개설", compact):
        return "msc"
    quantity = bool(re.search(r"몇|얼마|최소|필요|채워|채우|이수|들어|들으", compact))
    mentions_graduation = "졸업" in compact
    asks_requirements = bool(re.search(
        r"요건|조건|기준|학점|이수|필요|해야|하면|하려|할려|어떻|어떡|뭐|무엇|뭘|알려|설명|궁금|가능", compact))
    if not ((mentions_graduation and asks_requirements)
            or ("전공" in compact and quantity and re.search(r"학점|얼마나.*(들|이수|채)|몇학점", compact))):
        return None
    if re.search(r"영어|어학|토익|toeic|opic|토플|teps", compact):
        return "english"
    if "설계" in compact:
        return "design"
    if "msc" in compact:
        return "msc"
    if "전공" in compact and (quantity or "학점" in compact) and "전공필수" not in compact:
        return "major_credits"
    if quantity and re.search(r"총학점|전체학점|총몇|모두몇|학점.*(몇|얼마)|몇학점", compact):
        return "total_credits"
    return "overview"


def is_graduation_question(question: str) -> bool:
    return graduation_topic(question) is not None


def classify_question_intent(question: str) -> QuestionIntent:
    """규정 강신호를 최우선으로 적용한 뒤 실제 과목 조회만 분류한다."""

    compact = _compact(question)
    if not compact:
        return QuestionIntent.GENERAL_SEARCH

    if is_graduation_question(question):
        return QuestionIntent.ACADEMIC_RULE

    if any(pattern.search(compact) for pattern in _ACADEMIC_RULE_PATTERNS):
        return QuestionIntent.ACADEMIC_RULE

    if _COURSE_CODE_PATTERN.search(compact):
        return QuestionIntent.COURSE_LIST

    has_course_target = _COURSE_TARGET_PATTERN.search(compact) is not None
    has_request = _COURSE_REQUEST_PATTERN.search(compact) is not None
    has_filter = _COURSE_FILTER_PATTERN.search(compact) is not None
    if has_course_target and (has_request or has_filter):
        return QuestionIntent.COURSE_LIST
    return QuestionIntent.GENERAL_SEARCH


def is_retake_completion_rule_question(question: str) -> bool:
    """재수강에 따른 이수구분 처리를 묻는 핵심 규정 질문인지 반환한다."""

    compact = _compact(question)
    return "재수강" in compact and ("이수구분" in compact or "인정" in compact)


def academic_rule_anchor_groups(question: str) -> tuple[tuple[str, ...], ...]:
    """질문에 직접 답하는 PDF인지 판정할 필수 문맥 그룹을 만든다."""

    compact = _compact(question)
    groups: list[tuple[str, ...]] = []

    if "재수강" in compact:
        groups.append(("재수강",))
    if "성적" in compact and re.search(r"처리|반영|산정|평가", compact):
        groups.extend(
            (
                ("성적", "평점", "기록"),
                ("처리", "반영", "산정", "평가", "인정", "수정"),
            )
        )
    if "이수구분" in compact:
        groups.append(
            (
                "이수구분",
                "교양선택",
                "일반선택",
                "전공필수",
                "전공선택",
                "필수과목",
                "선택과목",
            )
        )
        if re.search(r"처리|인정|변경|어떻", compact):
            groups.append(("인정", "이수구분", "변경"))
    if re.search(r"(학사|성적)경고", compact):
        groups.append(("학사경고", "성적경고"))
    if is_graduation_question(question):
        groups.extend(
            (
                ("졸업", "졸업요건"),
                ("요건", "조건", "기준", "학점", "이수"),
            )
        )
    if "학점" in compact and re.search(r"인정|대체|전환", compact):
        groups.extend((("학점",), ("인정", "대체", "전환")))
    if re.search(r"필수과목", compact) and re.search(
        r"변경|바뀌|전환|폐지", compact
    ):
        groups.extend(
            (
                ("필수과목", "필수로", "필수이수구분"),
                ("변경", "바뀌", "전환", "폐지"),
            )
        )
    if re.search(r"선택과목", compact) and re.search(
        r"변경|바뀌|전환|폐지", compact
    ):
        groups.extend(
            (
                ("선택과목", "선택으로", "선택이수구분"),
                ("변경", "바뀌", "전환", "폐지"),
            )
        )
    if "복학" in compact:
        groups.append(("복학", "복학생"))
    if "재입학" in compact:
        groups.append(("재입학",))
    if re.search(r"(장학금|장학생).{0,12}(조건|요건|기준|자격|선발)", compact):
        groups.extend(
            (
                ("장학금", "장학생"),
                ("조건", "요건", "기준", "자격", "선발", "선정"),
            )
        )

    unique: list[tuple[str, ...]] = []
    for group in groups:
        if group not in unique:
            unique.append(group)
    return tuple(unique)


def academic_rule_signatures(content: str) -> frozenset[str]:
    """재수강 이수구분 규정의 서로 다른 조건을 인접 결과 문구로 식별한다."""

    compact = _compact(content)
    if "재수강" not in compact:
        return frozenset()

    signatures: set[str] = set()
    for match in re.finditer("재수강", compact):
        window = compact[
            max(0, match.start() - 260) : min(len(compact), match.end() + 260)
        ]
        core_outcome = _nearest_rule_outcome(
            window,
            "핵심교양",
            ("교양선택", "일반선택"),
        )
        if core_outcome == "교양선택":
            signatures.add("retake_core_to_general_elective")
        if core_outcome == "일반선택":
            signatures.add("retake_core_to_free_elective")
        msc_outcome = _nearest_rule_outcome(
            window,
            "msc",
            ("교양선택", "일반선택"),
        )
        if msc_outcome == "일반선택":
            signatures.add("retake_msc_to_general_elective")
        if msc_outcome == "교양선택":
            signatures.add("retake_msc_to_culture_elective")
        if (
            (
                "<필수로>" in window
                or "필수로변경된과목으로수강" in window
                or (
                    "선택과목" in window
                    and "필수과목" in window
                    and "변경" in window
                )
            )
            and (
                "필수과목의이수구분" in window
                or "필수이수구분" in window
            )
        ):
            signatures.add("retake_changed_to_required")
        if (
            (
                "<선택으로>" in window
                or "선택으로변경된과목으로수강" in window
                or (
                    "필수과목" in window
                    and "선택과목" in window
                    and "변경" in window
                )
            )
            and (
                "선택과목의이수구분" in window
                or "선택이수구분" in window
            )
        ):
            signatures.add("retake_changed_to_elective")
    return frozenset(signatures)


def _nearest_rule_outcome(
    text: str,
    subject: str,
    outcomes: tuple[str, ...],
) -> str | None:
    """주제 뒤에 가장 가까이 명시된 인정 결과만 연결한다."""

    subject_index = text.find(subject)
    if subject_index < 0:
        return None
    tail = text[subject_index + len(subject) : subject_index + len(subject) + 100]
    matches = [
        (tail.find(outcome), outcome)
        for outcome in outcomes
        if tail.find(outcome) >= 0
    ]
    if not matches:
        return None
    return min(matches)[1]


def academic_rule_relevance(question: str, content: str) -> int:
    """직접 규정 문맥이 아니면 -1, 맞으면 결정적 관련성 점수를 반환한다."""

    groups = academic_rule_anchor_groups(question)
    compact_content = _compact(content)
    compact_question = _compact(question)
    if not groups or any(
        not any(term in compact_content for term in group)
        for group in groups
    ):
        return -1

    if is_retake_completion_rule_question(question):
        signatures = academic_rule_signatures(content)
        if not signatures:
            return -1
        signature_weights = {
            "retake_core_to_general_elective": 250,
            "retake_core_to_free_elective": 250,
            "retake_msc_to_general_elective": 250,
            "retake_msc_to_culture_elective": 250,
            "retake_changed_to_required": 400,
            "retake_changed_to_elective": 300,
        }
        return sum(signature_weights[item] for item in signatures)

    matched_terms = {
        term
        for group in groups
        for term in group
        if term in compact_content
    }
    outcome_terms = (
        "인정",
        "이수구분",
        "변경",
        "교양선택",
        "일반선택",
        "전공필수",
        "전공선택",
        "규정",
    )
    outcome_score = sum(term in compact_content for term in outcome_terms)
    return len(matched_terms) * 10 + outcome_score


__all__ = [
    "QuestionIntent",
    "academic_rule_anchor_groups",
    "academic_rule_relevance",
    "academic_rule_signatures",
    "classify_question_intent",
    "is_retake_completion_rule_question",
]
