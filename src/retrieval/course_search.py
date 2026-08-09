"""교과과정 질문과 CSV 행의 구조화 정보를 해석하는 공용 도구."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


COURSE_QUERY_TERMS = (
    "학년",
    "학기",
    "이수구분",
    "전공과목",
    "전공필수",
    "전공선택",
    "교과목",
    "과목",
    "학수번호",
    "학점",
    "시수",
)
COURSE_DOCUMENT_TYPE = "학년별교과과정"
_GRADE_PATTERN = re.compile(r"(?<!\d)([1-4])\s*학년")
_SEMESTER_PATTERN = re.compile(r"(?<!\d)([12])\s*학기")
_TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")
_ADMINISTRATIVE_TERMS = ("장학금", "휴학", "복학", "신청기간", "신청 기간")
_EXPLICIT_COURSE_TERMS = (
    "이수구분",
    "전공과목",
    "전공필수",
    "전공선택",
    "교과목",
    "과목",
    "학수번호",
    "시수",
)
_COMPLETION_TYPE_TERMS = (
    ("전공필수", ("전공필수",)),
    ("전공선택", ("전공선택",)),
    ("전공과목", ("전공필수", "전공선택")),
    ("기본소양", ("기본소양",)),
    ("일반선택", ("일반선택",)),
    ("msc", ("MSC",)),
)


@dataclass(frozen=True, slots=True)
class CourseQueryIntent:
    """질문에서 추출한 교과과정 검색 조건."""

    is_course_query: bool
    grade: int | None = None
    semester: int | None = None
    completion_types: tuple[str, ...] = ()

    @property
    def has_structured_conditions(self) -> bool:
        """학년·학기·이수구분을 모두 추출했는지 반환한다."""

        return (
            self.is_course_query
            and self.grade is not None
            and self.semester is not None
            and bool(self.completion_types)
        )


@dataclass(frozen=True, slots=True)
class SemesterCourseInfo:
    semester: int
    course_code: str = ""
    credits: str = ""
    hours: str = ""

    @property
    def is_available(self) -> bool:
        return bool(self.course_code or self.credits or self.hours)


@dataclass(frozen=True, slots=True)
class CourseInfo:
    """CSV 한 행에서 읽은 학생용 교과목 정보."""

    course_name: str
    grade: str = ""
    completion_type: str = ""
    semesters: tuple[SemesterCourseInfo, ...] = ()

    def has_semester(self, semester: int) -> bool:
        return any(
            item.semester == semester and item.is_available
            for item in self.semesters
        )


def normalize_text(value: str) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", value).casefold().split()
    )


def parse_course_query(question: str) -> CourseQueryIntent:
    """교과과정 의도와 학년·학기·전공 구분을 질문에서 추출한다."""

    normalized = normalize_text(question)
    compact = normalized.replace(" ", "")
    strong_terms = tuple(term for term in COURSE_QUERY_TERMS if term != "학점")
    is_course_query = any(term in compact for term in COURSE_QUERY_TERMS)

    # "졸업 전공학점"은 기존 졸업요건 검색을 유지한다. 학점 외에 교과과정
    # 단서가 함께 있으면 정상적으로 교과과정 질문으로 처리한다.
    if "졸업" in compact and not any(term in compact for term in strong_terms):
        is_course_query = False

    grade_match = _GRADE_PATTERN.search(normalized)
    semester_match = _SEMESTER_PATTERN.search(normalized)
    administrative_context = any(
        term in normalized or term.replace(" ", "") in compact
        for term in _ADMINISTRATIVE_TERMS
    )
    explicit_course_context = bool(
        grade_match
        or semester_match
        or any(term in compact for term in _EXPLICIT_COURSE_TERMS)
    )
    if administrative_context and not explicit_course_context:
        is_course_query = False
    completion_types = next(
        (
            values
            for term, values in _COMPLETION_TYPE_TERMS
            if term in compact
        ),
        (),
    )

    return CourseQueryIntent(
        is_course_query=is_course_query,
        grade=int(grade_match.group(1)) if grade_match else None,
        semester=int(semester_match.group(1)) if semester_match else None,
        completion_types=completion_types,
    )


def parse_key_value_text(text: str) -> dict[str, str]:
    """`키: 값` 줄을 첫 콜론 기준으로 분리한다."""

    values: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip():
            values[key.strip()] = value.strip()
    return values


def parse_course_info(text: str) -> CourseInfo | None:
    values = parse_key_value_text(text)
    course_name = values.get("교과목명", "").strip()
    if not course_name:
        return None

    if values.get("전공필수여부", "").casefold() == "y":
        completion_type = "전공필수"
    elif values.get("전공선택여부", "").casefold() == "y":
        completion_type = "전공선택"
    else:
        completion_type = values.get("이수구분", "").strip()

    semesters = tuple(
        SemesterCourseInfo(
            semester=semester,
            course_code=values.get(f"{semester}학기_학수번호", "").strip(),
            credits=values.get(f"{semester}학기_학점", "").strip(),
            hours=values.get(f"{semester}학기_시수", "").strip(),
        )
        for semester in (1, 2)
    )
    return CourseInfo(
        course_name=course_name,
        grade=values.get("학년", "").strip(),
        completion_type=completion_type,
        semesters=semesters,
    )


def lexical_overlap(question: str, content: str) -> float:
    """실제 질문 토큰이 후보 원문에 포함된 비율을 반환한다."""

    query_tokens = {
        token
        for token in _TOKEN_PATTERN.findall(normalize_text(question))
        if len(token) >= 2
    }
    if not query_tokens:
        return 0.0
    normalized_content = normalize_text(content)
    matched = sum(token in normalized_content for token in query_tokens)
    return matched / len(query_tokens)


def format_semesters(course: CourseInfo | None) -> str:
    if course is None:
        return "해당 없음"
    available = [item for item in course.semesters if item.is_available]
    return " · ".join(f"{item.semester}학기" for item in available) or "미지정"


def format_grade(course: CourseInfo | None) -> str:
    if course is None:
        return "해당 없음"
    grade = course.grade.strip()
    if not grade:
        return "미지정"
    return grade if grade.endswith("학년") else f"{grade}학년"


def format_course_codes(course: CourseInfo | None) -> str:
    if course is None:
        return "해당 없음"
    available = [item for item in course.semesters if item.is_available]
    codes = [item for item in available if item.course_code]
    if not codes:
        return "미지정"
    def display_code(item: SemesterCourseInfo) -> str:
        if item.course_code.casefold() == "부학기":
            return "미지정(원문: 부학기)"
        return item.course_code

    if len(available) == 1:
        return display_code(codes[0])
    return " · ".join(
        f"{item.semester}학기 {display_code(item)}" for item in codes
    )


def format_credit_hours(course: CourseInfo | None) -> str:
    if course is None:
        return "해당 없음"
    available = [item for item in course.semesters if item.is_available]
    details = [
        (item, f"{item.credits or '-'}/{item.hours or '-'}")
        for item in available
        if item.credits or item.hours
    ]
    if not details:
        return "미지정"
    unique_values = {value for _, value in details}
    if len(unique_values) == 1:
        return details[0][1]
    return " · ".join(
        f"{item.semester}학기 {value}" for item, value in details
    )


def course_summary(course: CourseInfo) -> str:
    return " · ".join(
        (
            f"학년 {format_grade(course)}",
            f"학기 {format_semesters(course)}",
            f"이수구분 {course.completion_type or '미지정'}",
            f"학수번호 {format_course_codes(course)}",
            f"학점/시수 {format_credit_hours(course)}",
        )
    )


def truncate_text(text: str, *, limit: int) -> str:
    if limit <= 0:
        raise ValueError("limit은 1 이상이어야 합니다.")
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    if limit == 1:
        return "…"
    return collapsed[: limit - 1].rstrip() + "…"
