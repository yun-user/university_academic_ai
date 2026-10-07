"""Self-contained printable report, with escaped user content and no network assets."""
from html import escape

from src.planning.workspace import seoul_today


def _table(headers, rows):
    heading = "".join(f"<th>{escape(str(c))}</th>" for c in headers)
    body = "".join("<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{heading}</tr></thead><tbody>{body}</tbody></table>"


def render_report(profile, current, roadmap, rules, *, advice=None, model="") -> bytes:
    after = {c.key:c for c in roadmap.projected.checks}
    checks = _table(["점검 항목", "현재", "계획 후", "필요", "계획 후 상태", "기준"],
        [(c.key, c.current, after[c.key].current, c.required, after[c.key].status, after[c.key].detail) for c in current.checks])
    terms = "".join(f"<h3>{s.year}년 {s.term}학기 · {s.credits:g}학점</h3>" +
        _table(["학수번호", "과목", "학점", "추천 이유"],[(c.code,c.name,c.credits,c.reason) for c in s.courses]) for s in roadmap.semesters)
    def items(values):
        return "<ul>" + "".join(f"<li>{escape(v)}</li>" for v in values) + "</ul>"
    explanation = "<p>처리 방식: 기본 계산 · LLM 설명 없음</p>"
    if advice is not None:
        explanation = (f"<h2>LLM 맞춤 추천</h2><p>모델: {escape(model)} · 설명 문장은 참고용이며 졸업판정의 근거가 아닙니다.</p>"
                       f"<p>{escape(advice.summary)}</p>" +
                       items([p.code + ": " + p.reason for p in advice.priorities]) + items(advice.next_steps))
    html = f'''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; base-uri 'none'; form-action 'none'">
<title>졸업 로드맵 점검 보고서</title><style>
body{{font-family:Malgun Gothic,Arial,sans-serif;max-width:1100px;margin:32px auto;padding:0 24px;color:#18313a;line-height:1.65}}
h1,h2,h3{{color:#146c66}} table{{border-collapse:collapse;width:100%;font-size:12px;margin:12px 0 24px;table-layout:fixed}}
th,td{{border:1px solid #ccd8d7;padding:8px;text-align:left;overflow-wrap:anywhere}}th{{background:#ecf3f2}}
.notice{{padding:16px;background:#fff8dc;border-left:4px solid #b79535}}li{{overflow-wrap:anywhere}}
@media print{{body{{margin:0;padding:0;font-size:10pt}}thead{{display:table-header-group}}tr{{break-inside:avoid}}h2,h3{{break-after:avoid}}}}
@page{{size:A4 landscape;margin:12mm}}
</style></head><body><h1>나의 졸업 로드맵 · 참고용 점검 보고서</h1>
<p>2020학번 · 소프트웨어융합학과 · {escape(profile.track)}과정 · 작성일 {seoul_today().isoformat()}</p>
<div class="notice">학교의 공식 졸업판정이 아닙니다. 아래 계획은 입력 조건을 모두 만족하며 이수한다는 가정입니다.
브라우저의 인쇄 메뉴에서 인쇄하거나 PDF로 저장할 수 있습니다. 실제 이수내역과 사용자 확인 근거가 포함될 수 있으므로 공유 범위를 확인하세요.</div>
{explanation}<h2>현재와 계획 후의 요건 비교</h2>{checks}<h2>학기별 계획</h2>{terms}
<h2>계획 후에도 남는 항목</h2>{items(roadmap.unresolved)}
<h2>계산 가정</h2>{items(roadmap.assumptions)}<h2>출처와 적용 범위</h2>{items(list(rules.sources)+list(rules.notices))}
</body></html>'''
    return html.encode("utf-8")
