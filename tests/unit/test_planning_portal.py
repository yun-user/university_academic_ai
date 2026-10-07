"""Synthetic tables matching the observed portal layout; no student fixtures."""
import asyncio
from threading import get_ident

import pytest

from src.planning.io import parse_rows, to_rows
from src.planning.models import Candidate
from src.planning.portal import (PortalError, is_school_frame, local_portal_enabled,
                                 read_school_tables, TRANSCRIPT_PATH)
from src.planning.portal_import import HEADERS, parse_period, parse_portal_tables, parse_portal_text


def table(caption="2020학년도 1학년 1학기", rows=None):
    return {"caption": caption, "headers": list(HEADERS), "rows": rows if rows is not None else [
        ["001234", "가상 과목", "", "3", "B0", ""]]}


@pytest.mark.parametrize("text,expected", [
    ("2020학년도 0학년 1학기", (2020, 1)), ("2018학년도 1학년 2학기", (2018, 2)),
    ("2025학년도 3학년 하계계절학기", (2025, 3)), ("2025학년도 3학년 동계계절학기", (2025, 4))])
def test_periods(text, expected):
    assert parse_period(text) == expected


def test_unknown_period_not_guessed():
    with pytest.raises(ValueError):
        parse_period("2020년 1학기")
    result = parse_portal_tables([table(caption="")], [])
    assert not result.ready and result.errors


def test_exact_match_only_suggests_category_no_design_area_or_alias():
    catalog = [Candidate(code="001234", name="가상 과목", credits=3, category="전공", design_credits=2, equivalent_code="OTHER")]
    result = parse_portal_tables([table()], catalog)
    assert result.ready
    attempt = result.attempts[0]
    assert attempt.code == "001234" and attempt.category == "전공"
    assert attempt.design_credits == 0 and attempt.area == 0 and attempt.equivalent_code == ""
    assert "2026" in result.reviews[0]["분류 근거"]
    assert parse_rows(to_rows(result.attempts)) == result.attempts


@pytest.mark.parametrize("changes", [{"name": "다른 과목"}, {"credits": 2}, {"code": "009999"}])
def test_mismatch_stays_unknown(changes):
    course = {"code": "001234", "name": "가상 과목", "credits": 3, "category": "전공", **changes}
    result = parse_portal_tables([table()], [Candidate(**course)])
    assert result.ready and result.attempts[0].category == "미확인"


def test_retake_and_failed_attempts_preserved_with_warning():
    old = table(rows=[["001234", "가상 과목", "", "3", "F", "재수강"]])
    new = table("2021학년도 2학년 1학기")
    result = parse_portal_tables([old, new], [])
    assert result.ready and len(result.attempts) == 2
    assert result.attempts[0].grade == "F" and result.attempts[0].status == "인정제외"
    assert any("반복 수강" in w for w in result.warnings)


def test_earlier_coursework_preserved_without_changing_admission_scope():
    result = parse_portal_tables([table("2018학년도 1학년 1학기")], [])
    assert result.ready and result.attempts[0].year == 2018
    assert any("입학연도" in w for w in result.warnings)


@pytest.mark.parametrize("bad", [
    [], [table(rows=[])], [table(rows=[["bad"]])],
    [table(), table()], [table(rows=[["001234", "가상 과목", "", "3", "BAD", ""]])],
    [{**table(), "headers": ["이름", "학번"]}],
    [table(rows=[["001234", "가상 과목", "", "NaN", "A+", ""]])],
    [table(rows=[["001234", "가상 과목", "", "0", "P", ""]])],
])
def test_malformed_and_empty_imports_block_application(bad):
    result = parse_portal_tables(bad, [])
    assert not result.ready and result.errors
    assert "가상 과목" not in str(result.errors)


@pytest.mark.parametrize("url,expected", [
    ("https://cn.hongik.ac.kr" + TRANSCRIPT_PATH, True),
    ("http://cn.hongik.ac.kr" + TRANSCRIPT_PATH, False),
    ("https://cn.hongik.ac.kr.evil.test" + TRANSCRIPT_PATH, False),
    ("https://cn.hongik.ac.kr:8443" + TRANSCRIPT_PATH, False),
    ("https://name@cn.hongik.ac.kr" + TRANSCRIPT_PATH, False),
    ("https://my.hongik.ac.kr" + TRANSCRIPT_PATH, False),
    ("https://cn.hongik.ac.kr/stud/include/header.jsp", False),
])
def test_reader_only_accepts_official_https_transcript(url, expected):
    assert is_school_frame(url, transcript=True) == expected


def test_local_only_gate(monkeypatch):
    monkeypatch.delenv("PLANNER_LOCAL_PORTAL", raising=False)
    assert not local_portal_enabled("127.0.0.1")
    monkeypatch.setenv("PLANNER_LOCAL_PORTAL", "1")
    assert local_portal_enabled("127.0.0.1")
    assert not local_portal_enabled("0.0.0.0")


