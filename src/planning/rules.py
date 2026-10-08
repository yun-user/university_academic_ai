"""Read scoped rules with source integrity checks; draft data stays provisional."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from src.planning.cohorts import SUPPORTED_ADMISSION_YEARS


@dataclass(frozen=True)
class RuleSet:
    track: str
    thresholds: dict[str, float]
    liberal_cap: float
    sources: tuple[str, ...]
    notices: tuple[str, ...]
    msc_computing_cap: float | None = None
    admission_year: int = 2020
    cohort_range: tuple[int, int] = (2019, 2021)
    science_mode: str = "physics"
    msc_detail: str = ""


def _verify(root, source):
    source_root = (root / "sources").resolve()
    path = (source_root / source["file"]).resolve()
    if not path.is_relative_to(source_root):
        raise ValueError("규정 원본 경로가 올바르지 않습니다.")
    if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
        raise ValueError("규정 원본이 바뀌었습니다. 대조 검토 후 계산을 다시 실행하세요.")


def load_rules(project_root: Path, track: str, admission_year: int = 2020) -> RuleSet:
    if track not in {"심화", "일반"}:
        raise ValueError("지원하는 과정이 아닙니다.")
    if admission_year not in SUPPORTED_ADMISSION_YEARS:
        raise ValueError("검토된 입학연도는 2018~2026학번입니다. 해당 연도 원본을 확인한 뒤 지원 범위를 넓혀야 합니다.")
    root = project_root / "config/reviewed_rules"
    try:
        college = json.loads((root / "aid_college_2026.json").read_text(encoding="utf-8"))
        _verify(root, college["source"])
        cohort = next(c for c in college["cohorts"] if c["track"] == track and c["from"] <= admission_year <= c["to"])
        department = json.loads((root / "hongik.json").read_text(encoding="utf-8"))
        for source in department["sources"]:
            _verify(root, source)
        accreditation = json.loads((root / "aid_accreditation_2026.json").read_text(encoding="utf-8"))
        _verify(root, accreditation["source"])
        review_path = root / "software_program_review.json"
        review = json.loads(review_path.read_text(encoding="utf-8")) if review_path.exists() else None
        if review:
            for source in review["sources"]:
                _verify(root, source)
    except (OSError, KeyError, StopIteration, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{admission_year}학번 규정 자료를 읽을 수 없습니다.") from exc
    thresholds = {"총 졸업인정학점": cohort["total"], "전공": cohort["major"],
                  "전문교양": cohort["liberal"], "특성화교양": cohort["specialized"],
                  "전공기초영어": cohort["basic_english"], "MSC 합계": cohort["msc"],
                  "SW·데이터활용": cohort["sw_data"],
                  "MSC수학": 3, "MSC과학": 4 if track == "심화" or admission_year >= 2024 else 8,
                  "MSC전산": 3 if track == "심화" or admission_year >= 2024 else (2 if admission_year >= 2020 else 0)}
    thresholds = {key: value for key, value in thresholds.items() if value is not None and value > 0}
    science_mode = ("one_set" if admission_year >= 2024 else "both") if track == "일반" else ("physics" if admission_year <= 2020 else "one_set")
    if track == "심화":
        thresholds["설계 인정학점"] = 12
    sources = (f"2026 교과과정 책자(안) PDF {cohort['page']}쪽 · 인쇄 {cohort['printed_page']}쪽",
               "https://ibook.hongik.ac.kr/Viewer/2026curriculum",
               accreditation["source"]["url"] + " · 대학 공통 내규 2026-03-01 · 제5·8~13·20조",
               "https://software.hongik.ac.kr/home/assets/files/2022_gradu.png",
               "https://software.hongik.ac.kr/home/templates/community/bbs_more?select=1&n=566",
               "클래스넷 → 졸업정보 → 졸업요건 조회 → 교과과정 적용원칙")
    if review:
        sources += ("사용자 제공 이수체계도.pdf 1쪽 · 2026 수강연도부터 학번 무관 적용; 2쪽은 권장 순서",
                    "소프트웨어융합학과 프로그램 이수내규 2019.12 · 수업 제8조, 공학교육인증 운영 제5조 · 최신 개정과 대조 필요")
    return RuleSet(track, thresholds, cohort["liberal_cap"], sources, (
        f"{admission_year}학번·소프트웨어융합학과·단일전공 신입학 기준의 참고 계산입니다. 편입·전과·복수전공은 별도 확인이 필요합니다.",
        "단과대학 기준은 2026 교과과정 책자(안)를 사용합니다. 최종 확정본·학과 확인 전에는 공식 졸업판정으로 사용할 수 없습니다.",
        "필수과목은 실제 학년 이수시점과 개정에 따라 달라집니다. 클래스넷의 적용원칙과 학과 확인 결과를 입력하세요.",
        "2026년 공통 내규: 일반과정 변경에는 예외 요건·학교 승인 확인이 필요합니다. 화면에서 과정만 바꾸어도 변경 승인이 성립하는 것은 아닙니다.",
        "심화 설계과목은 기초→요소→종합 순서 및 프로그램 이수체계를 확인해야 합니다. 사이버·타 캠퍼스 교양/MSC와 수강연도별 설계 인정도 별도 대조하세요.",
        "졸업논문·어학·등록학기·평점·공학인증 세부 인정 및 기타 졸업사정 조건은 별도 확인해야 합니다.",
        "2026-10-07 클래스넷 안내 링크도 교과과정 책자(안)로 연결됨을 확인했습니다. 확정본으로 간주하지 않습니다.",
        "심화 MSC전산은 제공된 2019.12 학과 내규의 최대6학점 기준을 보수적으로 적용합니다. 초과분은 총학점에는 포함됩니다. 최신 학과 개정·인정과목·어학 요건은 학교에 재확인해야 합니다.",
        "2022학번부터 SW·데이터활용 9학점을 별도로 점검합니다. 이수구분과 별개인 인정학점으로 입력하며 총학점에는 다시 더하지 않습니다. 대상 과목·영역 간 중복 인정은 학교 확인이 필요합니다.",
        "2021학번 이후 심화는 대학 공통의 실험 포함 과학 1set를 점검합니다. 학과 표의 직접 확인 범위는 2020학번까지이므로 과학 지정과목은 별도 확인합니다.",
    ), msc_computing_cap=6 if track == "심화" and review else None,
       admission_year=admission_year, cohort_range=(cohort["from"], cohort["to"]),
       science_mode=science_mode, msc_detail=cohort["msc_detail"])
