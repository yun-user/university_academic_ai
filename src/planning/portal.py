"""User-operated school login in an isolated local browser; no saved credentials."""
from __future__ import annotations

import asyncio
from concurrent.futures import Future, TimeoutError as FutureTimeout
import os
from queue import Empty, Queue
import sys
from threading import Event, Thread
from time import monotonic
from urllib.parse import urlsplit

LOGIN_URL = "https://my.hongik.ac.kr/my/login.do?Refer=https://cn.hongik.ac.kr/"
ENTRY_URL = "https://cn.hongik.ac.kr/stud/"
TRANSCRIPT_PATH = "/stud/P/01000/01000.jsp"  # Observed Classnet menu href, 2026-10-06.

# Only the course tables seen in 전체성적조회. No form fields, cookies, account header,
# English course names, or whole-page HTML cross the browser boundary.
EXTRACT_TABLES = r"""() => {
  const visible = e => e.getClientRects().length > 0;
  const tables = [...document.querySelectorAll('table')].filter(t => visible(t) &&
    [...(t.rows[0]?.cells || [])].some(c => c.innerText.trim() === '학수번호'));
  if (tables.length > 50) throw new Error('table limit');
  return tables.map(t => {
    if (t.rows.length > 502) throw new Error('row limit');
    return {
      caption: (t.caption?.innerText || '').trim(),
      headers: [...(t.rows[0]?.cells || [])].map(c => c.innerText.trim()),
      rows: [...t.rows].slice(1).filter(r => !(
        r.cells.length === 1 && r.cells[0].colSpan === 6 &&
        /취득학점|신청학점|평점평균/.test(r.innerText)
      )).map(r => [...r.cells].map((c,i) => i === 2 ? '' : c.innerText.trim()))
    };
  });
}"""


class PortalError(ValueError):
    pass


def is_school_frame(url: str, *, transcript=False) -> bool:
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname == "cn.hongik.ac.kr"
                and parsed.port in (None, 443) and not parsed.username and not parsed.password
                and (parsed.path == TRANSCRIPT_PATH if transcript else parsed.path.startswith("/stud/")))
    except ValueError:
        return False


def local_portal_enabled(address: str | None) -> bool:
    return os.environ.get("PLANNER_LOCAL_PORTAL") == "1" and address in {"127.0.0.1", "localhost", "::1"}


async def read_school_tables(context):
    frames = [f for p in context.pages for f in p.frames if is_school_frame(f.url)]
    targets = [f for f in frames if is_school_frame(f.url, transcript=True)]
    if not targets:
        # Use the real menu link, preserving the school's frame navigation and session.
        for frame in frames:
            link = frame.locator(f'a[href="{TRANSCRIPT_PATH}"]')
            if await link.count() and await link.first.is_visible():
                await link.first.click(timeout=5000)
                break
        for _ in range(40):
            targets = [f for p in context.pages for f in p.frames if is_school_frame(f.url, transcript=True)]
            if targets:
                break
            await asyncio.sleep(0.2)
    if not targets:
        raise PortalError("학교 창에서 로그인한 뒤 클래스넷 → 성적정보 → 전체성적조회를 열어 주세요.")
    if len(targets) != 1:
        raise PortalError("전체성적조회 창을 한 개만 남긴 뒤 다시 가져와 주세요.")
    frame = targets[0]
    await frame.locator("table").first.wait_for(state="visible", timeout=10000)
    if not is_school_frame(frame.url, transcript=True):
        raise PortalError("학교 로그인이 만료되었습니다. 다시 로그인해 주세요.")
    return await frame.evaluate(EXTRACT_TABLES)


class PortalSession:
    """One worker/event loop/browser per Streamlit session, with bounded lifetime."""
    def __init__(self, idle_seconds=600, browser_channel="chrome"):
        if browser_channel not in {"chrome", "msedge"}:
            raise PortalError("설치된 Chrome 또는 Microsoft Edge를 선택하세요.")
        self._browser_channel = browser_channel
        self._queue = Queue()
        self._stop = Event()
        self._ready = Future()
        self._idle_seconds = idle_seconds
        self._thread = Thread(target=self._run, name="school-portal", daemon=True)

    @property
    def active(self):
        return self._thread.is_alive() and not self._stop.is_set()

    def start(self):
        self._thread.start()
        try:
            self._ready.result(timeout=35)
        except FutureTimeout:
            self.close()
            raise PortalError("학교 로그인 창을 여는 데 시간이 초과되었습니다. 잠시 후 다시 시도하세요.") from None
        return self

    def read(self):
        if not self.active:
            raise PortalError("학교 연결이 종료되었습니다. 로그인 창을 다시 열어 주세요.")
        response = Future()
        self._queue.put(response)
        try:
            return response.result(timeout=30)
        except FutureTimeout:
            self.close()
            raise PortalError("성적표 응답 시간이 초과되어 연결을 종료했습니다. 기존 입력은 유지됩니다.") from None

    def close(self):
        self._stop.set()

    def _run(self):
        # Streamlit may install a Selector policy; subprocesses need Proactor on Windows.
        loop_factory = asyncio.ProactorEventLoop if sys.platform == "win32" else asyncio.new_event_loop
        try:
            with asyncio.Runner(loop_factory=loop_factory) as runner:
                runner.run(self._serve())
        except Exception:
            if not self._ready.done():
                self._ready.set_exception(PortalError("로그인 창을 열지 못했습니다. setup_planner.cmd로 설치를 확인하고 선택한 브라우저가 설치되어 있는지 확인하세요."))
        finally:
            self._stop.set()
            while True:
                try:
                    pending = self._queue.get_nowait()
                except Empty:
                    break
                if not pending.done():
                    pending.set_exception(PortalError("학교 연결이 종료되었습니다. 다시 로그인해 주세요."))

    async def _serve(self):
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(channel=self._browser_channel, headless=False, timeout=20000)
            context = await browser.new_context(accept_downloads=False)
            try:
                page = await context.new_page()
                async def login_notice(dialog):
                    # The normal Classnet entry displays this notice before SSO.
                    # Leave every other dialog (including security prompts) to the user.
                    if dialog.type == "alert" and dialog.message.strip() == "통합로그인 후 접속 가능합니다.":
                        await dialog.dismiss()
                page.on("dialog", login_notice)
                await page.goto(ENTRY_URL, wait_until="domcontentloaded", timeout=20000)
                self._ready.set_result(None)
                last_use = monotonic()
                while not self._stop.is_set() and browser.is_connected() and context.pages:
                    if monotonic() - last_use > self._idle_seconds:
                        break
                    try:
                        response = self._queue.get_nowait()
                    except Empty:
                        await asyncio.sleep(0.2)
                        continue
                    last_use = monotonic()
                    try:
                        tables = await read_school_tables(context)
                    except PortalError as exc:
                        response.set_exception(exc)
                    except Exception:
                        response.set_exception(PortalError("성적표를 읽지 못했습니다. 로그인 상태와 전체성적조회 화면을 확인하세요. 기존 입력은 유지됩니다."))
                    else:
                        response.set_result(tables)
            finally:
                await context.close()
                await browser.close()
