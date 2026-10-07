import json
from types import SimpleNamespace

import pytest

from src.config import PROJECT_ROOT
from src.planning.llm import (Advice, Connection, assist_roadmap, make_context,
                              request_advice, saved_connection)
from src.planning.models import Attempt, Candidate, PlanOptions, Profile
from src.planning.planner import build_roadmap
from src.planning.report import render_report
from src.planning.audit import audit
from src.planning.rules import load_rules
from src.planning.workspace import PlannerWorkspace, restore_session, write_workspace


def inputs():
    attempts = [Attempt(code="DONE", name="PRIVATE NAME", credits=3, category="전공", year=2020, grade="A+")]
    candidates = [Candidate(code=c, name=c, credits=3, category="전공", semesters=(1,2)) for c in ("A","B","DONE")]
    return attempts, Profile(), load_rules(PROJECT_ROOT,"심화"), candidates, PlanOptions(start_year=2027,semesters=1,credit_limit=3)


def answer(code="B"):
    return {"summary":"관심 분야와 부족한 요건을 함께 준비하세요.",
            "priorities":[{"code":code,"reason":"희망 분야와 관련된 후보입니다."}],
            "next_steps":["실제 개설학기와 선수조건을 학과에서 확인하세요."]}


def run(args=None, response=None, **kwargs):
    return assist_roadmap(*(args or inputs()),consent=True,connection=Connection("secret-test-key","test-model"),
                          requester=lambda context,connection: response if response is not None else answer(),**kwargs)


def test_model_preference_changes_useful_selection_without_changing_audit():
    args=inputs()
    baseline=build_roadmap(*args)
    assisted=run(args)
    assert baseline.semesters[0].courses[0].code == "A"
    assert assisted.status == "llm"
    assert assisted.roadmap.semesters[0].courses[0].code == "B"
    assert assisted.roadmap.semesters[0].credits == 3
    assert assisted.roadmap.projected.as_dict() == baseline.projected.as_dict()


@pytest.mark.parametrize("code",["INVENTED","DONE"])
def test_unknown_or_completed_recommendation_falls_back(code):
    outcome=run(response=answer(code))
    assert outcome.status == "fallback" and outcome.advice is None
    assert outcome.roadmap.as_dict() == build_roadmap(*inputs()).as_dict()


def test_excluded_alias_is_not_transmitted_or_recommended():
    args=list(inputs())
    args[3].append(Candidate(code="ALIAS",name="alias",credits=3,category="전공",semesters=(1,),equivalent_code="B"))
    args[4]=args[4].model_copy(update={"excluded_codes":("ALIAS",)})
    assert run(args).status == "fallback"
    context=make_context(*args,"",build_roadmap(*args))
    assert {c["code"] for c in context["candidates"]} == {"A"}


def test_model_cannot_bypass_offering_prerequisite_or_credit_limit():
    args=list(inputs())
    args[3]=[
        Candidate(code="FIRST",name="first",credits=3,category="전공",semesters=(1,)),
        Candidate(code="NEXT",name="next",credits=3,category="전공",semesters=(2,),prerequisites=("FIRST",)),
        Candidate(code="BIG",name="big",credits=4,category="전공",semesters=(1,2))]
    args[4]=args[4].model_copy(update={"semesters":2})
    response=answer("NEXT")
    response["priorities"].append({"code":"BIG","reason":"높은 선호도"})
    out=run(args,response)
    assert [[c.code for c in s.courses] for s in out.roadmap.semesters] == [["FIRST"],["NEXT"]]


def test_context_omits_grades_student_course_names_and_notes():
    args=inputs()
    context=make_context(*args,"웹 개발",build_roadmap(*args))
    payload=json.dumps(context,ensure_ascii=False)
    assert "A+" not in payload and "PRIVATE NAME" not in payload
    assert '"grade"' not in payload and '"substitutions"' not in payload
    assert context["completed_courses"] == [{"code":"DONE","year":2020,"term":1}]
    assert context["student_goal"] == "웹 개발"


