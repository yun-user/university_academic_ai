import csv
import json

from scripts import build_evaluation


def test_generated_identifiers_skip_semester_markers_and_missing_codes(tmp_path, monkeypatch):
    path = tmp_path / "data/raw/tables/소프트웨어융합학과_학년별교과과정_2026.csv"
    path.parent.mkdir(parents=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["교과목명", "1학기_학수번호", "2학기_학수번호"])
        writer.writerow(["종합설계(2)", "부학기", "704814"])
        writer.writerow(["미지정과목", "", ""])
    monkeypatch.setattr(build_evaluation, "PROJECT_ROOT", tmp_path)
    build_evaluation.main()
    cases = [json.loads(line) for line in (tmp_path / "evals/regression.jsonl").read_text(encoding="utf-8").splitlines()]
    identifiers = [case for case in cases if case["question"].startswith("학수번호")]
    assert len(identifiers) == 1
    assert identifiers[0]["question"] == "학수번호 704814 교과목 정보"
    assert identifiers[0]["expected"][0]["row_number"] == 1
