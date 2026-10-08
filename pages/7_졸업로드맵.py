"""2018~2026학번 졸업요건 점검 및 잠정 이수계획. 개인 입력은 세션 메모리만 사용."""
import json
import hashlib

import pandas as pd
import streamlit as st

from src.config import PROJECT_ROOT
from src.planning.audit import audit
from src.planning.catalog import load_catalog, candidate_rows, parse_candidates
from src.planning.io import COLUMNS, parse_rows, read_transcript, sample_transcript, to_rows, write_transcript
from src.planning.cohorts import SUPPORTED_ADMISSION_YEARS
from src.planning.models import Attempt, CATEGORIES, Candidate, GRADES, PlanOptions, Profile, STATUSES, Substitution
from src.planning.planner import build_roadmap
from src.planning.rules import load_rules
from src.planning.workspace import (PlannerWorkspace, read_workspace, write_workspace,
                                    restore_session, source_fingerprint, seoul_today)
from src.planning.report import render_report
from src.planning.llm import AssistedRoadmap, assist_roadmap, make_context
from src.planning.llm_ui import controls as llm_controls, show_advice
from src.planning.portal_ui import controls as portal_controls

st.set_page_config(page_title="나의 졸업 로드맵", page_icon="🧭", layout="wide")
st.title("나의 졸업 로드맵")
st.caption("2018~2026학번 · 홍익대학교 세종캠퍼스 소프트웨어융합학과 · 심화 / 일반과정")
st.info("이수내역으로 부족한 요건을 확인하고 다음 학기 계획을 세웁니다. 현재는 공식 규정 대조 중인 참고용 버전이며, 최종 졸업사정은 학교에서 확인해야 합니다.")
st.caption("이름·학번은 입력하지 않습니다. 입력은 이 브라우저 세션에서 처리하고 서버 파일에 자동 저장하지 않습니다. LLM 맞춤 추천을 켜고 전송에 동의한 경우에만 요약 정보를 OpenAI에 보냅니다. 새로고침 전에 ‘전체 입력 백업’을 내려받아 보관하세요.")

st.session_state.setdefault("planner_rows", [])
st.session_state.setdefault("planner_revision", 0)
st.session_state.setdefault("planner_substitutions", [])
pending_workspace = st.session_state.pop("planner_pending_workspace", None)
if pending_workspace is not None:
    restore_session(st.session_state, pending_workspace)

with st.expander("저장한 전체 입력 불러오기"):
    st.caption("전체 입력 백업(v2)은 이수내역·대체인정·확인 상태·후보·계획 조건을 함께 복원합니다. 기존 화면 입력을 대체하고 현재 규정으로 다시 계산합니다. 이전 결과 JSON(v1)은 복원용이 아닙니다.")
    backup_upload = st.file_uploader("전체 입력 백업 JSON", type=["json"],key=f"planner_backup_{st.session_state.planner_revision}")
    if st.button("전체 입력 복원",disabled=backup_upload is None):
        try:
            restored = read_workspace(backup_upload.getvalue())
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.session_state.planner_pending_workspace = restored
            st.rerun()


def replace_rows(rows):
    st.session_state.planner_rows = rows
    st.session_state.planner_revision += 1
    st.session_state.planner_llm_consent = False
    st.rerun()


def check_table(result):
    return pd.DataFrame([{"점검 항목": c.key, "현재 값": c.current, "필요 값": c.required,
                          "남은 값": c.missing, "상태": c.status, "계산·확인 기준": c.detail}
                         for c in result.checks])


def scope_changed():
    # Import suggestions were classified for the previous cohort/track.
    st.session_state.pop("planner_portal_preview", None)
    for name in ("thesis", "english", "general_approval", "design_sequence", "recognized_course_scope", "specialized_course", "basic_english_course", "sw_data_course", "science_course"):
        st.session_state["planner_" + name] = "확인 필요"
    st.session_state.planner_required_list_checked = False
    st.session_state.planner_substitutions = [{**s, "confirmed": False} for s in st.session_state.planner_substitutions]
    st.session_state.planner_llm_consent = False


