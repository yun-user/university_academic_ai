"""Comparison, portable backups, evidence and evaluation endpoints."""
import json

from fastapi import Request
from fastapi.responses import Response

from backend.schemas import CompareRequest, EvaluationRecord, PlanningInput, TranscriptText, WebBackup
from src.planning.audit import audit
from src.planning.evaluation import evaluate_scenarios
from src.planning.io import write_transcript
from src.planning.manual import validate_plan
from src.planning.models import PlanOptions
from src.planning.report import render_report, _table
from src.planning.rules import load_rules, _verify
from src.planning.workspace import _unique_object, read_workspace, source_fingerprint


def register_features(app, service, database):
    root = service.root

    @app.post("/api/plan/validate")
    def validate(data: PlanningInput):
        candidates = service.candidates(data)
        rules = load_rules(root, data.profile.track)
        if data.placements is None:
            return {"valid":True, "violations":[], "roadmap":service.plan(data).as_dict()}
        plan, errors = validate_plan(data.attempts, data.profile, rules, candidates, data.options, data.placements)
        return {"valid":not errors, "violations":errors, "roadmap":plan.as_dict() if plan else None}

    @app.post("/api/compare")
    def compare(data: CompareRequest):
        results = []
        for limit in data.limits:
            caps = [limit]*data.options.semesters
            if data.last_limit is not None:
                caps[-1] = data.last_limit
            options = PlanOptions.model_validate({**data.options.model_dump(), "credit_limit":limit, "semester_limits":caps})
            scenario = PlanningInput.model_validate({**data.model_dump(exclude={"limits", "last_limit"}), "options":options, "placements":None})
            result = service.analyze(scenario)
            results.append({"limit":limit, "options":options.model_dump(), "result":result,
                            "planned_credits":sum(s["credits"] for s in result["roadmap"]["semesters"])})
        return {"scenarios":results, "notice":"같은 기간의 입력 제약을 비교합니다. 최단 졸업이나 실제 개설을 보장하지 않습니다."}

    @app.post("/api/export/backup")
    def backup(data: PlanningInput):
        # Validate input chronology/manual constraints but never call an LLM.
        service.plan(data)
        return WebBackup(data=data, rules_fingerprint=source_fingerprint(root)).model_dump(mode="json")

    @app.post("/api/import/backup")
    def restore(data: TranscriptText):
        try:
            raw = json.loads(data.text, object_pairs_hook=_unique_object)
            if raw.get("kind") == "hongik-graduation-workspace":
                old = read_workspace(data.text.encode())
                parsed = PlanningInput(attempts=old.attempts, profile=old.profile, options=old.options,
                                       candidates=old.candidates, goal=old.llm_goal)
                fingerprint = old.rules_fingerprint
            else:
                saved = WebBackup.model_validate(raw)
                parsed, fingerprint = saved.data, saved.rules_fingerprint
            service.plan(parsed)
        except Exception:
            raise ValueError("백업의 형식·학기·배치 제약을 확인하세요. 현재 입력은 변경되지 않았습니다.") from None
        warnings = [] if fingerprint == source_fingerprint(root) else ["백업 이후 규정 자료가 바뀌었습니다. 현재 자료로 다시 계산합니다."]
        return {"data":parsed.model_dump(mode="json"), "warnings":warnings}

    @app.post("/api/export/csv")
    def csv(data: PlanningInput):
        return Response(write_transcript(data.attempts), media_type="text/csv",
                        headers={"Content-Disposition":'attachment; filename="transcript.csv"'})

    @app.post("/api/export/report")
    def report(data: PlanningInput):
        candidates = service.candidates(data)
        rules = load_rules(root, data.profile.track)
        plan = service.plan(data, candidates, rules)
        current = audit(data.attempts, data.profile, rules, equivalences=candidates)
        html = render_report(data.profile, current, plan, rules).decode()
        tasks = _table(["할 일", "기한", "완료", "메모"],
                       [(t.title, t.due or "미정", "완료" if t.done else "진행 전", t.note) for t in data.checklist])
        html = html.replace("</body>", "<h2>졸업 준비 체크리스트</h2><p>체크는 학교 승인 여부를 변경하지 않습니다.</p>"+tasks+"</body>")
        return Response(html, media_type="text/html", headers={"Content-Disposition":'attachment; filename="graduation-report.html"'})

    @app.get("/api/sources")
    def sources():
        review = json.loads((root/"config/reviewed_rules/software_program_review.json").read_text(encoding="utf-8"))
        for source in review["sources"]:
            _verify(root/"config/reviewed_rules", source)
        return {**review, "rules_fingerprint":source_fingerprint(root)}

    @app.get("/api/evaluations")
    def evaluations(request: Request):
        return {"synthetic":evaluate_scenarios(root), "records":database.evaluations(request.state.owner_id)}

    @app.post("/api/evaluations", status_code=201)
    def add_evaluation(data: EvaluationRecord, request: Request):
        return database.add_evaluation(data, request.state.owner_id)

    @app.delete("/api/evaluations/{record_id}", status_code=204)
    def remove_evaluation(record_id: str, request: Request):
        database.delete_evaluation(record_id, request.state.owner_id)
        return Response(status_code=204)
