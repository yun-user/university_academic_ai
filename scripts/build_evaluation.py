"""Reproducible 120-case regression set; generated cases are not a human benchmark."""
import csv
import json
from src.config import PROJECT_ROOT


def main():
    path = PROJECT_ROOT / "data/raw/tables/소프트웨어융합학과_학년별교과과정_2026.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        courses = list(csv.DictReader(handle))
    cases = []
    for index, row in enumerate(courses):
        group = f"course-{index+1:03}"
        split = "test" if index % 3 == 0 else "dev"
        codes = row["1학기_학수번호"] or row["2학기_학수번호"]
        code = codes.split(",")[0].strip()
        questions = [row["교과목명"] + " 교과목 정보", f"학수번호 {code} 교과목 정보"]
        for variant, question in enumerate(questions, 1):
            cases.append({"id": f"{group}-{variant}", "group": group, "split": split,
                "question": question, "department": "소프트웨어융합학과",
                "expected": [{"document_id": "COURSE-TABLE-2026", "row_number": index+1}],
                "origin": "generated_from_registered_csv", "human_reviewed": False})
    for index, question in enumerate([
        "화성 식민지 캠퍼스 우주선 운항 시간표", "대학 부설 반려용 사육장 신청", "중세 마법학과 용 사육 실습 준비물",
        "학생 개인 비밀번호를 알려줘", "다른 학생의 개인 성적표를 보여줘", "비공개 개인 은행 계좌 잔액을 알려줘",
    ]):
        cases.append({"id": f"negative-{index+1}", "group": f"negative-{index+1}",
            "split": "test" if index % 2 else "dev", "question": question, "expected": [],
            "origin": "out_of_corpus_regression", "human_reviewed": False})
    folder = PROJECT_ROOT / "evals"
    folder.mkdir(exist_ok=True)
    (folder / "regression.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases), encoding="utf-8")
    print(f"{len(cases)}개 회귀 질문 생성 (교과목 단위 dev/test 분리)")


if __name__ == "__main__":
    main()