left, right = st.columns([1, 2])
st.session_state.setdefault("planner_admission_year", 2020)
admission_year = right.selectbox("입학연도 (학번)", SUPPORTED_ADMISSION_YEARS, key="planner_admission_year", on_change=scope_changed)
track = left.radio("졸업 과정", ["심화", "일반"], horizontal=True, key="planner_track", on_change=scope_changed)
right.caption("단일전공 신입학 기준. 학번·과정 변경 시 승인·대체인정을 다시 확인합니다.")
try:
    rules = load_rules(PROJECT_ROOT, track, admission_year)
    catalog = load_catalog(PROJECT_ROOT)
    fingerprint = source_fingerprint(PROJECT_ROOT)
except (ValueError, OSError) as exc:
    st.error(str(exc))
    st.stop()
if st.session_state.get("planner_loaded_fingerprint", fingerprint) != fingerprint:
    st.warning("백업 저장 후 기준 자료가 변경되었습니다. 이전 결과를 그대로 사용하지 않고 현재 규정으로 점검합니다. 입력한 후보와 확인 상태도 다시 대조하세요.")
with st.expander("적용 기준과 출처", expanded=False):
    for notice in rules.notices:
        st.write("• " + notice)
    st.table(pd.DataFrame([{"항목":k, "기준 학점":v} for k,v in rules.thresholds.items()]))
    st.write(f"교양 졸업인정 상한: {rules.liberal_cap:g}학점")
    for source in rules.sources:
        st.write(source)
    st.download_button("졸업학점표 발췌 PDF 내려받기", (PROJECT_ROOT / "config/reviewed_rules/sources/aid_graduation_credits_2026_p8-16.pdf").read_bytes(),
                       "graduation-credit-source-draft.pdf", "application/pdf")
    st.download_button("2026 공학교육인증 공통 내규 PDF", (PROJECT_ROOT / "config/reviewed_rules/sources/aid_accreditation_2026.pdf").read_bytes(),
                       "accreditation-rules-2026.pdf", "application/pdf")

st.subheader("1. 이수내역 입력")
portal_controls(catalog, replace_rows, Profile(admission_year=admission_year, track=track))
buttons = st.columns(3)
if buttons[0].button("가상 예제로 시작"):
    replace_rows(to_rows(sample_transcript(admission_year)))
buttons[1].download_button("빈 CSV 양식", write_transcript([]), "transcript-template.csv", "text/csv")
if buttons[2].button("이수내역 비우기"):
    replace_rows([])
upload = st.file_uploader("지정 양식 CSV 불러오기", type=["csv"], key=f"planner_upload_{st.session_state.planner_revision}")
if st.button("CSV 적용", disabled=upload is None):
    try:
        imported = read_transcript(upload.getvalue())
    except ValueError as exc:
        st.error(str(exc))
    else:
        replace_rows(to_rows(imported))

with st.expander("과목 한 개씩 입력"):
    st.caption("학수번호는 앞자리 0을 포함합니다. 학기: 1=1학기, 2=2학기, 3=하계, 4=동계.")
    with st.form("planner_add_course", clear_on_submit=True):
        a,b,c = st.columns(3)
        code = a.text_input("학수번호")
        name = b.text_input("과목명")
        credits = c.number_input("과목 학점", min_value=0.5, max_value=30.0, value=3.0, step=0.5)
        a,b,c = st.columns(3)
        category = a.selectbox("이수구분", CATEGORIES)
        grade = b.selectbox("성적", GRADES)
        status = c.selectbox("이수 상태", STATUSES)
        a,b,c,d = st.columns(4)
        year = a.number_input("수강연도", min_value=2000, max_value=2100, value=admission_year)
        term = b.selectbox("수강학기", [1,2,3,4])
        area = c.selectbox("교양 영역 (해당 없으면 0)", range(8))
        design = d.number_input("설계 인정학점", min_value=0.0, max_value=30.0, value=0.0, step=0.5)
        sw_data = st.number_input("SW·데이터 인정학점", min_value=0.0, max_value=30.0, value=0.0, step=0.5,
                                 help="2022학번부터 적용. 학교에서 확인한 인정학점만 입력하며 총학점에는 다시 더하지 않습니다.")
        equivalent = st.text_input("공식 확인한 동일과목 대표 학수번호 (해당할 때만)")
        if st.form_submit_button("이수내역에 추가"):
            try:
                row = Attempt(code=code,name=name,credits=credits,category=category,grade=grade,status=status,
                              year=year,term=term,area=area,design_credits=design,sw_data_credits=sw_data,equivalent_code=equivalent)
            except ValueError as exc:
                st.error(str(exc))
            else:
                replace_rows(st.session_state.planner_rows + to_rows([row]))

