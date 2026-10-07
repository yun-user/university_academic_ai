import json
from pathlib import Path

from src.answering.answer_service import AnswerService
from src.answering.graduation import reviewed_graduation
from src.answering.llm_answer_service import LLMAnswerService
from src.retrieval.document_models import DocumentSearchResponse, DocumentSearchResult
from src.retrieval.query_intent import QuestionIntent


def evidence():
    root = Path(__file__).resolve().parents[1]
    row = json.loads((root / 'tests/fixtures/graduation-page.json').read_text(encoding='utf-8'))
    import hashlib
    return DocumentSearchResult(document_id=row["document_id"], chunk_id="page-test",
        file_name=row["file_name"], file_type="pdf", document_type=row["document_type"],
        department=row["department"], title=row["title"], page_number=16,
        source_path=row["metadata"]["source_path"], text=row["text"], score=.8,
        source_year=row["source_year"], is_current=False,
        content_hash=hashlib.sha256(row["text"].encode()).hexdigest())


def test_reviewed_table_answers_requirements_and_preserves_scope():
    result = evidence()
    response = DocumentSearchResponse(results=[result], question_intent=QuestionIntent.ACADEMIC_RULE)
    answer = AnswerService.compose_answer("소프트웨어융합학과 졸업요건", response)
    for value in ["132학점", "140학점", "2019년", "2004~2015년", "심화과정", "12학점", "TOEIC 600"]:
        assert value in answer.text
    assert answer.sources[0].page_number == 16
    assert "최신" in answer.text
    assert "디자인엔지니어링" not in answer.text
    class Search:
        def search_with_context(self, *args, **kwargs):
            return response
    class NeverCall:
        def generate(self, **kwargs):
            raise AssertionError("Reviewed table must retain exact values")
    assert LLMAnswerService(Search(), provider=NeverCall(), enabled=True).answer_question(
        "소프트웨어융합학과 졸업요건").text == answer.text


def test_changed_or_partial_sources_cannot_use_old_summary():
    result = evidence()
    for changes in [{"text": result.text.replace("132", "130")}, {"text": result.text[:200]},
                    {"department": "다른학과"}, {"source_year": "2026"}, {"page_number": 17}]:
        assert reviewed_graduation("소프트웨어융합학과 졸업요건", [result.model_copy(update=changes)]) is None
    assert reviewed_graduation("소프트웨어융합학과 재수강 졸업요건", [result]) is None
    assert "일반과정의 졸업요건으로 적용할 수 없습니다" in reviewed_graduation(
        "소프트웨어융합학과 일반과정 졸업요건", [result])[0]


def test_colloquial_major_credit_questions_get_focused_answer():
    from src.retrieval.query_intent import is_graduation_question, classify_question_intent
    for question in ["졸업할려면 전공학점을 몇 학점 들어야 해?", "졸업하려면 전공 몇 학점 필요해?",
                     "전공학점 몇 학점 필요해?", "소프트웨어융합학과 졸업 전공학점"]:
        assert is_graduation_question(question)
        assert classify_question_intent(question) is QuestionIntent.ACADEMIC_RULE
        text, result = reviewed_graduation(question, [evidence()])
        assert "전공 54학점" in text
        assert "2019년" in text and "심화과정" in text
        assert len(text) < 600
        assert "디자인엔지니어링" not in text
