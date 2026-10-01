"""Collect reproducible natural-language answers; never auto-grade accuracy."""
import argparse
import json
from pathlib import Path
from src.config import PROJECT_ROOT, get_settings
from src.evaluation.natural import load_cases, capture_run, save_run, summarize_run
from src.retrieval.document_search_service import DocumentSearchService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=PROJECT_ROOT / "evals/natural_dev.jsonl")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--mode", choices=["dense", "hybrid"], default="hybrid")
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()
    cases, dataset_hash = load_cases(args.dataset)
    with DocumentSearchService.from_settings(get_settings()) as service:
        run = capture_run(service, cases, dataset_hash=dataset_hash, root=PROJECT_ROOT,
                          mode=args.mode, split=args.split, top_k=args.top_k)
    path = save_run(PROJECT_ROOT / "evals/local_runs", run)
    print(json.dumps(summarize_run(run, {}), ensure_ascii=False, indent=2))
    print(path)
    if any(r["status"] == "error" for r in run["rows"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
