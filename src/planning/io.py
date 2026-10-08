"""Explicit CSV schema. Transcript contents are never persisted by this module."""
import csv
import io

from src.planning.models import Attempt

COLUMNS = {"학수번호": "code", "과목명": "name", "학점": "credits", "이수구분": "category",
           "교양영역": "area", "설계인정학점": "design_credits", "동일과목코드": "equivalent_code",
           "SW데이터인정학점": "sw_data_credits",
           "수강연도": "year", "학기": "term", "성적": "grade", "상태": "status"}
REQUIRED = {"학수번호", "과목명", "학점", "이수구분", "수강연도", "학기", "성적", "상태"}


def parse_rows(rows) -> list[Attempt]:
    if len(rows) > 500:
        raise ValueError("이수내역은 최대 500행까지 입력할 수 있습니다.")
    result = []
    for index, row in enumerate(rows, 1):
        if not any(str(v or "").strip() for v in row.values()):
            continue
        if set(row) - set(COLUMNS):
            raise ValueError(f"{index}행: 지정 양식에 없는 열이 있습니다. 이름·학번 등은 입력하지 마세요.")
        values = {}
        for label, key in COLUMNS.items():
            value = row.get(label)
            if value is not None and str(value).strip() != "":
                values[key] = value
        try:
            result.append(Attempt.model_validate(values))
        except ValueError as exc:
            raise ValueError(f"{index}행의 학수번호·학점·이수구분·성적·수강연도를 확인하세요.\n{exc}") from exc
    return result


def read_transcript(raw: bytes) -> list[Attempt]:
    if len(raw) > 1_000_000:
        raise ValueError("CSV는 1MB 이하만 업로드할 수 있습니다.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("cp949")
        except UnicodeDecodeError as exc:
            raise ValueError("UTF-8 또는 CP949 CSV 파일을 사용하세요.") from exc
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    if len(headers) != len(set(headers)) or not REQUIRED.issubset(headers) or set(headers) - set(COLUMNS):
        raise ValueError("열 이름이 지정 양식과 다르거나 중복됩니다. CSV 양식을 내려받아 사용하세요.")
    rows = list(reader)
    if any(None in row or None in row.values() for row in rows):
        raise ValueError("일부 행의 열 개수가 맞지 않습니다.")
    return parse_rows(rows)


def to_rows(attempts):
    return [{label: getattr(a, key) for label, key in COLUMNS.items()} for a in attempts]


def write_transcript(attempts) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=COLUMNS)
    writer.writeheader()
    for row in to_rows(attempts):
        # Prevent CSV formula execution when a user opens the export in Excel.
        writer.writerow({k: "'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v for k, v in row.items()})
    return stream.getvalue().encode("utf-8-sig")


def sample_transcript(admission_year=2020):
    """Synthetic course list, unrelated to any logged-in account."""
    data = [("001012", "논리적사고와글쓰기(공학)", 3, "전문교양", 0, 0),
            ("001009", "영어", 3, "전문교양", 0, 0),
            ("012102", "대학물리(1)", 3, "MSC과학", 0, 0),
            ("012103", "대학물리실험(1)", 1, "MSC과학", 0, 0),
            ("012201", "대학수학(1)", 3, "MSC수학", 0, 0),
            ("012301", "공학컴퓨터입문및실습", 3, "MSC전산", 0, 0),
            ("725843", "창의적공학설계입문", 2, "전공", 0, 2),
            ("704818", "자료구조및프로그래밍실습", 3, "전공", 0, 0)]
    return [Attempt(code=c, name=n, credits=v, category=k, area=a, design_credits=d,
                    year=admission_year, grade="B0") for c,n,v,k,a,d in data]
