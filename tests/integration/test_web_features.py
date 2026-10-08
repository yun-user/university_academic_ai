"""Feature acceptance tests use synthetic data and isolated SQLite files only."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import time

from fastapi.testclient import TestClient
import pytest

from backend.app import create_app
from backend.auth import Auth, COOKIE, password_hash
from backend.schemas import PlanningInput
from src.planning.catalog import load_catalog, candidate_rows, parse_candidates
from src.planning.llm import Connection
from src.planning.models import Candidate, PlanOptions
from src.planning.workspace import PlannerWorkspace, write_workspace, source_fingerprint

ROOT = Path(__file__).resolve().parents[2]
H = {"x-planner-request":"1"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.service.saved_connection", lambda root:Connection())
    with TestClient(create_app(tmp_path/"test.sqlite3", auth_required=False)) as client:
        yield client


@pytest.fixture
def data(client):
    c = client.get('/api/bootstrap').json()
    candidates = [Candidate(code='A',name='가상 선수',credits=3,category='전공',semesters=(1,2)),
                  Candidate(code='B',name='가상 후속',credits=3,category='전공',semesters=(1,2),prerequisites=('A',)),
                  Candidate(code='C',name='가상 병수',credits=3,category='전공',semesters=(1,2),concurrent=('A',))]
    return {"attempts":[], "profile":c['profile'], "options":{**c['options'],'start_year':2027,'semesters':3},
            "candidates":[x.model_dump(mode='json') for x in candidates], "goal":"가상 사례"}


def post(client, path, data):
    return client.post('/api/'+path, headers=H, json=data)


def test_per_term_caps_and_concurrent_plan(client,data):
    data['options']['semester_limits']=[6,0,3]
    r=post(client,'analysis',data)
    assert r.status_code==200
    periods=r.json()['roadmap']['semesters']
    assert [[c['code'] for c in s['courses']] for s in periods]==[['A','C'],[],['B']]
    assert all(s['credits']<=cap for s,cap in zip(periods,[6,0,3]))
    data['options']['semester_limits']=[3]
    assert post(client,'analysis',data).status_code==422


def test_extended_semester_preserves_manual_plan_limits_and_saved_input(client, data):
    data['options']['semester_limits'] = [6, 0, 3]
    data['placements'] = [{'code': 'A', 'semester': 0}, {'code': 'B', 'semester': 2}]
    before = post(client, 'analysis', data).json()['roadmap']['semesters']
    data['options']['semesters'] += 1
    data['options']['semester_limits'].append(data['options']['credit_limit'])
    response = post(client, 'analysis', data)
    assert response.status_code == 200
    after = response.json()['roadmap']['semesters']
    assert after[:3] == before and len(after) == 4
    assert (after[-1]['year'], after[-1]['term'], after[-1]['credits']) == (2028, 2, 0)
    saved = post(client, 'profiles', {**data, 'label': 'synthetic extended plan'}).json()
    loaded = client.get('/api/profiles/' + saved['id']).json()
    assert loaded['placements'] == data['placements']
    assert loaded['options']['semester_limits'] == [6, 0, 3, 18]
    assert loaded['options']['semesters'] == 4


@pytest.mark.parametrize('placements,fragment',[
    ([{'code':'B','semester':0}], '선수과목'),
    ([{'code':'A','semester':0},{'code':'B','semester':0}], '선수과목'),
    ([{'code':'C','semester':0}], '병수'),
    ([{'code':'A','semester':0},{'code':'A','semester':1}], '중복'),
    ([{'code':'NOPE','semester':0}], '후보'),
    ([{'code':'A','semester':3}], '범위'),
])
def test_rejected_moves_never_publish_projected_audit(client,data,placements,fragment):
    data['placements']=placements
    r=post(client,'plan/validate',data).json()
    assert not r['valid'] and r['roadmap'] is None
    assert fragment in ' '.join(r['violations'])
    assert post(client,'analysis',data).status_code==422
    assert post(client,'profiles',{**data,'label':'invalid'}).status_code==422
    assert client.get('/api/profiles').json()==[]


def test_manual_valid_concurrent_same_term_and_previous_prerequisite(client,data):
    data['placements']=[{'code':'C','semester':0},{'code':'A','semester':0},{'code':'B','semester':1}]
    r=post(client,'analysis',data).json()
    assert r['mode']=='manual'
    assert r['roadmap']['projected']['checks'][0]['current']==9
    data['options']['semester_limits']=[3,6,3]
    assert '초과' in post(client,'analysis',data).json()['detail']


@pytest.mark.parametrize('change,fragment',[
    ({'excluded_codes':['A']},'제외'),
    ({'credit_limit':2},'초과'),
])
def test_manual_limits(client,data,change,fragment):
    data['options'].update(change);data['placements']=[{'code':'A','semester':0}]
    assert fragment in post(client,'analysis',data).json()['detail']


def test_manual_offering_alias_and_asymmetric_alternative(client,data):
    data['candidates'][0]['semesters']=[2]
    data['placements']=[{'code':'A','semester':0}]
    assert '개설' in post(client,'analysis',data).json()['detail']
    data['candidates'][0]['semesters']=[1,2]
    a={k:v for k,v in data['candidates'][0].items() if k not in {'semesters','prerequisites','concurrent','alternatives','source'}}
    data['attempts']=[{**a,'code':'OLD','equivalent_code':'A','year':2020,'term':1,'grade':'P','status':'취득'}]
    assert '이미' in post(client,'analysis',data).json()['detail']
    data['attempts'][0]['code']='A'; data['attempts'][0]['equivalent_code']=''
    data['candidates'][0]['alternatives']=['B']; data['placements']=[{'code':'B','semester':0}]
    assert '대안' in post(client,'analysis',data).json()['detail']
    data['placements']=None
    assert 'B' not in [c['code'] for s in post(client,'analysis',data).json()['roadmap']['semesters'] for c in s['courses']]


def test_compare_scoped_limits_last_zero_and_no_mutation(client,data):
    original=deepcopy(data)
    r=post(client,'compare',{**data,'limits':[3,6],'last_limit':0}).json()
    assert [s['options']['semester_limits'] for s in r['scenarios']]==[[3,3,0],[6,6,0]]
    assert [s['planned_credits'] for s in r['scenarios']]==[6,9]
    assert data==original and client.get('/api/profiles').json()==[]
    assert post(client,'compare',{**data,'limits':[0,99]}).status_code==422


def test_all_settings_roundtrip_restart_and_backup(client,data):
    data.update(placements=[{'code':'A','semester':0}], checklist=[{'id':'task1','title':'가상 제출','due':'2026-11-09','done':True,'note':'메모'}])
    record=post(client,'profiles',{**data,'label':'가상 저장'}).json()
    backup=post(client,'export/backup',data).json()
    assert set(backup)=={'kind','version','rules_fingerprint','data'}
    restored=post(client,'import/backup',{'text':json.dumps(backup)}).json()['data']
    for field in ('candidates','placements','checklist'):
        assert record[field]==restored[field]==data[field]
    with TestClient(create_app(client.app.state.database.path,auth_required=False)) as again:
        assert again.get('/api/profiles/'+record['id']).json()['checklist']==data['checklist']
    changed={**backup,'rules_fingerprint':'0'*64}
    assert post(client,'import/backup',{'text':json.dumps(changed)}).json()['warnings']
    backup['data']['consent']=True
    assert post(client,'import/backup',{'text':json.dumps(backup)}).status_code==422
    assert post(client,'import/backup',{'text':'{"kind":"a","kind":"b"}'}).status_code==422


def test_legacy_workspace_import(client,data):
    parsed=PlanningInput.model_validate(data)
    old=PlannerWorkspace(saved_on='2026-10-07', rules_fingerprint=source_fingerprint(ROOT),
                         attempts=parsed.attempts,profile=parsed.profile,options=parsed.options,candidates=parsed.candidates,llm_goal=parsed.goal)
    r=post(client,'import/backup',{'text':write_workspace(old).decode()})
    assert r.status_code==200 and r.json()['data']['goal']=='가상 사례'


def test_report_escapes_content_and_checklist_does_not_grant_thesis(client,data):
    data['checklist']=[{'id':'x','title':'<script>alert(1)</script>','note':'<img src=x>','done':True}]
    report=post(client,'export/report',data)
    assert report.status_code==200 and 'attachment' in report.headers['content-disposition']
    assert '&lt;script&gt;' in report.text and '<script>alert' not in report.text
    result=post(client,'analysis',data).json()
    assert next(c for c in result['audit']['checks'] if '논문' in c['key'])['status']=='확인 필요'
    assert post(client,'export/csv',data).status_code==200


def test_sources_evidence_and_declared_unknowns(client,data):
    source=client.get('/api/sources').json()
    assert len(source['sources'])==2 and '학교' in ' '.join(source['notes'])
    r=post(client,'analysis',data).json()
    for check,e in zip(r['audit']['checks'],r['evidence']):
        assert all(check[k]==e[k] for k in ['key','current','required','missing','status','detail'])
        assert e['sources'] and '최종 확인' in e['verification']


def test_evaluation_requires_evidence_and_synthetic_not_real(client):
    initial=client.get('/api/evaluations').json()
    assert initial['records']==[] and initial['synthetic']['real_student_accuracy'] is None
    assert initial['synthetic']['total']==initial['synthetic']['passed']==32
    row={'kind':'규정 대조','case_label':'SYNTHETIC-01','track':'심화','verified':True,'passed':True}
    assert post(client,'evaluations',row).status_code==422
    row.update(expected='3',observed='3',evidence='가상 검증; 실제 학교 대조 아님')
    r=post(client,'evaluations',row); assert r.status_code==201
    assert len(client.get('/api/evaluations').json()['records'])==1
    assert client.delete('/api/evaluations/'+r.json()['id'],headers=H).status_code==204


def test_auth_isolates_profiles_histories_evaluations_and_sessions(tmp_path,monkeypatch):
    monkeypatch.setattr('backend.service.saved_connection',lambda root:Connection())
    app=create_app(tmp_path/'auth.sqlite3',auth_required=True)
    with TestClient(app) as a, TestClient(app) as b:
        assert a.get('/api/bootstrap').status_code==401
        account={'username':'student_a','password':'Synthetic-password-123'}
        register=post(a,'auth/register',account)
        assert register.status_code==201 and 'httponly' in register.headers['set-cookie'].lower()
        assert 'samesite=strict' in register.headers['set-cookie'].lower()
        c=a.get('/api/bootstrap').json();data={'options':c['options'],'label':'private'}
        record=post(a,'profiles',data).json(); path='/api/profiles/'+record['id']
        assert post(b,'auth/register',{**account,'username':'student_b'}).status_code==201
        assert b.get('/api/profiles').json()==[]
        assert b.get(path).status_code==b.get(path+'/history').status_code==404
        assert b.put(path,json={**data,'revision':1},headers=H).status_code==404
        assert b.delete(path+'?revision=1',headers=H).status_code==404
        evaluation=post(a,'evaluations',{'kind':'사용성','case_label':'fake','track':'심화'}).json()
        assert b.get('/api/evaluations').json()['records']==[]
        assert b.delete('/api/evaluations/'+evaluation['id'],headers=H).status_code==404
        token=a.cookies.get(COOKIE)
        assert post(a,'auth/logout',{}).status_code==204
        a.cookies.set(COOKIE,token)
        assert a.get(path).status_code==401
        a.cookies.clear()  # remove the deliberately replayed cookie from the test jar
        assert post(a,'auth/login',{**account,'password':'wrong-password'}).status_code==401
        assert post(a,'auth/login',account).status_code==200
        assert a.get(path).status_code==200
        with app.state.database.connect() as db:
            assert account['password'] not in db.execute('SELECT password_hash FROM accounts').fetchone()[0]
            db.execute('UPDATE sessions SET expires=?',(time.time()-1,))
        assert a.get(path).status_code==401
    with TestClient(create_app(app.state.database.path,auth_required=False)) as local:
        assert local.get('/api/profiles').json()==[]


def test_auth_rate_limit_and_hash_salts(tmp_path):
    assert password_hash('test password')!=password_hash('test password')
    with TestClient(create_app(tmp_path/'db',auth_required=True)) as c:
        for _ in range(10):
            assert post(c,'auth/login',{'username':'missing','password':'wrong-password'}).status_code==401
        assert post(c,'auth/login',{'username':'missing','password':'wrong-password'}).status_code==429


def test_v1_database_migration_preserves_input_and_history(client,data):
    r=post(client,'profiles',{**data,'label':'legacy'}).json()
    path=client.app.state.database.path
    with sqlite3.connect(path) as db:
        db.execute('ALTER TABLE profiles DROP COLUMN settings_json')
        db.execute('DROP INDEX idx_profile_owner')
        db.execute('ALTER TABLE profiles DROP COLUMN owner_id')
        db.execute('PRAGMA user_version=1')
    with TestClient(create_app(path,auth_required=False)) as again:
        assert again.get('/api/profiles/'+r['id']).json()['label']=='legacy'
        assert len(again.get('/api/profiles/'+r['id']+'/history').json())==1
        assert post(again,'profiles',{**data,'label':'new'}).status_code==201


def test_source_prerequisites_not_recommendation_dotted_lines():
    catalog=load_catalog(ROOT);by={c.code:c for c in catalog}
    assert by['704818'].prerequisites==('012301',)
    assert by['704826'].prerequisites==('725843',)
    assert by['704612'].prerequisites==('704413','725843')
    assert by['704711'].prerequisites==('725843','704818','704413')
    assert by['704814'].concurrent==('704711',)
    assert by['012317'].concurrent==('012316',)
    assert not by['704840'].prerequisites  # official current AI code; dotted recommendation is not enforced
    parsed,_=parse_candidates(candidate_rows(catalog))
    assert next(c for c in parsed if c.code=='704814').concurrent==('704711',)


def test_legacy_computing_cap_is_not_applied_without_current_scope(client,data):
    data['attempts']=[{'code':f'COMP{i}','name':'가상 전산','credits':3,'category':'MSC전산',
                      'year':2020,'grade':'P'} for i in range(3)]
    checks={c['key']:c for c in post(client,'analysis',data).json()['audit']['checks']}
    assert checks['총 졸업인정학점']['current']==9
    assert checks['MSC전산']['current']==checks['MSC 합계']['current']==9
    assert '전산 9 = 9학점' in checks['MSC 합계']['detail']
    assert checks['종합설계(1) 포함']['status']=='미충족'
    data['profile']['track']='일반'
    checks={c['key']:c for c in post(client,'analysis',data).json()['audit']['checks']}
    assert checks['MSC 합계']['current']==9
    assert checks['종합설계(1) 포함']['status']==checks['종합설계 포함']['status']=='미충족'
    assert checks['일반과정 어학요건 확인']['status']=='확인 필요'


def test_chat_returns_server_evidence_without_task_notes(client,data,monkeypatch):
    from backend.service import ChatAnswer
    monkeypatch.setattr('backend.service.saved_connection',lambda root:Connection('fake-key','fake-model'))
    seen={}
    def reply(context,connection):
        seen.update(context)
        return ChatAnswer(answer='총학점은 0입니다.',referenced_checks=['총 졸업인정학점'],recommended_codes=[])
    monkeypatch.setattr('backend.service.request_chat',reply)
    data['checklist']=[{'id':'p','title':'PRIVATE TASK','note':'PRIVATE NOTE'}]
    response=post(client,'chat',{**data,'question':'총학점은?','consent':True}).json()
    assert response['mode']=='llm' and len(response['evidence'])==1
    assert response['evidence'][0]['current']==0 and response['evidence'][0]['sources']
    assert 'PRIVATE' not in json.dumps(seen)


def test_api_classification_preview_import_and_persistence(tmp_path):
    from src.planning.models import Attempt

    with TestClient(create_app(tmp_path / "planner.sqlite3")) as client:
        defaults = client.get("/api/bootstrap").json()
        row = Attempt(code="704818", name="자료구조및프로그래밍실습", credits=3, year=2021, grade="P", category="전공")
        payload = {"attempts": [row.model_dump()], "profile": defaults["profile"]}
        preview = client.post("/api/courses/classify", json=payload, headers=H)
        assert preview.status_code == 200
        assert preview.json()["suggestions"][0]["selected"]
        assert client.get("/api/profiles").json() == []
        raw = "2021학년도 2학년 1학기\n학수번호\t과목명\t영문과목명\t학점\t성적\t재수강\n007001\t교양영어(1)\t\t1\tP\t"
        imported = client.post("/api/import/portal", json={"text": raw, "profile": defaults["profile"]}, headers=H)
        assert imported.status_code == 200
        assert imported.json()["attempts"][0]["category"] == "일반선택"
        payload["attempts"][0]["category"] = "전공필수"
        saved = client.post("/api/profiles", json={**payload, "options": defaults["options"], "label": "synthetic classification"}, headers=H)
        assert saved.status_code == 201
        restored = client.get("/api/profiles/" + saved.json()["id"]).json()
        assert restored["attempts"][0]["category"] == "전공필수"
        assert client.post("/api/courses/classify", json=payload).status_code == 403
