from concurrent.futures import ThreadPoolExecutor
import pytest
from src.evaluation.natural import Case, load_cases
from src.evaluation.question_bank import add_question, bank_path, registered_cases


def add(root, **changes):
    return add_question(root, **(dict(question="설계 과목을 알려 줘", group="design", category="설계",
                                      origin="student", reference_note="학과 설계 인정학점 표 확인") | changes))


def test_register_preserves_provenance_and_scope(tmp_path):
    assert registered_cases(tmp_path) == []
    case = add(tmp_path, admission_year=2020, track="심화과정")
    loaded, checksum = load_cases(bank_path(tmp_path))
    assert loaded == [case]
    assert loaded[0].origin == "student"
    assert loaded[0].admission_year == 2020
    assert loaded[0].reference_note == "학과 설계 인정학점 표 확인"
    assert len(checksum) == 64


@pytest.mark.parametrize("changes", [dict(question="설계과목을알려줘"),
                                      dict(question="설계 교과목은 뭐야?", split="test")])
def test_invalid_append_keeps_existing_bytes(tmp_path, changes):
    add(tmp_path)
    before = bank_path(tmp_path).read_bytes()
    with pytest.raises(ValueError):
        add(tmp_path, **changes)
    assert bank_path(tmp_path).read_bytes() == before


@pytest.mark.parametrize("changes", [dict(question="AI 개발 예시", group="another"),
                                      dict(question="다른 문장", group="bundled", split="test")])
def test_bundled_development_overlap_rejected(tmp_path, changes):
    path = tmp_path / "evals/natural_dev.jsonl"
    path.parent.mkdir()
    path.write_text(Case(id="N1", group="bundled", category="예시", question="AI 개발 예시").model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError):
        add(tmp_path, **changes)
    assert not bank_path(tmp_path).exists()


def test_origin_must_be_explicit(tmp_path):
    with pytest.raises(ValueError):
        add(tmp_path, origin=None)
    assert not bank_path(tmp_path).exists()


def test_concurrent_registrations_do_not_overwrite(tmp_path):
    def submit(i):
        return add(tmp_path, question=f"질문 {i}")
    with ThreadPoolExecutor(max_workers=4) as pool:
        saved = list(pool.map(submit, range(8)))
    assert {c.id for c in registered_cases(tmp_path)} == {c.id for c in saved}
