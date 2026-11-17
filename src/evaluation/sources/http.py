"""
Polite JSON client with a record/replay cache, for the live evaluation sources.

  * identifies itself: a User-Agent with a contact address is mandatory
    (Wikimedia's User-Agent policy; good manners everywhere else);
  * one request at a time, at least `min_interval` seconds apart, retries on
    429/5xx honouring Retry-After (capped);
  * every response is stored under `cache_dir` (one file per request, keyed by
    the full URL), so a snapshot fetched once can be rebuilt offline byte for
    byte, and tests replay recorded responses with `offline=True`.
"""

import gzip
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple, Union
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.log import get_logger

logger = get_logger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RETRY_AFTER = 60.0
Params = Union[Mapping[str, Any], Sequence[Tuple[str, Any]]]


class OfflineCacheMiss(LookupError):
    """offline=True and the request was never recorded."""


class HttpJsonClient:
    def __init__(self, user_agent: str, cache_dir: Optional[Union[str, Path]] = None, min_interval: float = 0.5,
                 offline: bool = False, timeout: float = 30.0, retries: int = 3,
                 opener: Optional[Callable[..., Any]] = None):
        if offline and cache_dir is None:
            raise ValueError("offline mode needs a cache_dir to replay from")
        if not offline and ("@" not in user_agent and "http" not in user_agent):
            raise ValueError("user_agent must include a contact (e-mail or URL), e.g. "
                             "'SEO-Magus-eval/1.0 (you@example.com)' - required by Wikimedia's User-Agent policy")
        self.user_agent = user_agent
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.min_interval = min_interval
        self.offline = offline
        self.timeout = timeout
        self.retries = retries
        self._open = opener or urlopen
        self._last = 0.0
        self.requests_made = 0
        self.cache_hits = 0

    @staticmethod
    def url_for(url: str, params: Optional[Params] = None) -> str:
        items = sorted(params.items()) if isinstance(params, Mapping) else list(params or [])
        return f"{url}?{urlencode(items)}" if items else url

    def _cache_path(self, full_url: str) -> Optional[Path]:
        if self.cache_dir is None:
            return None
        return self.cache_dir / f"{hashlib.sha1(full_url.encode()).hexdigest()}.json"

    def record(self, url: str, params: Optional[Params], payload: Any) -> Path:
        """Store a response as if it had been fetched (used to write test fixtures)."""
        full = self.url_for(url, params)
        path = self._cache_path(full)
        if path is None:
            raise ValueError("record() needs a cache_dir")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"url": full, "body": payload}, ensure_ascii=False), encoding="utf-8")
        return path

    def get_json(self, url: str, params: Optional[Params] = None) -> Any:
        full = self.url_for(url, params)
        path = self._cache_path(full)
        if path is not None and path.is_file():
            self.cache_hits += 1
            return json.loads(path.read_text(encoding="utf-8"))["body"]
        if self.offline:
            raise OfflineCacheMiss(f"not in the cache ({self.cache_dir}): {full}")
        body = self._fetch(full)
        if path is not None:
            self.record(url, params, body)
        return body

    def _fetch(self, full_url: str) -> Any:
        attempt = 0
        while True:
            attempt += 1
            wait = self._last + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.requests_made += 1
            request = Request(full_url, headers={"User-Agent": self.user_agent, "Accept": "application/json",
                                                 "Accept-Encoding": "gzip"})
            try:
                with self._open(request, timeout=self.timeout) as response:
                    data = response.read()
                    if response.headers.get("Content-Encoding", "") == "gzip":
                        data = gzip.decompress(data)
                    return json.loads(data.decode("utf-8"))
            except HTTPError as exc:
                if exc.code not in RETRY_STATUSES or attempt > self.retries:
                    raise
                retry_after = (exc.headers or {}).get("Retry-After", "")
                delay = float(retry_after) if str(retry_after).isdigit() else 2.0 ** attempt
            except URLError:
                if attempt > self.retries:
                    raise
                delay = 2.0 ** attempt
            delay = min(delay, MAX_RETRY_AFTER)
            logger.warning("Retrying %s in %.0fs (attempt %d)", full_url, delay, attempt)
            time.sleep(delay)
