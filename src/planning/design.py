"""Reference design allocations; never equate course credits with design credits."""
import hashlib
import json
import re
import unicodedata

from src.planning.models import MAJOR_CATEGORIES


def load_design_policy(root):
    folder = root / "config/reviewed_rules"
    policy = json.loads((folder / "design_courses.json").read_text(encoding="utf-8"))
    path = (folder / "sources" / policy["source_file"]).resolve()
    if not path.is_relative_to((folder / "sources").resolve()):
        raise ValueError("설계 원본 경로가 올바르지 않습니다.")
    if hashlib.sha256(path.read_bytes()).hexdigest() != policy["sha256"]:
        raise ValueError("설계 인정학점 원본이 바뀌었습니다. 검토 후 다시 시도하세요.")
    return policy


def design_name(name):
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"(?:\s*\((?:\*|C)\)\s*)+$", "", name)
    return re.sub(r"\s+", "", name).replace("데이타", "데이터")


def design_allocation(attempt, policy):
    def result(credits, mode, reason, kind=""):
        return {"code": attempt.code, "name": attempt.name, "year": attempt.year, "term": attempt.term,
                "credits": credits, "mode": mode, "kind": kind, "reason": reason,
                "source": policy.get("source_url", "") if policy else ""}
    if attempt.category not in MAJOR_CATEGORIES:
        return result(0, "held", "전공 이수구분이 아니므로 설계 합계에서 제외. 미확인은 학과 자료로 분류를 먼저 확인하세요.")
    # Nonzero legacy inputs remain explicit overrides. Manual zero needs a flag.
    if attempt.design_override or attempt.design_credits > 0:
        return result(attempt.design_credits, "manual", "사용자가 입력한 설계학점 우선 적용 (0학점 포함)")
    if not policy:
        return result(0, "held", "설계과목 원본 확인 필요")
    matches = [r for r in policy["rows"] if r["code"] == attempt.code and r["credits"] == attempt.credits
               and design_name(r["name"]) == design_name(attempt.name)]
    if len(matches) != 1:
        return result(0, "unmatched", "학수번호·과목명·교과학점이 함께 일치하는 설계과목 없음. 대체과목은 별도 승인 확인 필요")
    if not policy["auto_compare_from"] <= attempt.year <= policy["auto_compare_to"]:
        return result(0, "held", "자동 대조 범위(2019~2026 수강연도) 밖입니다. 수강 당시 설계학점을 직접 확인·입력하세요.", matches[0]["kind"])
    row = matches[0]
    return result(row["design_credits"], "auto", "학과 설계/대체 교과목 표와 번호·이름·학점 일치. 현재 표 참고 배분이며 수강 당시 인정·이수순서는 별도 확인", row["kind"])