@pytest.mark.parametrize("consent,key,model",[(False,"secret","model"),(True,"","model"),(True,"secret","")])
def test_no_consent_or_credentials_never_calls_provider(consent,key,model):
    def forbidden(*_):
        pytest.fail("No request should be sent")
    out=assist_roadmap(*inputs(),connection=Connection(key,model),consent=consent,requester=forbidden)
    assert out.status in {"local","fallback"}
    assert out.advice is None


@pytest.mark.parametrize("response",[{}, {**answer(),"extra":"bad"},
    {**answer(),"priorities":[answer()["priorities"][0]]*2},
    {**answer(),"next_steps":["x"*501]}, {**answer(),"next_steps":[""]}])
def test_bad_structured_response_falls_back(response):
    assert run(response=response).status == "fallback"


def test_exception_secrets_are_not_exposed_and_no_retry():
    calls=[]
    def fail(context,connection):
        calls.append(1)
        raise RuntimeError("secret-test-key PRIVATE TRANSCRIPT")
    out=assist_roadmap(*inputs(),consent=True,connection=Connection("secret-test-key","test-model"),requester=fail)
    assert out.status == "fallback" and len(calls)==1
    assert "secret-test-key" not in repr(out) and "PRIVATE TRANSCRIPT" not in repr(out)
    assert "secret-test-key" not in repr(Connection("secret-test-key","test-model"))


def test_responses_api_uses_schema_fixed_destination_and_no_storage(monkeypatch):
    import openai
    observed={}
    class Client:
        def __init__(self,**kwargs):
            observed.update(kwargs); self.responses=self
        def __enter__(self): return self
        def __exit__(self,*_): pass
        def parse(self,**kwargs):
            observed.update(kwargs)
            return SimpleNamespace(status="completed",output_parsed=Advice.model_validate(answer()))
    monkeypatch.setattr(openai,"OpenAI",Client)
    assert request_advice({"safe":"context"},Connection("test-key","test-model")).priorities[0].code=="B"
    assert observed["store"] is False and observed["max_retries"]==0
    assert observed["base_url"]=="https://api.openai.com/v1"
    assert observed["text_format"] is Advice
    assert "test-key" not in json.dumps(observed["input"])


def test_custom_provider_key_is_never_sent_to_openai(tmp_path,monkeypatch):
    for name in ("OPENAI_API_KEY","OPENAI_MODEL","LLM_BASE_URL","LLM_API_KEY","LLM_MODEL_NAME","LLM_PROVIDER"):
        monkeypatch.delenv(name,raising=False)
    (tmp_path/".env").write_text("LLM_BASE_URL=https://custom.example/v1\nLLM_API_KEY=custom-secret\nLLM_MODEL_NAME=custom-model\n")
    assert saved_connection(tmp_path)==Connection()
    monkeypatch.setenv("OPENAI_API_KEY","official-key")
    monkeypatch.setenv("OPENAI_MODEL","official-model")
    assert saved_connection(tmp_path)==Connection("official-key","official-model")


def test_backup_keeps_goal_but_never_key_or_permission():
    args=inputs()
    workspace=PlannerWorkspace(saved_on="2026-10-05",rules_fingerprint="a"*64,
        attempts=args[0],profile=args[1],candidates=args[3],options=args[4],llm_goal="웹 개발")
    raw=write_workspace(workspace)
    assert b"api_key" not in raw and b"consent" not in raw
    state={"planner_llm_consent":True}
    restore_session(state,workspace)
    assert state["planner_llm_goal"]=="웹 개발" and state["planner_llm_consent"] is False


def test_html_escapes_model_text():
    args=inputs()
    advice=Advice(summary='<img src="https://evil.example">',priorities=[],next_steps=['<script>bad()</script>'])
    report=render_report(args[1],audit(*args[:3]),build_roadmap(*args),args[2],advice=advice,model="test")
    assert b'<img src=' not in report and b'<script>' not in report
    assert b'&lt;script&gt;' in report
