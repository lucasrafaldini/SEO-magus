"""
HTTP fetching for the crawler (standard library only).

* Redirects are followed manually so every hop is recorded (chains, loops,
  redirects leaving the site are not followed).
* Transient failures (HTTP 429/5xx, timeouts, connection errors) are retried
  with exponential backoff; Retry-After is honoured (capped).
* A shared rate limiter spaces requests (politeness delay / robots Crawl-delay).
* gzip/deflate responses are decompressed; non-HTML bodies are not downloaded;
  HTML bodies are capped at max_bytes; the charset comes from the headers or
  the page's <meta charset>.
"""

import gzip
import re
import threading
import time
import zlib
from dataclasses import dataclass, field
from email.message import Message
from typing import Callable, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import HTTPRedirectHandler, Request, build_opener

from src.log import get_logger

logger = get_logger(__name__)

USER_AGENT = "SEO-Magus/1.0 (+https://github.com/lucasrafaldini/SEO-magus)"
RETRY_STATUSES = {429, 500, 502, 503, 504}
RETRY_AFTER_CAP_SECONDS = 10.0
_TEXT_TYPES = ("text/html", "application/xhtml+xml", "application/xml", "text/xml", "text/plain",
               "application/gzip", "application/x-gzip")
_META_CHARSET_RE = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([\w-]+)""", re.IGNORECASE)


@dataclass
class FetchResult:
    url: str                                   # requested
    final_url: str                             # after redirects
    status: int                                # final HTTP status; 0 = network error
    content_type: str = ""
    body: str = ""                             # decoded text (HTML / XML / text only)
    error: str = ""
    redirect_chain: List[Tuple[str, int]] = field(default_factory=list)  # (url, status) of each redirect hop
    redirect_loop: bool = False
    headers: Dict[str, str] = field(default_factory=dict)                 # selected headers, lower-case names
    elapsed_ms: float = 0.0
    bytes: int = 0
    truncated: bool = False                    # body longer than max_bytes
    attempts: int = 1
    raw: bytes = b""                           # undecoded body for XML / gzip (sitemaps)


class RateLimiter:
    """Minimum interval between the starts of consecutive requests (thread-safe)."""

    def __init__(self, min_interval: float = 0.0):
        self.min_interval = max(0.0, min_interval)
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self):
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + self.min_interval
        if start > now:
            time.sleep(start - now)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None  # surface 3xx as HTTPError so each hop can be recorded


def _decode_body(data: bytes, encoding: str, content_type_header: str) -> bytes:
    encoding = (encoding or "").lower()
    if "gzip" in encoding or data[:2] == b"\x1f\x8b" and "gzip" in content_type_header:
        return gzip.decompress(data)
    if "deflate" in encoding:
        try:
            return zlib.decompress(data)
        except zlib.error:
            return zlib.decompress(data, -zlib.MAX_WBITS)
    return data


def _charset(headers: Message, data: bytes) -> str:
    charset = headers.get_content_charset()
    if charset:
        return charset
    match = _META_CHARSET_RE.search(data[:4096])
    return match.group(1).decode("ascii", "ignore") if match else "utf-8"


class HttpFetcher:
    def __init__(self, timeout: float = 10.0, user_agent: str = USER_AGENT, retries: int = 2,
                 backoff: float = 0.5, max_redirects: int = 10, max_bytes: int = 5_000_000,
                 rate_limiter: Optional[RateLimiter] = None, host_filter: Optional[Callable[[str], bool]] = None):
        self.timeout = timeout
        self.user_agent = user_agent
        self.retries = retries
        self.backoff = backoff
        self.max_redirects = max_redirects
        self.max_bytes = max_bytes
        self.rate_limiter = rate_limiter or RateLimiter()
        self.host_filter = host_filter          # redirects to hosts it rejects are not followed
        self._opener = build_opener(_NoRedirect)
        self._lock = threading.Lock()
        self.requests_made = 0
        self.bytes_downloaded = 0

    def __call__(self, url: str) -> FetchResult:
        return self.fetch(url)

    def _once(self, url: str, method: str):
        """One HTTP exchange without redirects: (status, headers, body bytes, error, truncated)."""
        self.rate_limiter.wait()
        with self._lock:
            self.requests_made += 1
        request = Request(url, method=method, headers={
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
        })
        try:
            response = self._opener.open(request, timeout=self.timeout)
        except HTTPError as exc:
            return exc.code, exc.headers, b"", str(exc), False
        except (URLError, OSError, ValueError) as exc:
            return 0, Message(), b"", str(getattr(exc, "reason", exc)), False
        with response:
            content_type = response.headers.get_content_type()
            wants_body = method == "GET" and content_type.startswith(_TEXT_TYPES)
            data, truncated = b"", False
            if wants_body:
                try:
                    data = response.read(self.max_bytes + 1)
                except (OSError, ValueError) as exc:
                    return 0, response.headers, b"", f"read failed: {exc}", False
                truncated = len(data) > self.max_bytes
                data = data[: self.max_bytes]
            with self._lock:
                self.bytes_downloaded += len(data)
            return response.status, response.headers, data, "", truncated

    def _with_retries(self, url: str, method: str):
        attempt = 0
        while True:
            attempt += 1
            status, headers, data, error, truncated = self._once(url, method)
            if (status in RETRY_STATUSES or status == 0) and attempt <= self.retries:
                retry_after = headers.get("Retry-After", "") if headers else ""
                delay = float(retry_after) if retry_after.strip().isdigit() else self.backoff * (2 ** (attempt - 1))
                delay = min(delay, RETRY_AFTER_CAP_SECONDS)
                logger.debug("Retrying %s in %.1fs after %s (attempt %d)", url, delay, status or error, attempt)
                time.sleep(delay)
                continue
            return status, headers, data, error, truncated, attempt

    def fetch(self, url: str, method: str = "GET") -> FetchResult:
        started = time.perf_counter()
        chain: List[Tuple[str, int]] = []
        seen = {url}
        current, attempts_total = url, 0
        while True:
            status, headers, data, error, truncated, attempts = self._with_retries(current, method)
            attempts_total += attempts
            location = headers.get("Location") if headers and 300 <= status < 400 else None
            if not location:
                break
            target = urljoin(current, location)
            chain.append((current, status))
            if target in seen:
                result = FetchResult(url, target, status, error="redirect loop", redirect_chain=chain, redirect_loop=True)
                result.elapsed_ms, result.attempts = 1000 * (time.perf_counter() - started), attempts_total
                return result
            if len(chain) > self.max_redirects:
                error = f"more than {self.max_redirects} redirects"
                break
            if self.host_filter is not None and not self.host_filter(target):
                # Redirect leaves the site: record it, do not follow.
                result = FetchResult(url, target, status, error="redirect to another host", redirect_chain=chain)
                result.elapsed_ms, result.attempts = 1000 * (time.perf_counter() - started), attempts_total
                return result
            seen.add(target)
            current = target

        header_map = {k.lower(): v for k, v in (headers.items() if headers else [])}
        content_type = headers.get_content_type() if headers and header_map.get("content-type") else ""
        raw = _decode_body(data, header_map.get("content-encoding", ""), header_map.get("content-type", "")) if data else b""
        body = raw.decode(_charset(headers, raw), errors="replace") if raw and "gzip" not in content_type else ""
        return FetchResult(
            url=url, final_url=current, status=status, content_type=content_type, body=body, error=error,
            redirect_chain=chain, headers={k: header_map[k] for k in ("x-robots-tag", "content-type", "last-modified")
                                           if k in header_map},
            elapsed_ms=1000 * (time.perf_counter() - started), bytes=len(data), truncated=truncated,
            attempts=attempts_total, raw=raw if "xml" in content_type or "gzip" in content_type else b"",
        )

    def head(self, url: str) -> FetchResult:
        """Status check for external links: HEAD, falling back to GET when HEAD is refused."""
        result = self.fetch(url, method="HEAD")
        if result.status in (405, 501, 0):
            result = self.fetch(url, method="GET")
        return result