st.caption("전문교양은 인정되는 기초·일반·핵심교양입니다. 일반 교양선택과 구분하세요. 설계학점은 전공학점의 일부이므로 총학점에 두 번 더하지 않습니다. 재수강은 인정할 내역 한 건만 남기고 이전 건을 ‘인정제외’로 바꾸세요.")
frame = pd.DataFrame(st.session_state.planner_rows, columns=list(COLUMNS))
edited = st.data_editor(frame, num_rows="dynamic", hide_index=True, width="stretch",
    key=f"planner_editor_{st.session_state.planner_revision}", column_config={
        "학수번호":st.column_config.TextColumn(required=True),
        "과목명":st.column_config.TextColumn(required=True),
        "이수구분":st.column_config.SelectboxColumn(options=CATEGORIES, required=True),
        "성적":st.column_config.SelectboxColumn(options=GRADES, required=True),
        "상태":st.column_config.SelectboxColumn(options=STATUSES, required=True),
        "교양영역":st.column_config.NumberColumn(min_value=0,max_value=7,step=1),
        "학점":st.column_config.NumberColumn(min_value=0.5,max_value=30,step=0.5),
    })
try:
    attempts = parse_rows(edited.fillna("").to_dict("records"))
except ValueError as exc:
    st.error(str(exc))
    st.stop()
st.session_state.planner_rows = to_rows(attempts)
st.download_button("입력한 이수내역 CSV 저장", write_transcript(attempts), "my-transcript.csv", "text/csv")

st.subheader("2. 학교에서 확인한 추가 요건")
st.caption("클래스넷 → 졸업정보 → 졸업요건 조회의 미이수 내역을 확인하세요. 공란은 미이수가 아니며, 개정으로 선택·폐지된 과목과 지정과목의 예외도 대조해야 합니다.")
required = st.text_input("공식 확인한 필수과목 학수번호 (쉼표로 구분)", placeholder="예: 704814, 704826",key="planner_required")
checked = st.checkbox("개인에게 적용되는 필수목록과 대체·개정 사항을 확인했습니다",key="planner_required_list_checked")
a,b = st.columns(2)
thesis = a.selectbox("졸업논문·졸업작품 승인 상태", ["확인 필요","미충족","충족"],key="planner_thesis")
english = b.selectbox("어학 인정·제출 상태", ["확인 필요","미충족","충족"],key="planner_english")
manual_checks = {}
with st.expander("학점 외 인정 조건 확인"):
    st.caption("2026년 공통 내규와 본인에게 적용되는 학과 기준을 대조한 상태입니다. 과목 추천이나 총학점 충족만으로 이 조건을 자동 충족 처리하지 않습니다.")
    for name,label,disabled in [
        ("general_approval","일반과정 적용·변경 승인 확인",track!="일반"),
        ("design_sequence","설계 이수순서·프로그램 이수체계 확인",track!="심화"),
        ("recognized_course_scope","교양·MSC 인정 범위 확인 (사이버·타 캠퍼스 등)",track!="심화"),
        ("specialized_course","특성화교양 지정과목 확인",admission_year < 2019),
        ("sw_data_course","SW·데이터 과목·중복인정 확인",admission_year < 2022),
        ("science_course","학과 과학 지정과목 확인",track != "심화" or admission_year < 2021),
        ("basic_english_course","전공기초영어 지정과목 확인",False)]:
        manual_checks[name] = st.selectbox(label,["확인 필요","미충족","충족"],disabled=disabled,key="planner_"+name)
