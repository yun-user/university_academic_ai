import streamlit as st
from filelock import Timeout

from src.admin_auth import require_admin
from src.config import get_settings
from src.evaluation.natural import capture_run, load_cases, save_run, summarize_run
from src.evaluation.question_bank import add_question, bank_path, registered_cases
from src.runtime import get_search_service

st.set_page_config(page_title="평가 질문 관리", page_icon="📋", layout="wide")
st.title("평가 질문 관리")
require_admin()
root = get_settings().project_root
st.caption("질문 등록 → 답변 수집 → 자연어답변평가에서 원문 대조·채점 순서로 진행하세요.")
notice = st.session_state.pop("question_saved_notice", None)
if notice:
    st.success(notice)
try:
    registered = registered_cases(root)
    bundled, _ = load_cases(root / "evals/natural_dev.jsonl")
except (ValueError, OSError):
    st.error("질문 파일을 읽을 수 없습니다. evals 폴더의 질문 파일을 확인하세요.")
    st.stop()

st.subheader("질문 등록")
st.write("실제로 받은 문장을 그대로 입력하고 작성 출처를 선택하세요. 이름·학번 같은 개인정보는 입력하지 마세요.")
st.caption("같은 뜻의 질문은 같은 그룹 이름을 사용하세요. 동일 그룹은 개발용과 최종 평가용에 나누어 넣을 수 없습니다.")
with st.expander("기존 그룹 확인"):
    st.dataframe([{"그룹": c.group, "구분": c.split, "질문": c.question}
                  for c in [*bundled, *registered]], hide_index=True)
origins = {"student": "실제 학생 질문", "instructor": "교수·조교 질문", "ai_authored": "AI가 작성한 예시 질문"}
with st.form("register_question", clear_on_submit=False):
    question = st.text_area("질문", max_chars=2000, key="new_question")
    origin = st.selectbox("작성 출처", [None, *origins],
                          format_func=lambda v: origins.get(v, "선택하세요"), key="new_origin")
    category = st.text_input("주제 (예: 설계학점)", key="new_category")
    group = st.text_input("질문 그룹 (예: design-course-list)", key="new_group")
    split = st.selectbox("사용 구분", ["dev", "test"],
                         format_func=lambda v: "개발용 (dev)" if v == "dev" else "최종 평가용 (test)", key="new_split")
    department = st.text_input("학과 (모르면 비워 두기)", value="소프트웨어융합학과", key="new_department")
    year = st.text_input("입학연도 (선택, 예: 2020)", key="new_year")
    track = st.selectbox("과정", [None, "심화과정", "일반과정"],
                         format_func=lambda v: v or "미지정", key="new_track")
    note = st.text_area("기대 답변·기대 행동과 확인한 문서명·페이지·URL (선택)", key="new_note")
    submitted = st.form_submit_button("질문 저장")
if submitted:
    try:
        if origin is None:
            raise ValueError("작성 출처를 선택하세요.")
        if not question.strip() or not category.strip() or not group.strip():
            raise ValueError("질문, 주제, 질문 그룹을 모두 입력하세요.")
        if year.strip() and (not year.strip().isascii() or not year.strip().isdigit() or not 1900 <= int(year.strip()) <= 2100):
            raise ValueError("입학연도는 1900~2100 사이의 숫자로 입력하세요.")
        case = add_question(root, question=question, origin=origin, category=category, group=group,
                            split=split, department=department.strip() or None,
                            admission_year=int(year.strip()) if year.strip() else None,
                            track=track, reference_note=note)
    except ValueError as exc:
        st.error(str(exc))
    except (OSError, Timeout):
        st.error("질문을 저장하지 못했습니다. 파일 사용 상태와 쓰기 권한을 확인하세요.")
    else:
        st.session_state["question_saved_notice"] = "질문을 저장했습니다: " + case.id
        st.rerun()

st.subheader(f"직접 등록한 질문 ({len(registered)}개)")
if registered:
    st.dataframe([{"ID": c.id, "질문": c.question, "출처": origins[c.origin], "그룹": c.group,
                   "구분": c.split, "기대 답변 메모": c.reference_note} for c in registered], hide_index=True)
else:
    st.info("아직 직접 등록한 질문이 없습니다. 기본 예시는 실제 학생 질문에 포함되지 않습니다.")
st.caption("등록 질문과 실행·채점 결과는 이 컴퓨터에 저장되며 GitHub와 배포 ZIP에서 제외됩니다.")

st.subheader("답변 수집")
st.info("기본 근거 답변을 기록합니다. OpenAI API를 호출하지 않으며, LLM 생성 품질 평가는 포함하지 않습니다. 수집 후 사람이 채점해야 정확도를 확인할 수 있습니다.")
dataset = st.selectbox("수집할 질문", ["bundled", "registered"],
                       format_func=lambda v: f"기본 개발 예시 ({len(bundled)}개, AI 작성)" if v == "bundled" else f"직접 등록한 질문 ({len(registered)}개)", key="capture_dataset")
capture_split = st.selectbox("수집 구분", ["dev", "test"], key="capture_split")
mode = st.selectbox("검색 방식", ["hybrid", "dense"], key="capture_mode")
st.caption("test는 구현을 고정한 뒤 평가하세요. 결과를 보고 수정했다면 독립적인 최종 평가로 간주할 수 없습니다. 수집 중에는 다른 검색·문서 반영이 잠시 대기할 수 있습니다.")
if st.button("답변 수집 실행", key="capture_answers"):
    try:
        path = root / "evals/natural_dev.jsonl" if dataset == "bundled" else bank_path(root)
        cases, dataset_hash = load_cases(path)
        if not any(c.split == capture_split for c in cases):
            raise ValueError("선택한 구분에 질문이 없습니다.")
        with st.spinner("질문별 답변과 출처를 기록하고 있습니다. 모델 첫 로딩은 시간이 걸릴 수 있습니다."):
            run = capture_run(get_search_service(), cases, dataset_hash=dataset_hash, root=root,
                              mode=mode, split=capture_split)
            output = save_run(root / "evals/local_runs", run)
        stats = summarize_run(run, {})
        if stats["errors"]:
            st.warning(f"{stats['questions']}개 기록, 실행 오류 {stats['errors']}건. 평가 화면에서 오류를 확인하세요.")
        else:
            st.success(f"{stats['questions']}개 답변을 기록했습니다. 아직 미채점입니다.")
        st.caption("저장 파일: " + output.name)
    except FileNotFoundError:
        st.error("질문을 먼저 등록하세요. 선택한 질문 파일이 없습니다.")
    except Exception:
        st.error("답변 수집을 완료하지 못했습니다. 선택한 구분에 질문이 있는지, 검색 모델·색인이 준비되어 있는지 확인하세요.")
st.page_link("pages/5_자연어답변평가.py", label="자연어답변평가에서 답변 채점하기")
