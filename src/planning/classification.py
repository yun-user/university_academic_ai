"""Reviewed, source-backed classification proposals; never train on student data."""
import json
import re
from pathlib import Path

from src.planning.catalog import normalized_name
from src.planning.models import Attempt, MAJOR_CATEGORIES, Profile
from src.planning.rules import _verify


def course_name(name: str) -> str:
    # Delivery markers may be stacked. Preserve meaningful course suffixes.
    return normalized_name(re.sub(r"(?:\s*\((?:\*|C)\)\s*)+$", "", name))


def is_english_bonus(course) -> bool:
    return (course.credits == 1 and bool(re.fullmatch(
        r"(?:교양|전공)영어\([1-5]\)", course_name(course.name))))


def load_classification(root: Path) -> dict:
    folder = root / "config/reviewed_rules"
    review = json.loads((folder / "course_classification.json").read_text(encoding="utf-8"))
    for source in review["sources"]:
        _verify(folder, source)
    return review


def classify_attempts(attempts: list[Attempt], profile: Profile, root: Path) -> dict:
    """Return index-stable patches. Applying a proposal is an explicit UI action.

    A current reference matches identity but is not proof of historical approval.
    Preserve unknown and conflicting identities; do not invent aliases/credits.
    """
    review = load_classification(root)
    suggestions = []
    for index, attempt in enumerate(attempts):
        matches = [r for r in review["courses"] if r["code"] == attempt.code
                   and attempt.credits == r["credits"]
                   and course_name(attempt.name) in [course_name(n) for n in r["names"]]
                   and r.get("cohorts", [2018, 2026])[0] <= profile.admission_year
                   <= r.get("cohorts", [2018, 2026])[1]]
        patch = None
        source = None
        reason = "학수번호·과목명·학점이 함께 일치하는 검토 자료 없음. 현재 값을 유지합니다."
        if is_english_bonus(attempt):
            source = review["sources"][2]
            patch = {"category": "일반선택", "area": 0}
            reason = "학교 FAQ: 교양·전공 영어전용강좌 추가 1학점. 실제 부여된 행만 합산(합계 최대 5학점), 원래 과목 및 전공기초영어와 별개."
        elif len(matches) == 1:
            match = matches[0]
            source = review["sources"][match["source"]]
            category, area = match["category"], match["area"]
            reason = f"학수번호·과목명·학점 일치 · {source['title']}"
            if match["page"]:
                reason += f" · PDF {match['page']}쪽"
            if match.get("source") == 3 and 48 <= match["page"] <= 49:
                reason += f" · {profile.admission_year}학번 영역표 대조"
            if match.get("historical_conflict") and attempt.year < 2026:
                category, area = "전공", 0
                reason = match["historical_conflict"]
            patch = {"category": category, "area": area}
            if attempt.year != 2026:
                reason += " · 현재 자료의 참고 분류이므로 수강 당시 인정은 별도 확인"
            if "(C)" in attempt.name.upper():
                reason += " · 사이버강좌의 전문교양·MSC 인정 제한 확인"
        elif len(matches) > 1:
            reason = "검토 자료가 중복되어 자동 분류를 보류했습니다."
        if patch:
            # A category change must not create an invalid Course. Warn in preview
            # when an incompatible design allocation would be cleared.
            if patch["category"] not in MAJOR_CATEGORIES and attempt.design_credits:
                patch["design_credits"] = 0
                reason += " · 적용 시 전공 외 구분으로 바뀌어 설계 인정학점을 0으로 초기화"
            changed = any(getattr(attempt, key) != value for key, value in patch.items())
        else:
            changed = False
        suggestions.append({"index": index, "code": attempt.code, "name": attempt.name,
                            "before": {"category": attempt.category, "area": attempt.area},
                            "patch": patch, "changed": changed,
                            "selected": changed and attempt.category in {"미확인", "전공"}
                                        and attempt.area == 0 and not (patch and "design_credits" in patch),
                            "reason": reason, "source": source["url"] if source else ""})
    return {"suggestions": suggestions, "notes": review["notes"],
            "matched": sum(s["patch"] is not None for s in suggestions),
            "unmatched": sum(s["patch"] is None for s in suggestions)}


def classify_import(attempts: list[Attempt], profile: Profile, root: Path):
    review = classify_attempts(attempts, profile, root)
    # A fresh portal import has no category evidence of its own. Explicit CSV
    # and already saved inputs use the separate, non-mutating preview endpoint.
    rows = [Attempt.model_validate({**a.model_dump(), **(s["patch"] or {})})
            for a, s in zip(attempts, review["suggestions"])]
    return rows, review
