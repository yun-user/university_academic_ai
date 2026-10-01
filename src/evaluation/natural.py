"""Capture answers separately from human quality judgements.

Unreviewed answers have no quality score. Reviews are bound to an immutable
run digest so that changed answers cannot silently inherit old ratings.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.answering.answer_service import AnswerService
from src.retrieval.reviewed_rules import add_scope_to_question


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=80)
    group: str = Field(min_length=1)
    category: str = Field(min_length=1)
    question: str = Field(min_length=1, max_length=2000)
    department: str | None = None
    admission_year: int | None = Field(default=None, ge=1900, le=2100)
    track: Literal["심화과정", "일반과정"] | None = None
    split: Literal["dev", "test"] = "dev"
    origin: Literal["ai_authored", "student", "instructor"] = "ai_authored"
    reference_note: str = ""


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    # All three dimensions are required for a completed human review.
    correctness: Literal["correct", "partial", "incorrect"]
    grounding: Literal["supported", "partial", "unsupported", "not_applicable"]
    scope_handling: Literal["appropriate", "inappropriate"]
    expected_action: Literal["answer", "clarify", "abstain"]
    reviewer: str = Field(min_length=1, max_length=80)
    rationale: str = Field(min_length=1, max_length=4000)
    reference: str = Field(min_length=1, max_length=4000)


def load_cases(path):
    raw = Path(path).read_bytes()
    cases = [Case.model_validate_json(line) for line in raw.decode("utf-8-sig").splitlines() if line.strip()]
    validate_cases(cases)
    return cases, hashlib.sha256(raw).hexdigest()


def validate_cases(cases):
    if not cases:
        raise ValueError("평가 질문이 없습니다.")
    if len({c.id for c in cases}) != len(cases):
        raise ValueError("평가 질문 ID가 중복됩니다.")
    dev = {c.group for c in cases if c.split == "dev"}
    test = {c.group for c in cases if c.split == "test"}
    if dev & test:
        raise ValueError("같은 질문 그룹이 dev/test에 섞여 있습니다.")
    questions = ["".join(c.question.casefold().split()) for c in cases]
    if len(set(questions)) != len(questions):
        raise ValueError("중복 질문이 있습니다.")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def project_fingerprint(root):
    root = Path(root)
    paths = [*root.glob("src/**/*.py"), *root.glob("config/reviewed_rules/**/*")]
    paths += [root / "data/processed/documents.jsonl", root / "config/defaults.toml"]
    hashes = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in paths if p.is_file()}
    return {"sha256": digest(hashes), "files": hashes}


def capture_run(service, cases, *, dataset_hash, root, mode="hybrid", split="dev", top_k=3):
    from src.operations import project_lock
    # The cached service is shared with interactive searches. Keep its temporary
    # search mode and the captured corpus/code version inside the same lock.
    with project_lock(getattr(service, "_project_root", Path(root).resolve())):
        return _capture_run(service, cases, dataset_hash=dataset_hash, root=root,
                            mode=mode, split=split, top_k=top_k)


def _capture_run(service, cases, *, dataset_hash, root, mode, split, top_k):
    if mode not in {"dense", "hybrid"} or top_k < 1:
        raise ValueError("평가 설정이 올바르지 않습니다.")
    selected = [c for c in cases if c.split == split]
    if not selected:
        raise ValueError("선택한 구분에 질문이 없습니다.")
    previous = service._search_mode
    rows = []
    try:
        service._search_mode = mode
        answerer = AnswerService(service)
        for case in selected:
            question = add_scope_to_question(case.question, case.admission_year, case.track)
            start = time.perf_counter()
            row = {"case": case.model_dump(), "effective_question": question}
            try:
                result = answerer.answer_question(question, department=case.department, top_k=top_k)
                row.update(status=result.status.value, answer=result.text,
                    answer_mode=result.answer_mode.value,
                    route="reviewed_rules" if result.search_response.reviewed_answer else "corpus",
                    sources=[s.model_dump(mode="json") for s in result.sources],
                    retrieved=[{"chunk_id": r.chunk_id, "file_name": r.file_name,
                        "page_number": r.page_number, "row_number": r.row_number,
                        "source_url": r.source_url, "text": r.text} for r in result.search_response.results],
                    error=None)
            except Exception as exc:
                # Do not persist provider errors/configuration secrets or tracebacks.
                row.update(status="error", answer="", answer_mode="deterministic",
                           route="error", sources=[], retrieved=[], error=type(exc).__name__)
            row["seconds"] = round(time.perf_counter() - start, 4)
            rows.append(row)
    finally:
        service._search_mode = previous
    return {"schema_version": 1, "run_id": uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(), "dataset_sha256": dataset_hash,
        "project_fingerprint": project_fingerprint(root), "split": split, "search_mode": mode,
        "top_k": top_k, "llm_requested": False,
        "limitation": "답변 수집 결과이며 아직 사람의 품질 평가가 아닙니다. AI 작성 질문은 개발 회귀용입니다. 검토 규정/정확 조회 경로는 두 검색 방식이 공유하므로 검색 방식 우월성의 근거로 사용할 수 없습니다.",
        "rows": rows}


def save_run(folder, run):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    # Caller-supplied IDs never become filesystem paths.
    path = folder / (uuid4().hex + ".json")
    with path.open("x", encoding="utf-8") as target:
        json.dump(run, target, ensure_ascii=False, indent=2)
    return path


def load_reviews(run_path, run):
    path = Path(str(run_path) + ".reviews.json")
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload["run_sha256"] != digest(run):
        raise ValueError("답변 실행 파일이 변경되어 기존 채점과 일치하지 않습니다.")
    ids = {r["case"]["id"] for r in run["rows"]}
    if not set(payload["reviews"]).issubset(ids):
        raise ValueError("채점에 알 수 없는 질문 ID가 있습니다.")
    return {key: Review.model_validate(value).model_dump() for key, value in payload["reviews"].items()}


def save_review(run_path, run, case_id, review):
    from filelock import FileLock
    path = Path(str(run_path) + ".reviews.json")
    with FileLock(str(path) + ".lock", timeout=10):
        actual_run = json.loads(Path(run_path).read_text(encoding="utf-8"))
        if digest(actual_run) != digest(run):
            raise ValueError("실행 결과가 변경되었습니다. 다시 불러오세요.")
        if case_id not in {r["case"]["id"] for r in run["rows"]}:
            raise ValueError("알 수 없는 질문 ID입니다.")
        reviews = load_reviews(run_path, run)
        reviews[case_id] = Review.model_validate(review).model_dump()
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(json.dumps({"run_sha256": digest(run), "reviews": reviews},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)


def summarize_run(run, reviews):
    ids = {r["case"]["id"] for r in run["rows"]}
    if not set(reviews).issubset(ids):
        raise ValueError("알 수 없는 질문 ID입니다.")
    reviewed = [Review.model_validate(r) for r in reviews.values()]
    grounded = [r for r in reviewed if r.grounding != "not_applicable"]
    refusal = [r for r in reviewed if r.expected_action in {"clarify", "abstain"}]
    def rate(hits, total):
        return hits / total if total else None
    return {"questions": len(run["rows"]), "reviewed": len(reviewed),
        "unreviewed": len(run["rows"]) - len(reviewed),
        "errors": sum(r["status"] == "error" for r in run["rows"]),
        "reviewed_rule_answers": sum(r["route"] == "reviewed_rules" for r in run["rows"]),
        "correct_answer_rate": rate(sum(r.correctness == "correct" for r in reviewed), len(reviewed)),
        "fully_grounded_rate": rate(sum(r.grounding == "supported" for r in grounded), len(grounded)),
        "grounding_denominator": len(grounded),
        "appropriate_scope_rate": rate(sum(r.scope_handling == "appropriate" for r in reviewed), len(reviewed)),
        "appropriate_clarification_or_abstention_rate": rate(sum(r.scope_handling == "appropriate" for r in refusal), len(refusal)),
        "clarification_or_abstention_denominator": len(refusal)}