def test_reader_checks_frames_not_account_or_other_domains():
    class Locator:
        @property
        def first(self): return self
        async def wait_for(self, **kwargs): pass
    class Frame:
        def __init__(self, url): self.url, self.read = url, False
        def locator(self, selector): return Locator()
        async def evaluate(self, script):
            self.read = True
            return [table()]
    main = Frame("https://cn.hongik.ac.kr" + TRANSCRIPT_PATH)
    account = Frame("https://cn.hongik.ac.kr/stud/include/header.jsp")
    foreign = Frame("https://example.com" + TRANSCRIPT_PATH)
    class Page: frames = [account, main, foreign]
    class Context: pages = [Page()]
    assert asyncio.run(read_school_tables(Context())) == [table()]
    assert main.read and not account.read and not foreign.read


def test_multiple_open_transcripts_rejected():
    class Frame: url = "https://cn.hongik.ac.kr" + TRANSCRIPT_PATH
    class Page: frames = [Frame(), Frame()]
    class Context: pages = [Page()]
    with pytest.raises(PortalError, match="한 개"):
        asyncio.run(read_school_tables(Context()))


@pytest.mark.parametrize("fail_login", [False, True])
@pytest.mark.parametrize("channel", ["chrome", "msedge"])
def test_worker_uses_one_thread_and_closes_browser_without_leaking_error(monkeypatch, fail_login, channel):
    from playwright import async_api
    from src.planning.portal import PortalSession

    calls, threads = [], set()
    def record(name):
        calls.append(name)
        threads.add(get_ident())
    class Locator:
        @property
        def first(self): return self
        async def wait_for(self, **kwargs): record("wait")
    class Page:
        url = "https://cn.hongik.ac.kr" + TRANSCRIPT_PATH
        def on(self, event, handler):
            assert event == "dialog"
        @property
        def frames(self): return [self]
        async def goto(self, *args, **kwargs):
            record("login")
            assert args[0] == "https://cn.hongik.ac.kr/stud/"
            if fail_login:
                raise RuntimeError("PRIVATE_PROVIDER_MESSAGE")
        def locator(self, selector): return Locator()
        async def evaluate(self, script):
            record("read")
            return [table()]
    class Context:
        pages = [Page()]
        async def new_page(self): return self.pages[0]
        async def close(self): record("context_close")
    class Browser:
        async def new_context(self, **kwargs):
            assert kwargs == {"accept_downloads": False}
            record("context")
            return Context()
        def is_connected(self): return True
        async def close(self): record("browser_close")
    class Chromium:
        async def launch(self, **kwargs):
            assert kwargs["headless"] is False and kwargs["channel"] == channel
            record("launch")
            return Browser()
    class Playwright:
        chromium = Chromium()
        async def __aenter__(self): return self
        async def __aexit__(self, *args): record("driver_close")
    monkeypatch.setattr(async_api, "async_playwright", Playwright)
    session = PortalSession(browser_channel=channel)
    if fail_login:
        with pytest.raises(PortalError) as exc:
            session.start()
        assert "PRIVATE_PROVIDER_MESSAGE" not in str(exc.value)
    else:
        session.start()
        assert session.read() == [table()]
        session.close()
    session._thread.join(timeout=3)
    assert not session.active
    assert calls[-3:] == ["context_close", "browser_close", "driver_close"]
    assert len(threads) == 1 and get_ident() not in threads


def test_pasted_semesters_ignore_account_and_totals_and_preserve_empty_f():
    raw = "개인 식별 정보는 결과에 포함하지 않음\n전체성적조회\n2020학년도 1학년 1학기\n" + "\t".join(HEADERS) + "\n001234\t가상 과목\tTEST COURSE\t3\t\t\n신청학점 3 신청평점 0\n취득학점 0\n2021학년도 2학년 2학기\n" + "\t".join(HEADERS) + "\n001234\t가상 과목\tTEST COURSE\t3\tA+\n전체성적\n총 취득학점 3"
    result = parse_portal_text(raw, [])
    assert result.ready and result.semester_count == 2
    assert [a.grade for a in result.attempts] == ["F", "A+"]
    assert "개인 식별" not in str(result)


@pytest.mark.parametrize("raw", ["", "[]", "개인정보만 있는 복사 내용", "x" * 1000001,
    "2020학년도 1학년 1학기\n잘못된 헤더\n001234\t가상 과목\tTEST\t3\tP"],
    ids=["empty", "wrong-format", "no-course-table", "oversize", "bad-header"])
def test_bad_paste_fails_without_exposing_raw_text(raw):
    result = parse_portal_text(raw, [])
    assert not result.ready and result.errors
    assert "개인정보만" not in str(result)


@pytest.mark.parametrize("annotation", [" (*)", " (C)"])
def test_school_delivery_annotation_is_not_part_of_matching_name(annotation):
    catalog = [Candidate(code="001234", name="가상 과목", credits=3, category="전공")]
    result = parse_portal_tables([table(rows=[["001234", "가상 과목" + annotation, "", "3", "", ""]])], catalog)
    assert result.ready and result.attempts[0].category == "전공"
    assert result.attempts[0].name.endswith(annotation) and result.attempts[0].grade == "F"
