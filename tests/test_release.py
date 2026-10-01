import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from src.ingestion.registry import (register_document, list_documents, set_active,
                                    validate_upload, safe_path, database)
from src.ingestion.build_corpus import build_corpus
from src.ingestion.web_collector import PublicCollector, parse_page, validate_url
from src.ingestion.ocr import review_page, language_data
from src.retrieval.keyword_search import KeywordIndex, fuse, tokenize
from src.retrieval.document_models import DocumentSearchResult, DocumentSearchResponse
from src.answering.llm_answer_service import LLMAnswerService, _parse_grounded_completion
from src.answering.models import AnswerMode, AnswerSource, AnswerResponse


def result(**changes):
    text = "장학금 신청 기간은 2026년 3월 1일부터 3월 10일까지입니다. 신청서는 학과 사무실에 제출합니다."
    values = dict(document_id="DOC", chunk_id="chunk-1", file_name="안내.pdf", file_type="pdf",
        document_type="장학안내", department="전체", title="장학안내", page_number=2,
        source_path="data/raw/pdfs/안내.pdf", text=text, score=.8,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        source_url="https://university.example/notice", source_year="2026", is_current=True)
    return DocumentSearchResult(**(values | changes))


def test_managed_upload_disable_and_restore_keeps_original(tmp_path):
    data = "공식 공개 학사 안내입니다. 신청 기간과 방법을 확인하세요.".encode()
    key = register_document(tmp_path, "학사안내.txt", data, {"department": "전체", "source_year": "2026"})
    row = list_documents(tmp_path)[0]
    original = safe_path(tmp_path, row["path"])
    assert original.read_bytes() == data
    assert register_document(tmp_path, "학사안내.txt", data, {"department": "전체", "source_year": "2026"}) == key
    assert build_corpus(tmp_path).documents[0]["file_name"] == "학사안내.txt"
    set_active(tmp_path, key, False)
    assert build_corpus(tmp_path).documents == []
    assert original.read_bytes() == data
    set_active(tmp_path, key, True)
    assert len(build_corpus(tmp_path).documents) == 1


def test_version_replacement_preserves_both_files(tmp_path):
    first = register_document(tmp_path, "공지.txt", "첫 번째 공지 내용".encode(), {})
    second = register_document(tmp_path, "공지.txt", "새로운 공지 내용".encode(), {}, replaces=first)
    documents = build_corpus(tmp_path).documents
    assert [d["document_id"] for d in documents] == [second]
    assert all(safe_path(tmp_path, d["path"]).exists() for d in list_documents(tmp_path))


@pytest.mark.parametrize("name,data", [("bad.pdf", b"not pdf"), ("x.exe", b"hi"),
    ("x.txt", b"\xff\xfe"), ("empty.csv", b"name\n"), ("empty.txt", b"")])
def test_bad_uploads_rejected(name, data):
    with pytest.raises(ValueError):
        validate_upload(name, data)


def test_paths_and_source_url_cannot_escape(tmp_path):
    with pytest.raises(ValueError):
        safe_path(tmp_path, "../outside.txt")
    with pytest.raises(ValueError):
        register_document(tmp_path, "text.txt", b"hello", {"source_url": "javascript:alert(1)"})
    key = register_document(tmp_path, "../../hello.txt", b"hello", {})
    assert list_documents(tmp_path)[0]["name"] == "hello.txt"


def test_keyword_cache_rebuilds_after_deletion(tmp_path):
    def candidate(key, text):
        return SimpleNamespace(chunk_id=key, content=text, content_hash=hashlib.sha256(text.encode()).hexdigest())
    path = tmp_path / "tokens.json"
    rows = [candidate("a", "졸업 전공학점 60학점 이상"), candidate("b", "장학금 신청")]
    index = KeywordIndex(rows, path)
    assert index.search("전공학점", {"a", "b"})[0][0] == "a"
    index = KeywordIndex(rows[1:], path)
    assert index.search("전공학점", {"a", "b"}) == []
    assert set(json.loads(path.read_text(encoding="utf-8"))["tokens"]) == {"b"}


