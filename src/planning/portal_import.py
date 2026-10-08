"""Convert the observed Classnet transcript table, without storing its contents."""
from dataclasses import dataclass, field
import re

from src.planning.catalog import normalized_name
from src.planning.io import to_rows
from src.planning.models import Attempt, Candidate

HEADERS = ("학수번호", "과목명", "영문과목명", "학점", "성적", "재수강")


@dataclass
class PortalImport:
    attempts: list[Attempt] = field(default_factory=list)
    reviews: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    semester_count: int = 0

    @property
    def ready(self):
        return bool(self.attempts) and not self.errors


def parse_period(caption: str):
    match = re.fullmatch(r"\s*(20\d{2})학년도\s+\d학년\s+(1학기|2학기|하계계절학기|동계계절학기)\s*", caption)
    if not match:
        raise ValueError("학기 제목을 인식하지 못했습니다.")
    return int(match[1]), {"1학기": 1, "2학기": 2, "하계계절학기": 3, "동계계절학기": 4}[match[2]]


def parse_portal_text(text: str, catalog: list[Candidate]) -> PortalImport:
    """Accept the visible table text copied from Classnet, not arbitrary instructions."""
    if not isinstance(text, str) or len(text.encode("utf-8")) > 1_000_000:
        return PortalImport(errors=["성적표 내용은 1MB 이하만 가져올 수 있습니다."])
    tables = []
    current = None
    headers = []
    ended = False
    errors = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"20\d{2}학년도", stripped):
            current = {"caption": stripped, "headers": [], "rows": []}
            tables.append(current)
            headers, ended = [], False
            continue
        if current is None:
            continue  # Ignore document title or account headings, never copy them into Attempts.
        if stripped == "전체성적" or re.match(r"^(신청학점|취득학점|총 취득학점)(\s|:)", stripped):
            ended = True
            continue
        if ended:
            continue
        if not current["headers"]:
            cells = [v.strip() for v in line.split("\t")]
            if cells == list(HEADERS):
                current["headers"] = cells
            elif stripped in HEADERS and len(headers) < len(HEADERS):
                headers.append(stripped)
                if len(headers) == len(HEADERS):
                    current["headers"] = headers
            else:
                errors.append(f"{number}줄: 성적표의 열 이름을 확인할 수 없습니다.")
            continue
        cells = [v.strip() for v in line.split("\t")]
        # Clipboard text often omits trailing empty grade / retake cells.
        if len(cells) in (4, 5):
            cells.extend([""] * (len(HEADERS) - len(cells)))
        current["rows"].append(cells)
    result = parse_portal_tables(tables, catalog)
    result.errors[:0] = errors
    return result


def portal_course_name(name: str):
    # The visible Classnet legend defines (*) as English and (C) as online delivery.
    # These are delivery annotations, not course identity or credit category.
    return re.sub(r"(?:\s*\((?:\*|C)\)\s*)+$", "", name).strip()


