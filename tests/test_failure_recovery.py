"""Failure injection for setup, corpus publication, search cache and OCR UI."""
import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotenv import dotenv_values

from src.ingestion.build_corpus import build_corpus
from src.ingestion.registry import register_document, set_active
from src.retrieval.keyword_search import KeywordIndex


@pytest.mark.parametrize("line", ["ADMIN_PASSWORD=", "ADMIN_PASSWORD=''", 'ADMIN_PASSWORD="  "',
                                     "export ADMIN_PASSWORD =  ", "ADMIN_PASSWORD='' # blank"])
def test_blank_password_syntax_is_initialized(tmp_path, monkeypatch, line):
    from scripts import initialize
    monkeypatch.setattr(initialize, "PROJECT_ROOT", tmp_path)
    env = tmp_path / ".env"
    env.write_text(line + "\nLLM_API_KEY=keep-test-value\n", encoding="utf-8")
    initialize.main()
    values = dotenv_values(env)
    assert len(values["ADMIN_PASSWORD"]) >= 12
    assert values["LLM_API_KEY"] == "keep-test-value"
    first = env.read_bytes()
    initialize.main()
    assert env.read_bytes() == first


def test_existing_quoted_password_is_preserved_and_example_is_copied(tmp_path, monkeypatch):
    from scripts import initialize
    monkeypatch.setattr(initialize, "PROJECT_ROOT", tmp_path)
    text = 'export ADMIN_PASSWORD = "already set password"\nLLM_API_KEY=test-value\n'
    (tmp_path / ".env.example").write_text(text, encoding="utf-8")
    initialize.main()
    assert (tmp_path / ".env").read_text(encoding="utf-8") == text
    initialize.main()
    assert (tmp_path / ".env").read_text(encoding="utf-8") == text


def source(tmp_path):
    key = register_document(tmp_path, "notice.txt", b"original content", {})
    return key, tmp_path / f"data/uploads/{key}/source.txt"


def test_failed_extraction_preserves_active_corpus_and_saves_diagnostics(tmp_path):
    _, path = source(tmp_path)
    good = build_corpus(tmp_path)
    previous = good.documents_path.read_bytes()
    path.write_bytes(b"\xff\xff")
    failed = build_corpus(tmp_path)
    assert failed.report["errors"]
    assert good.documents_path.read_bytes() == previous
    assert failed.documents_path.name == "documents.failed.jsonl"
    assert json.loads(failed.report_path.read_text(encoding="utf-8"))["errors"]


@pytest.mark.parametrize("entrypoint", ["ui", "cli"])
@pytest.mark.parametrize("initial", [True, False])
def test_embedding_failure_restores_corpus(tmp_path, monkeypatch, entrypoint, initial):
    _, path = source(tmp_path)
    active = tmp_path / "data/processed/documents.jsonl"
    if initial:
        build_corpus(tmp_path)
    previous = active.read_bytes() if initial else None
    path.write_text("new content", encoding="utf-8")
    class FailingService:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def index_corpus(self, candidate):
            assert "new content" in candidate.read_text(encoding="utf-8")
            raise RuntimeError("embedding failed")
    if entrypoint == "ui":
        from src import runtime as target
        monkeypatch.setattr(target, "get_search_service", FailingService)
        run = target.synchronize
    else:
        from scripts import prepare as target
        monkeypatch.setattr(target.DocumentSearchService, "from_settings", lambda _: FailingService())
        run = target.main
    monkeypatch.setattr(target, "get_settings", lambda: SimpleNamespace(project_root=tmp_path))
    with pytest.raises(RuntimeError, match="embedding failed"):
        run()
    assert (active.read_bytes() if active.exists() else None) == previous


def test_disabled_raw_pdf_does_not_block_build(tmp_path):
    raw = tmp_path / "data/raw/pdfs"
    raw.mkdir(parents=True)
    (raw / "broken.pdf").write_bytes(b"bad PDF")
    manifest = tmp_path / "data/metadata/documents_manifest.csv"
    manifest.parent.mkdir(parents=True)
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["document_id", "file_name", "file_type"])
        writer.writeheader()
        writer.writerow(dict(document_id="BROKEN", file_name="broken.pdf", file_type="pdf"))
    set_active(tmp_path, "BROKEN", False)
    result = build_corpus(tmp_path)
    assert not result.report["errors"]
    assert result.report["skipped_inactive_files"] == 1
    (raw / "broken.pdf").unlink()
    assert not build_corpus(tmp_path).report["errors"]
    set_active(tmp_path, "BROKEN", True)
    assert build_corpus(tmp_path).report["errors"]


@pytest.mark.parametrize("corruption", ["[]", "null", "invalid", "missing", "wrong_type", "nested"])
def test_corrupt_keyword_cache_is_rebuilt(tmp_path, corruption):
    path = tmp_path / "tokens.json"
    rows = [SimpleNamespace(chunk_id="a", content="전공학점", content_hash="hash")]
    KeywordIndex(rows, path)
    cache = json.loads(path.read_text(encoding="utf-8"))
    if corruption == "missing":
        cache["tokens"] = {}
    elif corruption == "wrong_type":
        cache["tokens"] = {"a": "bad"}
    elif corruption == "nested":
        cache["tokens"] = {"a": [["bad"]]}
    path.write_text(json.dumps(cache) if corruption in {"missing", "wrong_type", "nested"}
                    else corruption, encoding="utf-8")
    assert KeywordIndex(rows, path).search("전공학점", {"a"})[0][0] == "a"


def test_cache_write_failure_does_not_break_search(tmp_path, monkeypatch):
    original = Path.replace
    def denied(path, target):
        if Path(target).name == "tokens.json":
            raise PermissionError("read-only cache")
        return original(path, target)
    monkeypatch.setattr(Path, "replace", denied)
    rows = [SimpleNamespace(chunk_id="a", content="전공학점", content_hash="hash")]
    assert KeywordIndex(rows, tmp_path / "tokens.json").search("전공학점", {"a"})
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("contents", [None, b"broken PDF"])
def test_ocr_missing_or_broken_pdf_shows_error(tmp_path, monkeypatch, contents):
    from streamlit.testing.v1 import AppTest
    import src.admin_auth
    import src.config
    import src.ingestion.registry
    root = Path(__file__).resolve().parents[1]
    pdf = tmp_path / "data/bad.pdf"
    pdf.parent.mkdir()
    if contents is not None:
        pdf.write_bytes(contents)
    monkeypatch.setattr(src.admin_auth, "require_admin", lambda: None)
    monkeypatch.setattr(src.config, "get_settings", lambda: SimpleNamespace(project_root=tmp_path))
    monkeypatch.setattr(src.ingestion.registry, "list_documents", lambda _: [
        {"id": "PDF", "name": "bad.pdf", "path": "data/bad.pdf", "active": True}])
    app = AppTest.from_file(str(root / "pages/3_OCR검토.py")).run()
    assert not app.exception
    assert "원본 PDF가 없거나" in app.error[0].value
