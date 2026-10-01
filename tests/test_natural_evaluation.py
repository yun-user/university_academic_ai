import json
from types import SimpleNamespace
import pytest
from src.evaluation.natural import (Case, capture_run, load_cases, save_run,
    save_review, load_reviews, summarize_run)
from src.retrieval.document_models import DocumentSearchResponse


def run_fixture(tmp_path):
    service = SimpleNamespace(_search_mode="dense", search_with_context=lambda *a, **k: DocumentSearchResponse())
    run = capture_run(service, [Case(id="Q1", group="one", category="unknown", question="졸업요건")],
                      dataset_hash="a" * 64, root=tmp_path)
    assert service._search_mode == "dense"
    return run


def review(**changes):
    return dict(correctness="correct", grounding="not_applicable", scope_handling="appropriate",
        expected_action="abstain", reviewer="검토자A", reference="등록자료에 해당 학번 근거 없음",
        rationale="확정하지 않고 추가 원문을 요구함") | changes


def test_no_human_review_means_no_accuracy(tmp_path):
    stats = summarize_run(run_fixture(tmp_path), {})
    assert stats["correct_answer_rate"] is None
    assert stats["fully_grounded_rate"] is None
    assert stats["unreviewed"] == 1


def test_grounding_na_is_not_counted_as_success(tmp_path):
    stats = summarize_run(run_fixture(tmp_path), {"Q1": review()})
    assert stats["correct_answer_rate"] == 1
    assert stats["fully_grounded_rate"] is None
    assert stats["grounding_denominator"] == 0
    assert stats["appropriate_clarification_or_abstention_rate"] == 1


def test_partial_answer_is_not_full_credit(tmp_path):
    stats = summarize_run(run_fixture(tmp_path), {"Q1": review(correctness="partial", grounding="partial")})
    assert stats["correct_answer_rate"] == 0
    assert stats["fully_grounded_rate"] == 0


def test_review_bound_to_exact_run_and_case(tmp_path):
    run = run_fixture(tmp_path)
    path = save_run(tmp_path, run)
    save_review(path, run, "Q1", review())
    assert load_reviews(path, run)["Q1"]["reviewer"] == "검토자A"
    changed = dict(run, search_mode="dense")
    with pytest.raises(ValueError):
        load_reviews(path, changed)
    with pytest.raises(ValueError):
        save_review(path, changed, "Q1", review())
    with pytest.raises(ValueError):
        save_review(path, run, "UNKNOWN", review())
    with pytest.raises(ValueError):
        save_review(path, run, "Q1", review(reference=""))


@pytest.mark.parametrize("change", [{"id": "Q1", "question": "다른 질문"},
    {"id": "Q2", "split": "test", "question": "다른 질문"},
    {"id": "Q2", "group": "two", "question": "졸업 요건"}])
def test_duplicate_and_leaking_groups_rejected(tmp_path, change):
    base = Case(id="Q1", group="one", category="scope", question="졸업요건").model_dump()
    path = tmp_path / "questions.jsonl"
    path.write_text(json.dumps(base) + "\n" + json.dumps(base | change))
    with pytest.raises(ValueError):
        load_cases(path)


def test_errors_record_type_only_and_restore_search_mode(tmp_path):
    def fail(*args, **kwargs):
        raise RuntimeError("SECRET-API-KEY")
    service = SimpleNamespace(_search_mode="dense", search_with_context=fail)
    run = capture_run(service, [Case(id="q", group="g", category="x", question="test")],
                      dataset_hash="x", root=tmp_path)
    assert run["rows"][0]["error"] == "RuntimeError"
    assert "SECRET" not in json.dumps(run)
    assert service._search_mode == "dense"


def test_dataset_has_honest_provenance():
    from src.config import PROJECT_ROOT
    cases, _ = load_cases(PROJECT_ROOT / "evals/natural_dev.jsonl")
    assert len(cases) == 31
    assert all(c.origin == "ai_authored" and c.split == "dev" for c in cases)


def test_capture_holds_project_lock_during_mode_change(tmp_path):
    from src.operations import project_lock
    lock = project_lock(tmp_path.resolve())
    def search(*args, **kwargs):
        assert lock.is_locked
        assert service._search_mode == "hybrid"
        return DocumentSearchResponse()
    service = SimpleNamespace(_search_mode="dense", search_with_context=search)
    run = capture_run(service, [Case(id="q", group="g", category="x", question="test")],
                      dataset_hash="x", root=tmp_path)
    assert run["rows"][0]["error"] is None
    assert not lock.is_locked
    assert service._search_mode == "dense"
