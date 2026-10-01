"""Regression cases from actual questions and newly reviewed public sources."""
from pathlib import Path
import shutil
from types import SimpleNamespace
import pytest

from src.retrieval.reviewed_rules import reviewed_rule_search, admission_years, add_scope_to_question
from src.retrieval.query_intent import graduation_topic
from src.answering.answer_service import AnswerService
from src.answering.llm_answer_service import LLMAnswerService
from src.answering.models import AnswerStatus
from src.retrieval.document_search_service import DocumentSearchService

ROOT = Path(__file__).resolve().parents[1]
DEPT = "소프트웨어융합학과"

def answer(question):
    response = reviewed_rule_search(question, DEPT, ROOT)
    assert response is not None
    return AnswerService.compose_answer(question, response)

@pytest.mark.parametrize("q", ["2025년에 생활영어 들었는데 졸업 영어 대체돼?", "실용영어로 토익 대체 가능해?", "소프트웨어융합학과 어학 대체 인정돼?"])
def test_repealed_course_alternative_cannot_be_recommended(q):
    result = answer(q)
    assert "2024학년도 2학기부터" in result.text
    assert "인정되지 않" in result.text
    assert "227" in result.text and "258" not in result.text
    assert "실제 이수연도·학기" in result.text
    assert len(result.sources) == 2
    assert all(s.source_url.startswith("https://software.hongik.ac.kr/") for s in result.sources)

def test_admission_year_is_not_course_completion_year():
    assert admission_years("2025년에 생활영어 들었어") == set()
    assert admission_years("20학번이고 2025년에 수강") == {2020}
    assert admission_years("입학연도 2018") == {2018}
    assert "이전 이수자의 인정 여부도 이 공지만으로 확정하지 않습니다" in answer("2018학번인데 영어 졸업 대체 인정돼?").text

@pytest.mark.parametrize("q", ["1990학번 졸업학점", "2019학번과 2020학번 졸업요건 비교", "2027학번 심화과정 졸업요건", "2003학번 일반과정 졸업요건"])
def test_unsupported_scope_does_not_claim_a_credit_requirement(q):
    result = answer(q)
    assert result.status == AnswerStatus.INSUFFICIENT_EVIDENCE
    assert "54학점" not in result.text and "50학점" not in result.text
    assert not result.sources


# 2026 교과과정 책자(안) PDF 8~16쪽, AID융합과학기술대학 행
@pytest.mark.parametrize("q,expected,absent,page", [
    ("2023학번 심화과정 졸업요건", ["2022학번부터", "132학점", "54학점", "SW/데이터활용역량인증과목 | 9학점", "MSC | 30학점"], ["2022–2026"], 8),
    ("2021학번 심화과정 MSC 몇 학점 필요해?", ["2019–2021학번", "MSC는 30학점"], [], 8),
    ("2020학번 일반과정 전공 몇 학점 필요해?", ["일반과정", "2020–2021학번", "전공은 50학점"], ["54학점"], 12),
    ("2020학번 비인증 졸업요건", ["MSC | 27학점", "과학 8학점, 수학 3학점, 전산 2학점"], ["SW/데이터"], 12),
    ("2024학번 일반과정 MSC 몇 학점이야?", ["MSC는 27학점", "과학 4학점, 수학 3학점, 전산 3학점"], [], 10),
    ("2012학번 일반과정 졸업 총학점", ["140학점"], [], 15),
    ("2005학번 일반과정 졸업 전공 몇 학점", ["전공은 35학점"], [], 16),
])
def test_college_table_answers_cohorts_outside_department_table(q, expected, absent, page):
    result = answer(q)
    assert result.status == AnswerStatus.ANSWERED
    for value in expected:
        assert value in result.text
    for value in absent:
        assert value not in result.text
    assert f"PDF {page}쪽" in result.text
    assert "(안)" in result.text


def test_year_without_track_shows_both_tracks_and_asks():
    result = answer("21학번 졸업요건 알려줘")
    assert result.status == AnswerStatus.ANSWERED
    assert "심화과정(공학교육인증) | 일반과정(비인증)" in result.text
    assert "54학점 이상" in result.text and "50학점 이상" in result.text
    assert "일반과정/심화과정 중 어디에 속하는지" in result.text
    assert len(result.sources) == 2


def test_track_without_year_lists_every_cohort():
    text = answer("일반과정 졸업요건 알려줘").text
    assert "2024학번부터 | 132 | 50" in text and "2004–2009학번 | 140 | 35" in text
    assert "입학연도를 알려주시면" in text


