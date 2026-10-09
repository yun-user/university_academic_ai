"""Build an allowlisted source bundle; never traverse student data or .env."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from src.config import PROJECT_ROOT


def package(root: Path, output: Path, *, include_web=False):
    paths = ["planner_app.py","requirements-planner.txt","requirements-planner-tested.txt",
             "setup_planner.cmd","start_planner.cmd","src/__init__.py","src/config.py",
             "pages/7_졸업로드맵.py","scripts/__init__.py","scripts/evaluate_planner.py",
             "data/raw/tables/소프트웨어융합학과_학년별교과과정_2026.csv"]
    for folder, pattern in [("src/planning","*.py"),("config/reviewed_rules","*.json")]:
        paths += [p.relative_to(root).as_posix() for p in sorted((root/folder).glob(pattern))]
    for name in ["aid_college_2026.json","aid_accreditation_2026.json"]:
        data = json.loads((root/"config/reviewed_rules"/name).read_text(encoding="utf-8"))
        paths.append("config/reviewed_rules/sources/"+data["source"]["file"])
    department = json.loads((root/"config/reviewed_rules/hongik.json").read_text(encoding="utf-8"))
    paths += ["config/reviewed_rules/sources/"+s["file"] for s in department["sources"]]
    program = json.loads((root/"config/reviewed_rules/software_program_review.json").read_text(encoding="utf-8"))
    paths += ["config/reviewed_rules/sources/"+s["file"] for s in program["sources"]]
    guidance = json.loads((root/"config/reviewed_rules/department_guidance.json").read_text(encoding="utf-8"))
    paths += ["config/reviewed_rules/sources/"+s["file"] for s in guidance["sources"]]
    classification = json.loads((root/"config/reviewed_rules/course_classification.json").read_text(encoding="utf-8"))
    paths += ["config/reviewed_rules/sources/"+s["file"] for s in classification["sources"]]
    design = json.loads((root/"config/reviewed_rules/design_courses.json").read_text(encoding="utf-8"))
    paths.append("config/reviewed_rules/sources/"+design["source_file"])
    # Only these maintained docs/tests and synthetic outputs are distributable.
    paths += ["docs/"+n for n in ["졸업로드맵_실행및시연.md","졸업로드맵_설계와검증보고서.md",
                                  "졸업로드맵_규정확인과_검증.md","졸업로드맵_개발계획.md","졸업로드맵_학교연동.md","졸업로드맵_학번선택과검증.md","졸업로드맵_이수구분과영어추가학점.md","졸업로드맵_MSC계산정정.md"]]
    paths += ["tests/unit/"+n for n in ["test_planning.py","test_planning_substitutions.py","test_planning_workspace.py","test_planning_llm.py"]]
    paths += ["tests/unit/test_planning_portal.py", "tests/unit/test_course_classification.py", "tests/ui/test_planner_page.py", "tests/ui/test_planner_portal.py"]
    paths += ["tests/unit/test_planning_language.py", "docs/졸업로드맵_어학요건과상담캐릭터.md"]
    paths += ["tests/unit/test_planning_design.py", "docs/졸업로드맵_설계학점자동반영.md"]
    paths += ["docs/images/path-classification-20261008.jpg"]
    if include_web:
        paths += ["requirements-web.txt", "setup_web.cmd", "start_web.cmd", "scripts/start_web.py",
                  "tests/unit/test_web_launcher.py",
                  "docs/졸업로드맵_웹앱구조와시연.md", "docs/졸업로드맵_최종보강과검증.md",
                  "docs/졸업로드맵_화면이동과학기추가.md",
                  "tests/integration/test_web_api.py", "tests/integration/test_web_features.py", "tests/integration/test_web_cohorts.py",
                  "tests/integration/test_web_language.py",
                  "tests/integration/test_web_design.py",
                  "tests/integration/test_web_counseling.py", "docs/졸업로드맵_개인화상담과기록.md",
                  "docs/images/path-counseling-20261009.png", "docs/images/path-counseling-goals-20261009.png",
                  "frontend/package.json", "frontend/package-lock.json", "frontend/index.html",
                  "frontend/tests/planOptions.test.mjs",
                  "frontend/tests/chatInput.test.mjs",
                  "frontend/tests/chatMessages.test.mjs",
                  "frontend/tsconfig.json", "frontend/vite.config.ts"]
        paths += [p.relative_to(root).as_posix() for p in sorted((root / "backend").glob("*.py"))]
        for folder, extensions in [("frontend/src", {".ts", ".tsx", ".css"}),
                                   ("frontend/dist", {".html", ".js", ".css"})]:
            paths += [p.relative_to(root).as_posix() for p in sorted((root / folder).rglob("*"))
                      if p.is_file() and p.suffix in extensions]
        if not (root / "frontend/dist/index.html").is_file():
            raise ValueError("Run the React production build before packaging")
    files = {}
    for rel in sorted(set(paths)):
        path = (root/rel).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Package path escapes project root")
        files[rel] = path.read_bytes()
    readme = "졸업로드맵_웹앱구조와시연.md" if include_web else "졸업로드맵_실행및시연.md"
    files["README.md"] = (root/"docs"/readme).read_bytes()
    for name in ("evaluation.json","evaluation.md"):
        files["evaluation/"+name] = (root/"output/planner/evaluation"/name).read_bytes()
    files[".streamlit/config.toml"] = b'[server]\naddress = "127.0.0.1"\nheadless = true\n[browser]\ngatherUsageStats = false\n'
    manifest = {name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()}
    files["MANIFEST.sha256.json"] = json.dumps(manifest,ensure_ascii=False,indent=2).encode("utf-8")
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,"w",compression=zipfile.ZIP_DEFLATED) as archive:
        for name,raw in files.items():
            archive.writestr("graduation-planner/"+name,raw)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP integrity check failed")
        for name,digest in manifest.items():
            if hashlib.sha256(archive.read("graduation-planner/"+name)).hexdigest()!=digest:
                raise ValueError("ZIP manifest mismatch")
    return {"file":str(output),"files":len(files),"bytes":output.stat().st_size,
            "sha256":hashlib.sha256(output.read_bytes()).hexdigest()}


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=PROJECT_ROOT/"output/planner/graduation-planner-20261005.zip")
    parser.add_argument("--web", action="store_true", help="Include the separate React/FastAPI/SQLite app")
    args=parser.parse_args()
    print(json.dumps(package(PROJECT_ROOT,args.output,include_web=args.web),ensure_ascii=False))