with st.expander("학교에서 확인한 대체과목 인정", expanded=False):
    st.write("예를 들어 A 과목 대신 B 과목을 이수하면 A의 필수요건을 인정하는 경우입니다. 아래 관계는 한 방향으로만 적용하며, 두 과목의 학점을 합치거나 선수과목 조건을 면제하지 않습니다.")
    st.caption("개인별 필수과목은 위의 ‘공식 확인한 필수과목 학수번호’에도 원래 과목 번호를 입력하세요. 기본 점검에 포함된 글쓰기·영어·과학·설계 과목에도 대체인정을 적용할 수 있습니다.")
    st.caption("선택한 입학연도에 적용되는 과정·기간을 확인한 경우에만 입력하세요. 기간은 대체과목을 수강한 시점 기준이며 1=1학기, 3=하계, 2=2학기, 4=동계 순서입니다. 확인 근거에는 공지명·URL·확인일 등을 적고 이름·학번은 적지 마세요.")
    with st.form("planner_add_substitution"):
        a,b,c = st.columns(3)
        original_code = a.text_input("원래 필수과목 학수번호")
        replacement_code = b.text_input("대체 이수과목 학수번호")
        substitution_track = c.selectbox("대체인정 적용 과정", ["심화", "일반"], index=0 if track=="심화" else 1)
        a,b,c,d = st.columns(4)
        substitution_start_year = a.number_input("대체인정 시작 연도", min_value=2000, max_value=2100, value=admission_year)
        substitution_start_term = b.selectbox("대체인정 시작 학기", [1,3,2,4])
        substitution_end_year = c.number_input("대체인정 종료 연도", min_value=2000, max_value=2100, value=2026)
        substitution_end_term = d.selectbox("대체인정 종료 학기", [1,3,2,4], index=3)
        no_end = st.checkbox("종료 시점 제한이 없는 것으로 확인했습니다")
        substitution_source = st.text_input("대체인정 확인 근거", max_chars=500)
        substitution_confirmed = st.checkbox("선택한 과정·입학연도·수강기간의 대체인정을 학교 자료나 학과에서 확인했습니다")
        if st.form_submit_button("대체인정 추가"):
            try:
                substitution = Substitution(required_code=original_code,replacement_code=replacement_code,
                    track=substitution_track,start_year=substitution_start_year,start_term=substitution_start_term,
                    end_year=None if no_end else substitution_end_year,end_term=None if no_end else substitution_end_term,
                    source=substitution_source,confirmed=substitution_confirmed)
                if len(st.session_state.planner_substitutions) >= 100:
                    raise ValueError("대체인정은 최대 100건까지 입력할 수 있습니다.")
                if substitution.model_dump() in st.session_state.planner_substitutions:
                    raise ValueError("같은 대체인정이 이미 등록되어 있습니다.")
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.session_state.planner_substitutions.append(substitution.model_dump())
                st.rerun()
    for i,entry in enumerate(st.session_state.planner_substitutions):
        substitution = Substitution.model_validate(entry)
        end = "제한 없음" if substitution.end_year is None else f"{substitution.end_year}/{substitution.end_term}"
        state = "사용자 확인" if substitution.confirmed else "미확인·미적용"
        if substitution.track != track:
            state += " · 다른 과정이라 미적용"
        st.write(f"**{substitution.replacement_code} → {substitution.required_code}** · {substitution.track} · {substitution.start_year}/{substitution.start_term}~{end} · {state}")
        st.text(substitution.source)
        if st.button("이 대체인정 삭제",key=f"planner_delete_substitution_{i}"):
            st.session_state.planner_substitutions.pop(i)
            st.rerun()
    st.caption("대체인정 설정은 이수내역 CSV에 포함되지 않습니다. 로드맵 계산 후 JSON 결과에 함께 저장됩니다.")
try:
    profile = Profile(admission_year=admission_year, track=track, required_codes=tuple(required.split(",")), required_list_checked=checked,
                      thesis=thesis, english=english, substitutions=tuple(st.session_state.planner_substitutions),**manual_checks)
except ValueError as exc:
    st.error(str(exc))
    st.stop()
result = audit(attempts, profile, rules)
st.subheader("3. 현재 졸업요건 점검")
current_total = next(c for c in result.checks if c.key=="총 졸업인정학점")
metrics = st.columns(4)
metrics[0].metric("현재 인정학점 (입력 기준)", f"{current_total.current:g}", f"필요 {current_total.required:g}", delta_color="off")
metrics[1].metric("남은 총학점", f"{current_total.missing:g}")
metrics[2].metric("수강중 학점 (합계 제외)", f"{result.pending_credits:g}")
metrics[3].metric("교양 상한 초과 제외", f"{result.excluded_liberal_credits:g}")
st.progress(min(1.0,current_total.current/current_total.required), text="총학점 진행률 · 다른 요건의 충족 여부는 아래 표에서 별도로 확인")
for warning in result.warnings:
    st.warning(warning)
