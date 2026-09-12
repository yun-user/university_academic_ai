"""Bounded public HTTPS collection with robots rules and pinned public DNS addresses."""
from dataclasses import dataclass
import ipaddress
import socket
import time
from urllib.parse import urlsplit, urljoin, urlunsplit
from urllib.robotparser import RobotFileParser

import certifi
from bs4 import BeautifulSoup
import urllib3

USER_AGENT = "AcademicEvidenceBot/1.0"
MAX_BYTES = 3 * 1024 * 1024


def validate_url(url, allowed_hosts):
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").encode("idna").decode().lower()
        if (parts.scheme != "https" or parts.port not in {None, 443} or
                parts.username or parts.password or host not in allowed_hosts or
                any(ord(c) < 33 for c in url) or "\\" in url):
            raise ValueError("허용한 도메인의 HTTPS 주소만 수집할 수 있습니다.")
        ips = sorted({item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
            raise ValueError("내부망 또는 비공개 주소에는 접근할 수 없습니다.")
        return parts, host, ips[0]
    except (OSError, UnicodeError) as exc:
        raise ValueError("웹 주소를 확인할 수 없습니다.") from exc


def fetch_once(url, allowed_hosts):
    parts, host, ip = validate_url(url, allowed_hosts)
    # Connect to exactly the validated IP; keep TLS SNI and certificate checks for the host.
    pool = urllib3.HTTPSConnectionPool(ip, port=443, server_hostname=host,
        assert_hostname=host, cert_reqs="CERT_REQUIRED", ca_certs=certifi.where(),
        timeout=urllib3.Timeout(connect=8, read=12), retries=False)
    response = None
    try:
        target = urlunsplit(("", "", parts.path or "/", parts.query, ""))
        response = pool.urlopen("GET", target, headers={"Host": host, "User-Agent": USER_AGENT,
            "Accept": "text/html,text/plain", "Accept-Encoding": "identity"},
            assert_same_host=False, redirect=False, preload_content=False)
        body = response.read(MAX_BYTES + 1, decode_content=False)
        if len(body) > MAX_BYTES:
            raise ValueError("웹 문서가 3MB 제한을 초과했습니다.")
        if response.headers.get("Content-Encoding", "identity") not in {"", "identity"}:
            raise ValueError("지원하지 않는 압축 응답입니다.")
        return response.status, dict(response.headers), body
    finally:
        if response:
            response.close()
        pool.close()


@dataclass(frozen=True)
class WebDocument:
    url: str
    title: str
    text: str
    html: str
    published: str | None


class PublicCollector:
    def __init__(self, allowed_hosts, *, delay=2.0, fetch=fetch_once):
        self.allowed = {h.strip().lower().encode("idna").decode() for h in allowed_hosts if h.strip()}
        if not self.allowed or delay < 0:
            raise ValueError("허용 도메인과 요청 간격을 확인하세요.")
        self.delay = max(2., delay)
        self.fetch = fetch
        self.robots = {}
        self.last_request = 0.

    def _request(self, url):
        remaining = self.delay - (time.monotonic() - self.last_request)
        if remaining > 0:
            time.sleep(remaining)
        self.last_request = time.monotonic()
        return self.fetch(url, self.allowed)

    def _allowed_by_robots(self, url):
        host = urlsplit(url).hostname
        if host not in self.allowed:
            raise ValueError("허용되지 않은 도메인으로 이동했습니다.")
        if host not in self.robots:
            robot_url = f"https://{host}/robots.txt"
            status, headers, body = self._request(robot_url)
            parser = RobotFileParser(robot_url)
            if status == 404:
                parser.parse([])
            elif status == 200:
                parser.parse(body.decode("utf-8", errors="replace").splitlines())
            else:
                raise ValueError("robots.txt를 확인하지 못해 수집을 중단했습니다.")
            self.robots[host] = parser
        parser = self.robots[host]
        requested_delay = parser.crawl_delay(USER_AGENT) or parser.crawl_delay("*") or 0
        rate = parser.request_rate(USER_AGENT) or parser.request_rate("*")
        if rate:
            requested_delay = max(requested_delay, rate.seconds / rate.requests)
        if requested_delay > 60:
            raise ValueError("사이트가 긴 수집 간격을 요구합니다. 문서를 직접 등록하세요.")
        self.delay = max(self.delay, requested_delay)
        if not parser.can_fetch(USER_AGENT, url):
            raise ValueError("robots.txt에서 이 페이지의 수집을 허용하지 않습니다.")

    def collect(self, url, *, selector=""):
        for _ in range(6):
            parts = urlsplit(url)
            if parts.scheme != "https" or parts.username or parts.password or parts.port not in {None,443}:
                raise ValueError("인증정보 없는 HTTPS 주소만 입력하세요.")
            self._allowed_by_robots(url)
            status, headers, body = self._request(url)
            if status in {301, 302, 303, 307, 308}:
                location = headers.get("Location") or headers.get("location")
                if not location:
                    raise ValueError("잘못된 리다이렉트입니다.")
                url = urljoin(url, location)
                continue
            if status != 200:
                raise ValueError(f"공개 페이지를 읽지 못했습니다 (HTTP {status}).")
            mime = headers.get("Content-Type", headers.get("content-type", "")).lower()
            if "text/html" not in mime:
                raise ValueError("HTML 공지 페이지만 지원합니다. 파일은 다운로드 후 등록하세요.")
            return parse_page(url, body, selector=selector)
        raise ValueError("리다이렉트 횟수를 초과했습니다.")


def parse_page(url, body, *, selector=""):
    soup = BeautifulSoup(body, "html.parser")
    if soup.select_one('input[type="password"]'):
        raise ValueError("로그인이 필요한 페이지는 수집하지 않습니다.")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    date = soup.select_one('meta[property="article:published_time"]')
    published = date.get("content") if date else None
    if not published:
        time_tag = soup.find("time", datetime=True)
        published = time_tag.get("datetime") if time_tag else None
    for node in soup.select("script,style,noscript,nav,header,footer,form,iframe"):
        node.decompose()
    try:
        content = soup.select_one(selector) if selector else (soup.find("article") or soup.find("main"))
    except Exception as exc:
        raise ValueError("본문 CSS 선택자가 올바르지 않습니다.") from exc
    if content is None:
        raise ValueError("공지 본문을 찾지 못했습니다. 본문 CSS 선택자를 지정하세요.")
    text = content.get_text("\n", strip=True)
    if len(text) < 60 or not title:
        raise ValueError("제목 또는 본문이 부족해 등록할 수 없습니다.")
    return WebDocument(url, title, text, body.decode(soup.original_encoding or "utf-8", errors="replace"), published)
