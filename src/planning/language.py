"""Source-backed language score comparison; submission is a separate condition."""
from datetime import datetime
from zoneinfo import ZoneInfo


def assess_language(record, policy, *, today=None):
    today = today or datetime.now(ZoneInfo("Asia/Seoul")).date()
    policy = policy or {}
    criteria = next((r for r in policy.get("exams", []) if record and r["id"] == record.exam), None)
    if not record or not criteria:
        return {"status": "확인 필요", "score_status": "확인 필요", "detail": "학과 표에 있는 시험·점수 척도를 선택하세요. 기타 시험·새 점수 척도는 학과 인정 기준 확인이 필요합니다."}
    score_status = "확인 필요"
    raw = record.score
    if "levels" in criteria:
        levels = criteria["levels"]
        if raw in levels:
            score_status = "충족" if levels.index(raw) >= levels.index(criteria["minimum"]) else "미충족"
    else:
        # Invalid/out-of-range scores are unknown, never silently accepted.
        if raw.isascii() and raw.isdigit() and 0 <= int(raw) <= criteria["maximum"]:
            score_status = "충족" if int(raw) >= criteria["minimum"] else "미충족"
    details = [f"{criteria['label']} 기준 {criteria['requirement']} · 입력 {raw or '없음'} · 점수 {score_status}"]
    status = score_status
    confirmed = record.submission_confirmed and record.submitted_on is not None and record.submitted_on <= today
    reference = record.submitted_on if confirmed else today
    if record.expires_on is None:
        details.append("성적표 유효기한 확인 필요")
        if status != "미충족": status = "확인 필요"
    elif record.expires_on < reference:
        status = "미충족"
        details.append("제출일 기준 유효기간 만료" if confirmed else "현재 유효기간 만료 · 새 성적표 또는 유효기간 내 제출·접수 확인 필요")
    else:
        details.append("제출일 기준 유효기간 확인" if confirmed else "현재 유효기간 내")
    if not confirmed:
        details.append("이번 졸업에 사용할 성적표 제출일·접수·인정 확인 필요 (미래 제출일은 완료로 처리하지 않음)")
        if status != "미충족": status = "확인 필요"
    else:
        details.append("이번 졸업에 사용할 성적표 제출·접수·인정: 사용자 확인")
    return {"status": status, "score_status": score_status, "detail": "; ".join(details)}