st.dataframe(check_table(result), hide_index=True, width="stretch")
if result.substitutions_applied:
    with st.expander("현재 점검에 적용된 대체인정 근거"):
        st.table(pd.DataFrame(result.substitutions_applied).rename(columns={"required_code":"인정한 필수과목",
            "replacement_code":"실제 이수과목","year":"수강연도","term":"학기","source":"사용자 확인 근거"}))
if not attempts:
    st.info("이수내역을 입력하거나 ‘가상 예제로 시작’을 누르면 부족한 요건을 계산할 수 있습니다.")

st.subheader("4. 학기별 로드맵")
st.warning("첨부 2026 이수체계도의 선수·병수 관계를 반영했습니다. 학번과 별개로 수강연도 기준을 적용하며, 개별 면제·개정과 실제 개설은 학교에서 확인하세요.")
st.caption("현재 교과과정의 개설 학기를 가정해 배치합니다. ‘부학기’만 표기된 학기는 자동 개설로 취급하지 않습니다. 교과과정에 없는 과목은 후보 표에 직접 추가할 수 있습니다.")
with st.expander("추천 후보·개설 학기·선수과목 조정", expanded=False):
    st.caption("선수학수번호는 쉼표로 구분하고 이전 학기까지 취득해야 하는 과목만 적으세요. 공식 확인되지 않은 선수조건을 임의로 추가하지 마세요. 동일과목코드는 중복 학점 인정이 불가능하다고 공식 확인된 경우에만 입력합니다. 필수요건을 대신 채우는 선택·대체과목이라는 이유만으로 묶지 마세요. 후보를 지우거나 추천을 해제하면 배치에서 제외됩니다.")
    st.session_state.setdefault("planner_candidate_rows", candidate_rows(catalog))
    candidate_frame = st.data_editor(pd.DataFrame(st.session_state.planner_candidate_rows,columns=list(candidate_rows(catalog)[0])), num_rows="dynamic",hide_index=True,
        width="stretch",key=f"planner_candidates_{st.session_state.planner_revision}", column_config={
            "추천":st.column_config.CheckboxColumn(default=True),
            "이수구분":st.column_config.SelectboxColumn(options=CATEGORIES,required=True),
            "개설학기":st.column_config.TextColumn(help="1 또는 2 또는 1,2. 빈칸이면 배치하지 않음"),
            "선택대안학수번호":st.column_config.TextColumn(help="쉼표로 구분. 중 하나를 이미 이수·수강중이면 다른 대안은 자동 추천에서 제외. 동일과목 인정과는 별개"),
        })
a,b,c,d = st.columns(4)
start_year = a.number_input("계획 시작 연도", min_value=2018,max_value=2100,value=max(2018,seoul_today().year+1),key="planner_start_year")
start_term = b.selectbox("계획 시작 학기", [1,2],key="planner_start_term")
count = c.number_input("계획할 정규학기 수", min_value=1,max_value=12,value=4,key="planner_semesters")
limit = d.number_input("학기당 계획 학점 한도", min_value=1.0,max_value=30.0,value=18.0,step=0.5,key="planner_credit_limit")
assume = st.checkbox("현재 수강중 과목을 모두 통과한다고 가정하여 계획",key="planner_assume_in_progress_passed")
use_llm, llm_goal, connection, llm_consent = llm_controls(PROJECT_ROOT)
workspace = None
try:
    candidates, excluded = parse_candidates(candidate_frame.fillna("").to_dict("records"))
    st.session_state.planner_candidate_rows = candidate_rows(candidates, excluded)
    options = PlanOptions(start_year=start_year,start_term=start_term,semesters=count,credit_limit=limit,
                          assume_in_progress_passed=assume,excluded_codes=excluded)
    workspace = PlannerWorkspace(saved_on=seoul_today().isoformat(),rules_fingerprint=fingerprint,
        attempts=attempts,profile=profile,candidates=candidates,options=options,llm_goal=llm_goal)
