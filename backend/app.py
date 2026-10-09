"""Run with python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000."""
from contextlib import asynccontextmanager
from pathlib import Path
import os

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from backend.database import Database, MissingProfile, RevisionConflict
from backend.schemas import AnalysisRequest, ChatRequest, SaveProfile, TranscriptText, Credentials, ClassificationRequest, DesignRequest
from backend.service import PlannerService
from backend.auth import Auth, COOKIE, TTL
from backend.features import register_features
from src.planning.catalog import load_catalog
from src.planning.classification import classify_attempts, classify_import
from src.planning.io import read_transcript, sample_transcript, write_transcript
from src.planning.llm import saved_connection
from src.planning.models import CATEGORIES, GRADES, STATUSES, PlanOptions, Profile
from src.planning.portal_import import parse_portal_text
from src.planning.workspace import seoul_today
from src.planning.cohorts import SUPPORTED_ADMISSION_YEARS
from src.planning.rules import load_rules, load_department_guidance
from src.planning.language import assess_language

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ORIGINS = {f"http://{host}:{port}" for host in ("127.0.0.1", "localhost") for port in (8000, 5173)}


def create_app(db_path=None, root=ROOT, auth_required=None):
    database = Database(Path(db_path or os.getenv("PLANNER_DB_PATH", root / "data/private/planner.sqlite3")))
    service = PlannerService(root)
    auth_required = os.getenv("PLANNER_AUTH_REQUIRED") == "1" if auth_required is None else auth_required
    auth = Auth(database)

    @asynccontextmanager
    async def lifespan(app):
        database.initialize()
        yield

    app = FastAPI(title="졸업 로드맵 API", version="1.0.0", lifespan=lifespan)
    app.state.database = database
    app.state.service = service
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def local_boundary(request, call_next):
        if request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin and origin not in ALLOWED_ORIGINS:
                return JSONResponse({"detail": "허용되지 않은 웹페이지에서 보낸 요청입니다."}, status_code=403)
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                if request.headers.get("x-planner-request") != "1":
                    return JSONResponse({"detail": "앱에서 요청을 다시 보내세요."}, status_code=403)
                # Bound actual bytes, not just a caller-controlled Content-Length.
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > 2_000_000:
                        return JSONResponse({"detail": "입력은 2MB 이하만 허용합니다."}, status_code=413)
                request._body = bytes(body)
            request.state.owner_id = ""
            if auth_required:
                user = auth.user(request.cookies.get(COOKIE))
                request.state.user = user
                request.state.owner_id = user["id"] if user else ""
                public = {"/api/health", "/api/auth/me", "/api/auth/login", "/api/auth/register", "/api/auth/logout"}
                if not user and request.url.path not in public:
                    return JSONResponse({"detail":"로그인이 필요합니다."}, status_code=401)
            if request.url.path in {"/api/chat", "/api/analysis", "/api/compare"} and request.method == "POST":
                try:
                    auth.limit("compute:" + (request.state.owner_id or "local"), 30)
                except HTTPException as exc:
                    return JSONResponse({"detail":exc.detail}, status_code=exc.status_code)
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Do not echo raw records or credentials from malformed submissions.
        fields = [
            "계획 시작 연도는 2018~2100 사이의 정수로 입력하세요. 입학연도가 아니라 로드맵을 시작할 연도입니다(예: 2027년)."
            if tuple(error["loc"][-2:]) == ("options", "start_year")
            else ".".join(map(str, error["loc"][1:]))
            for error in exc.errors()[:10]
        ]
        return JSONResponse({"detail": "입력 형식을 확인하세요: " + ", ".join(fields)}, status_code=422)

    @app.exception_handler(MissingProfile)
    async def not_found(request, exc):
        return JSONResponse({"detail": "저장 항목을 찾을 수 없습니다."}, status_code=404)

    @app.exception_handler(RevisionConflict)
    async def conflict(request, exc):
        return JSONResponse({"detail": "다른 창에서 수정한 내용이 있습니다. 저장 항목을 다시 불러오세요."}, status_code=409)

    @app.exception_handler(ValueError)
    async def domain_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "storage": "sqlite", "version": "1.0.0"}

    @app.get("/api/auth/me")
    def me(request: Request):
        return {"required":auth_required, "user":auth.user(request.cookies.get(COOKIE)) if auth_required else None}

    def account(data, request, response, register=False):
        if not auth_required:
            raise HTTPException(400, "계정 기능은 서버의 계정 모드에서 사용합니다.")
        auth.limit("auth:" + (request.client.host if request.client else "local"))
        owner = auth.register(data) if register else auth.login(data)
        # Prevent stale sessions surviving a switch of account in this browser.
        auth.logout(request.cookies.get(COOKIE))
        token = auth.issue(owner)
        response.set_cookie(COOKIE, token, max_age=TTL, httponly=True, samesite="strict", secure=request.url.scheme=="https")
        return {"user":auth.user(token)}

    @app.post("/api/auth/register", status_code=201)
    def register(data: Credentials, request: Request, response: Response):
        return account(data, request, response, True)

    @app.post("/api/auth/login")
    def login(data: Credentials, request: Request, response: Response):
        return account(data, request, response)

    @app.post("/api/auth/logout", status_code=204)
    def logout(request: Request):
        auth.logout(request.cookies.get(COOKIE))
        response = Response(status_code=204)
        response.delete_cookie(COOKIE)
        return response

    @app.get("/api/bootstrap")
    def bootstrap():
        connection = saved_connection(root)
        today = seoul_today()
        options = PlanOptions(start_year=max(2018, today.year + (today.month >= 8)), start_term=1)
        return {"profile": Profile().model_dump(), "options": options.model_dump(),
                "department_guidance": load_department_guidance(root),
                "admission_years": SUPPORTED_ADMISSION_YEARS,
                "cohort_rules": [{"admission_year": year, "track": track,
                    "thresholds": (r := load_rules(root, track, year)).thresholds,
                    "liberal_cap": r.liberal_cap, "cohort_range": r.cohort_range,
                    "science_mode": r.science_mode, "msc_detail": r.msc_detail,
                    "source": r.sources[0]} for year in SUPPORTED_ADMISSION_YEARS for track in ("심화", "일반")],
                "categories": CATEGORIES, "grades": GRADES, "statuses": STATUSES,
                "catalog": [c.model_dump() for c in load_catalog(root)],
                "llm": {"configured": bool(connection.api_key and connection.model), "model": connection.model}}

    @app.get("/api/demo")
    def demo(admission_year: int = Query(default=2020, ge=2018, le=2026)):
        return {"attempts": [a.model_dump() for a in sample_transcript(admission_year)]}

    @app.post("/api/language/check")
    def language_check(profile: Profile):
        result = assess_language(profile.language, load_department_guidance(root))
        if profile.track == "일반" and profile.english != "충족":
            result = {**result, "status": "확인 필요", "detail": "일반과정은 학과 적용·예외 확인 필요. 아래는 심화 표 참고 대조입니다. " + result["detail"]}
        return result

    @app.get("/api/transcript/template")
    def template():
        return Response(write_transcript(sample_transcript()), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="transcript-example.csv"'})

    @app.post("/api/import/portal")
    def portal(data: TranscriptText):
        result = parse_portal_text(data.text, load_catalog(root))
        if not result.ready:
            raise HTTPException(422, " ".join(result.errors) or "성적표 과목을 찾지 못했습니다.")
        attempts, review = classify_import(result.attempts, data.profile, root)
        warnings = [w for w in result.warnings if "2026 교과과정" not in w and "‘미확인’" not in w]
        warnings += review["notes"][:3]
        if any(a.category == "미확인" for a in attempts):
            warnings.append("미확인 과목은 졸업학점 계산에서 제외됩니다. 이수 내역의 학과 자료로 분류 확인에서 근거를 검토하세요.")
        return {"attempts": [a.model_dump() for a in attempts], "warnings": warnings,
                "classification": review}

    @app.post("/api/courses/classify")
    def classification(data: ClassificationRequest):
        return classify_attempts(data.attempts, data.profile, root)

    @app.post("/api/courses/design")
    def design_credits(data: DesignRequest):
        from src.planning.audit import audit
        result = audit(data.attempts, data.profile, load_rules(root, data.profile.track, data.profile.admission_year), equivalences=service.candidates(data))
        return {"allocations": result.design_allocations,
                "total": sum(r["counted_credits"] for r in result.design_allocations)}

    @app.post("/api/import/csv")
    def csv(data: TranscriptText):
        return {"attempts": [a.model_dump() for a in read_transcript(data.text.encode("utf-8-sig"))], "warnings": []}

    @app.post("/api/analysis")
    def analysis(data: AnalysisRequest):
        return service.analyze(data, consent=data.consent)

    @app.post("/api/chat")
    def chat(data: ChatRequest):
        return service.chat(data)

    @app.get("/api/profiles")
    def profiles(request: Request):
        return database.list_profiles(request.state.owner_id)

    @app.post("/api/profiles", status_code=201)
    def create_profile(data: SaveProfile, request: Request):
        return database.save(data, service.analyze(data), owner_id=request.state.owner_id)

    @app.get("/api/profiles/{profile_id}")
    def get_profile(profile_id: str, request: Request):
        return database.get_profile(profile_id, request.state.owner_id)

    @app.put("/api/profiles/{profile_id}")
    def update_profile(profile_id: str, data: SaveProfile, request: Request):
        return database.save(data, service.analyze(data), profile_id, request.state.owner_id)

    @app.delete("/api/profiles/{profile_id}", status_code=204)
    def delete_profile(profile_id: str, request: Request, revision: int = Query(ge=1)):
        database.delete(profile_id, revision, request.state.owner_id)
        return Response(status_code=204)

    @app.get("/api/profiles/{profile_id}/history")
    def history(profile_id: str, request: Request):
        return database.history(profile_id, request.state.owner_id)

    register_features(app, service, database)

    dist = root / "frontend/dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
