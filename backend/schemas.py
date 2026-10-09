"""Public API inputs. Credentials and calculated results are never accepted here."""
from datetime import date
from typing import Literal
from pydantic import Field, field_validator, model_validator

from src.planning.models import Attempt, Candidate, PlanOptions, Profile, StrictModel
from src.planning.manual import Placement


class TaskItem(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    title: str = Field(min_length=1, max_length=150)
    due: date | None = None
    done: bool = False
    note: str = Field(default="", max_length=500)


class PlanningInput(StrictModel):
    attempts: list[Attempt] = Field(default_factory=list, max_length=500)
    profile: Profile = Field(default_factory=Profile)
    options: PlanOptions
    goal: str = Field(default="", max_length=1000)
    candidates: list[Candidate] | None = Field(default=None, max_length=500)
    placements: list[Placement] | None = Field(default=None, max_length=500)
    checklist: list[TaskItem] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_items(self):
        if self.candidates is not None and len({c.code for c in self.candidates}) != len(self.candidates):
            raise ValueError("후보 학수번호는 중복될 수 없습니다.")
        if len({t.id for t in self.checklist}) != len(self.checklist):
            raise ValueError("체크리스트 ID가 중복됩니다.")
        return self


class CompareRequest(PlanningInput):
    limits: list[float] = Field(default_factory=lambda: [15, 18], min_length=2, max_length=4)
    last_limit: float | None = Field(default=None, ge=0, le=30)

    @field_validator("limits")
    @classmethod
    def valid_limits(cls, values):
        if any(not 0 < x <= 30 for x in values):
            raise ValueError("비교 학점은 0 초과 30 이하로 입력하세요.")
        return values


class WebBackup(StrictModel):
    kind: Literal["path-web-backup"] = "path-web-backup"
    version: Literal[1] = 1
    rules_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    data: PlanningInput


class EvaluationRecord(StrictModel):
    kind: Literal["규정 대조", "LLM 답변", "사용성"]
    case_label: str = Field(min_length=1, max_length=80)
    track: Literal["심화", "일반"]
    admission_year: int | None = Field(default=None, ge=2018, le=2026)
    expected: str = Field(default="", max_length=2000)
    observed: str = Field(default="", max_length=2000)
    evidence: str = Field(default="", max_length=500)
    verified: bool = False
    passed: bool | None = None
    seconds: float | None = Field(default=None, ge=0, le=86400)
    rating: int | None = Field(default=None, ge=1, le=5)

    @model_validator(mode="after")
    def evidence_for_verified(self):
        if self.verified and (not self.evidence.strip() or not self.expected.strip() or not self.observed.strip() or self.passed is None):
            raise ValueError("검증 완료 기록은 기대값·실제값·근거·합격 여부를 모두 입력하세요.")
        return self


class Credentials(StrictModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9_-]{3,40}$")
    password: str = Field(min_length=10, max_length=128, repr=False)


class AnalysisRequest(PlanningInput):
    consent: bool = False


class SaveProfile(PlanningInput):
    label: str = Field(min_length=1, max_length=80)
    revision: int | None = Field(default=None, ge=1)

    @field_validator("label")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("저장 이름을 입력하세요.")
        return value.strip()


class TranscriptText(StrictModel):
    text: str = Field(min_length=1, max_length=1_000_000)
    profile: Profile = Field(default_factory=Profile)


class ClassificationRequest(StrictModel):
    attempts: list[Attempt] = Field(max_length=500)
    profile: Profile


class DesignRequest(ClassificationRequest):
    candidates: list[Candidate] | None = Field(default=None, max_length=500)


class ChatTurn(StrictModel):
    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(min_length=1, max_length=3000)


class ChatRequest(PlanningInput):
    question: str = Field(min_length=1, max_length=1000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=6)
    consent: bool = False

    @field_validator("question")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("질문을 입력하세요.")
        return value.strip()