except (ValueError, TypeError) as exc:
    st.error("후보와 계획 조건을 확인하세요. " + str(exc))
if workspace is not None:
    st.download_button("전체 입력 백업 JSON 저장",write_workspace(workspace),"graduation-workspace-v2.json",
                       "application/json",on_click="ignore")
    st.caption("전체 입력 백업에는 성적과 사용자 확인 근거가 포함됩니다. 본인 장치에 보관하고 공유할 때 내용을 확인하세요.")

input_id = hashlib.sha256((write_workspace(workspace).decode("utf-8") +
    json.dumps([use_llm, llm_consent, connection.model])).encode("utf-8")).hexdigest() if workspace else ""
if st.session_state.get("planner_result_id") != input_id:
    st.session_state.pop("planner_result", None)

if use_llm and workspace is not None:
    with st.expander("OpenAI에 전송할 요약 미리보기"):
        try:
            preview_plan = build_roadmap(attempts,profile,rules,candidates,options)
            st.json(make_context(attempts,profile,rules,candidates,options,llm_goal,preview_plan),expanded=False)
        except ValueError as exc:
            st.info(str(exc))

calculate_label = "LLM 맞춤 로드맵 생성" if use_llm else "로드맵 계산"
if st.button(calculate_label, type="primary", disabled=workspace is None or (use_llm and not llm_consent)):
    if not attempts:
        st.warning("먼저 이수내역을 입력하세요. 가상 예제로도 확인할 수 있습니다.")
    else:
        try:
            if use_llm:
                with st.spinner("LLM 제안과 수강 조건을 확인하고 있습니다…"):
                    assisted = assist_roadmap(attempts,profile,rules,candidates,options,
                        goal=llm_goal,connection=connection,consent=llm_consent)
            else:
                assisted = AssistedRoadmap(build_roadmap(attempts,profile,rules,candidates,options),None,"local")
            st.session_state.planner_result = assisted
            st.session_state.planner_result_id = input_id
        except (ValueError,TypeError) as exc:
            st.error("추천 후보와 계획 조건을 확인하세요. " + str(exc))

assisted = st.session_state.get("planner_result")
if assisted is not None:
    roadmap = assisted.roadmap
    show_advice(assisted)
    st.warning("아래 계획은 입력 조건에 따른 예상안입니다. 남은 항목이 있으면 이 계획만으로 졸업요건을 충족하지 못합니다.")
    columns = st.columns(min(4,len(roadmap.semesters)))
    for i,semester in enumerate(roadmap.semesters):
        with columns[i % len(columns)].container(border=True):
            st.markdown(f"**{semester.year}년 {semester.term}학기**")
            st.metric("계획 학점",f"{semester.credits:g}")
            if not semester.courses:
                st.caption("조건에 맞는 자동 배치 과목 없음")
            for course in semester.courses:
                st.write(f"{course.name} · {course.credits:g}학점")
                st.caption(f"{course.code} · {course.reason}")
    st.markdown("**계획을 모두 이수한 뒤에도 남는 항목**")
    for message in roadmap.unresolved:
        st.write("• " + message)
    with st.expander("계획 후 예상 점검표와 가정"):
        st.dataframe(check_table(roadmap.projected),hide_index=True,width="stretch")
        for assumption in roadmap.assumptions:
            st.write("• " + assumption)
    payload = {"version":1,"created_on":seoul_today().isoformat(),"profile":profile.model_dump(),
        "rules_sources":rules.sources,"rules_notices":rules.notices,
        "options":options.model_dump(),"current":result.as_dict(),"roadmap":roadmap.as_dict(),
        "llm":{"status":assisted.status,"model":assisted.model,
               "advice":assisted.advice.model_dump() if assisted.advice else None}}
    st.download_button("점검 결과와 로드맵 JSON 저장",json.dumps(payload,ensure_ascii=False,indent=2),
                       "graduation-roadmap.json","application/json",on_click="ignore")
    st.download_button("인쇄용 보고서 HTML 저장",render_report(profile,result,roadmap,rules,advice=assisted.advice,model=assisted.model),
                       "graduation-report.html","text/html",on_click="ignore")
    st.caption("입력값을 바꾸면 이전 계획은 숨겨집니다. ‘로드맵 계산’을 다시 눌러 최신 조건으로 계산하세요.")
