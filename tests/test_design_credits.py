from pathlib import Path
from types import SimpleNamespace
import shutil
import pytest
from src.answering.answer_service import AnswerService
from src.answering.llm_answer_service import LLMAnswerService
from src.retrieval.course_search import parse_course_info
from src.retrieval.document_search_service import DocumentSearchService
from src.retrieval.query_intent import graduation_topic
from src.retrieval.reviewed_rules import reviewed_rule_search

ROOT = Path(__file__).resolve().parents[1]
DEPT = '소프트웨어융합학과'

@pytest.mark.parametrize('question', ['설계학점 12학점에는 어떤 과목이 포함돼?', '설계 인정학점은 어떤 과목에서 채워?', '설계교과목 목록 알려줘', '2018학번인데 설계학점은 몇 학점 필요해?'])
def test_design_allocation_uses_complete_table_not_top_three_courses(question):
    assert graduation_topic(question) == 'design'
    service = DocumentSearchService(embedding_provider=None,
        vector_store=SimpleNamespace(list_metadata_values=lambda key: [DEPT]),
        chunk_size=500, chunk_overlap=50, top_k=3, min_retrieval_score=.2,
        dedup_similarity_threshold=.9, project_root=ROOT)
    response = service.search_with_context(question)
    answer = AnswerService.compose_answer(question, response)
    assert '설계 8학점' in answer.text
    assert '4학점 이상을 추가' in answer.text
    assert '| 소프트웨어공학 | 1학점 |' in answer.text
    assert '| 알고리즘및실습 | 1학점 |' in answer.text
    assert '실제 수강연도' in answer.text
    assert '전체 학점이 아니라' in answer.text
    assert len(answer.text.split('| 요소설계 |')) == 10
    assert answer.sources[0].source_url.endswith('/curriculum/courses')
    class NeverCall:
        def generate(self, **kwargs):
            pytest.fail('Do not rewrite verified credit allocations')
    search = SimpleNamespace(search_with_context=lambda *args, **kw: response)
    assert LLMAnswerService(search, provider=NeverCall(), enabled=True).answer_question(question).text == answer.text

@pytest.mark.parametrize('question', ['2017년에 수강한 설계교과목 알려줘', '2018년에 들은 설계학점 몇 학점이야?', '설계학점 수강연도 2016 기준 알려줘'])
def test_old_course_taking_year_never_inherits_2019_table(question):
    result = reviewed_rule_search(question, DEPT, ROOT)
    assert not result.results
    assert '해당 수강연도' in result.clarification_message

def test_design_source_change_blocks_answer(tmp_path):
    shutil.copytree(ROOT / 'config/reviewed_rules', tmp_path / 'config/reviewed_rules')
    (tmp_path / 'config/reviewed_rules/sources/design_courses.html').write_text('modified')
    result = reviewed_rule_search('설계학점 12학점에는 어떤 과목이 포함돼?', DEPT, tmp_path)
    assert not result.results and '보류' in result.clarification_message

def test_course_code_uses_real_semester_without_rewriting_source():
    course = parse_course_info('교과목명: 종합설계(2)\n1학기_학수번호: 부학기\n1학기_학점: 3\n1학기_시수: 4\n2학기_학수번호: 704814\n2학기_학점: 3\n2학기_시수: 4')
    assert AnswerService._answer_semester(course, None).course_code == '704814'
    assert AnswerService._answer_semester(course, 1).course_code == '부학기'