def parse_portal_tables(tables: list[dict], catalog: list[Candidate]) -> PortalImport:
    result = PortalImport()
    if not isinstance(tables, list) or not tables or len(tables) > 50:
        result.errors.append("전체성적조회에서 학기별 성적표를 찾지 못했습니다.")
        return result
    by_code = {}
    for course in catalog:
        by_code.setdefault(course.code, []).append(course)
    seen = set()
    periods = set()
    for table_no, table in enumerate(tables, 1):
        if not isinstance(table, dict) or table.get("headers") != list(HEADERS):
            result.errors.append(f"{table_no}번째 표의 열 구성이 바뀌었습니다. 기존 입력을 유지합니다.")
            continue
        try:
            year, term = parse_period(table.get("caption", ""))
        except (ValueError, TypeError):
            result.errors.append(f"{table_no}번째 표의 수강연도·학기를 확인할 수 없습니다.")
            continue
        if (year, term) in periods:
            result.errors.append(f"{table_no}번째 표의 학기가 중복됩니다. 열린 전체성적조회 창을 한 개만 남겨 주세요.")
        periods.add((year, term))
        rows = table.get("rows")
        if not isinstance(rows, list) or len(rows) > 500:
            result.errors.append(f"{table_no}번째 표의 행 수가 지원 범위를 벗어났습니다.")
            continue
        for row_no, row in enumerate(rows, 1):
            where = f"표 {table_no} / {row_no}행"
            if not isinstance(row, list) or len(row) != len(HEADERS) or any(not isinstance(v, str) or len(v) > 500 for v in row):
                result.errors.append(f"{where}: 성적표 형식을 확인하세요.")
                continue
            code, name, _, credits, grade, retake = [v.strip() for v in row]
            # The school's visible legend specifies blank grade = F for graded courses.
            grade = grade or "F"
            try:
                attempt = Attempt(code=code, name=name, credits=credits, grade=grade, year=year, term=term)
            except ValueError:
                # Do not expose Pydantic's raw input in errors or logs.
                result.errors.append(f"{where}: 학수번호·과목명·학점·성적을 인식하지 못했습니다.")
                continue
            identity = (attempt.year, attempt.term, attempt.code)
            if identity in seen:
                result.errors.append(f"{where}: 같은 학기의 학수번호가 중복됩니다.")
            seen.add(identity)
            matches = [c for c in by_code.get(attempt.code, [])
                       if normalized_name(c.name) == normalized_name(portal_course_name(attempt.name)) and c.credits == attempt.credits]
            category = "미확인"
            reason = "자료에 일치 과목 없음: 이수구분 확인 필요"
            if len(matches) == 1:
                category = matches[0].category
                reason = "2026 교과과정 번호·이름·학점 일치: 수강 당시 인정구분 확인 필요"
            # The suggestion is reviewed before application; design/area are never inferred.
            # Exact '재수강' rows are excluded from certificates per the portal legend.
            attempt = attempt.model_copy(update={"category": category,
                "status": "인정제외" if retake == "재수강" else attempt.status})
            result.attempts.append(attempt)
            result.reviews.append({**to_rows([attempt])[0], "분류 근거": reason, "재수강 표시": retake})
    if len(result.attempts) > 500:
        result.errors.append("전체 이수내역은 최대 500과목까지 지원합니다.")
    result.semester_count = len(periods)
    if result.attempts:
        result.warnings.append("전체성적조회에는 이수구분·교양영역·설계 인정학점이 없습니다. 분류 제안은 2026 교과과정과 정확히 일치하는 과목에만 제공하며, 수강 당시 기준을 확인해야 합니다. 교양영역·설계학점·SW데이터 인정학점은 0으로 가져옵니다. 입학연도는 직접 선택하세요.")
        if any(a.category == "미확인" for a in result.attempts):
            result.warnings.append("‘미확인’ 과목은 졸업학점 계산에서 제외됩니다. 아래 표에서 이수구분을 확인해 주세요.")
        if any(a.year < 2018 for a in result.attempts):
            result.warnings.append("2018년 이전 수강내역이 있습니다. 입학연도는 성적표에서 추정하지 않습니다. 선택한 입학연도와 이전 취득학점의 인정 기준을 확인하세요.")
        codes = [a.code for a in result.attempts]
        if len(codes) != len(set(codes)) or any(r["재수강 표시"] for r in result.reviews):
            result.warnings.append("재수강 표시 또는 반복 수강이 있습니다. 원 내역을 보존하고 학교 안내에 따라 ‘재수강’ 표시 행은 ‘인정제외’로 가져왔습니다. 표시가 없는 반복 수강은 학교에서 인정한 한 건과 이전 건의 상태를 확인하세요.")
    if not result.attempts and not result.errors:
        result.errors.append("가져올 수 있는 이수 과목이 없습니다. 현재 입력은 유지됩니다.")
    return result
