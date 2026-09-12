"""Compare dense/hybrid retrieval against fixed source locations, with no LLM calls."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from src.config import PROJECT_ROOT, get_settings
from src.evaluation.metrics import score_case, summarize
from src.retrieval.document_search_service import DocumentSearchService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=PROJECT_ROOT / "evals/regression.jsonl")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--modes", nargs="+", choices=["dense", "hybrid"], default=["dense", "hybrid"])
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    raw = args.dataset.read_bytes()
    all_cases = [json.loads(line) for line in raw.decode("utf-8-sig").splitlines() if line.strip()]
    dev_groups = {c["group"] for c in all_cases if c["split"] == "dev"}
    test_groups = {c["group"] for c in all_cases if c["split"] == "test"}
    if dev_groups & test_groups:
        raise ValueError("동일 질문 그룹이 dev와 test에 섞여 있습니다.")
    cases = [case for case in all_cases if case["split"] == args.split]
    settings = get_settings()
    output = {"created_at": datetime.now(timezone.utc).isoformat(), "split": args.split,
        "dataset_sha256": hashlib.sha256(raw).hexdigest(), "top_k": args.top_k,
        "threshold": args.threshold if args.threshold is not None else settings.min_retrieval_score,
        "embedding_model": settings.embedding_model_name,
        "limitation": "자동 생성 회귀 질문입니다. 실제 학생 질문을 사람이 검토한 품질 평가를 대체하지 않습니다.",
        "modes": {}}
    with DocumentSearchService.from_settings(settings) as service:
        # Encode the fixed evaluation questions together, then reuse identical vectors for both modes.
        vectors = service._embeddings._encode([c["question"] for c in cases], prefix=settings.embedding_query_prefix)
        lookup = dict(zip([c["question"] for c in cases], vectors, strict=True))
        service._embeddings.embed_query = lambda question: lookup[question]
        for mode in args.modes:
            service._search_mode = mode
            details = []
            for case in cases:
                start = time.perf_counter()
                results = service.search(case["question"], top_k=args.top_k, min_score=args.threshold,
                                         department=case.get("department"))
                details.append({"id": case["id"], "question": case["question"], **score_case(case, results),
                    "seconds_without_embedding": time.perf_counter() - start,
                    "returned": [{"document_id": r.document_id, "page_number": r.page_number,
                                  "row_number": r.row_number, "score": r.score} for r in results]})
            output["modes"][mode] = {"metrics": summarize(details), "details": details}
    directory = PROJECT_ROOT / "evals/reports"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (args.split + "-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".json")
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({mode: value["metrics"] for mode, value in output["modes"].items()}, ensure_ascii=False, indent=2))
    print(path.relative_to(PROJECT_ROOT))


if __name__ == "__main__":
    main()