def test_fusion_and_identifier_preservation():
    assert fuse(["a", "b"], ["b", "c"])[0] == "b"
    assert "001234" in tokenize("학수번호 001234 제외 불가")
    assert "불가" in tokenize("학수번호 001234 제외 불가")


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.1.1", "169.254.169.254", "::1"])
def test_ssrf_public_dns_required(monkeypatch, ip):
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **kw: [(0,0,0,"",(ip,443))])
    with pytest.raises(ValueError):
        validate_url("https://school.example/notice", {"school.example"})


@pytest.mark.parametrize("url", ["http://school.example/", "https://evil.example/",
    "https://user:pass@school.example/", "https://school.example:8443/"])
def test_invalid_web_targets(url):
    with pytest.raises(ValueError):
        validate_url(url, {"school.example"})


def test_robots_denial_stops_before_content(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    calls = []
    def fetch(url, hosts):
        calls.append(url)
        return 200, {}, b"User-agent: *\nDisallow: /private"
    with pytest.raises(ValueError, match="robots"):
        PublicCollector(["school.example"], fetch=fetch).collect("https://school.example/private")
    assert calls == ["https://school.example/robots.txt"]


def test_redirect_cannot_escape_allowlist(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    calls = []
    def fetch(url, hosts):
        calls.append(url)
        if url.endswith("robots.txt"):
            return 404, {}, b""
        return 302, {"Location": "https://evil.example/"}, b""
    with pytest.raises(ValueError):
        PublicCollector(["school.example"], fetch=fetch).collect("https://school.example/notice")
    assert len(calls) == 2


def test_html_extraction_excludes_navigation_and_script():
    html = ('<html><title>학사공지</title><nav>메뉴</nav><main><script>bad()</script>'
            + '공식 학사 안내 본문입니다. ' * 10 + '</main></html>').encode()
    page = parse_page("https://school.example/notice", html)
    assert "bad()" not in page.text and "메뉴" not in page.text
    assert page.title == "학사공지"
    with pytest.raises(ValueError):
        parse_page(page.url, b'<title>Login</title><input type="password">')


def test_missing_ocr_language_data_is_actionable(tmp_path, monkeypatch):
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    with pytest.raises(ValueError, match="setup_ocr"):
        language_data(tmp_path)


def test_ocr_review_requires_existing_matching_original(tmp_path):
    key = register_document(tmp_path, "sample.txt", b"test", {})
    document = list_documents(tmp_path)[0]
    with pytest.raises(ValueError):
        review_page(tmp_path, document, 1, "검토한 텍스트")


class Search:
    def __init__(self, evidence):
        self.evidence = evidence
    def search_with_context(self, *a, **kw):
        return DocumentSearchResponse(results=self.evidence)


class Provider:
    def __init__(self, payload=None, failure=False):
        self.payload, self.failure, self.calls = payload, failure, 0
    def generate(self, **kw):
        self.calls += 1
        if self.failure:
            raise TimeoutError("no response")
        return json.dumps(self.payload, ensure_ascii=False)


def test_llm_exact_quote_and_trusted_url():
    evidence = result()
    provider = Provider({"claims": [{"quote": evidence.text, "evidence_id": evidence.chunk_id}]})
    answer = LLMAnswerService(Search([evidence]), provider=provider, enabled=True).answer_question("장학금 신청 기간")
    assert answer.answer_mode == AnswerMode.LLM
    assert answer.sources[0].source_url == evidence.source_url
    assert provider.calls == 1


def test_same_named_documents_keep_distinct_citations():
    from src.answering.answer_service import AnswerService
    from src.answering.models import deduplicate_answer_sources
    first = result(document_id="old", chunk_id="old-1")
    second = result(document_id="new", chunk_id="new-1")
    sources = [AnswerService._source(r, r.text) for r in [first, second]]
    assert len(deduplicate_answer_sources(sources)) == 2
    assert len(deduplicate_answer_sources([sources[0], sources[0]])) == 1


@pytest.mark.parametrize("claim", [
    {"quote": "장학금은 무조건 999만원 지급됩니다.", "evidence_id": "chunk-1"},
    {"quote": "장학금 신청 기간은 2026년 3월 1일부터 3월 10일까지입니다.", "evidence_id": "invented"},
    {"quote": "장학금 신청 기간은 2026년 3월 1일부터 3월 10일까지입니다.", "evidence_id": "chunk-1", "text": "반대 주장"},
])
def test_llm_unverifiable_output_falls_back(claim):
    provider = Provider({"claims": [claim]})
    answer = LLMAnswerService(Search([result()]), provider=provider, enabled=True).answer_question("장학금 신청 기간")
    assert answer.answer_mode == AnswerMode.DETERMINISTIC


def test_llm_timeout_and_no_evidence_fallback():
    provider = Provider(failure=True)
    service = LLMAnswerService(Search([result()]), provider=provider, enabled=True)
    assert service.answer_question("장학금 신청 기간").answer_mode == AnswerMode.DETERMINISTIC
    provider.calls = 0
    service = LLMAnswerService(Search([]), provider=provider, enabled=True)
    assert not service.answer_question("없는 정보").sources
    assert provider.calls == 0


def test_admin_page_requires_password(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("ADMIN_PASSWORD", "test-password-at-least-12")
    page = AppTest.from_file(str(Path(__file__).parents[1] / "pages/1_문서관리.py")).run()
    assert not page.exception
    assert any(w.label == "관리자 비밀번호" for w in page.text_input)
    assert not any(b.label == "검색 데이터 반영" for b in page.button)


@pytest.mark.parametrize("filename", ["1_문서관리.py", "2_공개공지수집.py", "3_OCR검토.py", "4_평가결과.py"])
def test_admin_pages_render_after_login(monkeypatch, filename):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("ADMIN_PASSWORD", "test-password-at-least-12")
    page = AppTest.from_file(str(Path(__file__).parents[1] / "pages" / filename)).run(timeout=15)
    page.text_input[0].set_value("test-password-at-least-12")
    page.button[0].click().run(timeout=15)
    assert not page.exception
    assert any(button.label == "관리자 로그아웃" for button in page.button)


def test_reviewed_ocr_enters_corpus_only_after_approval(tmp_path):
    import pymupdf
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72,72), "Original text")
    data = pdf.tobytes()
    pdf.close()
    key = register_document(tmp_path, "scan.pdf", data, {})
    document = list_documents(tmp_path)[0]
    with database(tmp_path) as con:
        con.execute("INSERT INTO ocr VALUES (?,?,?,?,0)",
            (key, 1, hashlib.sha256(data).hexdigest(), "검토가 필요한 OCR 결과입니다."))
    assert "Original" in build_corpus(tmp_path).documents[0]["text"]
    review_page(tmp_path, document, 1, "검토가 끝난 OCR 결과입니다.")
    record = build_corpus(tmp_path).documents[0]
    assert record["text"] == "검토가 끝난 OCR 결과입니다."
    assert record["page_number"] == 1 and record["metadata"]["ocr_reviewed"]


def test_evaluation_metrics_and_group_meaning():
    from src.evaluation.metrics import score_case, summarize
    rows = [score_case({"expected": [{"document_id": "DOC", "page_number": 2}]}, [result()]),
            score_case({"expected": []}, [])]
    report = summarize(rows)
    assert report["hit_at_k"] == report["mrr"] == report["correct_rejection_rate"] == 1


def test_initialization_creates_password_and_preserves_existing_settings(tmp_path, monkeypatch):
    from scripts import initialize
    monkeypatch.setattr(initialize, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".env.example").write_text("ADMIN_PASSWORD=\nLLM_API_KEY=\n", encoding="utf-8")
    initialize.main()
    first = (tmp_path / ".env").read_text(encoding="utf-8")
    password_line = next(line for line in first.splitlines() if line.startswith("ADMIN_PASSWORD="))
    assert len(password_line.split("=", 1)[1]) >= 12
    initialize.main()
    assert (tmp_path / ".env").read_text(encoding="utf-8") == first
    custom = "LLM_API_KEY=test-value\nADMIN_PASSWORD=\n"
    (tmp_path / ".env").write_text(custom, encoding="utf-8")
    initialize.main()
    assert "LLM_API_KEY=test-value" in (tmp_path / ".env").read_text(encoding="utf-8")
