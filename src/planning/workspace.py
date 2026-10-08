"""Explicit, local-only planner backup format. No computed results are trusted."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from src.planning.models import Attempt, Candidate, PlanOptions, Profile, StrictModel


def seoul_today():
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def source_fingerprint(root: Path) -> str:
    paths = sorted((root / "config/reviewed_rules").glob("*.json"))
    paths += [root / "data/raw/tables/소프트웨어융합학과_학년별교과과정_2026.csv"]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


class PlannerWorkspace(StrictModel):
    kind: Literal["hongik-graduation-workspace"] = "hongik-graduation-workspace"
    version: Literal[2] = 2
    saved_on: str
    rules_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    attempts: list[Attempt] = Field(max_length=500)
    profile: Profile
    candidates: list[Candidate] = Field(max_length=500)
    options: PlanOptions
    llm_goal: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def unique_candidates(self):
        if len({c.code for c in self.candidates}) != len(self.candidates):
            raise ValueError("백업의 후보 학수번호가 중복됩니다.")
        return self


def write_workspace(workspace: PlannerWorkspace) -> bytes:
    return workspace.model_dump_json(indent=2).encode("utf-8")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON에 중복 키가 있습니다.")
        result[key] = value
    return result


def read_workspace(raw: bytes) -> PlannerWorkspace:
    if len(raw) > 2_000_000:
        raise ValueError("전체 입력 백업은 2MB 이하만 불러올 수 있습니다.")
    try:
        data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object)
        if isinstance(data, dict) and data.get("version") == 1:
            raise ValueError("이전 버전 결과 JSON에는 이수내역·후보 전체가 없어 복원할 수 없습니다. CSV를 사용하세요.")
        return PlannerWorkspace.model_validate(data)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ValueError("전체 입력 백업 형식을 확인하세요. " + str(exc)) from exc


def restore_session(state, workspace: PlannerWorkspace):
    """Called before constructing widgets; invalid files never reach this point."""
    from src.planning.io import to_rows
    from src.planning.catalog import candidate_rows

    profile = workspace.profile
    state["planner_rows"] = to_rows(workspace.attempts)
    state["planner_substitutions"] = [s.model_dump() for s in profile.substitutions]
    state["planner_candidate_rows"] = candidate_rows(workspace.candidates, workspace.options.excluded_codes)
    state["planner_revision"] = state.get("planner_revision", 0) + 1
    for name in ("admission_year", "track", "required_list_checked", "thesis", "english", "general_approval",
                 "design_sequence", "recognized_course_scope", "specialized_course", "basic_english_course", "sw_data_course", "science_course"):
        state["planner_" + name] = getattr(profile, name)
    state["planner_required"] = ", ".join(profile.required_codes)
    for name in ("start_year", "start_term", "semesters", "credit_limit", "assume_in_progress_passed"):
        state["planner_" + name] = getattr(workspace.options, name)
    state["planner_loaded_fingerprint"] = workspace.rules_fingerprint
    state["planner_llm_goal"] = workspace.llm_goal
    # Restoring input must never authorize a remote request or restore a credential.
    state["planner_llm_consent"] = False
