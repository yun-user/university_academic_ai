"""Validated student input; no account identifiers or remote services."""
from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CATEGORIES = ("전공", "전문교양", "교양선택", "특성화교양", "전공기초영어",
              "MSC수학", "MSC과학", "MSC전산", "일반선택", "미확인")
Category = Literal["전공", "전문교양", "교양선택", "특성화교양", "전공기초영어",
                   "MSC수학", "MSC과학", "MSC전산", "일반선택", "미확인"]
GRADES = ("A+", "A0", "B+", "B0", "C+", "C0", "D+", "D0", "P", "F", "F0", "NP", "미확정")
STATUSES = ("취득", "수강중", "인정제외")
PASS_GRADES = frozenset(GRADES[:9])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Course(StrictModel):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=150)
    credits: float = Field(gt=0, le=30)
    category: Category = "미확인"
    area: int = Field(default=0, ge=0, le=7)
    design_credits: float = Field(default=0, ge=0, le=30)
    equivalent_code: str = ""

    @field_validator("code", "equivalent_code")
    @classmethod
    def valid_code(cls, value):
        value = value.strip().upper()
        if value and not re.fullmatch(r"[A-Z0-9_-]{1,30}", value):
            raise ValueError("학수번호는 영문·숫자·하이픈·밑줄만 사용할 수 있습니다.")
        return value

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value):
        if not value.strip():
            raise ValueError("과목명을 입력하세요.")
        return value.strip()

    @field_validator("code")
    @classmethod
    def nonblank_code(cls, value):
        if not value:
            raise ValueError("학수번호를 입력하세요.")
        return value

    @model_validator(mode="after")
    def validate_allocation(self):
        if self.design_credits > self.credits:
            raise ValueError("설계 인정학점은 과목 학점보다 클 수 없습니다.")
        if self.design_credits and self.category != "전공":
            raise ValueError("설계 인정학점은 전공 과목에만 입력하세요.")
        if self.area and self.category != "전문교양":
            raise ValueError("교양 영역은 전문교양 과목에만 입력하세요.")
        return self

    @property
    def identity(self):
        return self.equivalent_code or self.code


class Attempt(Course):
    # Preserve earlier recognized coursework; admission scope remains 2020 only.
    year: int = Field(ge=2000, le=2100)
    term: Literal[1, 2, 3, 4] = 1
    grade: str = "미확정"
    status: Literal["취득", "수강중", "인정제외"] = "취득"

    @field_validator("term", mode="before")
    @classmethod
    def parse_term(cls, value):
        if isinstance(value, str) and value.strip() in {"1", "2", "3", "4"}:
            return int(value.strip())
        return value

    @field_validator("grade")
    @classmethod
    def valid_grade(cls, value):
        value = value.strip().upper().replace("O", "0")
        if value not in GRADES:
            raise ValueError("지원하는 성적 등급을 선택하세요.")
        return value


class Candidate(Course):
    semesters: tuple[Literal[1, 2], ...] = ()
    prerequisites: tuple[str, ...] = Field(default=(), max_length=100)
    concurrent: tuple[str, ...] = Field(default=(), max_length=100)
    alternatives: tuple[str, ...] = Field(default=(), max_length=100)
    source: str = Field(default="사용자 입력: 실제 개설·선수조건 확인 필요", max_length=500)

    @field_validator("prerequisites", "alternatives", "concurrent")
    @classmethod
    def valid_prerequisites(cls, values):
        return tuple(Course.valid_code(v) for v in values if v.strip())


def academic_period(year: int, term: int) -> tuple[int, int]:
    """Term IDs follow the transcript format; summer precedes term 2."""
    return year, {1: 0, 3: 1, 2: 2, 4: 3}[term]


class Substitution(StrictModel):
    """A user-confirmed, directional waiver of one course requirement.

    This does not merge credit identities or satisfy prerequisite conditions.
    Dates refer to the replacement course's completion period.
    """
    required_code: str = Field(min_length=1, max_length=30)
    replacement_code: str = Field(min_length=1, max_length=30)
    track: Literal["심화", "일반"]
    start_year: int = Field(ge=2020, le=2100)
    start_term: Literal[1, 2, 3, 4] = 1
    end_year: int | None = Field(default=None, ge=2020, le=2100)
    end_term: Literal[1, 2, 3, 4] | None = None
    source: str = Field(min_length=1, max_length=500)
    confirmed: bool = False

    @field_validator("required_code", "replacement_code")
    @classmethod
    def valid_codes(cls, value):
        return Course.nonblank_code(Course.valid_code(value))

    @field_validator("source")
    @classmethod
    def nonblank_source(cls, value):
        return Course.nonblank_name(value)

    @model_validator(mode="after")
    def valid_scope(self):
        if self.required_code == self.replacement_code:
            raise ValueError("원래 필수과목과 대체 이수과목은 서로 달라야 합니다.")
        if (self.end_year is None) != (self.end_term is None):
            raise ValueError("인정 종료 연도와 학기를 함께 입력하세요.")
        if self.end_year is not None and academic_period(self.end_year, self.end_term) < academic_period(self.start_year, self.start_term):
            raise ValueError("인정 종료 시점이 시작 시점보다 빠릅니다.")
        return self

    def covers(self, attempt: Attempt) -> bool:
        period = academic_period(attempt.year, attempt.term)
        return (academic_period(self.start_year, self.start_term) <= period
                and (self.end_year is None or period <= academic_period(self.end_year, self.end_term)))


class Profile(StrictModel):
    admission_year: Literal[2020] = 2020
    track: Literal["심화", "일반"] = "심화"
    required_codes: tuple[str, ...] = ()
    required_list_checked: bool = False
    thesis: Literal["확인 필요", "미충족", "충족"] = "확인 필요"
    english: Literal["확인 필요", "미충족", "충족"] = "확인 필요"
    substitutions: tuple[Substitution, ...] = Field(default=(), max_length=100)
    general_approval: Literal["확인 필요", "미충족", "충족"] = "확인 필요"
    design_sequence: Literal["확인 필요", "미충족", "충족"] = "확인 필요"
    recognized_course_scope: Literal["확인 필요", "미충족", "충족"] = "확인 필요"
    specialized_course: Literal["확인 필요", "미충족", "충족"] = "확인 필요"
    basic_english_course: Literal["확인 필요", "미충족", "충족"] = "확인 필요"

    @field_validator("required_codes")
    @classmethod
    def valid_required(cls, values):
        return tuple(dict.fromkeys(Course.valid_code(v) for v in values if v.strip()))


class PlanOptions(StrictModel):
    start_year: int = Field(ge=2026, le=2100)
    start_term: Literal[1, 2] = 1
    semesters: int = Field(default=4, ge=1, le=12)
    credit_limit: float = Field(default=18, gt=0, le=30)
    excluded_codes: tuple[str, ...] = ()
    assume_in_progress_passed: bool = False
    semester_limits: tuple[Annotated[float, Field(ge=0, le=30)], ...] = Field(default=(), max_length=12)

    def limit_for(self, offset: int) -> float:
        return self.semester_limits[offset] if self.semester_limits else self.credit_limit

    @model_validator(mode="after")
    def supported_end(self):
        if self.semester_limits and len(self.semester_limits) != self.semesters:
            raise ValueError("학기별 한도는 계획 학기 수만큼 입력하세요. 0은 해당 학기 수강하지 않음을 뜻합니다.")
        if self.start_year + (self.start_term - 1 + self.semesters - 1) // 2 > 2100:
            raise ValueError("계획 종료 연도는 2100년 이하여야 합니다.")
        return self
