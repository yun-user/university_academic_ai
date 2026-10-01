"""Small, locally reviewed rule bundles with source hashes and explicit scope.

These supplement the searchable corpus. They are curated reference data, not
an LLM response or a claim that every currently effective regulation is known.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unicodedata

from src.retrieval.college_rules import (
    CollegeRulesUnavailable,
    both_tracks_answer,
    cohort_answer,
    cohort_result,
    covered_years,
    find_cohort,
    load_college_rules,
    track_overview_answer,
)
from src.retrieval.document_models import DocumentSearchResponse, DocumentSearchResult
from src.retrieval.query_intent import QuestionIntent, graduation_topic


def compact(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).casefold())


def admission_years(question):
    # A course-taking year is not an admission year. Require an explicit label.
    value = compact(question)
    years = re.findall(r"(?<!\d)((?:19|20)\d{2}|\d{2})(?:년|년도)?(?:학번|입학)", value)
    years += re.findall(r"입학(?:연도|년도|년)?[:：]?(20\d{2}|19\d{2})(?!\d)", value)
    return {int(y) if len(y) == 4 else 2000 + int(y) if int(y) < 50 else 1900 + int(y) for y in years}


def add_scope_to_question(question, admission_year=None, track=None):
    """UI defaults remain unknown; explicit question context takes precedence."""
    additions = []
    if admission_year and not admission_years(question):
        additions.append(f"입학연도 {admission_year}")
    if track and not re.search(r"일반과정|비인증|심화|공학인증", compact(question)):
        additions.append(track)
    return question + ("\n적용 조건: " + ", ".join(additions) if additions else "")


def reviewed_rule_search(question, department, project_root, document_type=None):
    topic = graduation_topic(question)
    if topic is None or document_type not in {None, "검토된 학사규정"}:
        return None
    value = compact(question)
    if re.search(r"재수강|2019년?내규", value):
        return None
    root = Path(project_root) / "config" / "reviewed_rules"
    path = root / "hongik.json"
    if not path.exists():
        return None
    def unavailable(message):
        return DocumentSearchResponse(question_intent=QuestionIntent.ACADEMIC_RULE,
                                      clarification_message=message)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if department != data["department"]:
            return None
        sources = data["sources"]
        # Fail closed: never fall back to superseded advice if a reviewed file
        # was removed or replaced without re-reviewing the bundle.
        for source in sources:
            source_path = (root / "sources" / source["file"]).resolve()
            if not source_path.is_relative_to((root / "sources").resolve()):
                raise ValueError("invalid source path")
            if hashlib.sha256(source_path.read_bytes()).hexdigest() != source["sha256"]:
                raise ValueError("source changed")
        sections = data["sections"]
    except (OSError, ValueError, KeyError, TypeError):
        return unavailable("검토된 개정 자료를 확인할 수 없어 졸업요건 답변을 보류합니다. 관리자에게 원본 자료 복구와 재검토를 요청해 주세요.")

    if re.search(r"과정변경|포기|면제|복수전공|부전공|편입|전과", value):
        return unavailable("편입·전과·복수전공·면제 등 특례의 적용 여부는 현재 검토한 일반 졸업표와 어학 개정 공지만으로 확정할 수 없습니다. 해당 특례를 명시한 내규와 적용 입학연도를 확인해야 합니다.")
    if re.search(r"일반과정.*심화과정.*모르|심화과정.*일반과정.*모르", value):
        return unavailable("일반과정과 심화과정 중 어느 과정인지 먼저 확인해야 합니다. 현재 검토한 학과 표는 심화과정 기준이므로, 본인의 졸업 과정과 입학연도를 확인한 뒤 다시 질문해 주세요.")
    if re.search(r"(내가|나는|제가|저는).*(졸업가능|졸업할수)|졸업.*확정해", value):
        return unavailable("공개 규정만으로 개인의 졸업 가능 여부를 확정할 수 없습니다. 본인의 입학연도·졸업 과정과 학교의 졸업사정 결과를 확인해 주세요. 일반적인 졸업요건 안내는 가능합니다.")
    general = bool(re.search(r"일반과정|비인증", value))
    advanced = bool(re.search(r"심화|공학인증", value))
    if general and topic in {"english", "design"}:
        return unavailable("현재 검토된 영어·설계학점 기준은 공학교육인증 심화과정 자료입니다. 일반과정에 그대로 적용할 수 없습니다. 일반과정의 해당 요건은 학과 이수내규를 추가로 확인해야 합니다.")
    if topic == "design":
        from src.retrieval.design_rules import design_course_answer
        return design_course_answer(question, root)
    years = admission_years(question)
    if len(years) > 1:
        return unavailable("서로 다른 입학연도가 포함되어 있습니다. 적용할 입학연도를 하나씩 지정해 주세요.")
    year = next(iter(years), None)
    # 학과 심화 표(2004–2020학번)에 없는 일반과정·2021학번 이후는 단과대학 표로 안내한다.
    if topic != "english" and (general or (year is not None and year > data["admission_year_to"])):
        return _college_answer(root, topic, year, "일반" if general else "심화" if advanced else None, unavailable)
    if topic != "english" and year is not None and year < data["admission_year_from"]:
        return unavailable(f"현재 검토된 자료로는 {year}학번의 졸업요건을 확정할 수 없습니다. {data['admission_year_from']}학번 이후 구간만 검토되어 있습니다. 해당 학번의 졸업요건 원문을 추가로 확인해야 합니다.")
    if topic == "english" and year is not None and year < 2013:
        return unavailable("2024년 첨부표의 공인시험 최저점수 조항은 2013학번부터 심화과정 대상입니다. 2013년 이전 입학생의 외국어 요건은 해당 학번 내규를 추가 확인해야 합니다.")

    used_ids = {"english-amendment", "english-scores"} if topic == "english" else {"graduation-table"}
    if topic == "overview":
        used_ids.add("english-amendment")
    intro = "소프트웨어융합학과의 **공학교육인증 심화과정** 자료에서 확인한 내용입니다."
    body = sections.get(topic, sections["overview"])
    if topic == "overview":
        body += "\n\n" + sections["amendment"]
    if topic == "english" and re.search(r"대체|생활영어|실용영어|교양중국어|교양일본어", value):
        # Never infer enrollment semester from an admission year or approve an
        # old course: the notice alone does not establish grandfathering rules.
        body += "\n\n개인 적용을 확인하려면 **해당 과목의 실제 이수연도·학기**가 필요합니다. 입학연도가 아닌 이수시기가 기준입니다. 2024학년도 2학기 이전 이수자의 인정 여부도 이 공지만으로 확정하지 않습니다."
    college_results = []
    if year is None and topic != "english":
        try:
            rules = load_college_rules(root)
        except CollegeRulesUnavailable:
            rules = None
        if rules is not None:
            recent = [find_cohort(rules, "심화", 2021), find_cohort(rules, "심화", 2022)]
            college_results = [cohort_result(rules, cohort) for cohort in recent if cohort]
            body += ("\n\n**2021학번 이후 심화과정:** 위 학과 표에는 2021학번 이후 열이 없습니다. "
                     "2026 교과과정 책자(안)의 AID융합과학기술대학 표는 2019–2021학번을 같은 132학점 체계(전공 54·MSC 30·전문교양 23·특성화교양 3)로, "
                     "**2022학번부터는 SW/데이터활용역량인증과목 9학점을 추가**로 요구합니다. 입학연도를 알려주시면 해당 기준으로 안내합니다.")
    checks = []
    if year is None:
        checks.append("입학연도")
    if not advanced:
        checks.append("일반과정/심화과정 여부")
    scope_note = ("\n\n**적용 확인:** " + "와 ".join(checks) + "를 알려주시면 적용 범위를 더 좁힐 수 있습니다. 위 내용은 개인 졸업 가능 여부의 판정이 아닙니다.") if checks else ""
    end = ("\n\n자료 확인일: " + data["reviewed_on"] + ". 확인일이 규정 시행일을 뜻하지 않습니다. "
           "학과 표는 게시·개정일 미표시이며 파일명의 2022를 시행연도로 단정하지 않습니다. "
           "2024년 공지 이후 후속 개정 여부는 추가 확인이 필요합니다.")
    results = []
    links = []
    for source in sources:
        if source["id"] not in used_ids:
            continue
        text = source["text"]
        digest = hashlib.sha256(text.encode()).hexdigest()
        results.append(DocumentSearchResult(document_id="reviewed:" + source["id"],
            chunk_id="reviewed:" + source["id"] + ":" + digest[:16],
            file_name=source["id"] + "_reviewed.txt", file_type="txt",
            document_type="검토된 학사규정", department=data["department"],
            title=source["title"], source_year=source["published_year"],
            source_url=source["url"], source_path="config/reviewed_rules/hongik.json",
            text=text, score=1, score_kind="structured_exact", content_hash=digest,
            track="심화과정", authority="홍익대학교 소프트웨어융합학과",
            is_current=None, currentness_warning="적용 학번·과정·후속 개정 확인 필요"))
        links.append(f"- [{source['title']}]({source['url']})")
    if college_results:
        results.extend(college_results)
        links.append("- 2026_홍익대학교_전체교과과정.pdf · PDF 8쪽(인쇄 6쪽) · AID융합과학기술대학 졸업학점 현황")
    return DocumentSearchResponse(results=results, question_intent=QuestionIntent.ACADEMIC_RULE,
        reviewed_answer=intro + "\n\n" + body + scope_note + end + "\n\n출처:\n" + "\n".join(links))


def _college_answer(root, topic, year, track, unavailable):
    """단과대학 표에서 입학연도·과정에 맞는 구간을 골라 답한다. 모르는 값은 추정하지 않는다."""
    try:
        rules = load_college_rules(root)
    except CollegeRulesUnavailable:
        return unavailable("검토된 단과대학 졸업학점표 원본을 확인할 수 없어 답변을 보류합니다. 관리자에게 원본 자료 복구와 재검토를 요청해 주세요.")
    if year is None:
        return track_overview_answer(rules, track, topic)
    if track is None:
        answer = both_tracks_answer(rules, year, topic)
    else:
        cohort = find_cohort(rules, track, year)
        answer = cohort_answer(rules, cohort, topic) if cohort else None
    if answer is None:
        low, high = covered_years(rules, track or "심화")
        return unavailable(f"현재 검토된 자료에는 {year}학번의 {'일반과정' if track == '일반' else '졸업'} 기준이 없습니다. "
                           f"2026 교과과정 책자(안)의 표는 {low}–{high}학번 구간을 다룹니다. 해당 학번의 졸업요건 원문을 추가로 확인해야 합니다.")
    return answer
