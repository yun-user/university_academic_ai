"""Run: python -m scripts.evaluate_planner --output <new report directory>."""
import argparse
import json
from pathlib import Path

from src.config import PROJECT_ROOT
from src.planning.evaluation import evaluate_scenarios
from src.planning.workspace import seoul_today


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "output/planner/evaluation")
    args = parser.parse_args()
    report = evaluate_scenarios(PROJECT_ROOT)
    report["evaluated_on"] = seoul_today().isoformat()
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output / "evaluation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    lines = ["# 졸업 로드맵 합성 시나리오 평가", "", report["notice"], "",
             f"{report['evaluated_on']}: {report['passed']}/{report['total']} 통과", "",
             "| 시나리오 | 기대값 | 실제값 | 결과 |", "| --- | --- | --- | --- |"]
    for row in report["results"]:
        lines.append(f"| {row['scenario']} | {row['expected']} | {row['actual']} | {'통과' if row['passed'] else '실패'} |")
    (args.output / "evaluation.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(f"Synthetic scenarios: {report['passed']}/{report['total']}. Output: {args.output}")
    return 0 if report["total"]==report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