def test_general_track_does_not_inherit_advanced_english_or_design_rules():
    for q in ["2024학번 일반과정 영어 졸업 기준 알려줘", "일반과정 설계학점 몇 학점 필요해?"]:
        result = answer(q)
        assert result.status == AnswerStatus.INSUFFICIENT_EVIDENCE
        assert "TOEIC" not in result.text and "12학점" not in result.text


def test_college_source_corruption_blocks_answer(tmp_path):
    shutil.copytree(ROOT / "config/reviewed_rules", tmp_path / "config/reviewed_rules")
    (tmp_path / "config/reviewed_rules/sources/aid_graduation_credits_2026_p8-16.pdf").write_bytes(b"changed")
    response = reviewed_rule_search("2023학번 심화과정 졸업요건", DEPT, tmp_path)
    assert not response.results
    assert "보류" in response.clarification_message

def test_unknown_scope_is_explicit_not_assumed():
    text = answer("소프트웨어융합학과 졸업요건이 뭐야?").text
    assert "입학연도" in text and "일반과정/심화과정 여부" in text
    assert "2024학년도 2학기" in text
    assert "학과 표는 게시·개정일 미표시" in text

def test_department_table_replaces_conflicting_old_msc_numbers():
    text = answer("2020학번 심화과정 MSC 몇 학점 필요해?").text
    assert "과학 4학점" in text and "전산 3학점" in text
    assert "2019년" in text and "구분" in text

def test_english_scope_before_2013_does_not_inherit_minimum_scores():
    result = answer("2012학번 심화과정 영어 졸업요건")
    assert result.status == AnswerStatus.INSUFFICIENT_EVIDENCE
    assert "TOEIC 600" not in result.text

def test_source_corruption_blocks_stale_fallback(tmp_path):
    shutil.copytree(ROOT / "config/reviewed_rules", tmp_path / "config/reviewed_rules")
    (tmp_path / "config/reviewed_rules/sources/english_amendment_2024.html").write_text("changed")
    response = reviewed_rule_search("졸업요건", DEPT, tmp_path)
    assert not response.results
    assert "보류" in response.clarification_message

def test_unrelated_department_and_document_filter_are_respected():
    assert reviewed_rule_search("졸업요건", "디자인학과", ROOT) is None
    assert reviewed_rule_search("졸업요건", DEPT, ROOT, "장학금") is None
    assert reviewed_rule_search("자료구조 과목 학점", DEPT, ROOT) is None
    assert graduation_topic("MSC 과목 목록 알려줘") is None

def test_reviewed_response_is_not_rewritten_by_llm():
    response = reviewed_rule_search("졸업 영어 대체", DEPT, ROOT)
    class NeverCall:
        def generate(self, **kwargs):
            pytest.fail("Reviewed amendment must not be dropped by generation")
    search = SimpleNamespace(search_with_context=lambda *a, **k: response)
    result = LLMAnswerService(search, provider=NeverCall(), enabled=True).answer_question("졸업 영어 대체")
    assert result.text == response.reviewed_answer

def test_real_search_service_routes_before_old_index(tmp_path):
    # No embeddings or historical index should be needed for verified references.
    class Store:
        def list_metadata_values(self, field):
            return [DEPT]
        def count(self):
            pytest.fail("Reviewed references should precede the old index")
    service = DocumentSearchService(embedding_provider=None, vector_store=Store(),
        chunk_size=500, chunk_overlap=50, top_k=3, min_retrieval_score=.2,
        dedup_similarity_threshold=.9, project_root=ROOT)
    result = service.search_with_context("소프트웨융합학과 졸업할려면 뭐뭐 해야해?")
    assert result.reviewed_answer
    assert "2024학년도 2학기" in result.reviewed_answer

def test_ui_context_does_not_override_question_or_infer_year():
    assert add_scope_to_question("2020학번 일반과정 졸업요건", 2018, "심화과정") == "2020학번 일반과정 졸업요건"
    assert add_scope_to_question("졸업요건") == "졸업요건"
    assert admission_years(add_scope_to_question("졸업요건", 2020)) == {2020}


def test_natural_evaluation_discovered_design_phrase():
    assert "12학점" in answer("2020학번 심화과정 설계학점은 얼마나 필요해?").text


@pytest.mark.parametrize("q", ["편입생도 졸업할 때 전공 54학점만 들으면 돼?", "복수전공 하면 영어 졸업요건 면제돼?", "내가 이번 학기에 졸업 가능한지 확정해줘", "일반과정인지 심화과정인지 모르는데 졸업요건 알려줘"])
def test_natural_evaluation_discovered_unsupported_personal_and_exception_scope(q):
    result = answer(q)
    assert result.status == AnswerStatus.INSUFFICIENT_EVIDENCE
    assert "54학점" not in result.text
