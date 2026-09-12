"""Reviewed table summaries, bound to the exact source page and scope.

Tables cannot safely be summarized by splitting their extracted text at newlines.
Use a reviewed summary only while its complete source page remains unchanged.
"""
import hashlib
import json
from pathlib import Path
import re
from src.retrieval.query_intent import graduation_topic

CATALOG = Path(__file__).resolve().parents[2] / "config" / "reviewed_graduation.json"


def reviewed_graduation(question, results):
    topic = graduation_topic(question)
    if topic is None:
        return None
    # This summary covers the complete requirements table, not specific
    # questions about retaking courses, exceptions, or changing programs.
    compact = re.sub(r"\s+", "", question)
    if re.search(r"재수강|과정변경|포기|면제|복수전공|부전공|편입|전과", compact):
        return None
    try:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for result in results:
        for entry in catalog:
            if (result.department != entry["department"]
                or result.file_name != entry["file_name"]
                or result.page_number != entry["page_number"]
                or result.source_year != entry["source_year"]
                or hashlib.sha256(result.text.encode()).hexdigest() != entry["page_sha256"]):
                continue
            # A different institution/program sharing a department name must
            # also match the exact original content to use this summary.
            text = entry["summary"]
            if topic == "major_credits":
                text = entry.get("major_credit_answer", text)
            elif topic in {"total_credits", "english", "design"}:
                # Select reviewed sections; do not generate new numerical facts.
                summary = entry["summary"]
                introduction = summary.split("**1.")[0].strip()
                if topic == "total_credits":
                    body = "**1." + summary.split("**1.", 1)[1].split("**2.", 1)[0].strip()
                elif topic == "english":
                    body = "**3." + summary.split("**3.", 1)[1].split("**적용 확인:", 1)[0].strip()
                else:
                    body = next(line for line in summary.splitlines() if line.startswith("- **설계:**"))
                text = (introduction + "\n\n" + body + "\n\n"
                    "다른 영역의 졸업요건도 함께 충족해야 합니다. 입학연도와 일반/심화과정 여부에 맞는 최신 기준을 확인하세요.\n\n"
                    f"출처: {entry['file_name']} · PDF {entry['page_number']}쪽 · 기준연도 {entry['source_year']}년.")
            if "일반과정" in compact or "비인증" in compact:
                text = (f"등록된 {entry['source_year']}년 {entry['department']} 자료의 학점 표는 "
                        "**공학교육인증 심화과정** 기준입니다. 일반과정의 졸업요건으로 적용할 수 없습니다.\n\n"
                        "일반과정의 필요한 전공학점은 현재 확인한 표만으로 확정할 수 없습니다. "
                        "입학연도에 맞는 일반과정 졸업요건 자료가 필요합니다.\n\n"
                        f"출처: {entry['file_name']} · PDF {entry['page_number']}쪽.")
            return text, result
    return None
