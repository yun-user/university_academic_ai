"""학교 홈페이지 대학학사안내 검토 전사본 (www.hongik.ac.kr, 2026-10-01 확인)."""
from pathlib import Path
import shutil

import pytest

from src.answering.answer_service import AnswerService
from src.answering.models import AnswerStatus
from src.retrieval.query_intent import graduation_topic
from src.retrieval.university_guide import guide_topic, university_guide_search

ROOT = Path(__file__).resolve().parents[1]


def answer(question):
    response = university_guide_search(question, ROOT)
    assert response is not None
    return AnswerService.compose_answer(question, response)


@pytest.mark.parametrize("q,topic,expected", [
    ("조기졸업 조건이 뭐야?", "early_graduation", ["A0(4.00) 이상", "편입생은 신청 불가", "신청 후 취소할 수 없습니다"]),
    ("졸업 유예 신청 언제 해?", "degree_deferral", ["5월 초~7월 말", "11월 초~1월 말", "클래스넷"]),
    ("학위취득유예하면 재수강 돼?", "degree_deferral", ["재수강·학점포기 불가"]),
    ("학사경고 기준 알려줘", "academic_warning", ["1.75에 미달", "2과목 이상이 F", "3개 학기", "제적"]),
    ("3학년 수료하려면 몇 학점 필요해?", "completion_credit", ["99학점 이상", "105학점 이상"]),
    ("한 학기 최대 몇 학점까지 들을 수 있어?", "credit_limit", ["17학점까지", "19학점까지", "B+"]),
    ("결석 몇 번 하면 F야?", "attendance", ["3분의 1 이상을 결석", "F학점"]),
    ("A+ 평점 몇 점이야?", "grading_scale", ["| A+ | 95–100 | 4.5 |", "D0 이상"]),
])
def test_guide_topics_answer_from_official_pages(q, topic, expected):
    assert guide_topic(q) == topic
    result = answer(q)
    assert result.status == AnswerStatus.ANSWERED
    for value in expected:
        assert value in result.text
    assert result.sources[0].source_url.startswith("https://www.hongik.ac.kr/kr/education/")


@pytest.mark.parametrize("q", [
    "졸업하려면 전공 몇 학점 필요해?", "장학금 받으려면 평점 몇 이상이어야 해?", "자료구조 몇 학점이야?",
    "2학년 1학기 전공필수 과목 알려줘", "MSC 몇 학점 들어야 돼?", "졸업식 언제야?",
])
def test_department_and_course_questions_are_not_captured(q):
    assert guide_topic(q) is None


def test_early_graduation_is_not_answered_with_department_graduation_table():
    assert graduation_topic("조기졸업 조건이 뭐야?") is None
    assert graduation_topic("졸업유예 하면 졸업요건은?") is None


@pytest.mark.parametrize("question", ["조기졸업 조건이 뭐야?", "졸업유예 하면 졸업요건은?", "졸업을 미루려면 어떻게 해?"])
def test_guide_is_reachable_through_search_without_index(tmp_path, question):
    from src.retrieval.document_search_service import DocumentSearchService
    from src.retrieval.query_intent import QuestionIntent, classify_question_intent

    shutil.copytree(ROOT / "config/reviewed_rules", tmp_path / "config/reviewed_rules")
    class EmptyStore:
        def count(self):
            return 0
        def list_metadata_values(self, field):
            return []
    service = DocumentSearchService(embedding_provider=None, vector_store=EmptyStore(),
        chunk_size=600, chunk_overlap=100, top_k=3, min_retrieval_score=.35,
        dedup_similarity_threshold=.95, project_root=tmp_path)
    assert classify_question_intent(question) is QuestionIntent.ACADEMIC_RULE
    result = AnswerService(service).answer_question(question)
    assert result.status is AnswerStatus.ANSWERED
    assert result.sources[0].source_url.startswith("https://www.hongik.ac.kr/")
    assert "학교 학사안내" in service.available_document_types()
    assert not service.search_with_context(question, document_type="장학금").results


def test_changed_snapshot_blocks_answer(tmp_path):
    shutil.copytree(ROOT / "config/reviewed_rules", tmp_path / "config/reviewed_rules")
    (tmp_path / "config/reviewed_rules/sources/hongik_academic-warning.html").write_text("changed")
    response = university_guide_search("학사경고 기준", tmp_path)
    assert not response.results and "보류" in response.clarification_message
    assert university_guide_search("학사경고 기준", ROOT, "장학금") is None
