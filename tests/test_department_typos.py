from types import SimpleNamespace
import pytest
from src.retrieval.document_search_service import DocumentSearchService


@pytest.mark.parametrize("name", ["소프트웨융합학과", "소프트웨어융함학과", "소프트웨어어융합학과"])
def test_single_character_typo_matches_only_registered_department(name):
    service = SimpleNamespace(available_departments=lambda: ["전체", "소프트웨어융합학과"])
    assert DocumentSearchService._question_department(service, name + " 졸업할려면 뭐뭐 해야해?", None) == "소프트웨어융합학과"


def test_ambiguous_or_unrelated_department_never_guesses():
    service = SimpleNamespace(available_departments=lambda: ["소프트웨어융합학과", "소프트웨이융합학과"])
    assert DocumentSearchService._question_department(service, "소프트웨융합학과 졸업요건", None) == "소프트웨융합학과"
    assert DocumentSearchService._question_department(service, "디자인학과 졸업요건", None) == "디자인학과"
    assert DocumentSearchService._question_department(service, "소프트웨이융합학과 졸업요건", None) == "소프트웨이융합학과"
