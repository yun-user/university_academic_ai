"""Append-only local evaluation questions; never included in release archives."""
from pathlib import Path
from uuid import uuid4

from filelock import FileLock

from src.evaluation.natural import Case, load_cases, validate_cases


def bank_path(root):
    return Path(root) / "evals/private_questions/student.jsonl"


def registered_cases(root):
    path = bank_path(root)
    return load_cases(path)[0] if path.exists() else []


def add_question(root, *, question, group, category, origin, reference_note="",
                 department=None, admission_year=None, track=None, split="dev"):
    case = Case(id="Q-" + uuid4().hex, question=question, group=group,
                category=category, origin=origin, reference_note=reference_note,
                department=department, admission_year=admission_year, track=track, split=split)
    path = bank_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + ".lock", timeout=10):
        existing = registered_cases(root)
        bundled_path = Path(root) / "evals/natural_dev.jsonl"
        bundled = load_cases(bundled_path)[0] if bundled_path.exists() else []
        # Also reject overlap with the development examples already shipped.
        validate_cases([*bundled, *existing, case])
        temp = path.with_name(path.name + ".tmp")
        try:
            temp.write_text("".join(c.model_dump_json() + "\n" for c in [*existing, case]), encoding="utf-8")
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)
    return case
