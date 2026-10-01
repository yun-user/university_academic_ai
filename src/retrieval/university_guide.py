"""www.hongik.ac.kr 대학학사안내 검토 전사본: 조기졸업·학위취득유예·수료·성적경고·수강학점·출석·성적평가.

대학 전체 공통 기준이므로 학과 선택과 무관하게 적용한다. 원본 HTML 스냅샷이 바뀌면 답하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unicodedata

from src.retrieval.document_models import DocumentSearchResponse, DocumentSearchResult
from src.retrieval.query_intent import QuestionIntent

GUIDE_DOCUMENT_TYPE = "학교 학사안내"
_GUIDE_FILE = Path("config/reviewed_rules/hongik_academic_guide.json")


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).casefold())


def guide_topic(question: str) -> str | None:
    """질문이 대학 공통 학사안내 주제인지 판정한다. 학과 졸업요건·장학 질문은 넘긴다."""

    value = _compact(question)
    if "조기졸업" in value:
        return "early_graduation"
    if re.search(r"학위취득유예|졸업유예|학위유예|졸업(을)?(미루|연기)", value):
        return "degree_deferral"
    if re.search(r"학사경고|성적경고", value):
        return "academic_warning"
    if "장학" in value or "졸업" in value:
        return None
    if re.search(r"수료", value) and re.search(r"학점|조건|기준|몇|필요|하려면|되려면", value):
        return "completion_credit"
    if re.search(r"결석|출석미달|출석", value) and re.search(r"몇|f|성적|인정|기준|넘|이상|되면|하면", value):
        return "attendance"
    if "학점" in value and re.search(r"최대|까지|한학기|학기당|매학기|수강신청|신청가능|신청할수|들을수|초과", value) \
            and not re.search(r"과목|교과목|학수번호|전공|msc|교양|설계", value):
        return "credit_limit"
    if re.search(r"평점|성적등급|등급|상대평가|절대평가|a\+|a0|b\+|d0", value) and \
            re.search(r"몇|기준|어떻게|뭐|무엇|알려|비율|점수|이상|계산|평가", value):
        return "grading_scale"
    return None


def university_guide_search(question: str, project_root, document_type: str | None = None):
    topic = guide_topic(question)
    if topic is None or document_type not in {None, GUIDE_DOCUMENT_TYPE}:
        return None
    root = Path(project_root)
    try:
        data = json.loads((root / _GUIDE_FILE).read_text(encoding="utf-8"))
        entry = data["topics"][topic]
        source = data["sources"][entry["source"]]
        sources_dir = (root / "config/reviewed_rules/sources").resolve()
        original = (sources_dir / source["file"]).resolve()
        if not original.is_relative_to(sources_dir):
            raise ValueError("invalid source path")
        if hashlib.sha256(original.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError("source changed")
    except (OSError, ValueError, KeyError, TypeError):
        return DocumentSearchResponse(question_intent=QuestionIntent.ACADEMIC_RULE,
            clarification_message="검토된 학교 학사안내 원본을 확인할 수 없어 답변을 보류합니다. 관리자에게 원본 복구와 재검토를 요청해 주세요.")
    text = entry["text"]
    digest = hashlib.sha256(text.encode()).hexdigest()
    result = DocumentSearchResult(
        document_id="reviewed:hongik-guide:" + entry["source"],
        chunk_id=f"reviewed:hongik-guide:{topic}:{digest[:12]}",
        file_name=f"hongik-guide_{entry['source']}_reviewed.txt", file_type="txt",
        document_type=GUIDE_DOCUMENT_TYPE, department="전체", title=source["title"] + " (검토 전사본)",
        source_url=source["url"], source_year=None, source_path=_GUIDE_FILE.as_posix(), text=text,
        score=1, score_kind="structured_exact", content_hash=digest, authority=data["authority"],
        is_current=None, currentness_warning="학교 홈페이지 확인일 기준 · 이후 변경 여부 확인 필요")
    answer = (entry["answer"]
              + f"\n\n**참고:** 홍익대학교 대학학사안내의 대학 공통 기준입니다(확인일 {data['reviewed_on']}). "
              "학과별 세부 요건과 학기별 공지를 함께 확인하세요."
              + f"\n\n출처:\n- [{source['title']}]({source['url']})")
    return DocumentSearchResponse(results=[result], question_intent=QuestionIntent.ACADEMIC_RULE,
                                  reviewed_answer=answer)
