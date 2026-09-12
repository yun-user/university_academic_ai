import pytest
from src.retrieval.query_intent import graduation_topic, classify_question_intent, QuestionIntent


@pytest.mark.parametrize("question,topic", [
    ("소프트웨어융합학과 졸업요건이 뭐야?", "overview"),
    ("소프트웨어 융합 학과의 졸업 요건을 알려 주세요", "overview"),
    ("졸업하려면 뭘 해야 해?", "overview"),
    ("졸업할려면 뭐 해야 돼?", "overview"),
    ("졸업은 어떻게 하는 거야?", "overview"),
    ("우리 학과 졸업 조건 좀 설명해줘", "overview"),
    ("졸업하려고 하는데 필요한 게 뭐야?", "overview"),
    ("어떤 조건을 충족해야 졸업할 수 있나요?", "overview"),
    ("전공 얼마나 들어야 돼?", "major_credits"),
    ("전공을 얼마나 들어야 졸업해?", "major_credits"),
    ("전공 몇 학점 채워야 해?", "major_credits"),
    ("소프트웨어융합학과 졸업 전공학점", "major_credits"),
    ("졸업하려면 총 몇 학점 필요해?", "total_credits"),
    ("학점을 얼마나 채워야 졸업할 수 있어?", "total_credits"),
    ("졸업하려면 토익 몇 점 필요해?", "english"),
    ("졸업 영어 조건 좀 알려줘", "english"),
    ("설계 학점은 얼마나 들어야 졸업 가능해?", "design"),
])
def test_conversational_questions_have_consistent_intent(question, topic):
    assert graduation_topic(question) == topic
    assert classify_question_intent(question) is QuestionIntent.ACADEMIC_RULE


@pytest.mark.parametrize("question", [
    "졸업식 준비하려면 뭐 필요해?", "졸업사진은 어떻게 찍어?",
    "졸업 후 취업하려면 뭐 해야 돼?", "졸업논문 과목 몇 학점이야?",
    "졸업프로젝트 과목은 몇 학점인가요?", "자료구조는 몇 학점이야?",
    "2학년 1학기 전공필수 과목 알려줘", "학교 위치가 어디야?",
])
def test_unrelated_questions_do_not_receive_graduation_summary(question):
    assert graduation_topic(question) is None
