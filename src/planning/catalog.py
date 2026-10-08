"""Candidate courses from the existing curriculum, explicitly tentative."""
import csv
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from src.planning.models import Candidate, MAJOR_CATEGORIES


def candidate_rows(candidates, excluded=()):
    return [{"추천":c.code not in excluded,"학수번호":c.code,"과목명":c.name,"학점":c.credits,
        "이수구분":c.category,"교양영역":c.area,"설계인정학점":c.design_credits,
        "SW데이터인정학점":c.sw_data_credits,
        "동일과목코드":c.equivalent_code,"개설학기":",".join(map(str,c.semesters)),
        "선수학수번호":",".join(c.prerequisites),"병수학수번호":",".join(c.concurrent),"선택대안학수번호":",".join(c.alternatives),"출처":c.source} for c in candidates]


def parse_candidates(rows):
    from src.planning.io import COLUMNS
    if len(rows) > 500:
        raise ValueError("후보는 최대 500개까지 입력할 수 있습니다.")
    candidates, excluded = [], []
    for index, row in enumerate(rows, 1):
        if not str(row.get("학수번호", "")).strip() and not str(row.get("과목명", "")).strip():
            continue
        try:
            values = {field:row[label] for label,field in COLUMNS.items() if label in row and row[label]!=""}
            course = Candidate(**values,
                semesters=tuple(int(v.strip()) for v in str(row.get("개설학기", "")).split(",") if v.strip()),
                alternatives=tuple(str(row.get("선택대안학수번호", "")).split(",")),
                prerequisites=tuple(str(row.get("선수학수번호", "")).split(",")),
                concurrent=tuple(str(row.get("병수학수번호", "")).split(",")),
                source=row.get("출처") or "사용자 추가: 근거 확인 필요")
        except (ValueError, TypeError) as exc:
            raise ValueError(f"후보 {index}행을 확인하세요: {exc}") from exc
        candidates.append(course)
        if not row.get("추천"):
            excluded.append(course.code)
    if len({c.code for c in candidates}) != len(candidates):
        raise ValueError("후보 학수번호가 중복됩니다.")
    return candidates, tuple(excluded)


def normalized_name(name):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", name)).replace("데이타", "데이터")


def load_catalog(project_root: Path) -> list[Candidate]:
    root = project_root / "config/reviewed_rules"
    design = json.loads((root / "design_courses.json").read_text(encoding="utf-8"))
    source = root / "sources" / design["source_file"]
    if hashlib.sha256(source.read_bytes()).hexdigest() != design["sha256"]:
        raise ValueError("설계 인정학점 원본이 바뀌었습니다. 검토 후 다시 시도하세요.")
    design_by_name = {normalized_name(r["name"]): r["design_credits"] for r in design["rows"]}
    path = project_root / "data/raw/tables/소프트웨어융합학과_학년별교과과정_2026.csv"
    candidates = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row_no, row in enumerate(csv.DictReader(handle), 1):
            # An unresolved identifier (e.g. 02742 vs 002742) must not become a recommendation.
            if row.get("검토필요") == "Y":
                continue
            kind = row["이수구분"]
            category = kind if kind in MAJOR_CATEGORIES else "일반선택"
            if row["MSC여부"] == "Y":
                category = "MSC" + row["MSC분야"]
            elif kind == "기본소양":
                category = "전문교양" if row["세부분류"] in {"일반교양", "핵심교양"} or row["필수선택"] == "필수" else "교양선택"
            area = re.search(r"([1-7])영역", row["교과목명"])
            # Split alternative codes; do not assign the sum of both alternatives.
            by_code = {}
            for semester in (1, 2):
                codes = [v.strip() for v in row[f"{semester}학기_학수번호"].split(",")]
                for code in codes:
                    if not re.fullmatch(r"[A-Za-z0-9-]{4,}", code):
                        continue
                    credits = row[f"{semester}학기_학점"]
                    if not credits:
                        continue
                    key = (code, float(credits))
                    by_code.setdefault(key, []).append(semester)
            for (code, credits), semesters in by_code.items():
                candidates.append(Candidate(code=code, name=row["교과목명"], credits=credits,
                    category=category, area=int(area.group(1)) if area and category == "전문교양" else 0,
                    design_credits=design_by_name.get(normalized_name(row["교과목명"]), 0) if category in MAJOR_CATEGORIES else 0,
                    # Alternatives satisfying one requirement are not necessarily
                    # identical courses for credit recognition.
                    semesters=tuple(semesters),
                    alternatives=tuple(other for other, _ in by_code if other != code),
                    source=f"2026 학년별교과과정 CSV {row_no}행 · 개설 예정 가정, 선수조건 미확인"))
    review_path = root / "software_program_review.json"
    if review_path.exists():
        from src.planning.rules import _verify
        review = json.loads(review_path.read_text(encoding="utf-8"))
        for item in review["sources"]:
            _verify(root, item)
        candidates = [c.model_copy(update={
            "prerequisites": tuple(dict.fromkeys([*review["prerequisites"].get(c.code, ()),
                *(["725843"] if c.design_credits > 0 and c.code != "725843" else [])])),
            "concurrent": tuple(review["concurrent"].get(c.code, ())),
            "source": c.source.replace("선수조건 미확인", "2026 이수체계도 1쪽 선수·병수 적용, MSC 상세 규정 별도 확인")
        }) for c in candidates]
    # The department website separates actual course names from area headings.
    # Its reviewed snapshot also resolves the old CSV's required/elective labels.
    from src.planning.classification import load_classification
    review = load_classification(project_root)
    current = {row["code"]: row for row in review["courses"] if row.get("catalog")}
    candidates = [c.model_copy(update={"alternatives": ("001009",)}) if c.code == "001023" else c
                  for c in candidates]
    return [c.model_copy(update={"name": current[c.code]["names"][0],
                               "category": current[c.code]["category"],
                               "source": c.source + " · 학과 홈페이지 이수구분 대조(2026-10-08)"})
            if c.code in current else c for c in candidates]
