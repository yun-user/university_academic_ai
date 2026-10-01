import json
import streamlit as st
from pydantic import ValidationError
from src.admin_auth import require_admin
from src.config import get_settings
from src.evaluation.natural import load_reviews, save_review, summarize_run

st.set_page_config(page_title="자연어 답변 평가", page_icon="📝", layout="wide")
st.title("자연어 답변 평가")
require_admin()
st.caption("답변과 원문을 대조한 뒤 채점하세요. 미채점 답변에는 품질 점수가 없습니다.")
folder = get_settings().project_root / "evals/local_runs"
reports = sorted((p for p in folder.glob("*.json") if not p.name.endswith(".reviews.json")),
                 key=lambda p: p.stat().st_mtime, reverse=True)
if not reports:
    st.info("평가질문관리 페이지에서 답변 수집을 실행하세요. evaluate_natural.cmd로도 실행할 수 있습니다.")
    st.stop()
path = st.selectbox("평가 실행 파일", reports, format_func=lambda p: p.name)
try:
    run = json.loads(path.read_text(encoding="utf-8"))
    reviews = load_reviews(path, run)
    stats = summarize_run(run, reviews)
except (ValueError, KeyError, OSError) as exc:
    st.error("평가 파일을 읽을 수 없거나 기존 채점과 일치하지 않습니다. 원본 파일을 확인하세요.")
    st.stop()
st.info(run["limitation"])
st.caption(f"{run['created_at']} · {run['search_mode']} · {run['split']} · 기본 답변 수집 · API 호출 없음")
cols = st.columns(3)
cols[0].metric("질문 수", stats["questions"])
cols[1].metric("채점 완료", stats["reviewed"])
cols[2].metric("미채점", stats["unreviewed"])
st.write("채점된 표본의 정답률", "미채점" if stats["correct_answer_rate"] is None else f"{stats['correct_answer_rate']:.1%}")
st.caption("부분 정답은 정답률의 분자에 포함하지 않습니다. 전체 질문 정확도로 확대 해석하지 마세요.")
with st.expander("지표별 분모와 상세 결과"):
    st.json(stats)
row_id = st.selectbox("검토할 질문", range(len(run["rows"])),
    format_func=lambda i: run["rows"][i]["case"]["id"] + " · " + run["rows"][i]["case"]["question"])
row = run["rows"][row_id]
case = row["case"]
st.subheader(case["question"])
st.caption(f"범주: {case['category']} · 작성 출처: {case['origin']} · 상태: {row['status']} · 처리 경로: {row['route']}")
st.text(row["effective_question"])
if case.get("reference_note"):
    with st.expander("질문 등록 시 작성한 기대 답변 메모"):
        st.caption("등록자의 메모입니다. 채점 전 공식 원문과 대조하세요.")
        st.text(case["reference_note"])
st.markdown(row["answer"] or "실행 오류로 답변이 기록되지 않았습니다.")
with st.expander("답변에 사용된 출처와 원문", expanded=True):
    for source in row["sources"]:
        st.write(source["file_name"], "페이지", source.get("page_number"), "행", source.get("row_number"))
        url = source.get("source_url")
        if url and url.startswith("https://"):
            st.link_button("공식 원문 열기", url)
        st.text(source["excerpt"])
    if not row["sources"]:
        st.write("사용된 출처 없음")
with st.expander("검색에서 반환한 전체 근거"):
    st.json(row["retrieved"])
options = {
    "correctness": {"correct": "정답", "partial": "부분 정답", "incorrect": "오답"},
    "grounding": {"supported": "모든 주장과 출처가 일치", "partial": "일부만 일치", "unsupported": "근거 불일치", "not_applicable": "주장 없이 보류하여 해당 없음"},
    "scope_handling": {"appropriate": "적절", "inappropriate": "부적절"},
    "expected_action": {"answer": "답변", "clarify": "추가 질문", "abstain": "답변 보류"},
}
labels = {"correctness": "질문에 대한 정확성", "grounding": "출처에 의한 뒷받침", "scope_handling": "학번·과정·정보 부족 처리", "expected_action": "이 질문에 기대하는 행동"}
existing = reviews.get(case["id"], {})
with st.form("review-" + path.stem + "-" + case["id"]):
    values = {}
    for key, mapping in options.items():
        choices = [None, *mapping]
        values[key] = st.selectbox(labels[key], choices, index=choices.index(existing.get(key)),
            format_func=lambda v, m=mapping: "미채점" if v is None else m[v])
    values["reviewer"] = st.text_input("평가자 식별명 (별칭 가능)", value=existing.get("reviewer", ""))
    values["reference"] = st.text_area("기대 정답과 확인한 문서명·페이지·URL 또는 보류 이유", value=existing.get("reference", ""))
    values["rationale"] = st.text_area("채점 이유·누락·개선점", value=existing.get("rationale", ""))
    if st.form_submit_button("채점 저장"):
        try:
            save_review(path, run, case["id"], values)
        except (ValidationError, ValueError, OSError):
            st.error("모든 채점 항목과 평가자·근거·이유를 입력하세요. 파일이 바뀌었다면 다시 불러오세요.")
        else:
            st.rerun()
export = {"run": run, "reviews": reviews, "summary": stats}
st.download_button("실행·채점 결과 JSON 내려받기", json.dumps(export, ensure_ascii=False, indent=2),
                   "natural-evaluation.json", "application/json")
