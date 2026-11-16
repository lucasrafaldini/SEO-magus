"""URL normalization shared by the extractor, the crawler and the audit."""

import fnmatch
from typing import Iterable, Tuple
from urllib.parse import parse_qsl, urldefrag, urlencode, urlparse

# Query parameters that only track campaigns/clicks: removed so that
# /page?utm_source=x and /page are the same page.
DEFAULT_TRACKING_PARAMS: Tuple[str, ...] = (
    "utm_*", "gclid", "gbraid", "wbraid", "fbclid", "msclkid", "dclid", "yclid", "twclid",
    "mc_cid", "mc_eid", "_ga", "_gl", "_hsenc", "_hsmi", "mkt_tok", "igshid", "srsltid",
)
_DEFAULT_PORTS = {"http": "80", "https": "443"}


def normalize_url(url: str, strip_params: Iterable[str] = DEFAULT_TRACKING_PARAMS) -> str:
    """
    Canonical form of an absolute URL: fragment removed, scheme and host
    lower-cased, default port dropped, empty path -> "/", tracking query
    parameters removed (other parameters keep their order).
    """
    url, _ = urldefrag(url.strip())
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    port = parsed.port if parsed.netloc else None
    netloc = host if port is None or str(port) == _DEFAULT_PORTS.get(scheme) else f"{host}:{port}"
    if parsed.username or parsed.password:
        netloc = parsed.netloc.rsplit("@", 1)[0] + "@" + netloc
    path = parsed.path or ("/" if netloc else "")
    query = parsed.query
    patterns = tuple(strip_params)
    if query and patterns:
        kept = [(k, v) for k, v in parse_qsl(query, keep_blank_values=True)
                if not any(fnmatch.fnmatchcase(k.lower(), p) for p in patterns)]
        query = urlencode(kept, doseq=True)
    return parsed._replace(scheme=scheme, netloc=netloc, path=path, query=query, fragment="").geturl()


def same_site(url: str, host: str, allow_subdomains: bool = False) -> bool:
    """Is url on the crawled host (optionally including its subdomains)?"""
    netloc = urlparse(url).netloc.lower()
    if netloc == host:
        return True
    if allow_subdomains:
        bare = host.split(":")[0]
        return netloc.split(":")[0].endswith("." + bare.removeprefix("www."))
    return False
