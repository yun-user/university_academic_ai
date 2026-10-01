"""AID융합과학기술대학 입학연도·과정별 졸업학점표 (2026 교과과정 책자(안) 검토 전사본).

학과 심화프로그램 표(hongik.json)는 2020학번까지만 있으므로, 2021학번 이후 심화과정과
일반(비인증)과정은 이 단과대학 표로 안내한다. 원본 발췌 PDF의 해시가 바뀌면 답하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.retrieval.document_models import DocumentSearchResponse, DocumentSearchResult
from src.retrieval.query_intent import QuestionIntent

TRACK_LABELS = {"심화": "공학교육인증 심화과정", "일반": "일반과정(대학 표의 비인증과정)"}


class CollegeRulesUnavailable(ValueError):
    """검토 자료가 없거나 원본이 바뀌어 사용할 수 없다."""


def load_college_rules(root: Path) -> dict:
    path = root / "aid_college_2026.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        source = data["source"]
        original = (root / "sources" / source["file"]).resolve()
        if not original.is_relative_to((root / "sources").resolve()):
            raise ValueError("invalid source path")
        if hashlib.sha256(original.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError("source changed")
        data["cohorts"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise CollegeRulesUnavailable(str(error)) from error
    return data


def find_cohort(data: dict, track: str, year: int) -> dict | None:
    return next((c for c in data["cohorts"]
                 if c["track"] == track and c["from"] <= year <= c["to"]), None)


def covered_years(data: dict, track: str) -> tuple[int, int]:
    rows = [c for c in data["cohorts"] if c["track"] == track]
    return min(c["from"] for c in rows), max(c["to"] for c in rows)


def _years(cohort: dict) -> str:
    # 원문이 "입학생부터"인 구간의 상한(to)은 책자 연도로 둔 내부 값이므로 표시하지 않는다.
    if cohort.get("open_ended"):
        return f"{cohort['from']}학번부터"
    if cohort["from"] == cohort["to"]:
        return f"{cohort['from']}학번"
    return f"{cohort['from']}–{cohort['to']}학번"


def _basic_english(cohort: dict) -> str | None:
    value = cohort.get("basic_english")
    if value is None:
        return None
    if isinstance(value, int):
        return f"{value}학점 (전공기초영어 I/II 중 1과목 필수)"
    return value


def cohort_rows(cohort: dict) -> list[tuple[str, str]]:
    rows = [("총 졸업학점", f"{cohort['total']}학점 이상 (일반선택 포함)"),
            ("전공", f"{cohort['major']}학점 이상 (전공필수 모두 포함)"),
            (cohort.get("liberal_label", "전문교양"), f"{cohort['liberal']}학점"
             + (f" · 교양 취득학점은 최대 {cohort['liberal_cap']}학점까지 인정" if cohort.get("liberal_cap") else ""))]
    if cohort.get("specialized"):
        rows.append(("특성화교양", f"{cohort['specialized']}학점 (디자인씽킹, 창업과 실용법률 중 1과목 필수)"))
    if cohort.get("sw_data"):
        rows.append(("SW/데이터활용역량인증과목", f"{cohort['sw_data']}학점"))
    rows.append(("MSC", f"{cohort['msc']}학점 이상"))
    english = _basic_english(cohort)
    if english:
        rows.append(("전공기초영어", english))
    return rows


def _source_line(data: dict, cohort: dict) -> str:
    return (f"- {data['source']['document']} · PDF {cohort['page']}쪽(인쇄 {cohort['printed_page']}쪽) "
            f"· {data['college']} 졸업학점 현황")


def cohort_result(data: dict, cohort: dict) -> DocumentSearchResult:
    lines = [data["source"]["title"], f"{TRACK_LABELS[cohort['track']]} · {_years(cohort)}",
             *(f"{label}: {value}" for label, value in cohort_rows(cohort)),
             f"MSC 세부: {cohort['msc_detail']}"]
    text = "\n".join(lines)
    digest = hashlib.sha256(text.encode()).hexdigest()
    key = f"{cohort['track']}-{cohort['from']}-{cohort['to']}"
    return DocumentSearchResult(
        document_id="reviewed:" + data["source"]["id"],
        chunk_id=f"reviewed:{data['source']['id']}:{key}:{digest[:12]}",
        file_name=f"{data['source']['id']}_{key}_reviewed.txt", file_type="txt",
        document_type="검토된 학사규정", department=data["department"],
        title=f"{data['college']} 졸업학점 현황 PDF {cohort['page']}쪽 (검토 전사본)",
        source_year=data["source"]["published_year"], source_url=None,
        source_path="config/reviewed_rules/aid_college_2026.json", text=text,
        score=1, score_kind="structured_exact", content_hash=digest,
        track=cohort["track"] + "과정", authority="홍익대학교 " + data["college"],
        is_current=None, currentness_warning="2026 교과과정 책자(안) 기준 · 확정본 확인 필요")


def _closing(data: dict) -> str:
    return ("\n\n**참고:** 2026 교과과정 책자 **(안)** 기준입니다. 확정본·학과 이수내규와 다를 수 있고, "
            "설계학점·영어 요건 등 세부사항은 공학교육인증과정 이수내규와 프로그램별 이수내규를 따릅니다. "
            f"위 내용은 개인 졸업 가능 여부의 판정이 아닙니다. 자료 확인일: {data['reviewed_on']}.")


def cohort_answer(data: dict, cohort: dict, topic: str) -> DocumentSearchResponse:
    """한 입학연도 구간·과정의 졸업학점을 주제에 맞춰 보여 준다."""

    head = (f"{data['department']}({data['college']})의 **{TRACK_LABELS[cohort['track']]} · "
            f"{_years(cohort)}** 기준입니다.")
    rows = dict(cohort_rows(cohort))
    if topic == "major_credits":
        body = f"**전공은 {cohort['major']}학점 이상**(전공필수 모두 포함)이며, 총 {cohort['total']}학점 이상을 채워야 합니다. 전공학점만 채워서 졸업요건 전체를 충족하는 것은 아닙니다."
    elif topic == "total_credits":
        body = f"**총 {cohort['total']}학점 이상**(일반선택 포함)을 이수해야 합니다. 전공 {cohort['major']}학점·MSC {cohort['msc']}학점 등 영역별 요건도 함께 충족해야 합니다."
    elif topic == "msc":
        body = f"**MSC는 {cohort['msc']}학점 이상**입니다. {cohort['msc_detail']}"
    else:
        body = ("| 영역 | 조건 |\n| --- | --- |\n"
                + "\n".join(f"| {label} | {value} |" for label, value in rows.items())
                + f"\n\n**MSC 세부:** {cohort['msc_detail']}")
        if cohort["from"] >= 2016:
            body += ("\n\n**교양 영역:** 기초교양 6학점, 일반·핵심교양 1~7영역 중 ‘예술과 디자인’·‘제2외국어와 한문’을 "
                     "반드시 포함해 6개 영역에서 영역별 1과목 이상.")
        if cohort["track"] == "심화":
            body += ("\n\n**설계·영어:** 설계는 기초설계(창의적공학설계입문)와 종합설계를 포함해 학과 표 기준 12학점 이상이며, "
                     "영어는 2024년 개정 공지에 따라 공인시험 최저점수(TOEIC 600 등) 성적표 제출이 필요합니다.")
    response_text = (head + "\n\n" + body + _closing(data) + "\n\n출처:\n" + _source_line(data, cohort))
    return DocumentSearchResponse(results=[cohort_result(data, cohort)],
                                  question_intent=QuestionIntent.ACADEMIC_RULE,
                                  reviewed_answer=response_text)


def both_tracks_answer(data: dict, year: int, topic: str) -> DocumentSearchResponse | None:
    """입학연도만 알고 과정은 모를 때 두 과정을 나란히 보여 주고 확인을 요청한다."""

    pairs = [(track, find_cohort(data, track, year)) for track in ("심화", "일반")]
    if any(cohort is None for _track, cohort in pairs):
        return None
    advanced, general = (cohort for _track, cohort in pairs)
    a_rows, g_rows = dict(cohort_rows(advanced)), dict(cohort_rows(general))
    labels = list(dict.fromkeys([*a_rows, *g_rows]))
    table = ("| 영역 | 심화과정(공학교육인증) | 일반과정(비인증) |\n| --- | --- | --- |\n"
             + "\n".join(f"| {label} | {a_rows.get(label, '-')} | {g_rows.get(label, '-')} |" for label in labels))
    focus = {"major_credits": f"전공은 **심화과정 {advanced['major']}학점 / 일반과정 {general['major']}학점** 이상입니다.",
             "total_credits": f"총 졸업학점은 두 과정 모두 **{advanced['total']}학점 이상**입니다." if advanced["total"] == general["total"]
             else f"총 졸업학점은 **심화과정 {advanced['total']}학점 / 일반과정 {general['total']}학점** 이상입니다.",
             "msc": f"MSC는 **심화과정 {advanced['msc']}학점 / 일반과정 {general['msc']}학점** 이상입니다."}.get(topic, "")
    text = (f"{data['department']}({data['college']}) **{year}학번** 기준입니다. "
            "졸업 과정에 따라 요건이 다르므로 두 과정을 함께 보여 드립니다.\n\n"
            + (focus + "\n\n" if focus else "") + table
            + f"\n\n**MSC 세부(심화):** {advanced['msc_detail']}\n\n**MSC 세부(일반):** {general['msc_detail']}"
            + "\n\n**적용 확인:** 본인이 일반과정/심화과정 중 어디에 속하는지 알려주시면 하나로 좁혀 드립니다."
            + _closing(data) + "\n\n출처:\n" + _source_line(data, advanced) + "\n" + _source_line(data, general))
    return DocumentSearchResponse(results=[cohort_result(data, advanced), cohort_result(data, general)],
                                  question_intent=QuestionIntent.ACADEMIC_RULE, reviewed_answer=text)


def track_overview_answer(data: dict, track: str, topic: str) -> DocumentSearchResponse:
    """과정만 알고 입학연도를 모를 때 연도 구간별 핵심 학점을 표로 보여 준다."""

    cohorts = sorted((c for c in data["cohorts"] if c["track"] == track), key=lambda c: -c["from"])
    table = ("| 입학연도 | 총학점 | 전공 | 교양 | 특성화교양 | SW/데이터 | MSC |\n| --- | --- | --- | --- | --- | --- | --- |\n"
             + "\n".join(f"| {_years(c)} | {c['total']} | {c['major']} | {c['liberal']} | {c.get('specialized') or '-'} "
                         f"| {c.get('sw_data') or '-'} | {c['msc']} |" for c in cohorts))
    text = (f"{data['department']}({data['college']})의 **{TRACK_LABELS[track]}** 졸업학점은 입학연도에 따라 다릅니다. "
            "단위는 학점이며 각 값 이상을 이수해야 합니다.\n\n" + table
            + "\n\n**적용 확인:** 입학연도를 알려주시면 MSC 분야별 학점 등 세부 조건까지 안내해 드립니다."
            + _closing(data) + "\n\n출처:\n"
            + "\n".join(dict.fromkeys(_source_line(data, c) for c in cohorts)))
    return DocumentSearchResponse(results=[cohort_result(data, c) for c in cohorts],
                                  question_intent=QuestionIntent.ACADEMIC_RULE, reviewed_answer=text)
